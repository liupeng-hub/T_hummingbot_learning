from decimal import Decimal
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import random


class MockMarketData:
    """模拟市场数据"""
    
    def __init__(self, base_price: Decimal = Decimal("67000.00")):
        self.base_price = base_price
        self.current_price = base_price
        self.price_history: List[Dict[str, Any]] = []
        self._generate_price_history()
    
    def _generate_price_history(self, days: int = 30) -> None:
        """生成历史价格数据"""
        self.price_history = []
        price = self.base_price
        
        for i in range(days * 24 * 60):
            timestamp = datetime.now() - timedelta(minutes=i)
            
            change = Decimal(str(random.uniform(-0.001, 0.001)))
            price = price * (Decimal("1") + change)
            
            high = price * Decimal("1.005")
            low = price * Decimal("0.995")
            
            self.price_history.append({
                "timestamp": timestamp,
                "open": price,
                "high": high,
                "low": low,
                "close": price,
                "volume": Decimal(str(random.uniform(100, 1000)))
            })
        
        self.price_history.reverse()
    
    def get_current_price(self) -> Decimal:
        """获取当前价格"""
        return self.current_price
    
    def set_current_price(self, price: Decimal) -> None:
        """设置当前价格"""
        self.current_price = price
    
    def get_klines(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1m",
        limit: int = 100
    ) -> List[List]:
        """获取 K 线数据"""
        klines = []
        
        for i, candle in enumerate(self.price_history[-limit:]):
            klines.append([
                int(candle["timestamp"].timestamp() * 1000),
                str(candle["open"]),
                str(candle["high"]),
                str(candle["low"]),
                str(candle["close"]),
                str(candle["volume"]),
                int((candle["timestamp"] + timedelta(minutes=1)).timestamp() * 1000),
                str(candle["volume"] * candle["close"]),
                100,
                str(candle["volume"] * Decimal("0.5")),
                str(candle["volume"] * candle["close"] * Decimal("0.5"))
            ])
        
        return klines
    
    def get_klines_dict(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1m",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取 K 线数据（字典格式）"""
        klines = []
        
        for candle in self.price_history[-limit:]:
            klines.append({
                "timestamp": candle["timestamp"],
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"]
            })
        
        return klines
    
    def simulate_price_drop(self, drop_percent: Decimal = Decimal("0.01")) -> None:
        """模拟价格下跌"""
        self.current_price = self.current_price * (Decimal("1") - drop_percent)
    
    def simulate_price_rise(self, rise_percent: Decimal = Decimal("0.01")) -> None:
        """模拟价格上涨"""
        self.current_price = self.current_price * (Decimal("1") + rise_percent)
    
    def get_entry_price(self, level: int, grid_spacing: Decimal = Decimal("0.01")) -> Decimal:
        """获取入场价格"""
        return self.current_price * (Decimal("1") - grid_spacing * level)
    
    def get_take_profit_price(
        self,
        entry_price: Decimal,
        exit_profit: Decimal = Decimal("0.01")
    ) -> Decimal:
        """获取止盈价格"""
        return entry_price * (Decimal("1") + exit_profit)
    
    def get_stop_loss_price(
        self,
        entry_price: Decimal,
        stop_loss: Decimal = Decimal("0.08")
    ) -> Decimal:
        """获取止损价格"""
        return entry_price * (Decimal("1") - stop_loss)
    
    def simulate_fill_entry(self, entry_price: Decimal) -> bool:
        """模拟入场成交"""
        return self.current_price <= entry_price
    
    def simulate_take_profit_trigger(self, take_profit_price: Decimal) -> bool:
        """模拟止盈触发"""
        return self.current_price >= take_profit_price
    
    def simulate_stop_loss_trigger(self, stop_loss_price: Decimal) -> bool:
        """模拟止损触发"""
        return self.current_price <= stop_loss_price


class MockMarketDataScenario:
    """模拟市场数据场景"""
    
    def __init__(self, mock_market_data: MockMarketData):
        self.mock = mock_market_data
        self.scenarios = {
            "normal": self._normal_scenario,
            "take_profit": self._take_profit_scenario,
            "stop_loss": self._stop_loss_scenario,
            "volatile": self._volatile_scenario
        }
    
    def _normal_scenario(self) -> None:
        """正常市场场景"""
        pass
    
    def _take_profit_scenario(self) -> None:
        """止盈场景 - 价格上涨"""
        self.mock.simulate_price_rise(Decimal("0.02"))
    
    def _stop_loss_scenario(self) -> None:
        """止损场景 - 价格下跌"""
        self.mock.simulate_price_drop(Decimal("0.10"))
    
    def _volatile_scenario(self) -> None:
        """波动市场场景"""
        for _ in range(10):
            if random.random() > 0.5:
                self.mock.simulate_price_rise(Decimal("0.005"))
            else:
                self.mock.simulate_price_drop(Decimal("0.005"))
    
    def run_scenario(self, scenario_name: str) -> None:
        """运行场景"""
        if scenario_name in self.scenarios:
            self.scenarios[scenario_name]()
        else:
            raise ValueError(f"Unknown scenario: {scenario_name}")
