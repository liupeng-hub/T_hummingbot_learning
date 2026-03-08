# 文档更新计划

## 一、更新背景

### 近期代码变更

1. **入场价格策略**
   - 新增 5 种入场价格策略：fixed, atr, bollinger, support, composite
   - 振幅分析支持 `--entry-strategy` 参数
   - 配置文件新增 `entry_price_strategy` 字段
   - 报告文件新增入场策略说明

2. **CLI 参数简化**
   - `binance_live.py` 移除 `--stop-loss` 和 `--total-amount` 参数
   - 这些参数从配置文件读取

3. **配置文件变化**
   - 新增 `entry_price_strategy` 字段
   - 默认入场策略：ATR

## 二、需要更新的文档

### 2.1 README.md

#### 修改位置

1. **振幅分析命令行参数表格**（第 75-85 行）
   - 新增 `--entry-strategy` 参数说明

2. **振幅分析示例**（第 48-73 行）
   - 新增入场策略选择示例

3. **Binance 回测命令行参数表格**（第 110-120 行）
   - 移除 `--stop-loss` 和 `--total-amount` 说明

4. **Binance 实盘命令行参数表格**（第 148-158 行）
   - 移除 `--stop-loss` 和 `--total-amount` 说明

5. **配置文件格式示例**（第 309-338 行）
   - 新增 `entry_price_strategy` 字段

6. **配置参数说明表格**（第 352-365 行）
   - 新增 `entry_price_strategy` 参数说明

7. **V2 版本更新**（第 378-399 行）
   - 新增入场价格策略说明

### 2.2 docs/binance_live_design.md

#### 修改位置

1. **命令行参数说明**
   - 移除 `--stop-loss` 和 `--total-amount` 参数

2. **配置加载说明**
   - 说明入场策略从配置文件读取

### 2.3 docs/entry_price_strategy.md

#### 已完成

- 该文档已创建，包含完整的入场策略说明

## 三、具体修改内容

### 3.1 README.md 修改

#### 3.1.1 振幅分析命令行参数

```markdown
**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --interval | 1d | K线周期 |
| --limit | 1000 | K线数量 |
| --leverage | 10 | 杠杆倍数（LongPort 股票默认为 1） |
| --source | binance | 数据源: binance 或 longport |
| --output | None | 输出文件路径 |
| --entry-strategy | atr | 入场价格策略: fixed, atr, bollinger, support, composite |
```

#### 3.1.2 振幅分析示例

```markdown
# 使用 ATR 入场策略（默认）
python autofish_core.py --symbol BTCUSDT

# 使用布林带入场策略
python autofish_core.py --symbol BTCUSDT --entry-strategy bollinger

# 使用综合入场策略
python autofish_core.py --symbol BTCUSDT --entry-strategy composite
```

#### 3.1.3 Binance 回测命令行参数

```markdown
**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --interval | 1h | K线周期 |
| --limit | 500 | K线数量 |
| --decay-factor | 0.5 | 衰减因子（0.5 激进 / 1.0 保守） |

**说明**：
- 回测会自动加载对应的振幅配置文件 `{source}_{symbol}_amplitude_config.json`
- 根据指定的 `--decay-factor` 读取对应的策略配置（d_0.5 或 d_1.0）
- 如果没有振幅配置文件，则使用内置默认配置
- `stop_loss`、`total_amount_quote`、`entry_price_strategy` 从配置文件读取
```

#### 3.1.4 Binance 实盘命令行参数

```markdown
**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --testnet | - | 使用测试网 |
| --no-testnet | - | 使用主网 |
| --decay-factor | 0.5 | 衰减因子（0.5 激进 / 1.0 保守） |

**说明**：
- 实盘会自动加载对应的振幅配置文件 `{source}_{symbol}_amplitude_config.json`
- 根据指定的 `--decay-factor` 读取对应的策略配置（d_0.5 或 d_1.0）
- 如果没有振幅配置文件，则使用内置默认配置
- `stop_loss`、`total_amount_quote`、`entry_price_strategy` 从配置文件读取
```

#### 3.1.5 配置文件格式

