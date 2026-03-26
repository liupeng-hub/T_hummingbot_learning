# Autofish Bot V2 系统流程图

本文档包含 Autofish Bot V2 回测系统的核心流程图，涵盖回测主流程、交易执行、资金管理和模块交互。

---

## 1. 回测程序主流程图

展示从数据获取到结果输出的完整流程。

```mermaid
flowchart TD
    subgraph 初始化阶段
        A[启动回测] --> B[解析命令行参数]
        B --> C[加载配置文件]
        C --> D[初始化回测引擎]
        D --> E[创建资金池]
        E --> F[创建行情检测器]
    end

    subgraph 数据获取阶段
        F --> G[连接数据源]
        G --> H{获取历史K线}
        H -->|成功| I[缓存K线数据]
        H -->|失败| J[记录错误并退出]
        I --> K[设置回测时间范围]
    end

    subgraph 回测执行阶段
        K --> L[创建首个A1订单]
        L --> M[遍历每根K线]
        M --> N[检查A1超时]
        N --> O[检测市场状态]
        O --> P{市场状态}
        P -->|震荡| Q[允许交易]
        P -->|趋势| R[平仓停止交易]
        Q --> S[处理入场触发]
        R --> T[清空所有订单]
        S --> U[处理出场触发]
        U --> V[更新资金池]
        V --> W[记录交易结果]
        W --> X{还有K线?}
        T --> X
        X -->|是| M
        X -->|否| Y[计算统计指标]
    end

    subgraph 结果输出阶段
        Y --> Z[生成回测报告]
        Z --> AA[保存交易记录]
        AA --> AB[输出统计摘要]
        AB --> AC[回测完成]
    end
```

---

## 2. 交易执行流程图

展示订单创建、入场、出场的完整流程。

```mermaid
flowchart TD
    subgraph 订单创建
        A[开始创建订单] --> B[获取层级level]
        B --> C[计算入场价格]
        C --> D{level == 1?}
        D -->|是| E[使用入场策略计算]
        D -->|否| F[网格间距计算]
        E --> G[计算止盈价格]
        F --> G
        G --> H[计算止损价格]
        H --> I[计算下单数量]
        I --> J[创建订单对象]
        J --> K[设置订单状态为pending]
        K --> L[添加到链式状态]
    end

    subgraph 入场检测
        L --> M[遍历pending订单]
        M --> N{K线最低价 <= 入场价?}
        N -->|是| O[触发入场]
        N -->|否| P[继续等待]
        O --> Q[更新订单状态为filled]
        Q --> R[记录入场时间]
        R --> S[记录入场资金]
        S --> T[更新group_id]
    end

    subgraph 出场检测
        T --> U[遍历filled订单]
        U --> V{K线最高价 >= 止盈价?}
        V -->|是| W[止盈触发]
        V -->|否| X{K线最低价 <= 止损价?}
        X -->|是| Y[止损触发]
        X -->|否| Z[继续持仓]
        W --> AA[计算盈利]
        Y --> AB[计算亏损]
        AA --> AC[更新订单状态为closed]
        AB --> AC
        AC --> AD[记录出场信息]
    end

    subgraph 后续处理
        AD --> AE{出场类型}
        AE -->|止盈| AF[取消pending订单]
        AE -->|止损| AG[清空所有订单]
        AF --> AH[创建同级新订单]
        AG --> AI[等待创建新A1]
        AH --> AJ[更新链式状态]
        AI --> AJ
    end
```

### 2.1 订单状态机

```mermaid
stateDiagram-v2
    [*] --> pending: 创建订单
    pending --> filled: K线触发入场
    pending --> cancelled: 超时取消/手动取消
    filled --> closed: 止盈触发
    filled --> closed: 止损触发
    filled --> closed: 市场状态变化强制平仓
    closed --> [*]: 订单完成
    cancelled --> [*]: 订单取消

    note right of pending
        等待入场触发
        状态: 挂单中
    end note

    note right of filled
        已成交持仓中
        等待止盈/止损
    end note

    note right of closed
        已平仓
        记录盈亏结果
    end note
```

---

## 3. 资金管理流程图

展示资金池更新、提现、爆仓恢复的流程。

