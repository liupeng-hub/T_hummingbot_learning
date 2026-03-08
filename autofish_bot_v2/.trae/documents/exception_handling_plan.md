# 异常处理优化计划 - 发送通告并继续运行

## 问题描述

当前系统遇到异常后会直接退出，这会导致：
1. 无法及时发现问题
2. 需要手动重启
3. 可能错过交易机会

## 当前代码

```python
except Exception as e:
    logger.error(f"[运行] 异常退出: {e}")
    await self._handle_exit(f"异常退出: {e}")
```

## 修复方案

### 方案：捕获异常后发送通告并继续运行

```python
except Exception as e:
    logger.error(f"[运行] 发生异常: {e}")
    # 发送严重错误通告
    notify_critical_error(str(e), self.config)
    # 不退出，继续运行（等待下次循环或 WebSocket 重连）
```

### 需要区分的异常类型

1. **需要退出的异常**：
   - `KeyboardInterrupt` - 用户中断
   - `asyncio.CancelledError` - 任务取消
   - `SystemExit` - 系统退出

2. **可以恢复的异常**：
   - `BinanceAPIError` - API 错误（可能是临时问题）
   - `NetworkError` - 网络错误
   - `OrderError` - 订单错误
   - 其他未知异常

### 实施步骤

1. **添加严重错误通告函数**
   - 创建 `notify_critical_error()` 函数
   - 发送微信通知

2. **修改异常处理逻辑**
   - 捕获异常后发送通告
   - 记录错误日志
   - 继续运行（不调用 `_handle_exit()`）

3. **增加错误计数和冷却**
   - 如果连续发生多次错误，可能需要退出
   - 避免无限循环报错

## 实施细节

### 1. 添加严重错误通告函数

```python
def notify_critical_error(error_msg: str, config: dict):
    """发送严重错误通知"""
    symbol = config.get('symbol', 'BTCUSDT')
    content = dedent(f"""
        > **错误类型**: 严重错误
        > **交易标的**: {symbol}
        > **错误信息**: {error_msg}
        > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        > **状态**: 程序继续运行
    """).strip()
    send_wechat_notification("🚨 Autofish 严重错误", content)
```

### 2. 修改 run() 方法异常处理

```python
except Exception as e:
    logger.error(f"[运行] 发生异常: {e}")
    notify_critical_error(str(e), self.config)
    # 不退出，继续运行
    # 程序会在下次循环或 WebSocket 重连时恢复
```

### 3. 增加错误计数（可选）

```python
# 在 __init__ 中
self.error_count = 0
self.max_consecutive_errors = 5

# 在异常处理中
self.error_count += 1
if self.error_count >= self.max_consecutive_errors:
    logger.error(f"[运行] 连续错误 {self.error_count} 次，退出")
    await self._handle_exit(f"连续错误 {self.error_count} 次")
else:
    notify_critical_error(str(e), self.config)
    # 重置计数（在成功操作后）
```

## 测试验证

1. 模拟异常情况
2. 验证是否发送通告
3. 验证程序是否继续运行
