"""
Autofish V1 Binance 回测模块

使用历史 K 线数据进行策略回测

运行方式：
    cd hummingbot_learning
    source autofish_bot/venv/bin/activate
    python3 -m autofish_bot.binance_backtest --symbol BTCUSDT
"""

import asyncio
import json
import logging
import os
import argparse
from decimal import Decimal
from typing import List, Optional, Dict, Any
from datetime import datetime
import aiohttp
from dotenv import load_dotenv

from autofish_core import (
    Autofish_Order,
    Autofish_ChainState,
    Autofish_WeightCalculator,
    Autofish_OrderCalculator,
    Autofish_AmplitudeConfig,
)


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_FILE)
LOG_FILE = os.path.join(LOG_DIR, "binance_backtest.log")

HTTP_PROXY = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")

class FlushFileHandler(logging.FileHandler):
    """每次写入后自动刷新的 FileHandler"""
    def emit(self, record):
        super().emit(record)
        self.flush()

file_handler = FlushFileHandler(LOG_FILE, mode='a', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)


class BacktestEngine:
    """Binance 回测引擎
    
    使用历史 K 线数据模拟链式挂单策略的执行过程。
    
    主要功能：
    1. 获取历史 K 线数据
    2. 模拟订单执行（入场、止盈、止损）
    3. 计算盈亏统计
    4. 生成回测报告
    
    回测流程：
        获取K线 -> 遍历每根K线 -> 检查入场/出场条件 -> 
        更新状态 -> 计算盈亏 -> 生成报告
    
    Attributes:
        config: 配置字典（symbol, total_amount, leverage 等）
        interval: K线周期
        calculator: 权重计算器
        chain_state: 链式挂单状态
        results: 回测结果统计
        kline_count: 已处理的 K 线数量
        start_time: 回测开始时间
        end_time: 回测结束时间
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.interval = None
        
        self.calculator = Autofish_WeightCalculator(Decimal(str(self.config.get("decay_factor", 0.5))))
        self.chain_state: Optional[Autofish_ChainState] = None
        self.results = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "total_profit": Decimal("0"),
            "total_loss": Decimal("0"),
            "trades": [],
        }
        self.kline_count = 0
        self.start_time = None
        self.end_time = None
        self.klines_history: List[Dict] = []
    
    def _get_weights(self) -> Dict[int, Decimal]:
        """获取权重"""
        weights_list = self.config.get("weights", [])
        if not weights_list:
            return {}
        weights = {}
        for i, w in enumerate(weights_list):
            weights[i + 1] = Decimal(str(w))
        return weights
    
    def _create_order(self, level: int, base_price: Decimal, klines: List[Dict] = None) -> Autofish_Order:
        """创建订单
        
        参数:
            level: 层级
            base_price: 基准价格
            klines: K 线数据（用于 ATR 计算，仅 A1 使用）
        """
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.08"))
        total_amount = self.config.get("total_amount_quote", Decimal("1200"))
        
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=grid_spacing,
            exit_profit=exit_profit,
            stop_loss=stop_loss
        )
        
        weights = self._get_weights()
        if weights and level in weights:
            weight = weights[level]
            stake_amount = total_amount * weight
            
            if klines and level == 1:
                entry_price = order_calculator.calculate_dynamic_entry_price(
                    base_price, klines, level
                )
            else:
                entry_price = base_price * (Decimal("1") - grid_spacing * level)
            
            take_profit_price = entry_price * (Decimal("1") + exit_profit)
            stop_loss_price = entry_price * (Decimal("1") - stop_loss)
            quantity = stake_amount / entry_price
            
            order = Autofish_Order(
                level=level,
                entry_price=entry_price,
                quantity=quantity,
                stake_amount=stake_amount,
                take_profit_price=take_profit_price,
                stop_loss_price=stop_loss_price,
                state="pending",
                created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            )
            
            logger.info(f"[创建订单] A{level}: entry={entry_price:.2f}, "
                       f"tp={take_profit_price:.2f}, sl={stop_loss_price:.2f}, "
                       f"stake={stake_amount:.2f} USDT, qty={quantity:.6f} BTC, weight={weight:.4f}")
            
            return order
        
        return order_calculator.create_order(
            level=level,
            base_price=base_price,
            total_amount=total_amount,
            weight_calculator=self.calculator,
            klines=klines
        )
    
    def _process_entry(self, low_price: Decimal, current_price: Decimal):
        """处理入场"""
        max_level = self.config.get("max_entries", 4)
        
        pending_order = self.chain_state.get_pending_order()
        if pending_order:
            if Autofish_OrderCalculator.check_entry_triggered(low_price, pending_order.entry_price):
                pending_order.set_state("filled", "K线触发入场")
                
                weight_pct = self.calculator.get_weight_percentage(pending_order.level)
                logger.info(f"[入场成交] A{pending_order.level} (权重 {weight_pct:.2f}%): "
                           f"入场价={pending_order.entry_price:.2f}, "
                           f"数量={pending_order.quantity:.6f} BTC, "
                           f"金额={pending_order.stake_amount:.2f} USDT")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ A{pending_order.level} 成交: 入场价={pending_order.entry_price:.2f}")
                
                next_level = pending_order.level + 1
                if next_level <= max_level:
                    new_order = self._create_order(next_level, pending_order.entry_price)
                    self.chain_state.orders.append(new_order)
                    logger.info(f"[链式下单] 创建 A{next_level}: 入场价={new_order.entry_price:.2f}")
    
    def _process_exit(self, high_price: Decimal, low_price: Decimal, current_price: Decimal):
        """处理出场"""
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.08"))
        total_amount = self.config.get("total_amount_quote", Decimal("1200"))
        leverage = self.config.get("leverage", Decimal("10"))
        
        filled_orders = self.chain_state.get_filled_orders()
        
        for order in filled_orders:
            if order.state != "filled":
                continue
            
            if Autofish_OrderCalculator.check_take_profit_triggered(high_price, order.take_profit_price):
                self._close_order(order, "take_profit", order.take_profit_price, leverage)
                self.chain_state.cancel_pending_orders()
                new_order = self._create_order(order.level, current_price)
                self.chain_state.orders.append(new_order)
                logger.info(f"[止盈后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}")
                break

            elif Autofish_OrderCalculator.check_stop_loss_triggered(low_price, order.stop_loss_price):
                self._close_order(order, "stop_loss", order.stop_loss_price, leverage)
                self.chain_state.cancel_pending_orders()
                new_order = self._create_order(order.level, current_price)
                self.chain_state.orders.append(new_order)
                logger.info(f"[止损后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}")
                break
    
    def _close_order(self, order: Autofish_Order, reason: str, close_price: Decimal, leverage: Decimal):
        """平仓"""
        order.set_state("closed", reason)
        order.close_price = close_price
        order.profit = Autofish_OrderCalculator(leverage=leverage).calculate_profit(order, close_price)
        
        if reason == "take_profit":
            self.results["win_trades"] += 1
            self.results["total_profit"] += order.profit
            logger.info(f"[止盈] A{order.level}: 出场价={close_price:.2f}, "
                       f"盈利={order.profit:.2f} USDT")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎉 A{order.level} 止盈: 出场价={close_price:.2f}, 盈利={order.profit:.2f} USDT")
        else:
            self.results["loss_trades"] += 1
            self.results["total_loss"] += abs(order.profit)
            logger.info(f"[止损] A{order.level}: 出场价={close_price:.2f}, "
                       f"亏损={order.profit:.2f} USDT")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 A{order.level} 止损: 出场价={close_price:.2f}, 亏损={order.profit:.2f} USDT")
        
        self.results["total_trades"] += 1
        self.results["trades"].append({
            "level": order.level,
            "entry_price": float(order.entry_price),
            "close_price": float(close_price),
            "profit": float(order.profit),
            "reason": reason,
        })
    
    def _on_kline(self, kline: dict):
        """处理 K 线数据"""
        self.kline_count += 1
        
        open_price = Decimal(str(kline.get("open", kline.get("o", 0))))
        high_price = Decimal(str(kline.get("high", kline.get("h", 0))))
        low_price = Decimal(str(kline.get("low", kline.get("l", 0))))
        close_price = Decimal(str(kline.get("close", kline.get("c", 0))))
        volume = Decimal(str(kline.get("volume", kline.get("v", 0))))
        timestamp = kline.get("timestamp", kline.get("t", 0))
        
        if self.kline_count % 100 == 0:
            dt = datetime.fromtimestamp(timestamp / 1000) if timestamp else datetime.now()
            logger.debug(f"[K线 #{self.kline_count}] {dt.strftime('%Y-%m-%d %H:%M')} "
                        f"O={open_price:.2f} H={high_price:.2f} L={low_price:.2f} C={close_price:.2f}")
        
        self._process_entry(low_price, close_price)
        self._process_exit(high_price, low_price, close_price)
    
    async def fetch_klines(self, symbol: str, interval: str = "1m", limit: int = 1000) -> List[dict]:
        """获取历史 K 线数据"""
        url = f"https://fapi.binance.com/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        
        proxy = HTTPS_PROXY or HTTP_PROXY or None
        
        logger.info(f"[获取K线] symbol={symbol}, interval={interval}, limit={limit}, proxy={proxy}")
        
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            kwargs = {"params": params}
            if proxy:
                kwargs["proxy"] = proxy
            
            async with session.get(url, **kwargs) as response:
                if response.status == 200:
                    data = await response.json()
                    klines = []
                    for item in data:
                        klines.append({
                            "timestamp": item[0],
                            "open": item[1],
                            "high": item[2],
                            "low": item[3],
                            "close": item[4],
                            "volume": item[5],
                        })
                    logger.info(f"[获取K线] 成功获取 {len(klines)} 条数据")
                    return klines
                else:
                    text = await response.text()
                    logger.error(f"[获取K线] 失败: {response.status} - {text}")
                    return []
    
    async def run(self, symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 1000):
        """运行回测
        
        主要流程：
        1. 获取历史 K 线数据
        2. 遍历每根 K 线，模拟订单执行
        3. 统计盈亏结果
        4. 生成回测报告
        
        参数:
            symbol: 交易对
            interval: K线周期
            limit: K线数量
        """
        self.interval = interval
        logger.info("=" * 60)
        logger.info("Autofish V1 回测开始")
        logger.info("=" * 60)
        logger.info(f"配置: {self.config}")
        
        print("=" * 60)
        print("Autofish V1 回测")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {symbol}")
        print(f"  K线周期: {interval}")
        print(f"  数据量: {limit}")
        print(f"  网格间距: {float(self.config.get('grid_spacing', Decimal('0.01')))*100}%")
        print(f"  止盈: {float(self.config.get('exit_profit', Decimal('0.01')))*100}%")
        print(f"  止损: {float(self.config.get('stop_loss', Decimal('0.08')))*100}%")
        print(f"  杠杆: {self.config.get('leverage', 10)}x")
        print(f"  总资金: {self.config.get('total_amount_quote', 1200)} USDT")
        print(f"  最大层级: {self.config.get('max_entries', 4)}")
        
        klines = await self.fetch_klines(symbol, interval, limit)
        
        if not klines:
            logger.error("获取 K 线数据失败")
            return
        
        self.start_time = datetime.fromtimestamp(klines[0]["timestamp"] / 1000)
        self.end_time = datetime.fromtimestamp(klines[-1]["timestamp"] / 1000)
        
        print(f"\n📊 回测时间范围:")
        print(f"  开始: {self.start_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  结束: {self.end_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  K线数: {len(klines)}")
        
        first_price = Decimal(klines[0]["open"])
        self.chain_state = Autofish_ChainState(base_price=first_price)
        
        self.klines_history = klines[:30] if len(klines) >= 30 else klines
        first_order = self._create_order(1, first_price, self.klines_history)
        self.chain_state.orders.append(first_order)
        
        logger.info(f"[初始化] 创建 A1: 入场价={first_order.entry_price:.2f}")
        print(f"\n📋 创建首个订单: A1 入场价={first_order.entry_price:.2f}")
        
        print(f"\n⏳ 开始回测...")
        
        for kline in klines:
            self._on_kline(kline)
        
        self._print_summary()
    
    def _print_summary(self):
        """打印回测结果"""
        net_profit = self.results["total_profit"] - self.results["total_loss"]
        win_rate = (self.results["win_trades"] / self.results["total_trades"] * 100 
                   if self.results["total_trades"] > 0 else 0)
        
        print("\n" + "=" * 60)
        print("📊 回测结果")
        print("=" * 60)
        print(f"  回测时间: {self.start_time.strftime('%Y-%m-%d %H:%M')} - {self.end_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  K线数量: {self.kline_count}")
        print(f"  总交易: {self.results['total_trades']}")
        print(f"  盈利次数: {self.results['win_trades']}")
        print(f"  亏损次数: {self.results['loss_trades']}")
        print(f"  胜率: {win_rate:.2f}%")
        print(f"  总盈利: {float(self.results['total_profit']):.2f} USDT")
        print(f"  总亏损: {float(self.results['total_loss']):.2f} USDT")
        print(f"  净收益: {float(net_profit):.2f} USDT")
        print("=" * 60)
        
        logger.info("=" * 60)
        logger.info("回测结果")
        logger.info("=" * 60)
        logger.info(f"  总交易: {self.results['total_trades']}")
        logger.info(f"  盈利次数: {self.results['win_trades']}")
        logger.info(f"  亏损次数: {self.results['loss_trades']}")
        logger.info(f"  胜率: {win_rate:.2f}%")
        logger.info(f"  总盈利: {self.results['total_profit']:.2f} USDT")
        logger.info(f"  总亏损: {self.results['total_loss']:.2f} USDT")
        logger.info(f"  净收益: {net_profit:.2f} USDT")
    
    def save_report(self, symbol: str):
        """保存回测报告到 Markdown 文件
        
        生成包含以下内容的报告：
        1. 回测区间信息
        2. 振幅配置参数
        3. 回测结果统计
        4. 交易明细
        
        参数:
            symbol: 交易对
        """
        import os
        
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autofish_output")
        os.makedirs(output_dir, exist_ok=True)
        
        filepath = os.path.join(output_dir, f"binance_{symbol}_backtest_report.md")
        
        net_profit = self.results["total_profit"] - self.results["total_loss"]
        win_rate = (self.results["win_trades"] / self.results["total_trades"] * 100 
                   if self.results["total_trades"] > 0 else 0)
        
        lines = []
        lines.append(f"# Autofish V2 回测报告 (Binance: {symbol})")
        lines.append(f"")
        lines.append(f"**回测时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"")
        
        lines.append(f"## 回测区间")
        lines.append(f"")
        lines.append(f"| 项目 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 交易对 | {symbol} |")
        lines.append(f"| K线周期 | {self.interval} |")
        lines.append(f"| 开始时间 | {self.start_time.strftime('%Y-%m-%d %H:%M') if self.start_time else '-'} |")
        lines.append(f"| 结束时间 | {self.end_time.strftime('%Y-%m-%d %H:%M') if self.end_time else '-'} |")
        lines.append(f"| K线数量 | {self.kline_count} |")
        lines.append(f"")
        
        lines.append(f"## 振幅配置参数")
        lines.append(f"")
        weights_list = self.config.get("weights", [])
        if weights_list:
            weights_dict = {i+1: w for i, w in enumerate(weights_list)}
            valid_amplitudes = self.config.get("valid_amplitudes", [])
            total_expected_return = self.config.get("total_expected_return", 0)
            
            lines.append(f"| 参数 | 值 | 说明 |")
            lines.append(f"|------|-----|------|")
            lines.append(f"| 杠杆 | {self.config.get('leverage', 10)}x | - |")
            lines.append(f"| 总投入 | {self.config.get('total_amount_quote', 1200)} USDT | - |")
            lines.append(f"| 网格间距 | {float(self.config.get('grid_spacing', 0.01))*100:.1f}% | 入场价 = 基准价 × (1 - 网格间距) |")
            lines.append(f"| 止盈比例 | {float(self.config.get('exit_profit', 0.01))*100:.1f}% | 止盈价 = 入场价 × (1 + 止盈比例) |")
            lines.append(f"| 止损比例 | {float(self.config.get('stop_loss', 0.08))*100:.1f}% | 止损价 = 入场价 × (1 - 止损比例) |")
            lines.append(f"| 衰减因子 | {self.config.get('decay_factor', 0.5)} | 权重计算参数 |")
            lines.append(f"| 最大层级 | {self.config.get('max_entries', 4)} | 最多挂单层数 |")
            lines.append(f"| 有效振幅 | {valid_amplitudes} | 正收益区间 |")
            weight_items = [f"A{k}: {v*100:.2f}%" for k, v in sorted(weights_dict.items())]
            weight_lines = []
            for i in range(0, len(weight_items), 3):
                weight_lines.append(", ".join(weight_items[i:i+3]))
            lines.append(f"| 权重 | {'<br>'.join(weight_lines)} | 各层级资金分配比例 |")
            lines.append(f"| 总预期收益 | {float(total_expected_return)*100:.2f}% | 振幅分析预期 |")
        else:
            lines.append(f"未使用振幅配置，使用默认参数")
        lines.append(f"")
        
        lines.append(f"## 回测结果")
        lines.append(f"")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 总交易次数 | {self.results['total_trades']} |")
        lines.append(f"| 盈利次数 | {self.results['win_trades']} |")
        lines.append(f"| 亏损次数 | {self.results['loss_trades']} |")
        lines.append(f"| 胜率 | {win_rate:.2f}% |")
        lines.append(f"| 总盈利 | {float(self.results['total_profit']):.2f} USDT |")
        lines.append(f"| 总亏损 | {float(self.results['total_loss']):.2f} USDT |")
        lines.append(f"| 净收益 | {float(net_profit):.2f} USDT |")
        if self.config.get('total_amount_quote'):
            roi = float(net_profit) / float(self.config.get('total_amount_quote', 1200)) * 100
            lines.append(f"| 收益率 | {roi:.2f}% | 净收益 / 总投入 |")
        lines.append(f"")
        
        if self.results['trades']:
            lines.append(f"## 交易明细")
            lines.append(f"")
            lines.append(f"| 层级 | 入场价 | 出场价 | 类型 | 盈亏 |")
            lines.append(f"|------|--------|--------|------|------|")
            for trade in self.results['trades'][-50:]:
                lines.append(f"| A{trade['level']} | {trade['entry_price']:.2f} | {trade['close_price']:.2f} | {trade['reason']} | {float(trade['profit']):.2f} USDT |")
            if len(self.results['trades']) > 50:
                lines.append(f"| ... | ... | ... | ... | ... |")
                lines.append(f"*共 {len(self.results['trades'])} 笔交易，仅显示最近 50 笔*")
            lines.append(f"")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        logger.info(f"[保存报告] 成功保存到: {filepath}")
        print(f"\n📄 回测报告已保存: {filepath}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Autofish V2 回测")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对 (默认: BTCUSDT)")
    parser.add_argument("--interval", type=str, default="1m", help="K线周期 (默认: 1m)")
    parser.add_argument("--limit", type=int, default=1500, help="K线数量 (默认: 1500)")
    parser.add_argument("--decay-factor", type=float, default=0.5, help="衰减因子 (默认: 0.5，可选: 0.5/1.0)")
    parser.add_argument("--stop-loss", type=float, default=0.08, help="止损比例 (默认: 0.08)")
    parser.add_argument("--total-amount", type=float, default=1200, help="总投入金额 (默认: 1200)")
    
    args = parser.parse_args()
    
    decay_factor = Decimal(str(args.decay_factor))
    
    amplitude_config = Autofish_AmplitudeConfig.load_latest(args.symbol, decay_factor=decay_factor)
    
    if amplitude_config:
        config = {
            "symbol": amplitude_config.get_symbol(),
            "leverage": amplitude_config.get_leverage(),
            "grid_spacing": amplitude_config.get_grid_spacing(),
            "exit_profit": amplitude_config.get_exit_profit(),
            "stop_loss": amplitude_config.get_stop_loss(),
            "total_amount_quote": amplitude_config.get_total_amount_quote(),
            "max_entries": amplitude_config.get_max_entries(),
            "decay_factor": amplitude_config.get_decay_factor(),
            "weights": amplitude_config.get_weights(),
            "valid_amplitudes": amplitude_config.get_valid_amplitudes(),
            "total_expected_return": amplitude_config.get_total_expected_return(),
        }
        config_file = amplitude_config.config_path
    else:
        config = Autofish_OrderCalculator.get_default_config("binance")
        config["symbol"] = args.symbol
        config["decay_factor"] = decay_factor
        config.update({
            "stop_loss": Decimal(str(args.stop_loss)),
            "total_amount_quote": Decimal(str(args.total_amount)),
        })
        config_file = "无（使用内置默认配置）"
    
    logger.info(f"[配置加载] {'使用振幅分析配置' if amplitude_config else '使用默认配置'}: {args.symbol}")
    logger.info(f"  配置文件: {config_file}")
    logger.info(f"  交易标的: {config.get('symbol')}")
    logger.info(f"  交易杠杆: {config['leverage']}x")
    logger.info(f"  资金投入: {config['total_amount_quote']} USDT")
    logger.info(f"  网格间距: {float(config['grid_spacing'])*100:.1f}%")
    logger.info(f"  止盈比例: {float(config['exit_profit'])*100:.1f}%")
    logger.info(f"  止损比例: {float(config['stop_loss'])*100:.1f}%")
    logger.info(f"  衰减因子: {float(decay_factor)}")
    logger.info(f"  最大层级: {config['max_entries']}")
    logger.info(f"  网格权重: {config.get('weights', [])}")
    
    engine = BacktestEngine(config)
    await engine.run(symbol=args.symbol, interval=args.interval, limit=args.limit)
    engine.save_report(args.symbol)


if __name__ == "__main__":
    asyncio.run(main())
