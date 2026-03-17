# 导出位置和内容设计

## 1. 当前问题

当前各组件输出位置分散：

| 组件 | 当前输出位置 |
|------|-------------|
| `test_manager.py export` | 用户指定或控制台 |
| `optuna_dual_thrust_optimizer.py` | `out/market_optimization/` |
| `optuna_improved_strategy_optimizer.py` | `out/market_optimization/` |

**问题**：
1. 缺少统一的导出位置和命名规则
2. 各组件输出位置不一致
3. 缺少统一的报告内容格式

## 2. 设计方案

### 2.1 统一导出位置

```
out/test_report/
├── README.md                  # 汇总索引文件
├── backtest/                  # 普通回测
│   ├── *.md                   # MD 报告
│   └── *_trades.csv           # CSV 交易明细
├── market_aware/              # 行情感知回测
│   ├── *.md                   # MD 报告
│   └── *_trades.csv           # CSV 交易明细
├── visualizer/                # 行情可视化
│   ├── *.md                   # MD 报告
│   ├── *_daily.csv            # CSV 每日状态明细
│   ├── *.png                  # PNG 图表文件
│   └── *.html                 # HTML 交互文件
├── optimizer_DualThrust/      # Dual Thrust 参数优化
│   ├── *.md                   # MD 报告
│   └── *_results.csv          # CSV 优化结果
├── optimizer_Improved/        # Improved 参数优化
│   ├── *.md                   # MD 报告
│   └── *_results.csv          # CSV 优化结果
└── longport/                  # 港股回测
    ├── *.md                   # MD 报告
    └── *_trades.csv           # CSV 交易明细
```

### 2.2 命名规则

#### 2.2.1 回测类型（backtest, market_aware, longport）

**MD 报告命名**：`{symbol}_{date_range}_{execution_id}.md`
**CSV 交易明细命名**：`{symbol}_{date_range}_{execution_id}_trades.csv`

#### 2.2.2 行情可视化（visualizer）

**统一命名前缀**：`{symbol}_{date_range}_{algorithm}_{result_id}`

| 类型 | 文件名 |
|------|--------|
| MD 报告 | `{prefix}.md` |
| CSV 每日状态 | `{prefix}_daily.csv` |
| PNG 图表 | `{prefix}.png` |
| HTML 交互 | `{prefix}.html` |

#### 2.2.3 参数优化（optimizer_DualThrust, optimizer_Improved）

**MD 报告命名**：`{symbol}_{date_range}_{algorithm}_{optimizer_id}.md`
**CSV 优化结果命名**：`{symbol}_{date_range}_{algorithm}_{optimizer_id}_results.csv`

---

## 3. MD 报告内容设计

### 3.1 普通回测（backtest）

```markdown
# {symbol} 回测报告

**执行ID**: {execution_id}
**生成时间**: {generated_at}

---

## 基本信息

| 项目 | 值 |
|------|-----|
| 交易对 | {symbol} |
| K线周期 | {interval} |
| 开始时间 | {start_time} |
| 结束时间 | {end_time} |
| K线数量 | {klines_count} |
| 测试类型 | backtest |

## 配置参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 杠杆 | {leverage}x | - |
| 总投入 | {total_amount_quote} USDT | - |
| 网格间距 | {grid_spacing}% | 入场价 = 基准价 × (1 - 网格间距) |
| 止盈比例 | {exit_profit}% | 止盈价 = 入场价 × (1 + 止盈比例) |
| 止损比例 | {stop_loss}% | 止损价 = 入场价 × (1 - 止损比例) |
| 衰减因子 | {decay_factor} | 权重计算参数 |
| 最大层级 | {max_entries} | 最多挂单层数 |

## 回测结果

| 指标 | 值 |
|------|-----|
| 总交易次数 | {total_trades} |
| 盈利次数 | {win_trades} |
| 亏损次数 | {loss_trades} |
| 胜率 | {win_rate}% |
| 总盈利 | {total_profit} USDT |
| 总亏损 | {total_loss} USDT |
| 净收益 | {net_profit} USDT |
| 收益率 | {roi}% |

## 对比分析

| 指标 | 值 | 说明 |
|------|-----|------|
| 标的涨跌幅 | {price_change}% | 同期 {symbol} 涨跌 |
| 策略收益率 | {roi}% | 策略净收益率 |
| 超额收益 | {excess_return}% | 策略收益 - 标的涨跌 |

## 风险指标

| 指标 | 值 | 说明 |
|------|-----|------|
| 盈亏比 | {profit_loss_ratio} | 平均盈利 / 平均亏损 |
| 夏普比率 | {sharpe_ratio} | 风险调整后收益 |
| 最大单笔盈利 | {max_profit} USDT | - |
| 最大单笔亏损 | {max_loss} USDT | - |

## 交易明细

| 层级 | 入场价 | 出场价 | 类型 | 盈亏 | 入场时间 | 出场时间 |
|------|--------|--------|------|------|----------|----------|
| A1 | 50000.00 | 50500.00 | 止盈 | +50.00 | 2026-03-01 10:00 | 2026-03-01 14:00 |
| A2 | 49500.00 | 49000.00 | 止损 | -50.00 | 2026-03-02 09:00 | 2026-03-02 15:00 |
| ... | ... | ... | ... | ... | ... | ... |

---

*交易明细CSV: {csv_filename}*
```

