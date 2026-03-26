# 资金池策略与入场资金计算统一架构设计

## 背景
当前在 `binance_backtest.py` 文件中，资金池管理逻辑和入场资金计算逻辑分散且命名不一致：
- `capital_pool_strategy` 配置文件中定义了资金池管理策略（guding/baoshou/wenjian/jijin/fuli/zidingyi）
- 新创建的 `EntryCapitalStrategy` 定义了入场资金计算策略

两者关系不清晰，导致概念混乱。需要将两者统一，使架构更清晰。

## 核心概念澄清

### 资金池策略（Capital Pool Strategy）
**职责**：管理资金池的整体行为
- 如何处理交易盈亏
- 何时进行提现
- 爆仓后如何恢复
- **如何计算入场资金**（新增）

### 入场资金计算（Entry Capital Calculation）
**职责**：计算每个订单的入场资金和入场总资金
- 原来是独立的策略体系
- **现在作为资金池策略的一部分**

## 新架构设计

### 类关系图

```
┌─────────────────────────────────────────────────────────────────┐
│              CapitalPoolStrategy (抽象基类)                      │
│                    资金池策略                                    │
├─────────────────────────────────────────────────────────────────┤
│  # 资金池管理方法                                                │
│  + process_trade_profit(profit: Decimal) -> Dict                │
│  + check_withdrawal() -> Optional[Dict]                         │
│  + check_liquidation() -> Optional[Dict]                        │
│  + get_statistics() -> Dict                                     │
│                                                                 │
│  # 入场资金计算方法（统一整合）                                   │
│  + calculate_entry_capital(level: int, chain_state: Any)        │
│    -> Decimal                                                   │
│  + calculate_entry_total_capital(level: int, chain_state: Any)  │
│    -> Decimal                                                   │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ 继承
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌──────────────────┐    ┌──────────────────┐
│FixedCapital   │    │ProgressiveCapital│    │ CustomCapital    │
│Strategy       │    │   Strategy       │    │   Strategy       │
│   (固定模式)   │    │   (递进模式)      │    │   (自定义)        │
├───────────────┤    ├──────────────────┤    ├──────────────────┤
│               │    │                  │    │                  │
│ 资金池管理:    │    │ 资金池管理:       │    │ 资金池管理:       │
│ - 不提现       │    │ - 自动提现        │    │ - 自定义参数      │
│ - 不恢复       │    │ - 爆仓恢复        │    │                  │
│               │    │                  │    │                  │
│ 入场资金计算:  │    │ 入场资金计算:     │    │ 入场资金计算:     │
│ - 始终用初始   │    │ - 根据entry_mode  │    │ - 根据entry_mode  │
│   资金         │    │   决定           │    │   决定           │
│               │    │                  │    │                  │
│               │    │ entry_mode:      │    │ entry_mode:      │
│               │    │ - fixed: 固定     │    │ - fixed: 固定     │
│               │    │ - compound: 复利  │    │ - compound: 复利  │
│               │    │ - default: 默认   │    │ - default: 默认   │
└───────────────┘    └──────────────────┘    └──────────────────┘
```

### 配置文件设计（JSON）

```json
{
  "capital_pool_strategy": {
    "strategy": "guding",
    "entry_mode": "fixed",
    "baoshou": {
      "withdrawal_threshold": 2.0,
      "withdrawal_retain": 1.5
    },
    "wenjian": {
      "withdrawal_threshold": 3.0,
      "withdrawal_retain": 2.0
    },
    "jijin": {
      "withdrawal_threshold": 1.5,
      "withdrawal_retain": 1.2
    },
    "fuli": {
      "withdrawal_threshold": 999.0,
      "withdrawal_retain": 1.0
    },
    "zidingyi": {
      "withdrawal_threshold": 2.0,
      "withdrawal_retain": 1.5
    }
  }
}
```

**配置说明**：
- `strategy`: 主策略类型（guding/baoshou/wenjian/jijin/fuli/zidingyi）
- `entry_mode`: 入场资金计算模式（fixed/compound/default）
  - `fixed`: 始终使用初始资金
  - `compound`: 使用总资金（交易资金+利润池）
  - `default`: 入场资金=交易资金，入场总资金=总资金
