# Web 资金详情 - K 线图叠加资金曲线计划

## 目标
1. 在现有的 K 线图中叠加资金曲线
2. 资金历史记录使用 K 线时间
3. 通过双 Y 轴同时展示 K 线价格和资金变化

## 技术方案
- 在现有 K 线图（`chartModal`）中添加资金曲线
- 使用 ECharts 双 Y 轴：左轴显示价格，右轴显示资金
- 复用现有 `/api/results/<result_id>/chart` API，同时返回资金历史数据

## 实施步骤

### 步骤 1: 修改 autofish_core.py - 增加时间参数

**文件**: `autofish_core.py`

#### 1.1 FixedCapitalTracker.process_trade_profit
增加 `kline_time` 参数，使用 K 线时间而非系统时间

#### 1.2 ProgressiveCapitalTracker.process_trade_profit
同上，增加 `kline_time` 参数

### 步骤 2: 修改 binance_backtest.py - 传入 K 线时间

在调用 `_update_capital_after_trade` 时传入 K 线时间

### 步骤 3: 修改 API 返回资金历史

**文件**: `test_manager.py`

**位置**: `/api/results/<result_id>/chart` API

**修改内容**:
```python
@app.route('/api/results/<result_id>/chart', methods=['GET'])
def get_chart_data(result_id):
    # ... 现有代码 ...
    
    # 添加资金历史
    capital_history = db.get_capital_history(result_id)
    
    chart_data = {
        'result': result,
        'klines': klines,
        'trades': trades,
        'capital_history': capital_history  # 新增
    }
    
    return jsonify({'success': True, 'data': chart_data})
```

### 步骤 4: 修改前端 K 线图

**文件**: `web/test_results/index.html`

#### 4.1 添加复选框
**位置**: K 线图弹窗的控制区域（约第 885 行）

```html
<div class="btn-group" role="group">
    <input type="checkbox" class="btn-check" id="showTrades" checked onchange="updateChart()">
    <label class="btn btn-outline-primary" for="showTrades">显示交易标注</label>
    
    <input type="checkbox" class="btn-check" id="showCapital" checked onchange="updateChart()">
    <label class="btn btn-outline-success" for="showCapital">显示资金曲线</label>
</div>
```

#### 4.2 修改 renderKlineChart 函数
**位置**: 约 2120 行

**修改内容**:
```javascript
function renderKlineChart() {
    // ... 现有代码 ...
    
    const showTrades = document.getElementById('showTrades').checked;
    const showCapital = document.getElementById('showCapital').checked;
    const capitalHistory = currentChartData.capital_history || [];
    
    // 构建资金曲线数据
    let capitalSeries = null;
    if (showCapital && capitalHistory.length > 0) {
        // 将资金历史时间匹配到 K 线日期
        const capitalData = dates.map(date => {
            const match = capitalHistory.find(h => h.timestamp.startsWith(date));
            return match ? match.new_capital : null;
        });
        
        capitalSeries = {
            name: '资金',
            type: 'line',
            yAxisIndex: 1,  // 使用右 Y 轴
            data: capitalData,
            smooth: true,
            lineStyle: { width: 2, color: '#22c55e' },
            areaStyle: { opacity: 0.1, color: '#22c55e' },
            symbol: 'none'
        };
    }
    
    const option = {
        // ... 现有配置 ...
        yAxis: [
            { 
                type: 'value',
                name: '价格 (USDT)',
                position: 'left',
                scale: true
            },
            { 
                type: 'value',
                name: '资金 (USDT)',
                position: 'right',
                scale: true
            }
        ],
        series: [
            // K 线系列
            { type: 'candlestick', data: ohlc, yAxisIndex: 0 },
            // 成交量系列
            { type: 'bar', data: volumes, yAxisIndex: 0 },
            // 资金曲线系列（新增）
            capitalSeries
        ].filter(s => s !== null)
    };
    
    klineChart.setOption(option);
}
```

## 修改清单

| 文件 | 修改位置 | 修改内容 |
|------|----------|----------|
| `autofish_core.py` | process_trade_profit | 增加 kline_time 参数 |
| `binance_backtest.py` | _update_capital_after_trade | 传入 K 线时间 |
| `test_manager.py` | get_chart_data API | 返回 capital_history |
| `web/test_results/index.html` | chartModal 控制区 | 添加"显示资金曲线"复选框 |
| `web/test_results/index.html` | renderKlineChart | 添加资金曲线系列 |

## 效果预览
- K 线图左 Y 轴：价格
- K 线图右 Y 轴：资金金额
- 资金曲线：绿色实线 + 浅绿色区域填充
- 可通过复选框切换显示/隐藏资金曲线
- 交易标注（入场/出场点）与资金曲线同时显示
