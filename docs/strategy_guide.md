# Hummingbot 策略配置指南

## 概述

Hummingbot 策略框架采用模块化设计，策略由 **脚本 (Script)** 和 **控制器 (Controller)** 组成。

```
┌─────────────────────────────────────────────────────────────┐
│                    策略架构                                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐                                        │
│  │   Script        │  ← 策略入口脚本                         │
│  │  (v2_with_      │                                        │
│  │   controllers)  │                                        │
│  └────────┬────────┘                                        │
│           │                                                  │
│  ┌────────┴────────┐                                        │
│  │   Controller    │  ← 策略控制器                           │
│  │  (autofish_v1)  │    - 定义策略逻辑                       │
│  │                 │    - 管理执行器                         │
│  └────────┬────────┘                                        │
│           │                                                  │
│  ┌────────┴────────┐                                        │
│  │   Executor      │  ← 执行器                               │
│  │  (Position      │    - 订单执行                           │
│  │   Executor)     │    - 止盈止损                           │
│  └─────────────────┘                                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
hummingbot_learning/
├── conf/                              # 配置目录
│   ├── connectors/                    # 交易所配置
│   │   └── binance_perpetual_testnet.yml
│   ├── controllers/                   # 控制器配置
│   │   └── autofish_v1_config.yml
│   ├── scripts/                       # 脚本配置
│   │   └── autofish_v1.yml
│   ├── .password_verification
│   ├── conf_client.yml
│   ├── conf_fee_overrides.yml
│   └── hummingbot_logs.yml
│
├── controllers/                       # 控制器目录
│   ├── __init__.py                    # 包初始化文件
│   └── generic/                       # 控制器类型目录
│       ├── __init__.py                # 导出控制器类
│       └── autofish_v1.py             # 控制器实现
│
├── scripts/                           # 脚本目录
│   └── v2_with_controllers.py         # 框架脚本入口 (Hummingbot 内置)
│
├── logs/                              # 日志目录
│   ├── logs_conf/
│   │   └── scripts/                   # 脚本日志
│   │       └── autofish_v1.log
│   ├── errors.log
│   └── logs_hummingbot.log
│
├── data/                              # 数据库目录
│   └── conf/
│       └── scripts/
│           └── autofish_v1.sqlite
│
├── docs/                              # 文档目录
│   └── strategy_guide.md
│
├── tests/                             # 测试目录
│   ├── backtest_autofish_v1.py        # 历史数据回测
│   ├── backtest_param_optimize.py     # 参数优化回测
│   ├── realtime_simulator.py          # 实时模拟（本地模拟）
│   ├── realtime_simulator_api.py      # 实时模拟（Binance API）
│   └── test_autofish_v1.py            # 单元测试
│
├── README.md
└── docker-compose.yml                 # Docker 配置
```

## 核心文件说明

### 1. 控制器 (Controller)

**位置**: `controllers/{controller_type}/{controller_name}.py`

控制器定义策略的核心逻辑：

- 继承 `ControllerBase`
- 定义配置类 `ControllerConfigBase`
- 实现 `on_tick()` 方法处理每个时钟周期
- 实现 `on_executor_processed()` 处理执行器完成事件

**示例**:

```python
from hummingbot.strategy_v2.controllers import ControllerBase, ControllerConfigBase

class AutofishV1Config(ControllerConfigBase):
    controller_name: str = "autofish_v1"
    connector_name: str = "binance_perpetual_testnet"
    trading_pair: str = "BTC-USDT"
    # ... 其他配置

class AutofishV1Controller(ControllerBase):
    def on_tick(self):
        # 每个时钟周期执行的逻辑
        pass
    
    def on_executor_processed(self, executor_info):
        # 执行器完成时的处理
        pass
```

### 2. 控制器配置

**位置**: `conf/controllers/{config_name}.yml`

