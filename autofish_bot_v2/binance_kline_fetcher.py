#!/usr/bin/env python3
"""
K 线数据获取和缓存程序

功能:
- 从 Binance API 获取 K 线数据
- 缓存到本地 SQLite 数据库
- 支持增量更新
- 每个标的的每个周期单独存储

使用方法:
    # 获取单个标的单个周期
    python binance_kline_fetcher.py --symbol BTCUSDT --interval 1m

    # 按时间范围获取
    python binance_kline_fetcher.py --symbol BTCUSDT --interval 1m --date-range "20220616-20230107"

    # 按天数获取
    python binance_kline_fetcher.py --symbol BTCUSDT --interval 1m --days 365

    # 查看缓存状态
    python binance_kline_fetcher.py --symbol BTCUSDT --interval 1m --status

    # 清空缓存
    python binance_kline_fetcher.py --symbol BTCUSDT --interval 1m --clear
"""

import os
import sys
import asyncio
import argparse
import sqlite3
import aiohttp
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv

# 加载 .env 文件
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_FILE)

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("kline_fetcher")

# 代理设置
HTTP_PROXY = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")


class KlineFetcher:
    """K 线获取和缓存管理"""
    
    def __init__(self, cache_dir: str = "kline_cache"):
        self.cache_dir = cache_dir
        self.db_path = os.path.join(cache_dir, "klines.db")
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        os.makedirs(self.cache_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.close()
        logger.info(f"[数据库] 初始化完成: {self.db_path}")
    
    def _get_table_name(self, symbol: str, interval: str) -> str:
        """获取表名"""
        return f"klines_{symbol}_{interval}"
    
    def _ensure_table(self, symbol: str, interval: str):
        """确保表存在"""
        table = self._get_table_name(symbol, interval)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                timestamp INTEGER PRIMARY KEY,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL
            )
        """)
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_time ON {table}(timestamp)")
        conn.commit()
        conn.close()
    
    def query_cache(self, symbol: str, interval: str, 
                    start_time: int = None, end_time: int = None) -> List[Dict]:
        """从缓存查询 K 线数据"""
        table = self._get_table_name(symbol, interval)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 检查表是否存在
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if not cursor.fetchone():
                conn.close()
                return []
            
            # 查询数据
            if start_time and end_time:
                cursor.execute(f"""
                    SELECT timestamp, open, high, low, close, volume 
                    FROM {table} 
                    WHERE timestamp >= ? AND timestamp <= ?
                    ORDER BY timestamp ASC
                """, (start_time, end_time))
            elif start_time:
                cursor.execute(f"""
                    SELECT timestamp, open, high, low, close, volume 
                    FROM {table} 
                    WHERE timestamp >= ?
                    ORDER BY timestamp ASC
                """, (start_time,))
            elif end_time:
                cursor.execute(f"""
                    SELECT timestamp, open, high, low, close, volume 
                    FROM {table} 
                    WHERE timestamp <= ?
                    ORDER BY timestamp ASC
                """, (end_time,))
            else:
                cursor.execute(f"""
                    SELECT timestamp, open, high, low, close, volume 
                    FROM {table} 
                    ORDER BY timestamp ASC
                """)
            
            rows = cursor.fetchall()
            conn.close()
            
            klines = []
            for row in rows:
                klines.append({
                    "timestamp": row[0],
                    "open": row[1],
                    "high": row[2],
                    "low": row[3],
                    "close": row[4],
                    "volume": row[5],
                })
            
            return klines
        except Exception as e:
            logger.error(f"[查询缓存] 失败: {e}")
            conn.close()
            return []
    
    def _save_to_cache(self, symbol: str, interval: str, klines: List[Dict]):
        """保存 K 线数据到缓存"""
        if not klines:
            return
        
        self._ensure_table(symbol, interval)
        table = self._get_table_name(symbol, interval)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            for kline in klines:
                cursor.execute(f"""
                    INSERT OR REPLACE INTO {table} (timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    kline["timestamp"],
                    kline["open"],
                    kline["high"],
                    kline["low"],
                    kline["close"],
                    kline["volume"],
                ))
            
            conn.commit()
            logger.info(f"[保存缓存] {symbol} {interval}: {len(klines)} 条")
        except Exception as e:
            logger.error(f"[保存缓存] 失败: {e}")
        finally:
            conn.close()
    
    def _find_missing_ranges(self, symbol: str, interval: str,
                              start_time: int, end_time: int) -> List[Tuple[int, int]]:
        """找出缺失的时间范围"""
        table = self._get_table_name(symbol, interval)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 检查表是否存在
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if not cursor.fetchone():
                conn.close()
                return [(start_time, end_time)]
            
            # 获取已有数据的时间范围
            cursor.execute(f"""
                SELECT MIN(timestamp), MAX(timestamp), COUNT(*) 
                FROM {table}
            """)
            row = cursor.fetchone()
            conn.close()
            
            if not row or row[2] == 0:
                return [(start_time, end_time)]
            
            min_time, max_time, count = row
            
            missing_ranges = []
            
            # 检查开始时间之前的缺失
            if min_time > start_time:
                missing_ranges.append((start_time, min_time - 1))
            
            # 检查结束时间之后的缺失
            if max_time < end_time:
                missing_ranges.append((max_time + 1, end_time))
            
            return missing_ranges
        except Exception as e:
            logger.error(f"[检查缺失] 失败: {e}")
            conn.close()
            return [(start_time, end_time)]
    
    async def _fetch_from_api(self, symbol: str, interval: str,
                               start_time: int, end_time: int) -> List[Dict]:
        """从 Binance API 获取 K 线数据"""
        url = "https://fapi.binance.com/fapi/v1/klines"
        
        interval_minutes = {
            "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720,
            "1d": 1440, "3d": 4320, "1w": 10080
        }
        minutes = interval_minutes.get(interval, 1)
        total_klines = int((end_time - start_time) / (1000 * 60 * minutes))
        
        logger.info(f"[获取K线] {symbol} {interval}: 需要 {total_klines} 条")
        
        all_klines = []
        current_end_time = end_time
        batch_size = 1500
        
        proxy = HTTPS_PROXY or HTTP_PROXY or None
        
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            while len(all_klines) < total_klines:
                params = {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": batch_size,
                    "endTime": current_end_time,
                }
                
                kwargs = {"params": params}
                if proxy:
                    kwargs["proxy"] = proxy
                
                max_retries = 3
                retry_count = 0
                data = None
                
                while retry_count < max_retries:
                    try:
                        async with session.get(url, **kwargs, timeout=aiohttp.ClientTimeout(total=30)) as response:
                            if response.status == 200:
                                data = await response.json()
                                break
                            elif response.status == 429:
                                logger.warning(f"[获取K线] API 限制，等待 60 秒后重试")
                                await asyncio.sleep(60)
                                retry_count += 1
                            else:
                                text = await response.text()
                                logger.error(f"[获取K线] 失败: {response.status} - {text}")
                                retry_count += 1
                                if retry_count < max_retries:
                                    await asyncio.sleep(5)
                    except asyncio.TimeoutError:
                        logger.warning(f"[获取K线] 超时，重试 {retry_count + 1}/{max_retries}")
                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(5)
                    except Exception as e:
                        logger.error(f"[获取K线] 异常: {e}")
                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(5)
                
                if data is None:
                    logger.error(f"[获取K线] 重试 {max_retries} 次后仍失败")
                    break
                
                if not data:
                    logger.info(f"[获取K线] 没有更多数据")
                    break
                
                for item in data:
                    kline_time = item[0]
                    if kline_time < start_time:
                        continue
                    if kline_time > end_time:
                        continue
                    all_klines.append({
                        "timestamp": item[0],
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "volume": float(item[5]),
                    })
                
                earliest_time = data[0][0]
                if earliest_time <= start_time:
                    logger.info(f"[获取K线] 已到达开始时间")
                    break
                
                current_end_time = earliest_time - 1
                
                logger.info(f"[获取K线] 已获取 {len(all_klines)} 条")
                print(f"[获取K线] {symbol} {interval}: 已获取 {len(all_klines)} 条")
                
                await asyncio.sleep(1.0)
                
                if len(data) < batch_size:
                    break
        
        all_klines.sort(key=lambda x: x["timestamp"])
        return all_klines
    
    async def fetch_and_cache(self, symbol: str, interval: str,
                               start_time: int = None, end_time: int = None,
                               days: int = None):
        """获取 K 线并缓存"""
        # 计算时间范围
        if not end_time:
            end_time = int(datetime.now().timestamp() * 1000)
        
        if not start_time:
            if days:
                start_time = end_time - days * 24 * 60 * 60 * 1000
            else:
                start_time = end_time - 365 * 24 * 60 * 60 * 1000  # 默认 1 年
        
        print(f"\n{'='*60}")
        print(f"📊 {symbol} {interval}")
        print(f"  时间范围: {datetime.fromtimestamp(start_time/1000).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(end_time/1000).strftime('%Y-%m-%d')}")
        print(f"{'='*60}")
        
        # 检查缺失的时间范围
        missing_ranges = self._find_missing_ranges(symbol, interval, start_time, end_time)
        
        if not missing_ranges:
            print(f"✅ 缓存已完整，无需更新")
            return self.query_cache(symbol, interval, start_time, end_time)
        
        print(f"📋 缺失 {len(missing_ranges)} 个时间段:")
        for range_start, range_end in missing_ranges:
            print(f"  - {datetime.fromtimestamp(range_start/1000).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(range_end/1000).strftime('%Y-%m-%d')}")
        
        # 获取缺失数据
        for range_start, range_end in missing_ranges:
            klines = await self._fetch_from_api(symbol, interval, range_start, range_end)
            if klines:
                self._save_to_cache(symbol, interval, klines)
        
        return self.query_cache(symbol, interval, start_time, end_time)
    
    def get_cache_status(self, symbol: str = None, interval: str = None) -> Dict:
        """获取缓存状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 获取所有表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'klines_%'")
            tables = cursor.fetchall()
            
            status = {}
            for (table_name,) in tables:
                parts = table_name.replace("klines_", "").rsplit("_", 1)
                if len(parts) == 2:
                    tbl_symbol, tbl_interval = parts
                    
                    if symbol and tbl_symbol != symbol:
                        continue
                    if interval and tbl_interval != interval:
                        continue
                    
                    cursor.execute(f"SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM {table_name}")
                    row = cursor.fetchone()
                    
                    if row and row[0] > 0:
                        status[f"{tbl_symbol}_{tbl_interval}"] = {
                            "count": row[0],
                            "min_time": datetime.fromtimestamp(row[1] / 1000).strftime('%Y-%m-%d %H:%M'),
                            "max_time": datetime.fromtimestamp(row[2] / 1000).strftime('%Y-%m-%d %H:%M'),
                        }
            
            conn.close()
            return status
        except Exception as e:
            logger.error(f"[获取状态] 失败: {e}")
            conn.close()
            return {}
    
    def clear_cache(self, symbol: str = None, interval: str = None):
        """清空缓存"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            if symbol and interval:
                table = self._get_table_name(symbol, interval)
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
                print(f"✅ 已清空: {symbol} {interval}")
            elif symbol:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?", 
                              (f"klines_{symbol}_%",))
                tables = cursor.fetchall()
                for (table_name,) in tables:
                    cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
                print(f"✅ 已清空: {symbol} 所有周期")
            else:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'klines_%'")
                tables = cursor.fetchall()
                for (table_name,) in tables:
                    cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
                print(f"✅ 已清空所有缓存")
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"[清空缓存] 失败: {e}")
            conn.close()


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="K 线数据获取和缓存")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对 (默认: BTCUSDT)")
    parser.add_argument("--interval", type=str, default="1m", help="K线周期 (默认: 1m)")
    parser.add_argument("--date-range", type=str, default=None, help="时间范围 (格式: yyyymmdd-yyyymmdd)")
    parser.add_argument("--days", type=int, default=None, help="获取天数 (默认: 365)")
    parser.add_argument("--status", action="store_true", help="查看缓存状态")
    parser.add_argument("--clear", action="store_true", help="清空缓存")
    
    args = parser.parse_args()
    
    fetcher = KlineFetcher()
    
    # 查看状态
    if args.status:
        status = fetcher.get_cache_status(args.symbol, args.interval)
        if not status:
            print("📭 缓存为空")
            return
        
        print("\n📊 缓存状态:")
        print("-" * 80)
        for key, info in status.items():
            parts = key.rsplit("_", 1)
            if len(parts) == 2:
                sym, ivl = parts
                print(f"  {sym} {ivl}: {info['count']} 条, {info['min_time']} ~ {info['max_time']}")
        print("-" * 80)
        return
    
    # 清空缓存
    if args.clear:
        fetcher.clear_cache(args.symbol, args.interval)
        return
    
    # 解析时间范围
    start_time = None
    end_time = None
    
    if args.date_range:
        try:
            if args.date_range.count("-") == 1:
                parts = args.date_range.split("-")
                start_date = datetime.strptime(parts[0], "%Y%m%d")
                end_date = datetime.strptime(parts[1], "%Y%m%d")
            elif args.date_range.count("-") == 4:
                parts = args.date_range.split("-")
                start_date = datetime.strptime(f"{parts[0]}-{parts[1]}-{parts[2]}", "%Y-%m-%d")
                end_date = datetime.strptime(f"{parts[3]}-{parts[4]}-{parts[5]}", "%Y-%m-%d")
            else:
                raise ValueError(f"不支持的日期格式: {args.date_range}")
            
            start_time = int(start_date.timestamp() * 1000)
            end_time = int(end_date.timestamp() * 1000) + 86400000 - 1
        except ValueError as e:
            logger.error(f"[时间范围] 解析失败: {e}")
            return
    
    # 获取 K 线
    await fetcher.fetch_and_cache(
        symbol=args.symbol,
        interval=args.interval,
        start_time=start_time,
        end_time=end_time,
        days=args.days,
    )
    
    # 显示最终状态
    status = fetcher.get_cache_status(args.symbol, args.interval)
    if status:
        for key, info in status.items():
            print(f"\n✅ 完成: {info['count']} 条, {info['min_time']} ~ {info['max_time']}")


if __name__ == "__main__":
    asyncio.run(main())
