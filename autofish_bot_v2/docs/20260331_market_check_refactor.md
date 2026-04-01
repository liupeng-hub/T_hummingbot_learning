# 行情检查机制重构计划

## Context

用户需要重新设计行情检查机制，解决以下问题：

1. **与主程序耦合度高**：行情检测在 WebSocket 循环中，每秒检查一次，但实际检测频率被 `check_interval` 限制
2. **不同算法需求未区分**：各算法对 K线级别需求不同，但当前统一获取 1h K线
3. **K线重复获取**：每次检测都从 Binance API 获取，多个算法/Session 无法复用
4. **检测间隔不合理**：Dual Thrust 基于日线分析，但 `check_interval` 是秒级配置
5. **行情数据表未更新**：数据库有 `live_market_results` 表，但运行时数据可能未正确保存

## 设计决策

| 决策项 | 选择 |
|-------|------|
| 检测方式 | **WebSocket 事件驱动**：订阅 K线流，收盘时计算轨道，盘中检查突破 |
| 数据库策略 | **保持 SQLite**：复用现有 `klines.db` 缓存 |
| 前端展示 | 需要行情时间线 |

## 新架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    BinanceLiveTrader                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ WebSocket 循环 (组合流订阅)                           │   │
│  │                                                       │   │
│  │ 订阅: {symbol}@kline_1d/{listenKey}                   │   │
│  │                                                       │   │
│  │ 消息分发:                                             │   │
│  │ ├── K线事件 (kline) → 行情检测                        │   │
│  │ │   ├── 收盘 (x=true) → 重新计算轨道                  │   │
│  │ │   └── 盘中 (x=false) → 检查价格突破                 │   │
│  │ │                                                     │   │
│  │ └── 用户数据 (订单事件) → 订单处理                     │   │
│  │     ├── ORDER_TRADE_UPDATE → 成交处理                 │   │
│  │     └── 其他订单事件...                               │   │
│  │                                                       │   │
│  │ 周期检查 (timeout=1s):                                │   │
│  │ └── 超时订单检查                                      │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  Dual Thrust 检测逻辑                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  日线收盘事件 (x=true):                                      │
│  ├── 从缓存获取历史 N 天日线                                  │
│  ├── 计算 Range = max(HH-LC, HC-LL)                         │
│  ├── 计算新轨道 Upper/Lower                                  │
│  └── 保存到数据库                                            │
│                                                              │
│  盘中更新事件 (x=false):                                     │
│  ├── 获取当前价格 close                                      │
│  ├── 与已有轨道比较                                          │
│  ├── 突破上轨 → TRENDING_UP                                 │
│  ├── 跌破下轨 → TRENDING_DOWN                               │
│  └── 在轨道内 → RANGING                                      │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   数据库层 (SQLite)                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────┐    ┌──────────────────────────────┐   │
│  │ klines.db        │    │ live_trading.db              │   │
│  │ (K线缓存)        │    │                              │   │
│  │                  │    │ - live_sessions              │   │
│  │ - klines_BTCUSDT │    │ - live_orders                │   │
│  │   _1d            │    │ - live_market_results        │   │
│  │ - 初始化时预加载  │    │ - live_market_dual_thrust (新增)│   │
│  └──────────────────┘    └──────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 算法周期配置简化

事件驱动模式下，**不需要检测周期配置**：

| 方式 | 需要配置 | 检测时机 |
|------|---------|---------|
| 定时轮询 | `check_interval` (秒) | 每 N 秒检测一次 |
| **事件驱动** | 无需配置 | K线事件推送时自动触发 |

### 算法只需定义 K线周期

```python
class DualThrustAlgorithm(StatusAlgorithm):

    @classmethod
    def get_kline_interval(cls) -> str:
        return '1d'  # 日线算法，订阅日线 K线流
```

### 用户配置

```json
{
  "market": {
    "algorithm": "dual_thrust",
    "dual_thrust": {
      "n_days": 4,
      "k1": 0.4,
      "k2": 0.4
    }
  }
}
```

