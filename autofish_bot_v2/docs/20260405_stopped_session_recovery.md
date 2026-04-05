# Stopped 状态会话恢复支持

## Context

用户发现当网络连续失败5次后，session 状态会被设置为 `stopped`，此时无法通过 web 界面恢复。用户希望能够：
1. 恢复 `stopped` 状态的会话
2. 在可恢复列表中根据状态分类（running vs stopped）
3. 展示退出原因（run_message）

---

## 一、现状分析

### 1.1 数据库字段

`live_sessions` 表已有 `error_message` 字段，需重命名为 `run_message`：

```sql
-- database/live_trading_db.py:293
error_message TEXT,  -- 需改为 run_message
```

**命名原因**：该字段不仅记录错误信息，还可能记录其他运行时消息（如用户主动停止、正常退出等）。

### 1.2 问题点

| 问题 | 文件 | 位置 |
|------|------|------|
| 字段名 `error_message` 含义不准确 | `database/live_trading_db.py` | 多处 |
| `_handle_exit()` 没有传递 `reason` | `binance_live.py` | line 2793-2797 |
| `get_recoverable_sessions()` 只查 `running` | `database/live_trading_db.py` | line 868 |
| `recover_trader()` 只允许 `running` 状态 | `binance_live.py` | line 4918-4920 |
| Web 界面未展示退出原因 | `web/live/index.html` | line 1189-1268 |

### 1.3 数据流

```
退出流程：
_handle_exit(reason) → db.end_session(status='stopped') → session.status='stopped'
                                                    ↓
                                            run_message 未传递！（问题）

恢复流程：
web 恢复 → get_recoverable_sessions() → 只查 status='running'（问题）
        → recover_trader() → 只允许 status='running'（问题）
```

---

## 二、解决方案

### 2.1 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `database/live_trading_db.py` | 1. `error_message` 重命名为 `run_message`<br>2. `get_recoverable_sessions()` 查询改为 `IN ('running', 'stopped')` |
| `binance_live.py` | 1. `_handle_exit()` 传递 `reason` 到 `end_session()`<br>2. `recover_trader()` 允许 `stopped` 状态<br>3. 恢复时更新状态并清除 `run_message` |
| `web/live/index.html` | 可恢复列表展示状态分类和退出原因 |

### 2.2 详细修改

#### Step 1: 重命名数据库字段

**文件**: `database/live_trading_db.py`

需要修改的位置：
- `LiveSession` dataclass: `error_message: str = ""` → `run_message: str = ""`
- CREATE TABLE 语句: `error_message TEXT` → `run_message TEXT`
- `end_session()` 方法参数: `error_message: str = ""` → `run_message: str = ""`
- `update_session()` allowed_fields: `'error_message'` → `'run_message'`
- 其他引用处

**数据迁移**（如果数据库已存在）：
```sql
ALTER TABLE live_sessions RENAME COLUMN error_message TO run_message;
```

#### Step 2: `_handle_exit()` 传递退出原因

**文件**: `binance_live.py`
**位置**: line 2793-2797

```python
# 原代码
self.db.end_session(
    session_id=self.session_id,
    status='stopped',
    final_capital=float(self.capital_pool.trading_capital)
)

# 修改为
self.db.end_session(
    session_id=self.session_id,
    status='stopped',
    final_capital=float(self.capital_pool.trading_capital),
    run_message=reason  # 新增：保存退出原因
)
```

#### Step 3: 修改数据库查询

**文件**: `database/live_trading_db.py`
**位置**: `get_recoverable_sessions()` 方法 (line 864-870)

```python
# 原代码
WHERE s.status = 'running'

# 修改为
WHERE s.status IN ('running', 'stopped')
```

#### Step 4: 修改恢复验证逻辑

**文件**: `binance_live.py`
**位置**: `recover_trader()` 方法 (line 4918-4920)

```python
# 原代码
if session['status'] != 'running':
    logger.error(f"[恢复] Session 状态不是 running: {session['status']}")
    return None

# 修改为
if session['status'] not in ('running', 'stopped'):
    logger.error(f"[恢复] Session 状态不允许恢复: {session['status']}")
    return None

if session['status'] == 'stopped':
    logger.info(f"[恢复] 恢复 stopped 状态的会话: session_id={session_id}, reason={session.get('run_message', 'N/A')}")
```

#### Step 5: 恢复时清除 run_message

**文件**: `binance_live.py`
**位置**: `recover_trader()` 方法，在设置 `recover_session_id` 后

```python
# 设置恢复模式
trader.recover_session_id = session_id

# 新增：更新状态为 running 并清除 run_message
db.update_session(session_id, {
    'status': 'running',
    'run_message': ''  # 清除旧的消息
})
logger.info(f"[恢复] 已更新 session 状态: session_id={session_id}")
```

#### Step 6: Web 界面展示状态和退出原因

**文件**: `web/live/index.html`
**位置**: `loadRecoverableSessions()` 函数

在可恢复会话卡片中添加状态标识和退出原因展示：

```html
<!-- 状态标识 -->
${session.status === 'stopped' ?
    '<span class="status-badge status-stopped">异常停止</span>' :
    '<span class="status-badge status-running">中断</span>'
}

<!-- 退出原因（如果有） -->
${session.run_message ?
    `<div class="text-muted small mt-1">原因: ${session.run_message}</div>` :
    ''
}
```

---

## 三、状态分类说明

| 状态 | 含义 | 可能原因 | 用户操作 |
|------|------|---------|---------|
| `running` | 服务中断 | 后端重启、进程崩溃 | 直接恢复，状态同步即可 |
| `stopped` | 异常停止 | 网络错误5次、用户停止、其他异常 | 恢复后会同步交易所状态 |

---

## 四、验证方案

1. **测试退出原因保存**：
   - 手动触发异常退出（模拟网络错误）
   - 检查数据库 `run_message` 字段是否正确保存

2. **测试 stopped 状态恢复**：
   - 手动将 session 状态设为 `stopped`
   - 验证是否出现在可恢复列表
   - 点击恢复，验证状态更新为 `running`

3. **测试 web 展示**：
   - 验证状态标识正确显示
   - 验证退出原因正确展示

---

*创建日期: 2026-04-05*