- 各子策略配置参数：
  - `withdrawal_threshold`: 提现阈值（资金达到初始资金的倍数时提现）
  - `withdrawal_retain`: 提现后保留倍数（提现后保留初始资金的倍数）
- 注：
  - `initial_capital`（初始资金）来自于其他配置文件中的 `total_amount_quote` 字段
  - `liquidation_threshold`（爆仓阈值）由系统自动根据杠杆和止损比例计算得出，无需手动配置

## 修订计划

### [/] 任务 1: 重构资金池策略基类
- **Priority**: P0
- **Depends On**: None
- **Description**:
  - 在 `CapitalPoolStrategy` 抽象基类中添加入场资金计算方法
  - 移除独立的 `EntryCapitalStrategy` 体系
  - 统一命名和概念
- **Success Criteria**:
  - 基类包含 `calculate_entry_capital` 和 `calculate_entry_total_capital` 方法
  - 所有子类正确实现这些方法
- **Test Requirements**:
  - `programmatic` TR-1.1: 基类能够正确定义
  - `programmatic` TR-1.2: 子类能够正确实现方法

### [ ] 任务 2: 修改具体资金池策略类
- **Priority**: P0
- **Depends On**: 任务 1
- **Description**:
  - 修改 `FixedCapitalTracker`，实现入场资金计算方法（固定模式）
  - 修改 `ProgressiveCapitalTracker`，支持根据 `entry_mode` 计算入场资金
  - 移除 `EntryCapitalStrategy` 相关类
- **Success Criteria**:
  - `FixedCapitalTracker` 始终返回初始资金
  - `ProgressiveCapitalTracker` 根据配置决定计算方式
- **Test Requirements**:
  - `programmatic` TR-2.1: 固定模式计算正确
  - `programmatic` TR-2.2: 递进模式各entry_mode计算正确

### [ ] 任务 3: 更新 JSON 配置文件
- **Priority**: P1
- **Depends On**: 任务 2
- **Description**:
  - 在 `autofish_extern_strategy.json` 中添加 `entry_mode` 配置
  - 为每个策略配置合适的默认值
  - 更新配置文档
- **Success Criteria**:
  - JSON文件包含 `entry_mode` 配置
  - 各策略配置合理
- **Test Requirements**:
  - `programmatic` TR-3.1: JSON格式正确
  - `human-judgement` TR-3.2: 配置逻辑合理

### [ ] 任务 4: 修改数据库保存资金池参数
- **Priority**: P1
- **Depends On**: 任务 3
- **Description**:
  - 检查 `test_results_db.py` 中资金池参数的保存逻辑
  - 确保 `entry_mode` 被正确保存到数据库
  - 更新数据库schema（如需要）
- **Success Criteria**:
  - 资金池参数包含 `entry_mode`
  - 历史数据兼容性处理
- **Test Requirements**:
  - `programmatic` TR-4.1: 参数能够正确保存
  - `programmatic` TR-4.2: 参数能够正确读取

### [ ] 任务 5: 修改回测引擎识别参数
- **Priority**: P0
- **Depends On**: 任务 4
- **Description**:
  - 修改 `binance_backtest.py`，从配置中读取 `entry_mode`
  - 根据 `entry_mode` 调用相应的入场资金计算方法
  - 移除对 `EntryCapitalStrategyFactory` 的依赖
- **Success Criteria**:
  - 回测引擎正确识别 `entry_mode` 参数
  - 入场资金计算逻辑正确
- **Test Requirements**:
  - `programmatic` TR-5.1: 不同entry_mode回测正常
  - `human-judgement` TR-5.2: 资金计算结果符合预期

### [ ] 任务 6: 修改 web 页面配置资金池策略
- **Priority**: P1
- **Depends On**: 任务 5
- **Description**:
  - 修改 web 配置页面，添加入场资金计算模式（entry_mode）的选择
  - 更新结果展示页面，显示入场资金计算模式
  - 调整 API 接口，支持 entry_mode 参数的传递
- **Success Criteria**:
  - web 页面能够正确配置 entry_mode
  - 结果页面能够显示 entry_mode
  - API 接口能够正确处理 entry_mode 参数
- **Test Requirements**:
  - `programmatic` TR-6.1: web 页面加载无错误
  - `human-judgement` TR-6.2: 页面 UI 美观，操作流畅