不再需要 `check_interval` 配置。

## MarketCheckTask 设计

复用现有 `KlineFetcher` 缓存机制：

```python
class MarketCheckTask:
    """独立的行情检测任务"""

    def __init__(self, trader, algorithm):
        self.trader = trader
        self.algorithm = algorithm
        self.kline_fetcher = KlineFetcher()  # 复用现有缓存
        self.db = LiveTradingDB()
        self.running = False

        # 从算法获取配置
        self.kline_interval = algorithm.get_kline_interval()
        self.kline_limit = algorithm.get_kline_limit()
        self.check_interval = algorithm.get_check_interval()

        # 用户可通过配置覆盖 check_interval
        user_interval = trader.market_algorithm_params.get('check_interval')
        if user_interval:
            self.check_interval = user_interval

    async def start(self):
        """启动行情检测循环"""
        self.running = True
        self._current_status = MarketStatus.UNKNOWN

        while self.running:
            try:
                # 从缓存获取 K线（复用 KlineFetcher）
                klines = await self.kline_fetcher.fetch_kline(
                    symbol=self.trader.symbol,
                    interval=self.kline_interval,
                    limit=self.kline_limit
                )

                if len(klines) < self.algorithm.get_required_periods():
                    logger.warning("[行情检测] K线数量不足")
                    await asyncio.sleep(self.check_interval)
                    continue

                # 算法计算
                result = self.algorithm.calculate(klines, {})

                # 保存到数据库
                self._save_result(klines, result)

                # 状态变化时回调 Trader
                if result.status != self._current_status:
                    old_status = self._current_status
                    self._current_status = result.status
                    await self.trader.on_market_status_change(old_status, result.status, result)

            except Exception as e:
                logger.error(f"[行情检测] 错误: {e}")

            await asyncio.sleep(self.check_interval)

    def stop(self):
        self.running = False
```

## 涉及文件

| 文件 | 修改内容 |
|------|---------|
| `binance_live.py` | WebSocket 订阅 K线流；K线事件处理；Session 启动时创建 market_case；K线事件触发时保存行情结果；更新 K线缓存 |
| `market_status_detector.py` | `DualThrustAlgorithm` 新增 `get_kline_interval()` 方法 |
| `database/live_trading_db.py` | 新增 `live_market_dual_thrust` 表；`live_market_results` 新增 `event_type`, `indicators` 字段；新增 `save_dual_thrust_bands()` 方法 |
| `binance_kline_fetcher.py` | 新增从 WebSocket K线事件更新缓存的方法 |
| `web/live/index.html` | 添加行情时间线展示 |

## 实现步骤

### Step 1: WebSocket 组合流订阅

**文件**: `binance_live.py`

修改 WebSocket 连接，订阅 K线流 + 用户数据流：

```python
# 原来
ws_url = f"{self.client.ws_url}/{listen_key}"

# 改为组合流
symbol_lower = self.symbol.lower()
streams = f"{symbol_lower}@kline_1d/{listen_key}"
ws_url = f"{self.client.ws_url}/stream?streams={streams}"
```

### Step 2: 消息分发改造

**文件**: `binance_live.py`

```python
async def _handle_ws_message(self, data: Dict[str, Any]) -> None:
    """处理 WebSocket 消息（支持组合流）"""

    # 组合流格式: {"stream": "btcusdt@kline_1d", "data": {...}}
    stream = data.get('stream', '')

    if 'kline' in stream:
        # K线事件
        await self._handle_kline_event(data['data'])
    else:
        # 用户数据事件（原逻辑）
        await self._handle_user_event(data.get('data', data))

async def _handle_kline_event(self, kline_data: Dict) -> None:
    """处理 K线事件"""
    if not self.market_aware:
        return

    kline = kline_data.get('k', {})
    is_closed = kline.get('x', False)  # 是否收盘
    symbol = kline.get('s', '')

    if symbol.lower() != self.symbol.lower():
        return

    if is_closed:
        # 日线收盘，重新计算轨道
        await self._on_daily_kline_closed(kline)
    else:
        # 盘中更新，检查突破
        await self._on_kline_update(kline)
```

