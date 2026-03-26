# 分析：entry_capital 和 entry_total_capital 完整实现方案

## 问题分析

**根本原因**：`entry_capital` 和 `entry_total_capital` 应该记录**入场时**的资金信息，但当前代码在**出场时**才记录，此时资金已经变化。

## 完整解决方案

### 一、数据模型层（autofish_core.py）

#### 1. 修改 `Autofish_Order` 类

```python
class Autofish_Order:
    level: int
    entry_price: Decimal
    quantity: Decimal
    stake_amount: Decimal
    # ... 现有字段
    entry_capital: Optional[Decimal] = None      # 新增：入场时的交易资金
    entry_total_capital: Optional[Decimal] = None  # 新增：入场时的总资金
```

### 二、业务逻辑层（binance_backtest.py）

#### 1. 入场时记录资金

文件：`binance_backtest.py` 的 `_process_entry` 方法

```python
def _process_entry(self, low_price: Decimal, current_price: Decimal, kline_time: datetime = None):
    pending_order = self.chain_state.get_pending_order()
    if pending_order:
        if Autofish_OrderCalculator.check_entry_triggered(low_price, pending_order.entry_price):
            pending_order.set_state("filled", "K线触发入场")
            pending_order.filled_at = kline_time.strftime(...) if kline_time else ...
            
            # 新增：记录入场时的资金信息
            pending_order.entry_capital = self.capital_pool.trading_capital
            pending_order.entry_total_capital = self.capital_pool.trading_capital + (
                self.capital_pool.profit_pool if hasattr(self.capital_pool, 'profit_pool') else 0
            )
```

#### 2. 出场时读取资金

文件：`binance_backtest.py` 的 `_record_trade` 方法

```python
def _record_trade(self, order: Autofish_Order, close_price: Decimal, reason: str, kline_time: datetime = None):
    self.results["trades"].append({
        # ... 现有字段
        "entry_capital": float(order.entry_capital) if order.entry_capital else 0,
        "entry_total_capital": float(order.entry_total_capital) if order.entry_total_capital else 0,
    })
```

#### 3. MarketAwareBacktestEngine 类同样修改

- `_process_entry` 方法：入场时记录资金
- `_force_close_all_orders` 方法：出场时读取资金

### 三、数据库层（database/test_results_db.py）

#### 1. 表结构（已完成）

```sql
CREATE TABLE trade_details (
    -- ... 现有字段
    entry_capital REAL DEFAULT 0,
    entry_total_capital REAL DEFAULT 0
)
```

#### 2. TradeDetail 数据类（已完成）

```python
@dataclass
class TradeDetail:
    # ... 现有字段
    entry_capital: float = 0.0
    entry_total_capital: float = 0.0
```

#### 3. 保存方法（已完成）

```python
def save_trade_details(self, result_id: str, trades: List[TradeDetail]) -> bool:
    cursor.execute("""
        INSERT INTO trade_details 
        (result_id, trade_seq, level, entry_price, exit_price, entry_time,
         exit_time, trade_type, profit, quantity, stake, entry_capital, entry_total_capital)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (result_id, trade.trade_seq, trade.level, trade.entry_price,
          trade.exit_price, trade.entry_time, trade.exit_time,
          trade.trade_type, trade.profit, trade.quantity, trade.stake,
          trade.entry_capital, trade.entry_total_capital))
```

#### 4. 查询方法（已完成）

```python
def get_trade_details(self, result_id: str) -> List[Dict]:
    cursor.execute("SELECT * FROM trade_details WHERE result_id = ? ORDER BY trade_seq", (result_id,))
    return [dict(row) for row in cursor.fetchall()]
```

### 四、Web API 层（test_manager.py）

#### 1. API 接口（已完成）

```python
@app.route('/api/results/<result_id>/trades', methods=['GET'])
def get_trades(result_id):
    try:
        trades = db.get_trade_details(result_id)
        return jsonify({'success': True, 'data': trades})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
```

### 五、前端展示层（web/test_results/index.html）

#### 1. 模态框（已完成）

```html
<div class="modal fade" id="tradeModal" tabindex="-1">
    <div class="modal-dialog modal-xl">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">交易详情列表</h5>
            </div>
            <div class="modal-body">
                <div id="tradeDetailsContent">...</div>
            </div>
        </div>
    </div>
</div>
```

#### 2. 表格展示（已完成）

```javascript
function renderTradeDetailsTable(trades) {
    // ...
    html += `
        <tr>
            <td>${index + 1}</td>
            <td><small>${t.entry_time || '-'}</small></td>
            <td><small>${t.exit_time || '-'}</small></td>
            <td>A${t.level}</td>
            <td>${t.entry_price ? parseFloat(t.entry_price).toFixed(2) : '-'}</td>
            <td>${t.exit_price ? parseFloat(t.exit_price).toFixed(2) : '-'}</td>
            <td>${t.quantity ? parseFloat(t.quantity).toFixed(6) : '-'}</td>
            <td>${t.stake ? parseFloat(t.stake).toFixed(2) : '-'}</td>
            <td>${t.entry_capital ? parseFloat(t.entry_capital).toFixed(2) : '-'}</td>
            <td>${t.entry_total_capital ? parseFloat(t.entry_total_capital).toFixed(2) : '-'}</td>
            <td class="${profitClass}">${profit >= 0 ? '+' : ''}${profit.toFixed(2)}</td>
            <td class="${typeClass}">${t.trade_type === 'take_profit' ? '止盈' : '止损'}</td>
        </tr>
    `;
}
```