### 3.2 行情感知回测（market_aware）

```markdown
# {symbol} 行情感知回测报告

**执行ID**: {execution_id}
**生成时间**: {generated_at}

---

## 基本信息

| 项目 | 值 |
|------|-----|
| 交易对 | {symbol} |
| K线周期 | {interval} |
| 行情判断周期 | {market_interval} |
| 行情判断算法 | {algorithm} |
| 开始时间 | {start_time} |
| 结束时间 | {end_time} |
| K线数量 | {klines_count} |
| 测试类型 | market_aware |

## 配置参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 杠杆 | {leverage}x | - |
| 总投入 | {total_amount_quote} USDT | - |
| 网格间距 | {grid_spacing}% | - |
| 止盈比例 | {exit_profit}% | - |
| 止损比例 | {stop_loss}% | - |
| 行情算法 | {algorithm} | 行情判断算法 |

## 回测结果

| 指标 | 值 |
|------|-----|
| 总交易次数 | {total_trades} |
| 盈利次数 | {win_trades} |
| 亏损次数 | {loss_trades} |
| 胜率 | {win_rate}% |
| 总盈利 | {total_profit} USDT |
| 总亏损 | {total_loss} USDT |
| 净收益 | {net_profit} USDT |
| 收益率 | {roi}% |

## 行情分析

| 指标 | 值 |
|------|-----|
| 行情判断周期 | {market_interval} |
| 行情判断算法 | {algorithm} |
| 行情状态变化 | {total_events} 次 |
| 交易时间占比 | {trading_pct}% |
| 停止时间占比 | {stopped_pct}% |

## 行情状态分布

| 状态 | 天数 | 占比 |
|------|------|------|
| 震荡行情 | {ranging_days} | {ranging_pct}% |
| 上涨趋势 | {trending_up_days} | {trending_up_pct}% |
| 下跌趋势 | {trending_down_days} | {trending_down_pct}% |

## 交易时段统计

| 开始时间 | 结束时间 | 状态 | 交易次数 | 收益 |
|----------|----------|------|----------|------|
| 2026-03-01 | 2026-03-05 | ranging | 10 | +50.00 USDT |
| 2026-03-06 | 2026-03-10 | trending_up | 8 | +30.00 USDT |

## 交易明细

| 层级 | 入场价 | 出场价 | 类型 | 盈亏 | 入场时间 | 出场时间 |
|------|--------|--------|------|------|----------|----------|
| A1 | 50000.00 | 50500.00 | 止盈 | +50.00 | 2026-03-01 10:00 | 2026-03-01 14:00 |
| ... | ... | ... | ... | ... | ... | ... |

---

*交易明细CSV: {csv_filename}*
```

### 3.3 行情可视化（visualizer）

```markdown
# {symbol} 行情分析报告

**结果ID**: {result_id}
**生成时间**: {generated_at}

---

## 基本信息

| 项目 | 值 |
|------|-----|
| 交易对 | {symbol} |
| K线周期 | {interval} |
| 分析算法 | {algorithm} |
| 开始时间 | {start_time} |
| 结束时间 | {end_time} |
| 总天数 | {total_days} |

## 行情统计

| 行情状态 | 天数 | 占比 |
|----------|------|------|
| 震荡行情 | {ranging_days} | {ranging_pct}% |
| 上涨趋势 | {trending_up_days} | {trending_up_pct}% |
| 下跌趋势 | {trending_down_days} | {trending_down_pct}% |

## 算法参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 算法 | {algorithm} | 行情判断算法 |
| 置信度阈值 | {confidence_threshold} | 状态判断置信度 |
| ... | ... | ... |

## 每日状态

| 日期 | 状态 | 置信度 | 原因 | 开盘价 | 收盘价 | 最高价 | 最低价 |
|------|------|--------|------|--------|--------|--------|--------|
| 2026-03-01 | ranging | 0.85 | 震荡区间内波动 | 50000 | 50500 | 51000 | 49500 |
| 2026-03-02 | trending_up | 0.92 | 突破阻力位 | 50500 | 52000 | 52500 | 50200 |
| ... | ... | ... | ... | ... | ... | ... | ... |

## 图表

![行情状态图表]({png_filename})

---

*每日状态CSV: {csv_filename}*
*交互式HTML: {html_filename}*
```

