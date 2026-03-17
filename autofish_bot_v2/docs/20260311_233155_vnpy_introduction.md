# VNPY (VeighNa) 框架介绍

## 概述

**VNPY** (VeighNa Quant Framework，旧称 Vn.Py) 是一个基于 Python 语言开发的开源量化交易框架。由国内社区驱动，旨在为量化交易者提供一套完整、灵活、可扩展的解决方案。

**官网**: https://www.vnpy.com/

**GitHub**: https://github.com/vnpy/vnpy

---

## 核心特性

### 1. 事件驱动架构

VNPY 的核心设计思想是事件驱动模型，整个系统通过中央事件引擎 (Event Engine) 解耦各模块。

```
┌─────────────────────────────────────────────────────────────┐
│                    VNPY 事件驱动架构                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ Gateway     │───▶│ EventEngine │───▶│ Strategy    │     │
│  │ (交易接口)  │    │ (事件引擎)  │    │ (策略)      │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│         │                  │                  │            │
│         ▼                  ▼                  ▼            │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ MainEngine  │    │ Event       │    │ OrderEngine │     │
│  │ (主引擎)    │    │ (事件类型)  │    │ (订单引擎)  │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**事件类型**:
- `EVENT_TICK`: 行情推送
- `EVENT_BAR`: K线数据
- `EVENT_ORDER`: 订单状态更新
- `EVENT_TRADE`: 成交回报
- `EVENT_POSITION`: 持仓更新

### 2. 多交易所支持

| 类型 | 支持的交易所/接口 |
|------|------------------|
| 国内期货 | CTP (上期所/大商所/郑商所/中金所) |
| 数字货币 | Binance, OKX, Huobi, BitMEX 等 |
| 证券 | 华泰证券, 国泰君安 等 |
| 国际期货 | IB (盈透证券) |

### 3. 策略引擎

- **CTA策略引擎**: 趋势跟踪策略
- **价差交易引擎**: 跨品种/跨期套利
- **算法交易引擎**: TWAP, VWAP, Iceberg 等
- **组合策略引擎**: 多品种组合

### 4. 回测引擎

- 支持历史数据回测
- 支持参数优化
- 支持多品种组合回测
- 生成详细回测报告

---

## 核心模块

### 1. CtaTemplate 策略模板

所有 CTA 策略都继承自 `CtaTemplate` 类：

```python
from vnpy.app.cta_strategy import (
    CtaTemplate,
    StopOrder,
    TickData,
    BarData,
    TradeData,
    OrderData,
    BarGenerator,
    ArrayManager
)

class MyStrategy(CtaTemplate):
    """自定义策略"""
    
    # 策略参数
    author = "Your Name"
    
    # 参数定义（可在界面修改）
    fast_period = 10
    slow_period = 20
    stop_loss = 0.02  # 止损比例
    
    # 变量定义（用于界面显示）
    fast_ma = 0
    slow_ma = 0
    
    parameters = ['fast_period', 'slow_period', 'stop_loss']
    variables = ['fast_ma', 'slow_ma']
    
    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        
        self.bg = BarGenerator(self.on_bar, 15, self.on_15min_bar)
        self.am = ArrayManager()
    
    def on_init(self):
        """策略初始化"""
        self.write_log("策略初始化")
        self.load_bar(10)  # 加载10天历史数据
    
    def on_start(self):
        """策略启动"""
        self.write_log("策略启动")
    
    def on_stop(self):
        """策略停止"""
        self.write_log("策略停止")
    
    def on_tick(self, tick: TickData):
        """Tick 数据推送"""
        self.bg.update_tick(tick)
    
    def on_bar(self, bar: BarData):
        """K线数据推送"""
        self.bg.update_bar(bar)
    
    def on_15min_bar(self, bar: BarData):
        """15分钟K线"""
        self.am.update_bar(bar)
        
        if not self.am.inited:
            return
        
        # 计算指标
        self.fast_ma = self.am.sma(self.fast_period)
        self.slow_ma = self.am.sma(self.slow_period)
        
        # 交易逻辑
        if self.fast_ma > self.slow_ma:
            if self.pos == 0:
                self.buy(bar.close_price * 1.001, 1)
            elif self.pos < 0:
                self.cover(bar.close_price * 1.001, abs(self.pos))
                self.buy(bar.close_price * 1.001, 1)
        else:
            if self.pos > 0:
                self.sell(bar.close_price * 0.999, abs(self.pos))
    
    def on_order(self, order: OrderData):
        """订单状态更新"""
        if order.status == Status.ALLTRADED:
            self.write_log(f"订单全部成交: {order.vt_orderid}")
        elif order.status == Status.CANCELLED:
            self.write_log(f"订单已取消: {order.vt_orderid}")
    
    def on_trade(self, trade: TradeData):
        """成交回报"""
        self.write_log(f"成交: {trade.direction} {trade.volume}@{trade.price}")
        
        # 成交后设置止损
        if trade.direction == Direction.LONG:
            stop_price = trade.price * (1 - self.stop_loss)
            self.sell(stop_price, abs(self.pos), stop=True)
    
    def on_stop_order(self, stop_order: StopOrder):
        """停止单状态更新"""
        pass