```mermaid
flowchart TD
    subgraph 初始化
        A[创建资金池] --> B[设置初始资金]
        B --> C[选择提现策略]
        C --> D{策略类型}
        D -->|保守| E[阈值2.0x/保留1.5x]
        D -->|稳健| F[阈值3.0x/保留2.0x]
        D -->|激进| G[阈值1.5x/保留1.2x]
        D -->|福利| H[不提现]
        D -->|固定| I[无资金管理]
        E --> J[计算爆仓阈值]
        F --> J
        G --> J
        H --> J
        I --> K[固定资金模式]
    end

    subgraph 交易后更新
        J --> L[接收交易盈亏]
        L --> M{盈亏类型}
        M -->|盈利| N[增加交易资金]
        M -->|亏损| O[减少交易资金]
        N --> P[累计总盈利]
        O --> Q[累计总亏损]
        P --> R[更新最大资金]
        Q --> R
    end

    subgraph 提现检查
        R --> S{交易资金 >= 提现阈值?}
        S -->|是| T[触发提现]
        S -->|否| U[继续交易]
        T --> V[计算提现金额]
        V --> W[转入利润池]
        W --> X[保留指定倍数资金]
        X --> Y[提现次数+1]
        Y --> Z[记录提现历史]
    end

    subgraph 爆仓检查
        U --> AA{交易资金 < 爆仓阈值?}
        Z --> AA
        AA -->|是| AB[触发爆仓]
        AA -->|否| AC[继续监控]
        AB --> AD{利润池 >= 初始资金?}
        AD -->|是| AE[从利润池恢复]
        AD -->|否| AF[无法恢复]
        AE --> AG[重置交易资金]
        AG --> AH[爆仓次数+1]
        AH --> AI[记录爆仓历史]
    end

    subgraph 统计输出
        AC --> AJ[计算总收益率]
        AI --> AJ
        AJ --> AK[计算最大回撤]
        AK --> AL[输出统计报告]
    end
```

### 3.1 资金池状态流转

```mermaid
flowchart LR
    subgraph 正常增长
        A1[初始资金<br/>10000] --> A2[盈利累积<br/>15000]
        A2 --> A3[继续盈利<br/>20000]
    end

    subgraph 提现触发
        A3 --> B1{达到阈值<br/>20000 >= 20000?}
        B1 -->|是| B2[提现5000<br/>保留15000]
        B2 --> B3[利润池: 5000<br/>交易资金: 15000]
    end

    subgraph 爆仓恢复
        B3 --> C1[连续亏损<br/>资金降至800]
        C1 --> C2{低于阈值<br/>800 < 2000?}
        C2 -->|是| C3{利润池充足?}
        C3 -->|是| C4[从利润池恢复<br/>10000]
        C3 -->|否| C5[无法恢复<br/>停止交易]
    end
```

---

## 4. 系统模块交互图

展示各模块之间的调用关系。

```mermaid
flowchart TB
    subgraph 用户界面层
        UI1[命令行入口<br/>binance_backtest.py]
        UI2[测试管理器<br/>test_manager.py]
        UI3[Web界面<br/>test_results/]
    end

    subgraph 回测引擎层
        BE1[BacktestEngine<br/>基础回测引擎]
        BE2[MarketAwareBacktestEngine<br/>行情感知引擎]
        BE3[LongPortBacktestEngine<br/>港股回测引擎]
    end

    subgraph 核心模块层
        CM1[autofish_core.py<br/>核心策略模块]
        CM2[market_status_detector.py<br/>行情检测模块]
        CM3[binance_kline_fetcher.py<br/>数据获取模块]
    end

    subgraph 数据存储层
        DS1[test_results_db.py<br/>测试结果数据库]
        DS2[SQLite数据库<br/>test_results.db]
        DS3[JSON报告文件]
    end

    subgraph 外部服务
        ES1[Binance API]
        ES2[LongPort API]
        ES3[微信通知服务]
    end

    UI1 --> BE1
    UI1 --> BE2
    UI2 --> BE1
    UI2 --> BE2
    UI3 --> DS1

    BE1 --> CM1
    BE1 --> CM3
    BE2 --> CM1
    BE2 --> CM2
    BE2 --> CM3
    BE3 --> CM1

    CM1 --> DS3
    CM3 --> ES1
    BE3 --> ES2

    DS1 --> DS2

    style BE2 fill:#e1f5fe
    style CM1 fill:#fff3e0
    style CM2 fill:#e8f5e9
```

### 4.1 核心模块内部结构

```mermaid
flowchart TD
    subgraph autofish_core.py
        AC1[Autofish_Order<br/>订单数据类]
        AC2[Autofish_ChainState<br/>链式状态管理]
        AC3[Autofish_WeightCalculator<br/>权重计算器]
        AC4[Autofish_OrderCalculator<br/>订单计算器]
        AC5[Autofish_CapitalPool<br/>资金池管理]
        AC6[EntryCapitalStrategy<br/>入场资金策略]
    end

    subgraph market_status_detector.py
        MD1[MarketStatus<br/>市场状态枚举]
        MD2[MarketStatusDetector<br/>状态检测器]
        MD3[StatusAlgorithm<br/>算法基类]
        MD4[RealTimeStatusAlgorithm<br/>实时算法]
        MD5[ImprovedStatusAlgorithm<br/>改进算法]
        MD6[DualThrustAlgorithm<br/>DualThrust算法]
        MD7[ADXAlgorithm<br/>ADX算法]
    end

    subgraph 数据流
        AC2 --> AC1
        AC4 --> AC1
        AC4 --> AC3
        AC5 --> AC6
        MD2 --> MD3
        MD3 --> MD4
        MD3 --> MD5
        MD3 --> MD6
        MD3 --> MD7
    end
```