### 3.4 参数优化（optimizer_DualThrust / optimizer_Improved）

```markdown
# {symbol} 参数优化报告

**优化ID**: {optimizer_id}
**生成时间**: {generated_at}

---

## 基本信息

| 项目 | 值 |
|------|-----|
| 交易对 | {symbol} |
| 优化算法 | {algorithm} |
| 回测天数 | {days} |
| 优化次数 | {n_trials} |
| 最佳收益 | {best_value}% |

## 优化参数范围

| 参数 | 范围 | 最佳值 |
|------|------|--------|
| grid_spacing | 0.005 ~ 0.02 | {best_grid_spacing} |
| exit_profit | 0.005 ~ 0.02 | {best_exit_profit} |
| stop_loss | 0.05 ~ 0.15 | {best_stop_loss} |
| decay_factor | 0.3 ~ 0.7 | {best_decay_factor} |
| max_entries | 3 ~ 6 | {best_max_entries} |

## 最佳参数配置

```json
{
  "grid_spacing": {best_grid_spacing},
  "exit_profit": {best_exit_profit},
  "stop_loss": {best_stop_loss},
  "decay_factor": {best_decay_factor},
  "max_entries": {best_max_entries}
}
```

## 优化历史 Top 10

| 排名 | 收益率 | grid_spacing | exit_profit | stop_loss | decay_factor |
|------|--------|--------------|-------------|-----------|--------------|
| 1 | +8.56% | 0.01 | 0.012 | 0.08 | 0.5 |
| 2 | +8.23% | 0.009 | 0.011 | 0.09 | 0.52 |
| 3 | +7.89% | 0.011 | 0.013 | 0.07 | 0.48 |
| ... | ... | ... | ... | ... | ... |

## 优化过程统计

| 指标 | 值 |
|------|-----|
| 总优化次数 | {n_trials} |
| 最佳收益 | {best_value}% |
| 平均收益 | {avg_value}% |
| 收益标准差 | {std_value}% |

---

*优化结果CSV: {csv_filename}*
```

### 3.5 港股回测（longport）

```markdown
# {symbol} 港股回测报告

**执行ID**: {execution_id}
**生成时间**: {generated_at}

---

## 基本信息

| 项目 | 值 |
|------|-----|
| 股票代码 | {symbol} |
| 股票名称 | {stock_name} |
| K线周期 | {interval} |
| 开始时间 | {start_time} |
| 结束时间 | {end_time} |
| K线数量 | {klines_count} |
| 测试类型 | longport |

## 配置参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 总投入 | {total_amount} HKD | - |
| 网格间距 | {grid_spacing}% | - |
| 止盈比例 | {exit_profit}% | - |
| 止损比例 | {stop_loss}% | - |

## 回测结果

| 指标 | 值 |
|------|-----|
| 总交易次数 | {total_trades} |
| 盈利次数 | {win_trades} |
| 亏损次数 | {loss_trades} |
| 胜率 | {win_rate}% |
| 总盈利 | {total_profit} HKD |
| 总亏损 | {total_loss} HKD |
| 净收益 | {net_profit} HKD |
| 收益率 | {roi}% |

## 交易明细

| 层级 | 入场价 | 出场价 | 类型 | 盈亏 | 入场时间 | 出场时间 |
|------|--------|--------|------|------|----------|----------|
| A1 | 100.00 | 102.00 | 止盈 | +200.00 | 2026-03-01 10:00 | 2026-03-01 14:00 |
| ... | ... | ... | ... | ... | ... | ... |

---

*交易明细CSV: {csv_filename}*
```

---

## 4. CSV 文件内容设计

### 4.1 交易明细（*_trades.csv）

```csv
trade_seq,level,entry_price,exit_price,trade_type,profit,entry_time,exit_time
1,1,50000.00,50500.00,止盈,50.00,2026-03-01 10:00:00,2026-03-01 14:00:00
2,2,49500.00,49000.00,止损,-50.00,2026-03-02 09:00:00,2026-03-02 15:00:00
```

### 4.2 每日状态（*_daily.csv）

