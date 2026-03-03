"""
Autofish V1 振幅分析模块

分析历史K线数据，计算各振幅区间的概率分布和权重

运行方式：
    cd hummingbot_learning
    python3 -m autofish_bot.amplitude_analyzer
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

from .core import WeightCalculator


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(PROJECT_DIR, ".env")
load_dotenv(ENV_FILE)

LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, "amplitude_analyzer.log")

def get_config_filepath(symbol: str) -> str:
    return os.path.join(LOG_DIR, f"amplitude_config_{symbol}.json")

def get_report_filepath(symbol: str) -> str:
    return os.path.join(LOG_DIR, f"amplitude_report_{symbol}.md")

HTTP_PROXY = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AmplitudeAnalyzer:
    """振幅分析器
    
    分析历史K线数据，计算各振幅区间的概率分布，
    根据预期收益计算权重，输出配置文件供回测和实盘使用。
    """
    
    AMPLITUDE_RANGES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    DEFAULT_LEVERAGE = Decimal("10")
    LIQUIDATION_AMPLITUDE = 10
    
    def __init__(self, symbol: str = "BTCUSDT", interval: str = "1d", limit: int = 1000, leverage: int = 10):
        self.symbol = symbol
        self.interval = interval
        self.limit = limit
        self.leverage = Decimal(str(leverage))
        self.klines: List[dict] = []
        self.amplitudes: List[Decimal] = []
        self.amplitude_counts: Dict[int, int] = {amp: 0 for amp in self.AMPLITUDE_RANGES}
        self.probabilities: Dict[int, Decimal] = {}
        self.expected_returns: Dict[int, Decimal] = {}
        self.weights: Dict[str, Dict[int, Decimal]] = {}
        
        logger.info(f"初始化振幅分析器: symbol={symbol}, interval={interval}, limit={limit}, leverage={leverage}")
    
    async def fetch_klines(self) -> List[dict]:
        """获取历史K线数据"""
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {
            "symbol": self.symbol,
            "interval": self.interval,
            "limit": self.limit,
        }
        
        proxy = HTTPS_PROXY or HTTP_PROXY or None
        
        logger.info(f"[获取K线] symbol={self.symbol}, interval={self.interval}, limit={self.limit}, proxy={proxy}")
        
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
                            "open": Decimal(item[1]),
                            "high": Decimal(item[2]),
                            "low": Decimal(item[3]),
                            "close": Decimal(item[4]),
                            "volume": Decimal(item[5]),
                        })
                    logger.info(f"[获取K线] 成功获取 {len(klines)} 条数据")
                    return klines
                else:
                    text = await response.text()
                    logger.error(f"[获取K线] 失败: {response.status} - {text}")
                    return []
    
    def calculate_amplitude(self, kline: dict) -> Decimal:
        """计算单根K线的振幅
        
        振幅 = (high - low) / open * 100
        """
        open_price = kline["open"]
        high_price = kline["high"]
        low_price = kline["low"]
        
        if open_price == 0:
            return Decimal("0")
        
        amplitude = (high_price - low_price) / open_price * 100
        return amplitude
    
    def calculate_all_amplitudes(self):
        """计算所有K线振幅"""
        self.amplitudes = [self.calculate_amplitude(k) for k in self.klines]
        logger.info(f"[振幅计算] 完成，共 {len(self.amplitudes)} 条")
    
    def classify_amplitude(self, amplitude: Decimal) -> int:
        """将振幅归类到区间
        
        1%: 1 <= amp < 2
        2%: 2 <= amp < 3
        ...
        10%: amp >= 10
        """
        amp_int = int(amplitude)
        if amp_int < 1:
            return 0
        elif amp_int >= 10:
            return 10
        else:
            return amp_int
    
    def calculate_probabilities(self):
        """计算各振幅区间概率"""
        total = len(self.amplitudes)
        if total == 0:
            logger.warning("[概率计算] 无振幅数据")
            return
        
        for amp in self.amplitudes:
            amp_class = self.classify_amplitude(amp)
            if amp_class in self.amplitude_counts:
                self.amplitude_counts[amp_class] += 1
        
        for amp_class, count in self.amplitude_counts.items():
            if amp_class == 0:
                continue
            self.probabilities[amp_class] = Decimal(count) / Decimal(total)
        
        logger.info(f"[概率计算] 完成")
        for amp_class, prob in self.probabilities.items():
            logger.info(f"  {amp_class}%: {prob:.4f} ({self.amplitude_counts[amp_class]}次)")
    
    def calculate_expected_returns(self):
        """计算各振幅预期收益
        
        预期收益 = 振幅 × 杠杆 × 概率
        
        注意：>=10%振幅会触发强平，收益为负
        """
        for amp in self.AMPLITUDE_RANGES:
            prob = self.probabilities.get(amp, Decimal("0"))
            
            if amp >= self.LIQUIDATION_AMPLITUDE:
                self.expected_returns[amp] = -prob * self.leverage
            else:
                self.expected_returns[amp] = Decimal(amp) / 100 * self.leverage * prob
        
        logger.info(f"[预期收益] 计算（杠杆={self.leverage}x）")
        for amp, ret in self.expected_returns.items():
            logger.info(f"  {amp}%: {ret:.6f}")
    
    def calculate_weights_for_decay(self, decay_factor: Decimal) -> Dict[int, Decimal]:
        """计算指定衰减因子下的权重
        
        权重 = 振幅 × 概率^(1/d)
        
        优化：剔除负收益区间后归一化
        """
        beta = Decimal("1") / decay_factor
        
        positive_items = []
        for amp in self.AMPLITUDE_RANGES:
            prob = self.probabilities.get(amp, Decimal("0"))
            ret = self.expected_returns.get(amp, Decimal("0"))
            
            if ret > 0 and prob > 0:
                raw_weight = Decimal(amp) * (prob ** beta)
                positive_items.append((amp, raw_weight))
        
        total = sum(w for _, w in positive_items)
        
        weights = {}
        for amp, raw_weight in positive_items:
            weights[amp] = (raw_weight / total) if total > 0 else Decimal("0")
        
        return weights
    
    def calculate_all_weights(self):
        """计算所有衰减因子的权重"""
        decay_factors = [Decimal("0.5"), Decimal("1.0")]
        
        for d in decay_factors:
            key = f"d_{float(d)}"
            self.weights[key] = self.calculate_weights_for_decay(d)
            
            logger.info(f"[权重计算] d={d}")
            total = sum(self.weights[key].values())
            for amp, w in sorted(self.weights[key].items()):
                logger.info(f"  {amp}%: {w:.4f} ({float(w)*100:.2f}%)")
            logger.info(f"  总计: {total:.4f}")
    
    def get_recommended_config(self) -> dict:
        """获取推荐配置"""
        weights_d05 = self.weights.get("d_0.5", {})
        
        valid_amplitudes = sorted(weights_d05.keys())
        max_entries = min(4, len(valid_amplitudes))
        
        total_positive = sum(
            self.expected_returns.get(amp, Decimal("0")) 
            for amp in valid_amplitudes
        )
        
        return {
            "valid_amplitudes": valid_amplitudes,
            "max_entries": max_entries,
            "grid_spacing": Decimal("0.01"),
            "decay_factor": Decimal("0.5"),
            "stop_loss": Decimal("0.08"),
            "total_expected_return": float(total_positive),
        }
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "metadata": {
                "symbol": self.symbol,
                "interval": self.interval,
                "limit": self.limit,
                "analyzed_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "kline_count": len(self.klines),
            },
            "amplitude_stats": {
                str(amp): {
                    "count": self.amplitude_counts.get(amp, 0),
                    "probability": round(float(self.probabilities.get(amp, Decimal("0"))), 4),
                }
                for amp in self.AMPLITUDE_RANGES
            },
            "expected_returns": {
                str(amp): round(float(ret), 4)
                for amp, ret in self.expected_returns.items()
            },
            "weights": {
                decay_key: {
                    str(amp): round(float(w), 4)
                    for amp, w in weights.items()
                }
                for decay_key, weights in self.weights.items()
            },
            "recommended_config": {
                "symbol": self.symbol,
                "valid_amplitudes": sorted(self.weights.get("d_0.5", {}).keys()),
                "max_entries": min(4, len(self.weights.get("d_0.5", {}))),
                "grid_spacing": 0.01,
                "exit_profit": 0.01,
                "stop_loss": 0.08,
                "decay_factor": 0.5,
                "total_amount_quote": 1200,
                "leverage": int(self.leverage),
                "total_expected_return": round(float(sum(
                    self.expected_returns.get(amp, Decimal("0")) 
                    for amp in self.weights.get("d_0.5", {}).keys()
                )), 4),
            },
        }
    
    def save_to_file(self, filepath: str = None):
        """保存配置到JSON文件"""
        if filepath is None:
            filepath = get_config_filepath(self.symbol)
        
        weights_d05 = self.weights.get("d_0.5", {})
        max_entries = min(4, len(weights_d05))
        
        weight_list = []
        for amp in sorted(weights_d05.keys()):
            w = weights_d05.get(amp, Decimal("0"))
            weight_list.append(round(float(w), 4))
        
        valid_amps = sorted(weights_d05.keys())
        total_ret = sum(self.expected_returns.get(amp, Decimal("0")) for amp in valid_amps)
        
        lines = []
        lines.append("{")
        lines.append(f'  "symbol":"{self.symbol}",')
        lines.append(f'  "total_amount_quote":1200,')
        lines.append(f'  "leverage":{int(self.leverage)},')
        lines.append(f'  "decay_factor":0.5,')
        lines.append(f'  "max_entries":{max_entries},')
        lines.append(f'  "valid_amplitudes":{json.dumps(valid_amps)},')
        lines.append(f'  "weights":{json.dumps(weight_list)},')
        lines.append(f'  "grid_spacing":0.01,')
        lines.append(f'  "exit_profit":0.01,')
        lines.append(f'  "stop_loss":0.08,')
        lines.append(f'  "total_expected_return":{round(float(total_ret), 4)}')
        lines.append("}")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        logger.info(f"[保存配置] 成功保存到: {filepath}")
    
    def save_to_markdown(self, filepath: str = None):
        """保存分析报告到Markdown文件"""
        if filepath is None:
            filepath = get_report_filepath(self.symbol)
        
        lines = []
        lines.append(f"# Autofish V1 振幅分析报告")
        lines.append(f"")
        lines.append(f"**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"")
        
        lines.append(f"## 分析结果")
        lines.append(f"")
        lines.append(f"```json")
        lines.append(f"{{")
        
        lines.append(f'  "metadata":{{"symbol":"{self.symbol}","interval":"{self.interval}","limit":{self.limit},"analyzed_at":"{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}","kline_count":{len(self.klines)}}},')
        
        lines.append(f'  "amplitude_stats":{{')
        amp_stat_items = []
        for amp in self.AMPLITUDE_RANGES:
            count = self.amplitude_counts.get(amp, 0)
            prob = round(float(self.probabilities.get(amp, Decimal("0"))), 4)
            amp_stat_items.append(f'    "{amp}":{{"count":{count},"probability":{prob}}}')
        lines.append(',\n'.join(amp_stat_items))
        lines.append(f'  }},')
        
        er_items = [f'"{amp}":{round(float(self.expected_returns.get(amp, Decimal("0"))), 4)}' for amp in self.AMPLITUDE_RANGES]
        lines.append(f'  "expected_returns":{{' + ','.join(er_items) + '},')
        
        lines.append(f'  "weights":{{')
        w_d05_items = [f'"{amp}":{round(float(w), 4)}' for amp, w in sorted(self.weights.get("d_0.5", {}).items())]
        lines.append(f'    "d_0.5":{{' + ','.join(w_d05_items) + '},')
        w_d10_items = [f'"{amp}":{round(float(w), 4)}' for amp, w in sorted(self.weights.get("d_1.0", {}).items())]
        lines.append(f'    "d_1.0":{{' + ','.join(w_d10_items) + '}')
        lines.append(f'  }},')
        
        weights_d05 = self.weights.get("d_0.5", {})
        max_entries_md = min(4, len(weights_d05))
        weight_list_md = []
        for amp in sorted(weights_d05.keys()):
            w = weights_d05.get(amp, Decimal("0"))
            weight_list_md.append(round(float(w), 4))
        valid_amps_md = sorted(weights_d05.keys())
        total_ret_md = sum(self.expected_returns.get(amp, Decimal("0")) for amp in valid_amps_md)
        
        lines.append(f'  "recommended_config":{{')
        lines.append(f'    "symbol":"{self.symbol}",')
        lines.append(f'    "total_amount_quote":1200,')
        lines.append(f'    "leverage":{int(self.leverage)},')
        lines.append(f'    "decay_factor":0.5,')
        lines.append(f'    "max_entries":{max_entries_md},')
        lines.append(f'    "valid_amplitudes":{json.dumps(valid_amps_md)},')
        lines.append(f'    "weights":{json.dumps(weight_list_md)},')
        lines.append(f'    "grid_spacing":0.01,')
        lines.append(f'    "exit_profit":0.01,')
        lines.append(f'    "stop_loss":0.08,')
        lines.append(f'    "total_expected_return":{round(float(total_ret_md), 4)}')
        lines.append(f'  }}')
        
        lines.append(f"}}")
        lines.append(f"```")
        lines.append(f"")
        
        lines.append(f"## 元数据")
        lines.append(f"")
        lines.append(f"| 字段 | 值 | 说明 |")
        lines.append(f"|------|-----|------|")
        lines.append(f"| symbol | {self.symbol} | 交易对 |")
        lines.append(f"| interval | {self.interval} | K线周期 |")
        lines.append(f"| limit | {self.limit} | K线数量 |")
        lines.append(f"| leverage | {self.leverage}x | 杠杆倍数 |")
        lines.append(f"| kline_count | {len(self.klines)} | 实际获取K线数 |")
        lines.append(f"")
        
        lines.append(f"## 振幅统计")
        lines.append(f"")
        lines.append(f"| 振幅 | 出现次数 | 概率 | 预期收益 | 说明 |")
        lines.append(f"|------|----------|------|----------|------|")
        for amp in self.AMPLITUDE_RANGES:
            count = self.amplitude_counts.get(amp, 0)
            prob = self.probabilities.get(amp, Decimal("0"))
            ret = self.expected_returns.get(amp, Decimal("0"))
            note = "爆仓风险" if amp >= 10 else "正收益区间" if ret > 0 else "负收益"
            lines.append(f"| {amp}% | {count} | {float(prob)*100:.2f}% | {float(ret)*100:.4f}% | {note} |")
        lines.append(f"")
        
        lines.append(f"## 权重分配")
        lines.append(f"")
        lines.append(f"### 衰减因子 d=0.5（激进策略）")
        lines.append(f"")
        lines.append(f"| 振幅 | 权重 | 说明 |")
        lines.append(f"|------|------|------|")
        for amp, w in sorted(self.weights.get("d_0.5", {}).items()):
            lines.append(f"| {amp}% | {float(w)*100:.2f}% | 第{amp}层资金分配比例 |")
        lines.append(f"")
        
        lines.append(f"### 衰减因子 d=1.0（保守策略）")
        lines.append(f"")
        lines.append(f"| 振幅 | 权重 | 说明 |")
        lines.append(f"|------|------|------|")
        for amp, w in sorted(self.weights.get("d_1.0", {}).items()):
            lines.append(f"| {amp}% | {float(w)*100:.2f}% | 第{amp}层资金分配比例 |")
        lines.append(f"")
        
        lines.append(f"## 推荐配置说明")
        lines.append(f"")
        lines.append(f"| 字段 | 值 | 说明 |")
        lines.append(f"|------|-----|------|")
        lines.append(f"| symbol | {self.symbol} | 交易对 |")
        valid_amps = sorted(self.weights.get("d_0.5", {}).keys())
        lines.append(f"| valid_amplitudes | {valid_amps} | 有效振幅区间（正收益区间，≥10%已剔除） |")
        max_entries = min(4, len(self.weights.get("d_0.5", {})))
        lines.append(f"| max_entries | {max_entries} | 最大层级数（前{max_entries}层权重合计约84%） |")
        lines.append(f"| grid_spacing | 1% | 网格间距，入场价 = 基准价 × (1 - 1%) |")
        lines.append(f"| exit_profit | 1% | 止盈比例，止盈价 = 入场价 × (1 + 1%) |")
        lines.append(f"| stop_loss | 8% | 止损比例，止损价 = 入场价 × (1 - 8%) |")
        lines.append(f"| decay_factor | 0.5 | 衰减因子（d=0.5为激进策略） |")
        lines.append(f"| total_amount_quote | 1200 | 总投入金额（USDT） |")
        lines.append(f"| leverage | {int(self.leverage)}x | 杠杆倍数 |")
        total_ret = sum(self.expected_returns.get(amp, Decimal("0")) for amp in valid_amps)
        lines.append(f"| total_expected_return | {float(total_ret)*100:.2f}% | 总预期收益（所有正收益区间之和） |")
        lines.append(f"")
        
        weights_d05 = self.weights.get("d_0.5", {})
        max_entries_md = min(4, len(weights_d05))
        weight_list_md = []
        for amp in range(1, max_entries_md + 1):
            w = weights_d05.get(amp, Decimal("0"))
            weight_list_md.append(round(float(w), 4))
        valid_amps_md = list(range(1, max_entries_md + 1))
        total_ret_md = sum(self.expected_returns.get(amp, Decimal("0")) for amp in valid_amps_md)
        
        lines.append(f"## 算法说明")
        lines.append(f"")
        lines.append(f"### 振幅计算")
        lines.append(f"```")
        lines.append(f"振幅 = (high - low) / open × 100")
        lines.append(f"```")
        lines.append(f"")
        lines.append(f"### 预期收益计算")
        lines.append(f"```")
        lines.append(f"预期收益 = 振幅 × 杠杆 × 概率")
        lines.append(f"```")
        lines.append(f"")
        lines.append(f"### 权重计算")
        lines.append(f"```")
        lines.append(f"权重 = 振幅 × 概率^(1/d)")
        lines.append(f"```")
        lines.append(f"- d=0.5: 幂次β=2，权重集中在前几层（激进）")
        lines.append(f"- d=1.0: 幂次β=1，权重分布均匀（保守）")
        lines.append(f"")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        logger.info(f"[保存报告] 成功保存到: {filepath}")
    
    async def analyze(self) -> dict:
        """执行完整分析"""
        logger.info("=" * 60)
        logger.info("Autofish V1 振幅分析")
        logger.info("=" * 60)
        
        print("=" * 60)
        print("Autofish V1 振幅分析")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {self.symbol}")
        print(f"  K线周期: {self.interval}")
        print(f"  数据量: {self.limit}")
        
        self.klines = await self.fetch_klines()
        if not self.klines:
            logger.error("获取K线数据失败")
            return {}
        
        print(f"\n📊 数据统计:")
        print(f"  K线数量: {len(self.klines)}")
        
        first_kline = self.klines[0]
        last_kline = self.klines[-1]
        start_time = datetime.fromtimestamp(first_kline["timestamp"] / 1000)
        end_time = datetime.fromtimestamp(last_kline["timestamp"] / 1000)
        print(f"  时间范围: {start_time.strftime('%Y-%m-%d')} - {end_time.strftime('%Y-%m-%d')}")
        
        print(f"\n⏳ 开始分析...")
        
        self.calculate_all_amplitudes()
        self.calculate_probabilities()
        self.calculate_expected_returns()
        self.calculate_all_weights()
        
        self._print_summary()
        
        return self.to_dict()
    
    def _print_summary(self):
        """打印分析结果摘要"""
        print("\n" + "=" * 60)
        print("📊 振幅统计")
        print("=" * 60)
        print(f"{'振幅':<8} {'次数':<8} {'概率':<12} {'预期收益':<12}")
        print("-" * 60)
        for amp in self.AMPLITUDE_RANGES:
            count = self.amplitude_counts.get(amp, 0)
            prob = self.probabilities.get(amp, Decimal("0"))
            ret = self.expected_returns.get(amp, Decimal("0"))
            ret_str = f"{float(ret)*100:.4f}%" if ret >= 0 else f"{float(ret)*100:.4f}%"
            print(f"{amp}%{'':<5} {count:<8} {float(prob)*100:.2f}%{'':<6} {ret_str}")
        
        print("\n" + "=" * 60)
        print("📐 权重分配")
        print("=" * 60)
        
        for decay_key, weights in self.weights.items():
            d = decay_key.replace("d_", "")
            print(f"\n衰减因子 d={d}:")
            print(f"{'振幅':<8} {'权重':<12}")
            print("-" * 30)
            for amp, w in sorted(weights.items()):
                print(f"{amp}%{'':<5} {float(w)*100:.2f}%")
            total = sum(weights.values())
            print(f"{'合计':<8} {float(total)*100:.2f}%")
        
        recommended = self.get_recommended_config()
        print("\n" + "=" * 60)
        print("📋 推荐配置")
        print("=" * 60)
        print(f"  有效振幅范围: {recommended['valid_amplitudes']}")
        print(f"  最大层级: {recommended['max_entries']}")
        print(f"  网格间距: {float(recommended['grid_spacing'])*100}%")
        print(f"  衰减因子: {recommended['decay_factor']}")
        print(f"  止损比例: {float(recommended['stop_loss'])*100}%")
        print(f"  总预期收益: {recommended['total_expected_return']*100:.2f}%")
        print("=" * 60)


class AmplitudeConfig:
    """振幅配置加载器"""
    
    def __init__(self, config_path: str = None, symbol: str = None):
        if config_path is None:
            if symbol is None:
                symbol = "BTCUSDT"
            config_path = get_config_filepath(symbol)
        self.config_path = config_path
        self.data: Dict[str, Any] = {}
    
    def load(self) -> bool:
        """加载配置"""
        if not os.path.exists(self.config_path):
            logger.warning(f"[配置加载] 文件不存在: {self.config_path}")
            return False
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            logger.info(f"[配置加载] 成功加载: {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"[配置加载] 失败: {e}")
            return False
    
    def get_probabilities(self) -> Dict[int, Decimal]:
        """获取概率分布"""
        probs = {}
        for amp_str, stats in self.data.get("amplitude_stats", {}).items():
            amp = int(amp_str)
            probs[amp] = Decimal(str(stats.get("probability", 0)))
        return probs
    
    def get_weights(self, decay_factor: Decimal = Decimal("0.5")) -> Dict[int, Decimal]:
        """获取权重（根据max_entries截取）"""
        weights_data = self.data.get("weights", [])
        max_entries = self.get_max_entries()
        
        if isinstance(weights_data, list):
            weights = {}
            for i, w in enumerate(weights_data[:max_entries]):
                weights[i + 1] = Decimal(str(w))
            return weights
        
        if isinstance(weights_data, dict):
            first_key = list(weights_data.keys())[0] if weights_data else None
            if first_key and isinstance(weights_data.get(first_key), dict):
                key = f"d_{float(decay_factor)}"
                weights_data = weights_data.get(key, {})
            
            weights = {}
            for i, (amp_str, w) in enumerate(sorted(weights_data.items(), key=lambda x: int(x[0]))):
                if i >= max_entries:
                    break
                try:
                    amp = int(amp_str)
                    weights[amp] = Decimal(str(w))
                except (ValueError, TypeError):
                    continue
            
            return weights
        
        return {}
    
    def get_expected_returns(self) -> Dict[int, Decimal]:
        """获取预期收益"""
        returns = {}
        for amp_str, ret in self.data.get("expected_returns", {}).items():
            amp = int(amp_str)
            returns[amp] = Decimal(str(ret))
        return returns
    
    def get_leverage(self) -> Decimal:
        """获取杠杆倍数"""
        return Decimal(str(self.data.get("leverage", 10)))
    
    def get_symbol(self) -> str:
        """获取交易对"""
        return self.data.get("symbol", "BTCUSDT")
    
    def get_grid_spacing(self) -> Decimal:
        """获取网格间距"""
        return Decimal(str(self.data.get("grid_spacing", 0.01)))
    
    def get_exit_profit(self) -> Decimal:
        """获取止盈比例"""
        return Decimal(str(self.data.get("exit_profit", 0.01)))
    
    def get_stop_loss(self) -> Decimal:
        """获取止损比例"""
        return Decimal(str(self.data.get("stop_loss", 0.08)))
    
    def get_total_amount_quote(self) -> Decimal:
        """获取总投入金额"""
        return Decimal(str(self.data.get("total_amount_quote", 1200)))
    
    def get_max_entries(self) -> int:
        """获取最大层级"""
        return self.data.get("max_entries", 4)
    
    def get_valid_amplitudes(self) -> List[int]:
        """获取有效振幅区间"""
        return self.data.get("valid_amplitudes", [1, 2, 3, 4])
    
    def get_decay_factor(self) -> Decimal:
        """获取衰减因子"""
        return Decimal(str(self.data.get("decay_factor", 0.5)))
    
    def get_total_expected_return(self) -> Decimal:
        """获取总预期收益"""
        return Decimal(str(self.data.get("total_expected_return", 0)))
    
    @classmethod
    def load_latest(cls, symbol: str = "BTCUSDT") -> Optional['AmplitudeConfig']:
        """加载最新配置"""
        config = cls(symbol=symbol)
        if config.load():
            return config
        return None


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Autofish V1 振幅分析")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对 (默认: BTCUSDT)")
    parser.add_argument("--interval", type=str, default="1d", help="K线周期 (默认: 1d)")
    parser.add_argument("--limit", type=int, default=1000, help="K线数量 (默认: 1000)")
    parser.add_argument("--leverage", type=int, default=10, help="杠杆倍数 (默认: 10)")
    parser.add_argument("--output", type=str, default=None, help="输出文件路径 (默认: amplitude_config.json)")
    
    args = parser.parse_args()
    
    analyzer = AmplitudeAnalyzer(
        symbol=args.symbol,
        interval=args.interval,
        limit=args.limit,
        leverage=args.leverage
    )
    
    await analyzer.analyze()
    analyzer.save_to_file(args.output)
    analyzer.save_to_markdown()


if __name__ == "__main__":
    asyncio.run(main())
