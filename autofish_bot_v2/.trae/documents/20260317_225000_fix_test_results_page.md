# 测试用例和结果页面修复计划

## 任务概述
修复三个问题：
1. 用例增加删除按钮
2. 测试结果类型显示 undefined
3. K线图无法显示

## 问题分析

### 问题1：用例删除按钮
- 当前状态：删除按钮已存在于编辑表单中 (`id="deleteCaseBtn"`)
- 只在编辑模式下显示 (`style="display:none;"` 默认隐藏)
- **重要**：数据库表没有设置级联删除
  - `test_results` 表：`FOREIGN KEY (case_id) REFERENCES test_cases(case_id)` - 无 CASCADE
  - `trade_details` 表：`FOREIGN KEY (result_id) REFERENCES test_results(result_id)` - 无 CASCADE
- **解决方案**：在删除用例时手动删除关联数据

### 问题2：测试结果类型显示 undefined
- **根本原因**：`test_results` 表没有 `test_type` 字段
- `test_cases` 表有 `test_type` 字段
- 前端代码 `${r.test_type}` 尝试访问不存在的字段
- **解决方案**：修改 API 查询，通过 JOIN 从 test_cases 表获取 test_type

### 问题3：K线图无法显示
- **根本原因**：`/api/results/<result_id>/chart` API 返回空 K 线数据
- 当前代码：`'klines': []` 硬编码为空数组
- **解决方案**：使用 KlineFetcher 从缓存获取 K 线数据

## 实施步骤

### 步骤1：添加级联删除功能
在 `database/test_results_db.py` 中添加删除用例及其关联数据的方法：

```python
def delete_case(self, case_id: str) -> bool:
    """删除测试用例及其所有关联数据"""
    conn = self._get_connection()
    cursor = conn.cursor()
    
    try:
        # 1. 获取该用例的所有结果ID
        cursor.execute("SELECT result_id FROM test_results WHERE case_id = ?", (case_id,))
        result_ids = [row[0] for row in cursor.fetchall()]
        
        # 2. 删除所有交易详情
        for result_id in result_ids:
            cursor.execute("DELETE FROM trade_details WHERE result_id = ?", (result_id,))
        
        # 3. 删除所有测试结果
        cursor.execute("DELETE FROM test_results WHERE case_id = ?", (case_id,))
        
        # 4. 删除测试用例
        cursor.execute("DELETE FROM test_cases WHERE case_id = ?", (case_id,))
        
        conn.commit()
        logger.info(f"删除测试用例 {case_id} 及其关联数据")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"删除测试用例失败: {e}")
        return False
    finally:
        conn.close()
```

### 步骤2：修复测试结果类型显示
修改 `database/test_results_db.py` 中的 `list_results` 方法：

```python
def list_results(self, filters=None, limit=100, offset=0):
    conn = self._get_connection()
    cursor = conn.cursor()
    
    sql = """
        SELECT r.*, c.test_type, c.name as case_name
        FROM test_results r
        LEFT JOIN test_cases c ON r.case_id = c.case_id
        WHERE 1=1
    """
    params = []
    
    if filters:
        if filters.get('case_id'):
            sql += " AND r.case_id = ?"
            params.append(filters['case_id'])
        if filters.get('symbol'):
            sql += " AND r.symbol = ?"
            params.append(filters['symbol'])
        if filters.get('status'):
            sql += " AND r.status = ?"
            params.append(filters['status'])
    
    sql += " ORDER BY r.executed_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]
```

### 步骤3：修复 K 线图 API
修改 `test_manager.py` 中的 `get_chart_data` 函数：

```python
from binance_kline_fetcher import KlineFetcher
from datetime import datetime

@app.route('/api/results/<result_id>/chart', methods=['GET'])
def get_chart_data(result_id):
    try:
        result = db.get_result(result_id)
        if not result:
            return jsonify({'success': False, 'error': '测试结果不存在'})
        
        trades = db.get_trade_details(result_id)
        
        # 获取 K 线数据
        klines = []
        symbol = result.get('symbol')
        date_start = result.get('start_time')
        date_end = result.get('end_time')
        interval = result.get('interval', '1d')
        
        if symbol and date_start and date_end:
            try:
                fetcher = KlineFetcher()
                start_dt = datetime.strptime(date_start.split()[0], '%Y-%m-%d')
                end_dt = datetime.strptime(date_end.split()[0], '%Y-%m-%d')
                start_ts = int(start_dt.timestamp() * 1000)
                end_ts = int(end_dt.timestamp() * 1000)
                klines = fetcher.get_klines(symbol, interval or '1d', start_ts, end_ts)
            except Exception as e:
                logger.error(f"获取K线数据失败: {e}")
        
        # 转换 K 线数据格式
        formatted_klines = []
        for k in klines:
            dt = datetime.fromtimestamp(k['timestamp'] / 1000)
            formatted_klines.append({
                'date': dt.strftime('%Y-%m-%d'),
                'open': k['open'],
                'high': k['high'],
                'low': k['low'],
                'close': k['close'],
                'volume': k['volume']
            })
        
        return jsonify({
            'success': True,
            'data': {
                'result': result,
                'klines': formatted_klines,
                'trades': trades
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
```

### 步骤4：添加删除用例 API
在 `test_manager.py` 中添加删除用例的 API：

```python
@app.route('/api/cases/<case_id>', methods=['DELETE'])
def delete_case(case_id):
    try:
        success = db.delete_case(case_id)
        if success:
            return jsonify({'success': True, 'message': f'测试用例 {case_id} 已删除'})
        else:
            return jsonify({'success': False, 'error': '删除失败'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
```

### 步骤5：更新前端删除功能
修改 `index.html` 中的 `deleteCase` 函数：

```javascript
async function deleteCase() {
    const caseId = document.getElementById('editCaseId').value;
    if (!caseId) return;
    
    if (!confirm('确定要删除此测试用例吗？\n\n删除后将同时删除所有相关的测试结果和交易详情！')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/cases/${caseId}`, {
            method: 'DELETE'
        });
        const data = await response.json();
        
        if (data.success) {
            bootstrap.Modal.getInstance(document.getElementById('caseFormModal')).hide();
            loadCases();
        } else {
            showError('删除失败', data.error);
        }
    } catch (error) {
        showError('删除失败', error.message);
    }
}
```

## 文件修改清单

1. **database/test_results_db.py**
   - 添加 `delete_case` 方法（级联删除）
   - 修改 `list_results` 方法，添加 JOIN 查询获取 test_type

2. **test_manager.py**
   - 添加 `from binance_kline_fetcher import KlineFetcher` 导入
   - 添加删除用例 API (`DELETE /api/cases/<case_id>`)
   - 修改 `get_chart_data` 函数，使用 KlineFetcher 获取 K 线

3. **web/test_results/index.html**
   - 更新 `deleteCase` 函数调用删除 API
   - 确认 test_type 显示正确
   - 确认图表渲染逻辑正确