```

### 2. 核心方法说明

| 方法 | 说明 |
|------|------|
| `on_init()` | 策略初始化，加载历史数据 |
| `on_start()` | 策略启动 |
| `on_stop()` | 策略停止 |
| `on_tick(tick)` | 接收 Tick 数据 |
| `on_bar(bar)` | 接收 K线数据 |
| `on_order(order)` | 订单状态更新回调 |
| `on_trade(trade)` | 成交回报回调 |
| `on_stop_order(stop_order)` | 停止单状态更新 |

### 3. 交易方法

| 方法 | 说明 |
|------|------|
| `buy(price, volume, stop=False)` | 买入开仓 |
| `sell(price, volume, stop=False)` | 卖出平仓 |
| `short(price, volume, stop=False)` | 卖出开仓 |
| `cover(price, volume, stop=False)` | 买入平仓 |
| `cancel_order(vt_orderid)` | 撤销订单 |

**止损止盈设置**:
```python
# 成交后设置止损
def on_trade(self, trade: TradeData):
    if trade.direction == Direction.LONG:
        # 止损单
        stop_price = trade.price * 0.98
        self.sell(stop_price, abs(self.pos), stop=True)
        
        # 止盈单
        take_profit_price = trade.price * 1.05
        self.sell(take_profit_price, abs(self.pos))
```

---

## 回测引擎

### 使用示例

```python
from vnpy.app.cta_strategy.backtesting import BacktestingEngine
from vnpy.trader.constant import Interval
from datetime import datetime

def run_backtesting():
    # 创建回测引擎
    engine = BacktestingEngine()
    
    # 设置回测参数
    engine.set_parameters(
        vt_symbol="BTCUSDT.BINANCE",  # 交易对
        interval=Interval.MINUTE,      # K线周期
        start=datetime(2023, 1, 1),    # 开始时间
        end=datetime(2023, 12, 31),    # 结束时间
        rate=0.001,                    # 手续费率
        slippage=0.01,                 # 滑点
        size=1,                        # 合约乘数
        pricetick=0.01,                # 最小价格变动
        capital=1_000_000,             # 初始资金
    )
    
    # 添加策略
    engine.add_strategy(MyStrategy, {})
    
    # 加载历史数据
    engine.load_data()
    
    # 运行回测
    engine.run_backtesting()
    
    # 计算统计指标
    df = engine.calculate_result()
    stats = engine.calculate_statistics()
    
    # 显示结果
    engine.show_chart()
    
    # 输出统计
    for key, value in stats.items():
        print(f"{key}: {value}")
```

### 回测统计指标

| 指标 | 说明 |
|------|------|
| total_return | 总收益率 |
| annual_return | 年化收益率 |
| max_drawdown | 最大回撤 |
| sharpe_ratio | 夏普比率 |
| total_trade | 总交易次数 |
| win_rate | 胜率 |
| profit_loss_ratio | 盈亏比 |

---

## 实盘交易

### 启动流程

```python
from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.ui import MainWindow, create_qapp
from vnpy.gateway.binance import BinanceGateway
from vnpy.app.cta_strategy import CtaStrategyApp