### 六、资金曲线图表（新增）

#### 1. 功能说明

在交易详情列表页面增加资金曲线图表，使用 `entry_capital` 和 `entry_total_capital` 展示资金变化趋势。

#### 2. 图表设计

- **X 轴**：交易序号（#1, #2, #3...）
- **Y 轴**：资金金额（USDT）
- **两条曲线**：
  - **交易资金**（`entry_capital`）：蓝色线
  - **总资金**（`entry_total_capital`）：绿色线

#### 3. 实现代码

```html
<!-- 在模态框中添加图表容器 -->
<div id="tradeCapitalChart" style="height: 300px; margin-bottom: 20px;"></div>
```

```javascript
function renderTradeDetailsTable(trades) {
    const container = document.getElementById('tradeDetailsContent');
    
    // ... 统计卡片代码 ...
    
    // 新增：渲染资金曲线图表
    renderTradeCapitalChart(trades);
    
    // ... 表格代码 ...
}

function renderTradeCapitalChart(trades) {
    const chartDom = document.getElementById('tradeCapitalChart');
    const existingChart = echarts.getInstanceByDom(chartDom);
    if (existingChart) {
        existingChart.dispose();
    }
    
    const chart = echarts.init(chartDom);
    
    const xData = trades.map((t, i) => `#${i + 1}`);
    const capitalData = trades.map(t => t.entry_capital || 0);
    const totalCapitalData = trades.map(t => t.entry_total_capital || 0);
    
    const option = {
        title: {
            text: '资金曲线',
            left: 'center'
        },
        tooltip: {
            trigger: 'axis',
            formatter: function(params) {
                let result = params[0].axisValue + '<br/>';
                params.forEach(p => {
                    result += `${p.marker} ${p.seriesName}: ${p.value.toFixed(2)} USDT<br/>`;
                });
                return result;
            }
        },
        legend: {
            data: ['交易资金', '总资金'],
            top: 30
        },
        grid: {
            left: '10%',
            right: '10%',
            top: 80,
            bottom: 60
        },
        xAxis: {
            type: 'category',
            data: xData,
            axisLabel: {
                rotate: 45
            }
        },
        yAxis: {
            type: 'value',
            name: '资金 (USDT)',
            axisLabel: {
                formatter: '{value}'
            }
        },
        series: [
            {
                name: '交易资金',
                type: 'line',
                data: capitalData,
                smooth: true,
                lineStyle: { width: 2, color: '#3b82f6' },
                itemStyle: { color: '#3b82f6' },
                areaStyle: { opacity: 0.1, color: '#3b82f6' }
            },
            {
                name: '总资金',
                type: 'line',
                data: totalCapitalData,
                smooth: true,
                lineStyle: { width: 2, color: '#22c55e' },
                itemStyle: { color: '#22c55e' },
                areaStyle: { opacity: 0.1, color: '#22c55e' }
            }
        ]
    };
    
    chart.setOption(option);
}
```

#### 4. 图表效果

```
资金曲线
┌────────────────────────────────────────┐
│  ── 交易资金  ── 总资金                  │
│                                        │
│     12000 ───────────────────────      │
│           /                            │
│    10000 ───────────────────────       │
│         /                              │
│     8000 ───────────────────────       │
│                                        │
│    #1   #2   #3   #4   #5   #6         │
└────────────────────────────────────────┘
```

## 修改文件清单

| 文件 | 修改内容 | 状态 |
|------|----------|------|
| `autofish_core.py` | `Autofish_Order` 类添加字段 | 待修改 |
| `binance_backtest.py` | `_process_entry` 入场时记录资金 | 待修改 |
| `binance_backtest.py` | `_record_trade` 出场时读取资金 | 待修改 |
| `binance_backtest.py` | `MarketAwareBacktestEngine` 同样修改 | 待修改 |
| `database/test_results_db.py` | 表结构、TradeDetail、保存方法 | 已完成 |
| `test_manager.py` | API 接口 | 已完成 |
| `web/test_results/index.html` | 模态框、表格展示 | 已完成 |
| `web/test_results/index.html` | 资金曲线图表 | 待修改 |

## 数据流程图

```
入场时：
  _process_entry()
    -> order.entry_capital = capital_pool.trading_capital
    -> order.entry_total_capital = trading_capital + profit_pool

出场时：
  _record_trade(order)
    -> 读取 order.entry_capital
    -> 读取 order.entry_total_capital
    -> 写入 results["trades"]

保存时：
  save_trade_details()
    -> 写入 trade_details 表

展示时：
  /api/results/{id}/trades
    -> 返回 trade_details 数据
  -> 前端表格展示
  -> 资金曲线图表展示
```