### Step 3: 轨道计算与突破检测

**文件**: `binance_live.py`

```python
async def _on_daily_kline_closed(self, kline: Dict) -> None:
    """日线收盘时重新计算轨道"""

    # 1. 从缓存获取历史日线（含刚收盘的）
    klines = await self._fetch_daily_klines(limit=self.n_days + 1)

    # 2. 计算 Dual Thrust 轨道
    result = self.market_detector.algorithm.calculate(klines, {})

    # 3. 缓存轨道数据
    self._current_bands = {
        'upper': result.indicators.get('upper_band'),
        'lower': result.indicators.get('lower_band'),
        'range': result.indicators.get('range'),
        'today_open': result.indicators.get('today_open'),
    }

    # 4. 保存到数据库
    self._save_bands_to_db(result)

    # 5. 更新当前状态
    self.current_market_status = result.status

    logger.info(f"[行情] 日线收盘，新轨道: Upper={self._current_bands['upper']:.2f}, "
                f"Lower={self._current_bands['lower']:.2f}")

async def _on_kline_update(self, kline: Dict) -> None:
    """盘中 K线更新，检查突破"""

    if not self._current_bands:
        # 首次需要先计算轨道
        await self._on_daily_kline_closed(kline)
        return

    current_price = Decimal(str(kline.get('c', 0)))
    upper = self._current_bands.get('upper')
    lower = self._current_bands.get('lower')

    if not upper or not lower:
        return

    # 判断突破
    old_status = self.current_market_status

    if current_price > upper:
        new_status = MarketStatus.TRENDING_UP
    elif current_price < lower:
        new_status = MarketStatus.TRENDING_DOWN
    else:
        new_status = MarketStatus.RANGING

    # 状态变化时触发回调
    if new_status != old_status:
        self.current_market_status = new_status
        await self._handle_market_status_change(old_status, new_status, current_price)

        # 保存到数据库
        self._save_market_result(kline, new_status)
```

### Step 4: 初始化轨道

**文件**: `binance_live.py`

在 `run()` 启动时，初始化轨道：

```python
async def run(self):
    # ...

    # 初始化行情轨道（从历史日线计算）
    if self.market_aware:
        await self._initialize_bands()

    # WebSocket 连接（订阅 K线流）
    # ...
```

### Step 5: 数据库表改进

**文件**: `database/live_trading_db.py`

**新增 live_market_dual_thrust 表（Dual Thrust 专用）**：

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS live_market_dual_thrust (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        calc_time TEXT NOT NULL,
        kline_date TEXT NOT NULL,
        upper_band REAL NOT NULL,
        lower_band REAL NOT NULL,
        range_value REAL NOT NULL,
        today_open REAL NOT NULL,
        hh REAL DEFAULT 0,
        ll REAL DEFAULT 0,
        hc REAL DEFAULT 0,
        lc REAL DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES live_sessions(id)
    )