def main():
    # 创建 Qt 应用
    qapp = create_qapp()
    
    # 创建事件引擎
    event_engine = EventEngine()
    
    # 创建主引擎
    main_engine = MainEngine(event_engine)
    
    # 添加交易接口
    main_engine.add_gateway(BinanceGateway)
    
    # 添加策略应用
    main_engine.add_app(CtaStrategyApp)
    
    # 创建主窗口
    main_window = MainWindow(main_engine, event_engine)
    main_window.showMaximized()
    
    # 运行
    qapp.exec()

if __name__ == "__main__":
    main()
```

### 接口配置

```python
# Binance 配置
setting = {
    "key": "your_api_key",
    "secret": "your_api_secret",
    "proxy_host": "",
    "proxy_port": 0,
}

main_engine.connect(setting, "BINANCE")
```

---

## 与 Autofish 的兼容性

### 优势

| 特性 | VNPY 支持 | Autofish 需求 |
|------|----------|--------------|
| 事件驱动 | ✅ EventEngine | ✅ WebSocket |
| 订单回调 | ✅ on_order | ✅ 必须 |
| 成交回调 | ✅ on_trade | ✅ 必须 |
| 条件单 | ✅ StopOrder | ✅ 必须 |
| 回测 | ✅ 内置 | ✅ 需要 |
| 多交易所 | ✅ 支持 | ⚠️ 可扩展 |

### 迁移方案

```python
class AutofishStrategy(CtaTemplate):
    """Autofish 策略迁移到 VNPY"""
    
    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        
        # 链式订单状态
        self.orders = {}  # 订单层级管理
        self.current_level = 0
        self.max_levels = 4
    
    def on_trade(self, trade: TradeData):
        """成交后触发下一层挂单"""
        if trade.direction == Direction.LONG:
            # 当前层级成交，下止盈止损
            self._set_stop_loss_take_profit(trade)
            
            # 触发下一层挂单
            if self.current_level < self.max_levels:
                self._place_next_level_order(trade)
    
    def _set_stop_loss_take_profit(self, trade):
        """设置止盈止损"""
        stop_loss_price = trade.price * 0.92
        take_profit_price = trade.price * 1.01
        
        # 止损单
        self.sell(stop_loss_price, trade.volume, stop=True)
        # 止盈单
        self.sell(take_profit_price, trade.volume)
    
    def _place_next_level_order(self, trade):
        """下一层挂单"""
        self.current_level += 1
        next_price = trade.price * 0.99  # 下一个入场价
        self.buy(next_price, trade.volume)
```

### 需要自定义的部分

1. **链式挂单逻辑**: 在 `on_trade()` 中实现
2. **订单层级管理**: 自定义数据结构
3. **状态持久化**: 需要额外实现
4. **交易所特定条件单**: Binance 的 STOP_MARKET 等

---

## 安装与配置

### 安装

```bash
# 使用 pip 安装
pip install vnpy

# 或安装完整版
pip install vnpy[all]
```

### 目录结构

```
vnpy/
├── trader/           # 核心交易模块
│   ├── engine.py     # 主引擎
│   ├── event.py      # 事件引擎
│   └── object.py     # 数据对象
├── gateway/          # 交易接口
│   ├── binance/      # Binance 接口
│   └── ctp/          # CTP 接口
├── app/              # 应用模块
│   ├── cta_strategy/ # CTA策略
│   ├── spread_trading/ # 价差交易
│   └── algo_trading/ # 算法交易
└── examples/         # 示例代码
```

---

## 学习资源

### 官方资源
- **官网**: https://www.vnpy.com/
- **文档**: https://www.vnpy.com/docs/
- **论坛**: https://www.vnpy.com/forum/
- **GitHub**: https://github.com/vnpy/vnpy

### 推荐学习路径
1. 阅读官方文档了解基本概念
2. 运行 examples 中的示例代码
3. 学习 CTA 策略模板编写
4. 尝试回测自己的策略
5. 小资金实盘测试

---

## 总结

VNPY 是目前国内最成熟的开源量化交易框架之一，特别适合：

1. **事件驱动策略**: 与 Autofish 的架构匹配
2. **多交易所支持**: 可扩展到多个交易所
3. **回测与实盘一体化**: 同一套代码可回测可实盘
4. **国内社区活跃**: 中文文档丰富，问题容易解决

**推荐程度**: ⭐⭐⭐⭐⭐ (如果需要迁移到框架，VNPY 是首选)