```json
{
  "d_0.5": {
    "symbol": "BTCUSDT",
    "total_amount_quote": 1200,
    "leverage": 10,
    "decay_factor": 0.5,
    "max_entries": 4,
    "valid_amplitudes": [1, 2, 3, 4, 5, 6, 7, 8, 9],
    "weights": [0.0852, 0.2956, 0.3177, 0.137, 0.1008, 0.0282, 0.0271, 0.0066, 0.0019],
    "grid_spacing": 0.01,
    "exit_profit": 0.01,
    "stop_loss": 0.08,
    "total_expected_return": 0.2942,
    "entry_price_strategy": {
      "name": "atr",
      "params": {
        "atr_period": 14,
        "atr_multiplier": 0.5,
        "min_spacing": 0.005,
        "max_spacing": 0.03
      }
    }
  },
  "d_1.0": {
    ...
    "entry_price_strategy": {
      "name": "atr",
      "params": {
        "atr_period": 14,
        "atr_multiplier": 0.5,
        "min_spacing": 0.005,
        "max_spacing": 0.03
      }
    }
  }
}
```

#### 3.1.6 配置参数说明

```markdown
| 参数 | 默认值 | 说明 |
|------|--------|------|
| symbol | BTCUSDT | 交易对 |
| total_amount_quote | 1200 | 总投入金额 |
| leverage | 10 | 杠杆倍数（LongPort 股票为 1） |
| decay_factor | 0.5 | 权重衰减因子（0.5 激进 / 1.0 保守） |
| max_entries | 4 | 最大层级（读取前N个权重） |
| valid_amplitudes | [1,2,3,4,5,6,7,8,9] | 有效振幅区间 |
| weights | [...] | 各层级权重列表 |
| grid_spacing | 0.01 (1%) | 网格间距 |
| exit_profit | 0.01 (1%) | 止盈比例 |
| stop_loss | 0.08 (8%) | 止损比例 |
| entry_price_strategy | {"name": "atr", ...} | 入场价格策略配置 |
```

#### 3.1.7 V2 版本更新

```markdown
## V2 版本更新

### 主要变更

1. **代码整合**：将 `amplitude_analyzer.py` 合并到 `autofish_core.py`，减少文件数量
2. **类名统一**：所有类增加 `Autofish_` 前缀，避免命名冲突
3. **脚本整合**：`start.sh`、`stop.sh`、`status.sh` 合并为 `binance_live_run.sh`
4. **日志统一**：所有日志输出到 `logs/` 目录
5. **代理支持**：振幅分析自动从 `.env` 读取代理配置
6. **双策略支持**：配置文件同时包含 d=0.5（激进）和 d=1.0（保守）两种策略
7. **配置简化**：移除冗余参数，统一使用 `--decay-factor` 选择策略
8. **入场价格策略**：支持 5 种入场价格策略（fixed, atr, bollinger, support, composite）
9. **CLI 简化**：移除 `--stop-loss` 和 `--total-amount` 参数，从配置文件读取
```

### 3.2 docs/binance_live_design.md 修改

#### 3.2.1 命令行参数说明

```markdown
### 7.1 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --testnet | - | 使用测试网 |
| --no-testnet | - | 使用主网 |
| --decay-factor | 0.5 | 衰减因子（0.5 激进 / 1.0 保守） |

**说明**：
- `stop_loss`、`total_amount_quote`、`entry_price_strategy` 从配置文件读取
- 配置文件由振幅分析生成，或使用内置默认配置
```

## 四、实施步骤

### 步骤 1: 更新 README.md

- 更新振幅分析命令行参数
- 更新振幅分析示例
- 更新 Binance 回测命令行参数
- 更新 Binance 实盘命令行参数
- 更新配置文件格式示例
- 更新配置参数说明
- 更新 V2 版本更新说明

### 步骤 2: 更新 docs/binance_live_design.md

- 更新命令行参数说明
- 添加配置文件读取说明

### 步骤 3: 验证

- 检查所有文档的一致性
- 确保示例代码正确

## 五、注意事项

1. 保持文档风格一致
2. 确保示例代码可执行
3. 更新后提交到 Git
