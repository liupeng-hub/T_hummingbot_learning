# 新旧代码对接 Binance API 差异对比

## 1. 架构差异

| 项目 | 旧代码 (autofish_bot) | 新代码 (autofish_bot_v2) |
|------|----------------------|-------------------------|
| 类结构 | 单一类 `BinanceLiveTrader` | 分离为 `BinanceClient` + `BinanceLiveTrader` |
| 职责分离 | API 和交易逻辑混合 | API 客户端独立，交易逻辑分离 |

## 2. HTTP 请求差异

### 2.1 错误处理

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 错误返回 | `{"error": str(e)}` | 抛出 `BinanceAPIError` / `NetworkError` 异常 |
| API 错误检测 | 无 | 检查 `code` 字段并抛出异常 |

**旧代码**:
```python
except Exception as e:
    return {"error": str(e)}
```

**新代码**:
```python
if "code" in data and data["code"] != 200:
    raise BinanceAPIError(code=data.get("code", -1), message=data.get("msg", "Unknown error"), response=data)

except aiohttp.ClientError as e:
    raise NetworkError(f"Request failed: {e}", e)
```

### 2.2 请求超时

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 超时设置 | 无显式超时 | 30 秒超时 |
| 限流 | 无 | `AsyncLimiter(1000, 60)` |

### 2.3 签名方法

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 编码 | `self.api_secret.encode()` | `self.api_secret.encode('utf-8')` |
| 结果 | ✅ 一致 | ✅ 一致 |

## 3. 下单参数差异

### 3.1 普通订单 (place_order)

| 参数 | 旧代码 | 新代码 |
|------|--------|--------|
| quantity 格式 | `f"{quantity:.3f}"` (固定3位小数) | `str(quantity)` (原始值) |
| price 格式 | 强制对齐到 0.1 精度 | `str(price)` (原始值) |
| reduce_only | 无 | 支持 `reduceOnly` 参数 |

**旧代码**:
```python
params = {
    "quantity": f"{quantity:.3f}",
}
if price:
    price = (price / Decimal("0.1")).quantize(Decimal("1")) * Decimal("0.1")
    params["price"] = f"{price:.1f}"
```

**新代码**:
```python
params = {
    "quantity": str(quantity),
}
if order_type == "LIMIT":
    params["price"] = str(price)
if reduce_only:
    params["reduceOnly"] = "true"
```

### 3.2 Algo 条件单 (place_algo_order)

| 参数 | 旧代码 | 新代码 |
|------|--------|--------|
| quantity 格式 | `f"{quantity:.3f}"` | `str(quantity)` |
| triggerPrice 格式 | `f"{trigger_price:.1f}"` | `str(trigger_price)` |
| reduce_only | 无 | 支持 (参数未使用) |

**旧代码**:
```python
params = {
    "quantity": f"{quantity:.3f}",
    "triggerPrice": f"{trigger_price:.1f}",
}
```

**新代码**:
```python
params = {
    "quantity": str(quantity),
    "triggerPrice": str(trigger_price),
}
```

## 4. WebSocket 差异

### 4.1 连接参数

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| proxy 设置 | `ws_kwargs["proxy"] = self.proxy` | `ws_kwargs["proxy"] = self.client.proxy` |
| SSL 处理 | 通过 session 的 connector | 通过 session 的 connector |

### 4.2 keepalive

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 续期间隔 | 1800 秒 (30分钟) | 1800 秒 (30分钟) |
| 方法名 | `keepalive_listen_key()` | `keepalive_listen_key()` |

## 5. API 方法差异

### 5.1 方法签名

| 方法 | 旧代码 | 新代码 |
|------|--------|--------|
| `get_positions` | `symbol: str` 必填 | `symbol: str = None` 可选 |
| `get_open_orders` | `symbol: str` 必填 | `symbol: str = None` 可选 |
| `get_open_algo_orders` | `symbol: str` 必填 | `symbol: str = None` 可选 |

### 5.2 返回值处理

| 方法 | 旧代码 | 新代码 |
|------|--------|--------|
| `get_positions` | 直接返回 | 确保返回 list |
| `get_open_algo_orders` | 检查 list 或取 `orders` | 检查 list 或取 `orders` |

## 6. 潜在问题

### 6.1 精度问题 (已修复)

新代码使用 `str(quantity)` 和 `str(trigger_price)` 可能导致精度不符合 Binance 要求。

**解决方案**: 在 `BinanceLiveTrader` 中添加了精度调整方法:
- `_adjust_price()` - 调整价格精度
- `_adjust_quantity()` - 调整数量精度

### 6.2 错误处理差异

新代码使用异常机制，需要在调用处正确处理异常。

**当前状态**: 已在 `run()` 方法中添加 try-except 处理。

## 7. 需要修复的问题

### 7.1 place_order 中的精度处理

**问题**: 新代码直接使用 `str(quantity)` 和 `str(price)`，没有精度控制。

**建议**: 参考 `BinanceLiveTrader._place_entry_order()` 中的精度调整逻辑。

### 7.2 place_algo_order 中的精度处理

**问题**: 新代码直接使用 `str(quantity)` 和 `str(trigger_price)`。

**建议**: 在调用 `place_algo_order` 前进行精度调整。

## 8. 总结

| 类别 | 差异程度 | 风险等级 |
|------|----------|----------|
| 架构 | 大 | 低 (改进) |
| 错误处理 | 大 | 中 (需适配) |
| 精度处理 | 中 | 高 (可能导致下单失败) |
| WebSocket | 小 | 低 |
| API 方法 | 小 | 低 |

**主要风险**: 精度处理问题可能导致下单失败，已在 `BinanceLiveTrader` 中修复。