```yaml
id: autofish_v1_config
controller_name: autofish_v1          # 控制器名称
controller_type: generic               # 控制器类型 → controllers/generic/

# 交易所配置
connector_name: binance_perpetual_testnet
trading_pair: BTC-USDT
leverage: 10

# 资金配置
total_amount_quote: 5000

# 网格参数
grid_spacing: 0.005
max_entries: 4

# 风控参数
stop_loss: 0.08
exit_profit: 0.005

# 订单类型配置 (1=MARKET, 2=LIMIT, 3=LIMIT_MAKER, 4=AMM_SWAP)
triple_barrier_config:
  take_profit: 0.005
  stop_loss: 0.08
  open_order_type: 3
  take_profit_order_type: 3
  stop_loss_order_type: 1
```

### 3. 脚本配置

**位置**: `conf/scripts/{config_name}.yml`

```yaml
script_file_name: v2_with_controllers
candles_config: []
markets: {}
controllers_config:
  - autofish_v1_config.yml             # 控制器配置文件名
max_global_drawdown_quote: null
max_controller_drawdown_quote: null
```

### 4. Docker Compose 配置

```yaml
services:
  hummingbot:
    image: hummingbot/hummingbot:latest
    container_name: hummingbot_learning
    volumes:
      - ./conf:/home/hummingbot/conf
      - ./conf/connectors:/home/hummingbot/conf/connectors
      - ./conf/controllers:/home/hummingbot/conf/controllers
      - ./conf/scripts:/home/hummingbot/conf/scripts
      - ./scripts:/home/hummingbot/scripts
      - ./controllers:/home/hummingbot/controllers
      - ./logs:/home/hummingbot/logs
      - ./logs/logs_conf:/home/hummingbot/logs/logs_conf
      - ./logs/logs_conf/scripts:/home/hummingbot/logs/logs_conf/scripts
      - ./logs/logs_conf/controllers:/home/hummingbot/logs/logs_conf/controllers
      - ./data:/home/hummingbot/data
    stdin_open: true
    tty: true
    restart: unless-stopped
    environment:
      - TZ=Asia/Shanghai
```

## 重要规则

### 控制器路径映射

| 配置项 | 路径 |
|--------|------|
| `controller_type: generic` | `controllers/generic/` |
| `controller_name: autofish_v1` | `controllers/generic/autofish_v1.py` |

### 订单类型枚举

| 数值 | 类型 | 说明 |
|------|------|------|
| 1 | MARKET | 市价单 |
| 2 | LIMIT | 限价单 |
| 3 | LIMIT_MAKER | 只做 Maker 限价单 |
| 4 | AMM_SWAP | AMM 交换 |

### 必须预先创建的目录

```bash
mkdir -p logs/logs_conf/scripts
mkdir -p logs/logs_conf/controllers
mkdir -p data
```

### 配置文件命名规则

- 不要在配置文件名中使用路径分隔符 `/`
- 使用简单的文件名，如 `autofish_v1.yml`
- 避免使用 `conf/scripts/autofish_v1.yml` 这样的命名

## CLI 命令

### 启动策略

```
>>> start --script v2_with_controllers --conf conf/scripts/autofish_v1.yml
```

### 停止策略

```
>>> stop
```

### 查看状态

```
>>> status
```

### 连接交易所

```
>>> connect binance_perpetual_testnet
```

### 创建控制器配置

```
>>> create --controller-config autofish_v1
```

## 常见问题

### 1. No module named 'controllers.generic'

**原因**: 控制器目录结构不正确

**解决**: 确保目录结构为 `controllers/generic/autofish_v1.py`

### 2. Input should be 1, 2, 3 or 4

**原因**: 订单类型使用了字符串而非枚举值

**解决**: 使用数字枚举值，如 `open_order_type: 3`

### 3. unable to open database file

**原因**: 数据库目录不存在

**解决**: 创建 `data/` 目录并设置权限

### 4. Unable to configure handler 'file_handler'

**原因**: 日志目录不存在

**解决**: 创建 `logs/logs_conf/scripts/` 目录

## 参考资料

- [Hummingbot 官方文档](https://hummingbot.org/)
- [策略框架](https://hummingbot.org/strategy-v2/)
- [控制器开发指南](https://hummingbot.org/strategy-v2/controllers/)