```csv
date,status,confidence,reason,open_price,close_price,high_price,low_price,volume
2026-03-01,ranging,0.85,震荡区间内波动,50000.00,50500.00,51000.00,49500.00,1234567.89
2026-03-02,trending_up,0.92,突破阻力位,50500.00,52000.00,52500.00,50200.00,2345678.90
```

### 4.3 优化结果（*_results.csv）

```csv
trial,value,grid_spacing,exit_profit,stop_loss,decay_factor,max_entries
1,0.0856,0.01,0.012,0.08,0.5,4
2,0.0823,0.009,0.011,0.09,0.52,4
3,0.0789,0.011,0.013,0.07,0.48,5
```

---

## 5. 数据库表设计补充

### 5.1 优化结果表（optimizer_results）

用于存储 Optuna 优化器的优化结果：

```sql
CREATE TABLE IF NOT EXISTS optimizer_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    optimizer_id TEXT UNIQUE NOT NULL,
    symbol TEXT NOT NULL,
    algorithm TEXT NOT NULL,              -- DualThrust / Improved
    days INTEGER,                         -- 回测天数
    n_trials INTEGER DEFAULT 100,         -- 优化次数
    best_value REAL,                      -- 最佳收益
    best_params TEXT,                     -- 最佳参数 JSON
    param_ranges TEXT,                    -- 参数范围 JSON
    optimization_history TEXT,            -- 优化历史 JSON
    avg_value REAL,                       -- 平均收益
    std_value REAL,                       -- 收益标准差
    duration_ms INTEGER,                  -- 优化耗时
    status TEXT DEFAULT 'completed',      -- 状态
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_optimizer_symbol ON optimizer_results(symbol);
CREATE INDEX IF NOT EXISTS idx_optimizer_algorithm ON optimizer_results(algorithm);
CREATE INDEX IF NOT EXISTS idx_optimizer_id ON optimizer_results(optimizer_id);
```

### 5.2 优化历史表（optimizer_history）

用于存储每次优化的详细历史：

```sql
CREATE TABLE IF NOT EXISTS optimizer_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    optimizer_id TEXT NOT NULL,
    trial INTEGER,                        -- 优化轮次
    value REAL,                           -- 收益率
    grid_spacing REAL,
    exit_profit REAL,
    stop_loss REAL,
    decay_factor REAL,
    max_entries INTEGER,
    params_json TEXT,                     -- 完整参数 JSON
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_optimizer_history_id ON optimizer_history(optimizer_id);
```

### 5.3 数据库表关系

```
test_results.db
├── test_plans                 # 测试计划
├── test_scenarios             # 测试场景
├── test_executions            # 测试执行记录
├── test_params                # 测试参数
├── test_results               # 回测交易结果
├── trade_details              # 交易明细
├── visualizer_cases           # 可视化测试用例
├── visualizer_results         # 可视化测试结果
├── visualizer_daily_statuses  # 每日行情状态
├── optimizer_results          # 优化结果（新增）
├── optimizer_history          # 优化历史（新增）
└── message_counter            # 消息计数器
```

---

## 6. 实施步骤

### 步骤 1：修改 `test_manager.py` 的 `export` 命令

1. 查询对应的记录
2. 获取 `test_type`、`symbol`、`algorithm`、`start_time`、`end_time` 等信息
3. 如果没有指定 `--output`，生成默认路径
4. 根据类型生成对应格式的 MD 报告
5. 导出完成后，更新汇总索引文件

### 步骤 2：修改 Optuna 优化器

1. 修改输出位置到统一目录
2. 按照设计格式生成 MD 报告
3. 导出完成后，更新汇总索引文件

### 步骤 3：修改 Visualizer 输出

1. 修改输出位置到统一目录
2. 支持导出 MD、CSV、PNG、HTML 四种格式
3. 导出完成后，更新汇总索引文件

### 步骤 4：实现汇总索引文件更新

1. 创建 `update_readme_index()` 函数
2. 从数据库查询所有报告信息
3. 生成汇总索引文件

---

## 6. 验收标准

1. ✅ 不指定 `--output` 时，自动生成默认路径
2. ✅ 默认路径根据 `test_type` 选择子目录
3. ✅ MD 报告内容格式统一、完整
4. ✅ 文件名包含 `symbol`、`date_range`、`algorithm`、`execution_id` 等信息
5. ✅ 自动创建输出目录
6. ✅ 指定 `--output` 时，使用用户指定的路径
7. ✅ 导出完成后自动更新 `out/test_report/README.md` 汇总索引文件
8. ✅ Visualizer 支持导出 MD、CSV、PNG、HTML 四种格式
9. ✅ Optuna 优化器输出到统一位置
10. ✅ CSV 文件格式统一