### 4.2 回测执行时序图

```mermaid
sequenceDiagram
    participant CLI as 命令行
    participant Engine as 回测引擎
    participant Fetcher as 数据获取器
    participant Detector as 行情检测器
    participant Capital as 资金池
    participant State as 链式状态

    CLI->>Engine: 启动回测(参数)
    Engine->>Fetcher: 获取历史K线
    Fetcher-->>Engine: 返回K线数据
    Engine->>Capital: 初始化资金池
    Engine->>State: 创建初始状态
    Engine->>State: 创建A1订单

    loop 遍历每根K线
        Engine->>Detector: 检测市场状态
        Detector-->>Engine: 返回状态(震荡/趋势)
        
        alt 震荡状态
            Engine->>State: 检查入场触发
            State-->>Engine: 返回触发订单
            Engine->>State: 更新订单状态
            Engine->>State: 检查出场触发
            State-->>Engine: 返回出场订单
            Engine->>Capital: 更新资金池
            Engine->>Capital: 检查提现/爆仓
        else 趋势状态
            Engine->>State: 平仓所有订单
            Engine->>Capital: 更新资金池
        end
    end

    Engine->>Engine: 计算统计指标
    Engine->>Engine: 生成报告
    Engine-->>CLI: 返回结果
```

---

## 5. 关键决策点说明

### 5.1 入场决策

| 决策点 | 条件 | 动作 |
|--------|------|------|
| A1入场价计算 | level == 1 | 使用入场策略(ATR/Fixed/Percentage) |
| A2+入场价计算 | level > 1 | 基准价 × (1 - grid_spacing × level) |
| 入场触发 | K线最低价 <= 入场价 | 更新状态为filled，记录入场资金 |

### 5.2 出场决策

| 决策点 | 条件 | 动作 |
|--------|------|------|
| 止盈触发 | K线最高价 >= 止盈价 | 平仓，计算盈利，创建同级新订单 |
| 止损触发 | K线最低价 <= 止损价 | 平仓，计算亏损，清空所有订单 |
| 同时触发 | 止盈和止损同时满足 | 根据K线阴阳线判断顺序 |

### 5.3 资金管理决策

| 决策点 | 条件 | 动作 |
|--------|------|------|
| 提现触发 | 交易资金 >= 初始资金 × 提现阈值 | 转移超出部分到利润池 |
| 爆仓触发 | 交易资金 < 初始资金 × 爆仓阈值 | 尝试从利润池恢复 |
| 恢复成功 | 利润池 >= 初始资金 | 重置交易资金为初始资金 |

### 5.4 市场状态决策

| 决策点 | 条件 | 动作 |
|--------|------|------|
| 震荡转趋势 | 状态从RANGING变为TRENDING | 平仓所有订单，停止交易 |
| 趋势转震荡 | 状态从TRENDING变为RANGING | 创建新A1订单，恢复交易 |
| 保持震荡 | 状态保持RANGING | 正常执行交易逻辑 |

---

## 6. 数据流向标注

```
┌─────────────────────────────────────────────────────────────────┐
│                        数据流向总览                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [外部数据源]                                                    │
│       │                                                         │
│       ▼                                                         │
│  [K线数据] ──────► [行情检测器] ──────► [市场状态]               │
│       │                                    │                    │
│       ▼                                    ▼                    │
│  [回测引擎] ◄──────────────────── [交易控制]                    │
│       │                                                         │
│       ▼                                                         │
│  [链式状态] ──────► [订单管理] ──────► [交易记录]               │
│       │                                    │                    │
│       ▼                                    ▼                    │
│  [资金池] ◄─────────────────────── [盈亏计算]                   │
│       │                                                         │
│       ▼                                                         │
│  [统计报告] ──────► [数据库存储] ──────► [Web展示]              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. 配置参数流向

```mermaid
flowchart LR
    subgraph 输入配置
        C1[振幅参数<br/>amplitude]
        C2[行情参数<br/>market]
        C3[入场参数<br/>entry]
        C4[超时参数<br/>timeout]
        C5[资金参数<br/>capital]
    end

    subgraph 参数处理
        P1[参数验证]
        P2[默认值填充]
        P3[类型转换]
    end

    subgraph 模块配置
        M1[回测引擎配置]
        M2[行情检测器配置]
        M3[入场策略配置]
        M4[资金池配置]
    end

    C1 --> P1
    C2 --> P1
    C3 --> P1
    C4 --> P1
    C5 --> P1

    P1 --> P2
    P2 --> P3

    P3 --> M1
    P3 --> M2
    P3 --> M3
    P3 --> M4
```

---

*文档生成时间: 2026-03-26*
*版本: V2.0*
