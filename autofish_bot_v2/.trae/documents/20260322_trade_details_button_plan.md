# 计划：修复 entry_time + 新增"交易"按钮 + 记录交易资金信息

## 任务一：修复 entry_time 使用 K 线时间

### 问题原因
在 `binance_backtest.py` 第 971 行，`_process_entry` 调用时**没有传递 `kline_time` 参数**：

```python
# 第 971 行 - 缺少 kline_time 参数
self._process_entry(low_price, close_price)

# 第 972 行 - 有 kline_time 参数
self._process_exit(open_price, high_price, low_price, close_price, kline_time)
```

### 修复方案
修改 `binance_backtest.py` 第 971 行：
```python
self._process_entry(low_price, close_price, kline_time)
```

---

## 任务二：trade_details 表添加交易资金字段

### 新增字段
| 字段 | 类型 | 说明 |
|------|------|------|
| `entry_capital` | REAL | 入场时的交易资金（trading_capital） |
| `entry_total_capital` | REAL | 入场时的总资金（trading_capital + profit_pool） |

### 修改内容

#### 1. 数据库表结构（迁移脚本）
```sql
ALTER TABLE trade_details ADD COLUMN entry_capital REAL;
ALTER TABLE trade_details ADD COLUMN entry_total_capital REAL;
```

#### 2. TradeDetail 数据类
```python
@dataclass
class TradeDetail:
    # ... 现有字段
    entry_capital: float = 0
    entry_total_capital: float = 0
```

#### 3. 保存交易详情时记录资金信息
在 `binance_backtest.py` 中，入场时记录当前资金：
```python
# 入场时
"entry_capital": float(self.capital_tracker.trading_capital),
"entry_total_capital": float(self.capital_tracker.trading_capital + self.capital_tracker.profit_pool),
```

---

## 任务三：新增"交易"按钮展示交易历史详情

### 现有按钮区域
```html
<td>
    <button class="btn btn-sm btn-outline-primary" onclick="showResultDetail('${r.result_id}')">详情</button>
    <button class="btn btn-sm btn-outline-info" onclick="showChart('${r.result_id}')">图表</button>
    <button class="btn btn-sm btn-outline-success" onclick="showCapitalDetail('${r.result_id}')">资金</button>
</td>
```

### 实现方案

#### 1. 添加"交易"按钮
```html
<button class="btn btn-sm btn-outline-warning" onclick="showTradeDetails('${r.result_id}')">交易</button>
```

#### 2. 创建交易详情模态框
```html
<div class="modal fade" id="tradeModal" tabindex="-1">
    <div class="modal-dialog modal-xl">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">交易详情列表</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <div id="tradeDetailsContent">...</div>
            </div>
        </div>
    </div>
</div>
```

#### 3. 交易详情表格字段
| 字段 | 说明 |
|------|------|
| 序号 | 交易序号 |
| 入场时间 | 入场 K 线时间 |
| 出场时间 | 出场 K 线时间 |
| 级别 | A1/A2/A3/A4 |
| 入场价 | 入场价格 |
| 出场价 | 出场价格 |
| 数量 | 交易数量（BTC） |
| 金额 | 下单金额（USDT）= stake |
| 入场资金 | 入场时的交易资金 |
| 入场总资金 | 入场时的总资金 |
| 盈亏 | 本次盈亏 |
| 类型 | 止盈/止损 |

#### 4. 统计卡片
- 总交易次数
- 累计盈亏
- 平均盈亏
- 盈利次数/亏损次数

---

## 文件修改

| 文件 | 修改内容 |
|------|----------|
| `binance_backtest.py` | 1. 第 971 行添加 `kline_time` 参数<br>2. 入场时记录资金信息 |
| `database/test_results_db.py` | 1. TradeDetail 添加字段<br>2. 表结构迁移<br>3. 保存时包含新字段 |
| `web/test_results/index.html` | 1. 添加"交易"按钮<br>2. 添加交易详情模态框<br>3. 添加 JavaScript 函数 |