""")
```

**改进 live_market_results 表**：

```python
# 新增字段
cursor.execute("ALTER TABLE live_market_results ADD COLUMN event_type TEXT DEFAULT 'periodic'")
# event_type: 'daily_close' | 'breakthrough' | 'periodic'

cursor.execute("ALTER TABLE live_market_results ADD COLUMN indicators TEXT DEFAULT '{}'")
# indicators: JSON 存储各算法指标
```

### Step 6: Session 启动时创建 market_case

**文件**: `binance_live.py`

修改 `run()` 方法，在 session 创建后立即创建 market_case：

```python
async def run(self):
    # 创建 session
    self.session_id = self.db.create_session(...)

    # 立即创建 market_case（如果启用行情感知）
    if self.market_aware:
        self.market_case_id = self.db.create_market_case(
            session_id=self.session_id,
            symbol=self.symbol,
            algorithm=self.market_algorithm,
            algorithm_config=self.market_algorithm_params,
            check_interval=0  # 事件驱动模式，不再需要check_interval
        )

    # ... 后续逻辑
```

### Step 7: K线事件触发时保存数据

**文件**: `binance_live.py`

在 `_on_daily_kline_closed()` 和 `_on_kline_update()` 中保存行情结果：

```python
async def _on_daily_kline_closed(self, kline: Dict) -> None:
    # ... 计算轨道 ...

    # 保存到数据库
    if self.market_case_id:
        self.db.save_market_result(
            case_id=self.market_case_id,
            result={
                'check_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'market_status': result.status.value,
                'confidence': result.confidence,
                'reason': result.reason,
                'indicators': result.indicators,  # 新增：保存轨道等指标
                # ... K线数据
            }
        )

        # 保存轨道历史
        self.db.save_dual_thrust_bands(
            session_id=self.session_id,
            bands=self._current_bands
        )
```

### Step 8: K线缓存更新

**文件**: `binance_live.py`

WebSocket 收到 K线事件后，更新 `klines.db` 缓存：

```python
async def _handle_kline_event(self, kline_data: Dict) -> None:
    kline = kline_data.get('k', {})

    # 更新 K线缓存（供其他逻辑复用）
    await self._update_kline_cache(kline)

    # ... 后续行情检测逻辑

async def _update_kline_cache(self, kline: Dict) -> None:
    """更新 K线缓存表"""
    # 使用 KlineFetcher 的缓存机制
    # 将 WebSocket 推送的 K线数据写入 klines.db
    pass
```

### Step 9: 前端展示

**文件**: `web/live/index.html`

添加轨道历史和状态变化时间线展示。

## 验证方案

1. **测试 WebSocket K线订阅**：
   - 验证收到 K线事件
   - 验证区分收盘事件 (`x=true`) 和更新事件

2. **测试轨道计算**：
   - 日线收盘时验证轨道重新计算
   - 检查数据库 `live_market_dual_thrust` 记录

3. **测试突破检测**：
   - 模拟价格突破轨道
   - 验证状态变化触发正确回调

4. **测试数据库保存**：
   - 检查每次状态变化保存到 `live_market_results`
   - 验证 Session 启动时 `live_market_cases` 有记录
   - 验证轨道历史保存到 `live_market_dual_thrust`

5. **测试 K线缓存更新**：
   - 验证 WebSocket K线事件更新 `klines.db` 缓存表

## 回测兼容性说明

**回测逻辑不受影响**：

| 场景 | 数据来源 | 触发时机 | 共用逻辑 |
|------|---------|---------|---------|
| **回测** | 历史缓存 K线 | 遍历 1m K线，每天第一根时检测 | `algorithm.calculate()` |
| **实盘（新）** | WebSocket K线事件 | 收盘时 / 盘中更新时 | `algorithm.calculate()` |

**不修改的部分**：
- `DualThrustAlgorithm.calculate()` 核心计算逻辑
- 回测的 `_check_market_status()` 方法
- `KlineFetcher` 历史数据获取

**仅修改的部分**：
- 实盘的 WebSocket 订阅方式
- 实盘的 K线事件处理
- 实盘的轨道缓存和突破检测

---

*计划版本: 3.1*
*创建日期: 2026-03-31*
*更新: WebSocket 事件驱动 + 数据存储适配（market_case/market_results/klines缓存）*

## 实现状态

✅ **已完成** - 2026-04-01

所有步骤已实现：
1. ✅ 数据库表改进：新增 `live_market_dual_thrust` 表，`live_market_results` 新增 `event_type`、`indicators` 字段
2. ✅ `DualThrustAlgorithm.get_kline_interval()` 方法
3. ✅ WebSocket 组合流订阅：K线流 + 用户数据流
4. ✅ 消息分发改造：区分 K线事件和用户数据事件
5. ✅ K线事件处理：日线收盘计算轨道、盘中检查突破
6. ✅ Session 启动时创建 market_case 和初始化轨道
7. ✅ 保存行情结果到数据库
8. ✅ 前端展示：行情时间线（CSS + `buildMarketTimelineHtml` 函数 + API 调用）