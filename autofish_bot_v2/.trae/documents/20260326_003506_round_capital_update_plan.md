# 轮次资金更新实现计划

## 问题分析
用户报告在同一个轮次中，连续盈利几个订单记录中，总入场资金没有变化。从提供的数据来看：
- 轮次 6：入场资金 10507.05，盈利 +104.45
- 轮次 7：入场资金 10611.51（包含了轮次 6 的盈利），盈利 +380.33 和 +105.49
- 轮次 8：入场资金 11097.33（包含了轮次 7 的盈利）

问题在于：轮次 7 内部的两个交易使用了相同的入场资金 10611.51，没有反映轮次内部的盈利累积。

## 任务分解

### [x] 任务 1：分析当前轮次资金管理逻辑
- **Priority**: P0
- **Depends On**: None
- **Description**: 分析 `binance_backtest.py` 中轮次资金的设置和管理逻辑，特别是 `_process_entry` 方法中如何设置 `round_entry_capital` 和 `round_entry_total_capital`。
- **Success Criteria**: 理解当前轮次资金的设置时机和更新逻辑。
- **Test Requirements**:
  - `programmatic` TR-1.1: 确认轮次资金在 A1 入场时设置，后续 A2/A3/A4 入场时使用相同值。
  - `programmatic` TR-1.2: 确认交易后资金池更新但轮次资金不更新。
- **Completion Notes**: 已分析当前逻辑，轮次资金在 A1 入场时设置，后续交易使用相同值，交易后资金池更新但轮次资金不更新。

### [ ] 任务 2：修改轮次资金更新逻辑
- **Priority**: P0
- **Depends On**: 任务 1
- **Description**: 修改 `_update_capital_after_trade` 方法，在每笔交易后更新当前轮次的总资金，使其反映累积的盈利或亏损。
- **Success Criteria**: 同一轮次中的后续交易使用更新后的总资金值。
- **Test Requirements**:
  - `programmatic` TR-2.1: 同一轮次中，第二笔交易的入场资金应包含第一笔交易的盈利。
  - `programmatic` TR-2.2: 轮次结束后，新轮次的入场资金应包含上一轮次的所有盈利。

### [ ] 任务 3：测试轮次资金更新逻辑
- **Priority**: P1
- **Depends On**: 任务 2
- **Description**: 运行回测测试，验证同一轮次中的资金更新逻辑是否正确。
- **Success Criteria**: 回测结果显示同一轮次中的后续交易使用更新后的总资金值。
- **Test Requirements**:
  - `programmatic` TR-3.1: 运行回测，验证同一轮次中多笔交易的资金值是否正确累积。
  - `human-judgement` TR-3.2: 检查交易详情中的入场资金和总资金值是否符合预期。

### [ ] 任务 4：重启 Web 服务并验证结果
- **Priority**: P1
- **Depends On**: 任务 3
- **Description**: 重启 Web 服务，让用户可以查看修复后的结果。
- **Success Criteria**: Web 服务正常运行，用户可以查看修复后的测试结果。
- **Test Requirements**:
  - `programmatic` TR-4.1: Web 服务成功启动在端口 5002。
  - `human-judgement` TR-4.2: 用户可以在 Web 界面上查看修复后的测试结果。

## 实现思路
1. 在 `_update_capital_after_trade` 方法中，在更新资金池后，同时更新 `self.chain_state.round_entry_total_capital`。
2. 确保 `_process_entry` 方法在设置 A2/A3/A4 订单的 `entry_total_capital` 时使用更新后的值。
3. 保持 `round_entry_capital` 在轮次开始时设置，保持不变，以确保订单金额计算的一致性。

## 预期结果
- 同一轮次中的所有交易：入场资金保持不变，使用轮次开始时的资金值
- 同一轮次中的第一笔交易：入场总资金使用轮次开始时的资金值
- 同一轮次中的第二笔交易：入场总资金使用第一笔交易后的资金值（包含第一笔的盈利）
- 同一轮次中的第三笔交易：入场总资金使用第二笔交易后的资金值（包含前两笔的盈利）
- 轮次结束后：新轮次使用上一轮次结束时的资金值作为新的轮次开始资金值