### [ ] 任务 7: 测试和验证
- **Priority**: P1
- **Depends On**: 任务 6
- **Description**:
  - 运行回测测试，验证不同策略组合
  - 对比新旧版本的资金计算结果
  - 确保功能一致性
- **Success Criteria**:
  - 所有策略组合回测正常
  - 资金计算结果正确
- **Test Requirements**:
  - `programmatic` TR-7.1: 回测运行无错误
  - `programmatic` TR-7.2: 资金计算结果与预期一致

## 回测参数识别流程

```
回测开始
    │
    ▼
读取 capital_pool_strategy 配置
    │
    ├─── strategy: guding ────────┐
    │                              ▼
    ├─── strategy: baoshou ──────► 创建对应策略实例
    │                              │   (FixedCapitalTracker/
    ├─── strategy: wenjian ──────┤    ProgressiveCapitalTracker)
    │                              │
    ├─── strategy: jijin ────────┤
    │                              │
    ├─── strategy: fuli ─────────┤
    │                              │
    └─── strategy: zidingyi ─────┘
                                   │
                                   ▼
                    读取 entry_mode 配置
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                    ▼              ▼              ▼
                 fixed        compound        default
                    │              │              │
                    ▼              ▼              ▼
              始终使用初始    使用总资金      入场资金=交易资金
                资金         (交易+利润)      入场总资金=总资金
                    │              │              │
                    └──────────────┼──────────────┘
                                   │
                                   ▼
                    执行回测，使用对应计算方式
                                   │
                                   ▼
                    保存结果到数据库（包含entry_mode）
```

## Web 页面配置修改分析

### 1. 配置页面修改
- **添加 entry_mode 选择器**：在资金池策略配置区域添加入场资金计算模式的下拉选择
- **选项**：固定模式（fixed）、复利模式（compound）、默认模式（default）
- **默认值**：根据策略类型自动设置
  - 固定模式（guding）：默认选择 fixed
  - 其他策略：默认选择 compound

### 2. 结果展示页面修改
- **添加 entry_mode 显示**：在结果详情页面显示使用的入场资金计算模式
- **用例详情页面**：在配置参数区域展示 entry_mode 参数及其默认值
- **资金按钮弹出子页面**：在测试结果列表的详情页面中，资金按钮的弹出子页面增加显示 entry_mode 参数
- **资金计算结果对比**：在交易详情表格中显示入场资金和入场总资金的计算结果

### 3. API 接口修改
- **配置保存接口**：支持保存 entry_mode 参数
- **结果查询接口**：返回 entry_mode 参数
- **兼容性处理**：对历史数据使用默认值（fixed 或 compound）

### 4. 前端代码修改
- **文件**：`web/test_results/index.html`
- **修改点**：
  - 配置表单区域添加 entry_mode 选择器
  - 结果展示区域添加 entry_mode 显示
  - API 调用时包含 entry_mode 参数

### 5. 后端代码修改
- **文件**：`test_manager.py`
- **修改点**：
  - 接收和处理 entry_mode 参数
  - 保存 entry_mode 到数据库
  - 返回 entry_mode 到前端

## 数据库设计

### 资金池参数存储

资金池参数已经在策略用例中以JSON格式保存，无需单独设计数据库表。

**存储位置**：`test_results` 表的 `capital` 字段（JSON格式）

**存储内容示例**：
```json
{
  "strategy": "baoshou",
  "entry_mode": "compound",
  "params": {
    "withdrawal_threshold": 2.0,
    "withdrawal_retain": 1.5
  }
}
```

**字段说明**：
- `strategy`: 资金池策略类型
- `entry_mode`: 入场资金计算模式
- `params`: 子策略参数（withdrawal_threshold, withdrawal_retain）
- 注：`initial_capital`（初始资金）来自于其他配置文件中的 `total_amount_quote` 字段

## 预期效果

1. **架构清晰**：资金池策略统一管理资金行为和入场资金计算
2. **配置简单**：用户只需配置 `capital_pool_strategy`，自动决定入场资金计算方式
3. **扩展性强**：新增策略时只需继承基类并实现相应方法
4. **向后兼容**：历史数据通过默认值保持兼容
