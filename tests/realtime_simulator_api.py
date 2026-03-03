"""
Autofish V1 实时模拟测试（使用 Binance API）

使用 Binance 测试网 API 进行模拟交易

运行方式：
    cd /Users/liupeng/Documents/trae_projects/hummingbot_learning
    python3 tests/realtime_simulator_api.py
"""

import asyncio
import json
import hmac
import hashlib
import time
import logging
import os
import requests
from decimal import Decimal
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
import aiohttp
from dotenv import load_dotenv


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(PROJECT_DIR, ".env")
load_dotenv(ENV_FILE)

LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, "realtime_simulator_api.log")
STATE_FILE = os.path.join(LOG_DIR, "autofish_state.json")

WECHAT_WEBHOOK = os.getenv("WECHAT_WEBHOOK", "")

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def send_wechat_notification(title: str, content: str) -> bool:
    """发送微信通知"""
    message = {
        "msgtype": "markdown",
        "markdown": {
            "content": f"## {title}\n\n{content}"
        }
    }
    try:
        response = requests.post(WECHAT_WEBHOOK, json=message, timeout=10)
        result = response.json()
        if result.get("errcode") == 0:
            logger.debug(f"[微信通知] 发送成功: {title}")
            return True
        else:
            logger.warning(f"[微信通知] 发送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"[微信通知] 发送异常: {e}")
        return False


def notify_entry_order(order: 'Order', config: dict):
    """通知入场单下单"""
    max_entries = config.get('max_entries', 4)
    content = f"""> **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
> **入场价**: {order.entry_price:.2f} USDT
> **数量**: {order.quantity:.6f} BTC
> **金额**: {order.stake_amount:.2f} USDT
> **止盈价**: {order.take_profit_price:.2f} USDT (+{float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%)
> **止损价**: {order.stop_loss_price:.2f} USDT (-{float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%)
> **订单ID**: {order.order_id}
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    send_wechat_notification(f"🟢 入场单下单 A{order.level}", content)


def notify_entry_filled(order: 'Order', filled_price: Decimal, commission: Decimal, config: dict):
    """通知入场成交"""
    max_entries = config.get('max_entries', 4)
    content = f"""> **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
> **成交价**: {filled_price:.2f} USDT
> **数量**: {order.quantity:.6f} BTC
> **金额**: {order.stake_amount:.2f} USDT
> **止盈价**: {order.take_profit_price:.2f} USDT (+{float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%)
> **止损价**: {order.stop_loss_price:.2f} USDT (-{float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%)
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    send_wechat_notification(f"✅ 入场成交 A{order.level}", content)


def notify_take_profit(order: 'Order', profit: Decimal, config: dict):
    """通知止盈触发"""
    max_entries = config.get('max_entries', 4)
    profit_pct = float(config.get('exit_profit', Decimal('0.01'))) * 100
    content = f"""> **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
> **止盈价**: {order.take_profit_price:.2f} USDT (+{profit_pct:.1f}%)
> **订单金额**: {order.stake_amount:.2f} USDT
> **盈利**: +{profit:.2f} USDT (+{profit_pct:.1f}%)
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    send_wechat_notification(f"🎯 止盈触发 A{order.level}", content)


def notify_stop_loss(order: 'Order', loss: Decimal, config: dict):
    """通知止损触发"""
    max_entries = config.get('max_entries', 4)
    loss_pct = float(config.get('stop_loss', Decimal('0.08'))) * 100
    content = f"""> **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
> **止损价**: {order.stop_loss_price:.2f} USDT (-{loss_pct:.1f}%)
> **订单金额**: {order.stake_amount:.2f} USDT
> **亏损**: -{loss:.2f} USDT (-{loss_pct:.1f}%)
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    send_wechat_notification(f"🛑 止损触发 A{order.level}", content)


def notify_order_amended(order: 'Order', old_price: Decimal, new_price: Decimal, 
                         old_qty: Decimal, new_qty: Decimal, config: dict):
    """通知订单修改"""
    max_entries = config.get('max_entries', 4)
    changes = []
    if new_price != old_price:
        changes.append(f"> **价格**: {old_price:.2f} → {new_price:.2f} USDT")
    if new_qty != old_qty:
        changes.append(f"> **数量**: {old_qty:.6f} → {new_qty:.6f} BTC")
    
    content = f"""> **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
{chr(10).join(changes)}
> **新止盈价**: {order.take_profit_price:.2f} USDT (+{float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%)
> **新止损价**: {order.stop_loss_price:.2f} USDT (-{float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%)
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    send_wechat_notification(f"📝 订单修改 A{order.level}", content)


def notify_error(title: str, error_msg: str):
    """通知错误"""
    content = f"""> **错误**: {error_msg}
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    send_wechat_notification(f"❌ {title}", content)


def notify_orders_recovered(orders: list, config: dict, current_price: Decimal):
    """通知订单恢复"""
    max_entries = config.get('max_entries', 4)
    symbol = config.get('symbol', 'BTCUSDT')
    exit_profit_pct = float(config.get('exit_profit', Decimal('0.01'))) * 100
    stop_loss_pct = float(config.get('stop_loss', Decimal('0.08'))) * 100
    
    state_map = {
        'pending': '挂单中',
        'filled': '已成交',
        'closed': '已平仓',
        'cancelled': '已取消',
    }
    
    order_lines = []
    for order in orders:
        state_text = state_map.get(order.state, order.state)
        level_text = f"第{order.level}层/共{max_entries}层"
        
        if order.state == 'pending':
            order_lines.append(f"""**A{order.level}** `{state_text}` `{level_text}`
> 入场价: {order.entry_price:.2f} USDT
> 止盈价: {order.take_profit_price:.2f} USDT (+{exit_profit_pct:.1f}%)
> 止损价: {order.stop_loss_price:.2f} USDT (-{stop_loss_pct:.1f}%)
> 订单ID: {order.order_id}""")
        elif order.state == 'filled':
            tp_info = f"止盈ID: {order.tp_order_id}" if order.tp_order_id else "止盈ID: 无"
            sl_info = f"止损ID: {order.sl_order_id}" if order.sl_order_id else "止损ID: 无"
            order_lines.append(f"""**A{order.level}** `{state_text}` `{level_text}`
> 入场价: {order.entry_price:.2f} USDT
> 止盈价: {order.take_profit_price:.2f} USDT (+{exit_profit_pct:.1f}%)
> 止损价: {order.stop_loss_price:.2f} USDT (-{stop_loss_pct:.1f}%)
> {tp_info}
> {sl_info}""")
        elif order.state == 'closed':
            close_reason = "止盈" if order.close_reason == "take_profit" else "止损"
            profit_text = f"+{order.profit:.2f}" if order.profit and order.profit > 0 else f"{order.profit:.2f}" if order.profit else "0.00"
            order_lines.append(f"""**A{order.level}** `{state_text}` `{level_text}` ({close_reason})
> 入场价: {order.entry_price:.2f} USDT
> 盈亏: {profit_text} USDT""")
        else:
            order_lines.append(f"""**A{order.level}** `{state_text}` `{level_text}`""")
    
    orders_content = "\n\n".join(order_lines)
    
    content = f"""> **交易对**: {symbol}
> **当前价格**: {current_price:.2f} USDT
> **恢复时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

### 📋 订单列表 (共{len(orders)}个)

{orders_content}"""
    
    send_wechat_notification("🔄 订单恢复", content)


def notify_startup(config: dict, current_price: Decimal):
    """通知程序启动"""
    content = f"""> **交易对**: {config.get('symbol', 'BTCUSDT')}
> **当前价格**: {current_price:.2f} USDT
> **网格间距**: {float(config.get('grid_spacing', Decimal('0.01')))*100:.1f}%
> **止盈**: {float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%
> **止损**: {float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%
> **最大层级**: {config.get('max_entries', 4)}
> **测试网**: True
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    send_wechat_notification("🚀 Autofish V1 启动", content)


def notify_shutdown(results: dict):
    """通知程序停止"""
    net_profit = results['total_profit'] - results['total_loss']
    profit_emoji = "📈" if net_profit >= 0 else "📉"
    
    content = f"""> **总交易**: {results['total_trades']}
> **盈利次数**: {results['win_trades']}
> **亏损次数**: {results['loss_trades']}
> **总盈利**: {results['total_profit']:.2f} USDT
> **总亏损**: {results['total_loss']:.2f} USDT
> **净收益**: {profit_emoji} {net_profit:.2f} USDT
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    send_wechat_notification("⏹️ Autofish V1 停止", content)


@dataclass
class Order:
    """订单"""
    level: int
    entry_price: Decimal
    quantity: Decimal
    stake_amount: Decimal
    take_profit_price: Decimal
    stop_loss_price: Decimal
    state: str = "pending"
    order_id: Optional[int] = None
    tp_order_id: Optional[int] = None
    sl_order_id: Optional[int] = None
    close_price: Optional[Decimal] = None
    close_reason: Optional[str] = None
    profit: Optional[Decimal] = None
    state_history: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    filled_at: Optional[str] = None
    closed_at: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.state_history.append(f"{self.created_at}: pending")

    def set_state(self, new_state: str, reason: str = ""):
        old_state = self.state
        self.state = new_state
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        history_entry = f"{timestamp}: {old_state} -> {new_state}"
        if reason:
            history_entry += f" ({reason})"
        self.state_history.append(history_entry)
        
        if new_state == "filled":
            self.filled_at = timestamp
        elif new_state in ["closed", "cancelled"]:
            self.closed_at = timestamp
        
        logger.info(f"[订单状态变更] A{self.level}: {old_state} -> {new_state} {reason}")
        return self

    def __repr__(self):
        return (f"Order(level={self.level}, state={self.state}, "
                f"entry_price={self.entry_price}, order_id={self.order_id}, "
                f"tp_order_id={self.tp_order_id}, sl_order_id={self.sl_order_id})")
    
    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "level": self.level,
            "entry_price": str(self.entry_price),
            "quantity": str(self.quantity),
            "stake_amount": str(self.stake_amount),
            "take_profit_price": str(self.take_profit_price),
            "stop_loss_price": str(self.stop_loss_price),
            "state": self.state,
            "order_id": self.order_id,
            "tp_order_id": self.tp_order_id,
            "sl_order_id": self.sl_order_id,
            "close_price": str(self.close_price) if self.close_price else None,
            "close_reason": self.close_reason,
            "profit": str(self.profit) if self.profit else None,
            "state_history": self.state_history,
            "created_at": self.created_at,
            "filled_at": self.filled_at,
            "closed_at": self.closed_at,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Order':
        """从字典反序列化"""
        order = cls(
            level=data["level"],
            entry_price=Decimal(data["entry_price"]),
            quantity=Decimal(data["quantity"]),
            stake_amount=Decimal(data["stake_amount"]),
            take_profit_price=Decimal(data["take_profit_price"]),
            stop_loss_price=Decimal(data["stop_loss_price"]),
            state=data.get("state", "pending"),
            order_id=data.get("order_id"),
            tp_order_id=data.get("tp_order_id"),
            sl_order_id=data.get("sl_order_id"),
        )
        if data.get("close_price"):
            order.close_price = Decimal(data["close_price"])
        order.close_reason = data.get("close_reason")
        if data.get("profit"):
            order.profit = Decimal(data["profit"])
        order.state_history = data.get("state_history", [])
        order.created_at = data.get("created_at")
        order.filled_at = data.get("filled_at")
        order.closed_at = data.get("closed_at")
        return order


@dataclass
class ChainState:
    """链式挂单状态"""
    base_price: Decimal
    orders: List[Order] = field(default_factory=list)
    is_active: bool = True

    def get_pending_order(self) -> Optional[Order]:
        for order in self.orders:
            if order.state == "pending":
                return order
        return None

    def get_filled_orders(self) -> List[Order]:
        return [o for o in self.orders if o.state == "filled"]

    def cancel_pending_orders(self):
        for order in self.orders:
            if order.state == "pending":
                order.state = "cancelled"

    def get_order_by_order_id(self, order_id: int) -> Optional[Order]:
        logger.debug(f"[订单查找] 查找order_id={order_id}, 当前订单数={len(self.orders)}")
        for order in self.orders:
            logger.debug(f"  检查订单: A{order.level}, order_id={order.order_id}")
            if order.order_id == order_id:
                logger.debug(f"[订单查找] 找到订单: A{order.level}")
                return order
        logger.debug(f"[订单查找] 未找到order_id={order_id}")
        return None

    def get_order_by_algo_id(self, algo_id: int) -> Optional[Order]:
        logger.debug(f"[订单查找] 查找algo_id={algo_id}, 当前订单数={len(self.orders)}")
        for order in self.orders:
            logger.debug(f"  检查订单: A{order.level}, tp_order_id={order.tp_order_id}, sl_order_id={order.sl_order_id}")
            if order.tp_order_id == algo_id or order.sl_order_id == algo_id:
                order_type = "TP" if order.tp_order_id == algo_id else "SL"
                logger.debug(f"[订单查找] 找到订单: A{order.level}, 类型={order_type}")
                return order
        logger.debug(f"[订单查找] 未找到algo_id={algo_id}")
        return None
    
    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "base_price": str(self.base_price),
            "orders": [o.to_dict() for o in self.orders],
            "is_active": self.is_active,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ChainState':
        """从字典反序列化"""
        state = cls(
            base_price=Decimal(data["base_price"]),
            is_active=data.get("is_active", True),
        )
        state.orders = [Order.from_dict(o) for o in data.get("orders", [])]
        return state
    
    def save_to_file(self, filepath: str):
        """保存状态到文件"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info(f"[状态保存] 成功保存到: {filepath}")
        except Exception as e:
            logger.error(f"[状态保存] 保存失败: {e}")
    
    @classmethod
    def load_from_file(cls, filepath: str) -> Optional['ChainState']:
        """从文件加载状态"""
        try:
            if not os.path.exists(filepath):
                logger.info(f"[状态加载] 文件不存在: {filepath}")
                return None
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            state = cls.from_dict(data)
            logger.info(f"[状态加载] 成功加载 {len(state.orders)} 个订单")
            return state
        except Exception as e:
            logger.error(f"[状态加载] 加载失败: {e}")
            return None


class WeightCalculator:
    """权重计算器"""

    def __init__(self, decay_factor: Decimal = Decimal("0.5")):
        self.decay_factor = decay_factor
        self.amplitude_probabilities = {
            1: Decimal("0.36"),
            2: Decimal("0.24"),
            3: Decimal("0.16"),
            4: Decimal("0.09"),
        }

    def calculate_weights(self) -> List[Decimal]:
        beta = Decimal("1") / self.decay_factor
        raw_weights = []
        for amp, prob in self.amplitude_probabilities.items():
            raw_weight = Decimal(str(amp)) * (prob ** beta)
            raw_weights.append(raw_weight)
        total = sum(raw_weights)
        return [w / total for w in raw_weights]

    def get_stake_amount(self, level: int, total_amount: Decimal) -> Decimal:
        weights = self.calculate_weights()
        if level <= len(weights):
            return total_amount * weights[level - 1]
        return total_amount * weights[-1]


class BinanceAPISimulator:
    """Binance API 模拟器"""

    def __init__(self, config: dict, api_key: str, api_secret: str, testnet: bool = True):
        self.config = config
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        if testnet:
            self.base_url = "https://testnet.binancefuture.com"
            self.ws_url = "wss://stream.binancefuture.com/ws"
        else:
            self.base_url = "https://fapi.binance.com"
            self.ws_url = "wss://fstream.binance.com/ws"
        
        self.calculator = WeightCalculator(config.get("decay_factor", Decimal("0.5")))
        self.chain_state = None
        self.results = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "total_profit": Decimal("0"),
            "total_loss": Decimal("0"),
        }
        self.listen_key = None
        self.session = None
        self.ws_connected = False
        self.ws_last_message_time = None
        self.ws_message_count = 0
        self.ws_error_count = 0
        
        logger.info(f"初始化模拟器: testnet={testnet}, base_url={self.base_url}")
        logger.debug(f"配置: {config}")

    def _sign(self, params: dict) -> str:
        """生成签名"""
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        signature = hmac.new(
            self.api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        logger.debug(f"签名参数: {query_string[:100]}...")
        return signature

    async def _request(self, method: str, endpoint: str, params: dict = None, signed: bool = False) -> dict:
        """发送请求"""
        url = f"{self.base_url}{endpoint}"
        headers = {"X-MBX-APIKEY": self.api_key}
        
        if params is None:
            params = {}
        
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)
        
        request_id = f"{method}-{endpoint}-{int(time.time()*1000)}"
        logger.debug(f"[API请求] {request_id}")
        logger.debug(f"  method={method}, endpoint={endpoint}")
        logger.debug(f"  params={list(params.keys())}")
        
        try:
            start_time = time.time()
            async with self.session.request(method, url, params=params, headers=headers) as resp:
                data = await resp.json()
                elapsed = (time.time() - start_time) * 1000
                
                if resp.status != 200:
                    logger.error(f"[API响应] {request_id} 失败: status={resp.status}, elapsed={elapsed:.0f}ms")
                    logger.error(f"  响应: {data}")
                    if "code" in data and "msg" in data:
                        logger.error(f"  错误码: {data['code']}, 错误信息: {data['msg']}")
                else:
                    logger.debug(f"[API响应] {request_id} 成功: status={resp.status}, elapsed={elapsed:.0f}ms")
                return data
        except aiohttp.ClientError as e:
            logger.error(f"[API请求] {request_id} 网络错误: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"[API请求] {request_id} JSON解析错误: {e}")
            raise
        except Exception as e:
            logger.error(f"[API请求] {request_id} 异常: {e}", exc_info=True)
            raise

    async def get_listen_key(self) -> str:
        """获取用户数据流 listenKey"""
        data = await self._request("POST", "/fapi/v1/listenKey")
        listen_key = data.get("listenKey")
        logger.info(f"获取listenKey: {listen_key[:20]}...")
        return listen_key

    async def keepalive_listen_key(self):
        """保持 listenKey 有效"""
        logger.debug("保持listenKey有效")
        await self._request("PUT", "/fapi/v1/listenKey")

    async def get_account_balance(self) -> dict:
        """获取账户余额"""
        return await self._request("GET", "/fapi/v2/balance", signed=True)

    async def get_current_price(self, symbol: str) -> Decimal:
        """获取当前价格"""
        data = await self._request("GET", "/fapi/v1/ticker/price", {"symbol": symbol})
        price = Decimal(data["price"])
        logger.info(f"当前价格: {symbol}={price}")
        return price

    async def place_order(self, symbol: str, side: str, order_type: str, 
                          quantity: Decimal, price: Decimal = None) -> dict:
        """下单"""
        original_qty = quantity
        original_price = price
        
        quantity = (quantity / Decimal("0.001")).quantize(Decimal("1")) * Decimal("0.001")
        
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        
        params["quantity"] = f"{quantity:.3f}"
        
        if price:
            price = (price / Decimal("0.1")).quantize(Decimal("1")) * Decimal("0.1")
            params["price"] = f"{price:.1f}"
        
        if order_type == "LIMIT":
            params["timeInForce"] = "GTC"
        
        logger.info(f"[下单] {side} {order_type} {symbol}")
        logger.info(f"  原始数量: {original_qty:.6f}, 调整后: {quantity:.3f}")
        if original_price:
            logger.info(f"  原始价格: {original_price:.2f}, 调整后: {price:.1f}")
        logger.debug(f"  下单参数: {params}")
        
        result = await self._request("POST", "/fapi/v1/order", params, signed=True)
        
        if "orderId" in result:
            logger.info(f"[下单] 成功: orderId={result['orderId']}")
            logger.debug(f"  返回结果: {result}")
        else:
            logger.error(f"[下单] 失败: {result}")
        
        return result

    async def cancel_order(self, symbol: str, order_id: int) -> dict:
        """取消订单"""
        logger.info(f"[取消订单] 开始: orderId={order_id}, symbol={symbol}")
        params = {
            "symbol": symbol,
            "orderId": order_id,
        }
        try:
            result = await self._request("DELETE", "/fapi/v1/order", params, signed=True)
            logger.info(f"[取消订单] 成功: orderId={order_id}, status={result.get('status')}")
            logger.debug(f"[取消订单] 结果: {result}")
            return result
        except Exception as e:
            logger.error(f"[取消订单] 失败: orderId={order_id}, error={e}")
            raise

    async def cancel_algo_order(self, symbol: str, algo_id: int) -> dict:
        """取消 Algo 条件单"""
        logger.info(f"[取消Algo订单] 开始: algoId={algo_id}, symbol={symbol}")
        params = {
            "symbol": symbol,
            "algoId": algo_id,
        }
        try:
            result = await self._request("DELETE", "/fapi/v1/algoOrder", params, signed=True)
            logger.info(f"[取消Algo订单] 成功: algoId={algo_id}")
            logger.debug(f"[取消Algo订单] 结果: {result}")
            return result
        except Exception as e:
            logger.error(f"[取消Algo订单] 失败: algoId={algo_id}, error={e}")
            raise

    async def get_open_orders(self, symbol: str) -> list:
        """获取当前挂单"""
        params = {"symbol": symbol}
        return await self._request("GET", "/fapi/v1/openOrders", params, signed=True)
    
    async def get_open_algo_orders(self, symbol: str = None) -> list:
        """获取当前 Algo 条件单"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        result = await self._request("GET", "/fapi/v1/openAlgoOrders", params, signed=True)
        return result.get("orders", []) if isinstance(result, dict) else result
    
    async def get_positions(self, symbol: str = None) -> list:
        """获取当前持仓"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v2/positionRisk", params, signed=True)
    
    async def sync_orders_from_binance(self) -> ChainState:
        """从 Binance 同步订单状态"""
        symbol = self.config.get("symbol", "BTCUSDT")
        logger.info(f"[订单同步] 开始从 Binance 同步订单...")
        
        open_orders = await self.get_open_orders(symbol)
        logger.info(f"[订单同步] 获取到 {len(open_orders)} 个挂单")
        
        algo_orders = await self.get_open_algo_orders(symbol)
        logger.info(f"[订单同步] 获取到 {len(algo_orders)} 个 Algo 条件单")
        
        positions = await self.get_positions(symbol)
        logger.info(f"[订单同步] 获取到 {len(positions)} 个持仓信息")
        
        current_price = await self.get_current_price(symbol)
        
        chain_state = ChainState(base_price=current_price)
        
        entry_orders = [o for o in open_orders if o.get("side") == "BUY" and o.get("type") == "LIMIT"]
        entry_orders.sort(key=lambda x: Decimal(x.get("price", "0")), reverse=True)
        
        for idx, order_data in enumerate(entry_orders):
            order_id = order_data.get("orderId")
            price = Decimal(order_data.get("price", "0"))
            quantity = Decimal(order_data.get("origQty", "0"))
            
            level = idx + 1
            
            exit_profit = self.config.get("exit_profit", Decimal("0.01"))
            stop_loss = self.config.get("stop_loss", Decimal("0.08"))
            take_profit_price = price * (Decimal("1") + exit_profit)
            stop_loss_price = price * (Decimal("1") - stop_loss)
            stake_amount = quantity * price
            
            order = Order(
                level=level,
                entry_price=price,
                quantity=quantity,
                stake_amount=stake_amount,
                take_profit_price=take_profit_price,
                stop_loss_price=stop_loss_price,
                state="pending",
                order_id=order_id,
            )
            order.created_at = datetime.fromtimestamp(order_data.get("time", 0) / 1000).strftime('%Y-%m-%d %H:%M:%S') if order_data.get("time") else None
            
            for algo in algo_orders:
                algo_id = algo.get("algoId")
                algo_type = algo.get("origType")
                algo_qty = Decimal(algo.get("origQty", "0"))
                algo_trigger = Decimal(algo.get("stopPrice", "0"))
                
                if abs(algo_qty - quantity) < Decimal("0.001"):
                    if algo_type == "TAKE_PROFIT_MARKET" and abs(algo_trigger - take_profit_price) < Decimal("10"):
                        order.tp_order_id = algo_id
                        logger.debug(f"[订单同步] A{level} 匹配到止盈单: algoId={algo_id}")
                    elif algo_type == "STOP_MARKET" and abs(algo_trigger - stop_loss_price) < Decimal("10"):
                        order.sl_order_id = algo_id
                        logger.debug(f"[订单同步] A{level} 匹配到止损单: algoId={algo_id}")
            
            chain_state.orders.append(order)
            logger.info(f"[订单同步] 恢复入场单 A{level}: orderId={order_id}, price={price}, "
                       f"tp_id={order.tp_order_id}, sl_id={order.sl_order_id}")
        
        filled_orders_tp = {}
        filled_orders_sl = {}
        for algo in algo_orders:
            algo_type = algo.get("orderType")
            algo_qty_str = algo.get("quantity") or algo.get("origQty", "0")
            algo_trigger_str = algo.get("triggerPrice") or algo.get("stopPrice", "0")
            algo_qty = Decimal(algo_qty_str) if algo_qty_str else Decimal("0")
            algo_trigger = Decimal(algo_trigger_str) if algo_trigger_str else Decimal("0")
            algo_id = algo.get("algoId")
            
            logger.debug(f"[Algo单解析] algoId={algo_id}, type={algo_type}, qty={algo_qty}, trigger={algo_trigger}")
            
            if algo_type == "TAKE_PROFIT_MARKET":
                if algo_qty not in filled_orders_tp:
                    filled_orders_tp[algo_qty] = []
                filled_orders_tp[algo_qty].append({"algo_id": algo_id, "trigger": algo_trigger})
            elif algo_type == "STOP_MARKET":
                if algo_qty not in filled_orders_sl:
                    filled_orders_sl[algo_qty] = []
                filled_orders_sl[algo_qty].append({"algo_id": algo_id, "trigger": algo_trigger})
        
        logger.info(f"[Algo单统计] TP单数量分组: {list(filled_orders_tp.keys())}")
        logger.info(f"[Algo单统计] SL单数量分组: {list(filled_orders_sl.keys())}")
        
        for pos in positions:
            pos_symbol = pos.get("symbol")
            if pos_symbol != symbol:
                continue
            pos_qty = Decimal(pos.get("positionAmt", "0"))
            entry_price = Decimal(pos.get("entryPrice", "0"))
            
            if pos_qty > 0:
                logger.info(f"[订单同步] 发现持仓: quantity={pos_qty}, entryPrice={entry_price}")
                
                matched = False
                for order in chain_state.orders:
                    if abs(order.quantity - pos_qty) < Decimal("0.001") and order.state == "pending":
                        order.set_state("filled", "从持仓恢复")
                        matched = True
                        logger.info(f"[订单同步] 持仓匹配到订单 A{order.level}")
                        break
                
                if not matched:
                    logger.info(f"[订单同步] 持仓未匹配到挂单，创建已成交订单")
                    
                    exit_profit = self.config.get("exit_profit", Decimal("0.01"))
                    stop_loss = self.config.get("stop_loss", Decimal("0.08"))
                    take_profit_price = entry_price * (Decimal("1") + exit_profit)
                    stop_loss_price = entry_price * (Decimal("1") - stop_loss)
                    stake_amount = pos_qty * entry_price
                    
                    level = len(chain_state.orders) + 1
                    
                    filled_order = Order(
                        level=level,
                        entry_price=entry_price,
                        quantity=pos_qty,
                        stake_amount=stake_amount,
                        take_profit_price=take_profit_price,
                        stop_loss_price=stop_loss_price,
                        state="filled",
                    )
                    filled_order.set_state("filled", "从持仓恢复")
                    
                    if pos_qty in filled_orders_tp:
                        for algo_info in filled_orders_tp[pos_qty]:
                            if abs(algo_info["trigger"] - take_profit_price) < Decimal("10"):
                                filled_order.tp_order_id = algo_info["algo_id"]
                                logger.info(f"[订单同步] 匹配到止盈单: algoId={algo_info['algo_id']}, "
                                           f"trigger={algo_info['trigger']}, expected={take_profit_price}")
                                break
                    
                    if pos_qty in filled_orders_sl:
                        for algo_info in filled_orders_sl[pos_qty]:
                            if abs(algo_info["trigger"] - stop_loss_price) < Decimal("10"):
                                filled_order.sl_order_id = algo_info["algo_id"]
                                logger.info(f"[订单同步] 匹配到止损单: algoId={algo_info['algo_id']}, "
                                           f"trigger={algo_info['trigger']}, expected={stop_loss_price}")
                                break
                    
                    chain_state.orders.append(filled_order)
                    logger.info(f"[订单同步] 创建已成交订单 A{level}: entry={entry_price}, "
                               f"tp_id={filled_order.tp_order_id}, sl_id={filled_order.sl_order_id}")
        
        chain_state.orders.sort(key=lambda x: x.entry_price, reverse=True)
        
        logger.info(f"[订单同步] 订单按入场价格排序完成")
        for o in chain_state.orders:
            logger.info(f"  A{o.level}: entry_price={o.entry_price}, state={o.state}")
        
        logger.info(f"[订单同步] 完成，共恢复 {len(chain_state.orders)} 个订单")
        return chain_state

    def _create_order(self, level: int, base_price: Decimal):
        """创建订单"""
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.03"))
        total_amount = self.config.get("total_amount_quote", Decimal("10000"))
        
        logger.debug(f"[价格计算] A{level} 开始: base_price={base_price}, grid_spacing={grid_spacing}, "
                    f"exit_profit={exit_profit}, stop_loss={stop_loss}")
        
        entry_price = base_price * (Decimal("1") - grid_spacing)
        take_profit_price = entry_price * (Decimal("1") + exit_profit)
        stop_loss_price = entry_price * (Decimal("1") - stop_loss)
        stake_amount = self.calculator.get_stake_amount(level, total_amount)
        quantity = stake_amount / entry_price
        
        logger.info(f"[价格计算] A{level} 结果:")
        logger.info(f"  base_price={base_price} -> entry_price={entry_price} (下跌{float(grid_spacing)*100:.1f}%)")
        logger.info(f"  take_profit_price={take_profit_price} (上涨{float(exit_profit)*100:.1f}%)")
        logger.info(f"  stop_loss_price={stop_loss_price} (下跌{float(stop_loss)*100:.1f}%)")
        logger.info(f"  stake_amount={stake_amount} USDT, quantity={quantity:.6f} BTC")
        
        order = Order(
            level=level,
            entry_price=entry_price,
            quantity=quantity,
            stake_amount=stake_amount,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            state="pending",
        )
        self.chain_state.orders.append(order)
        
        logger.info(f"创建订单 A{level}: entry={entry_price}, tp={take_profit_price}, sl={stop_loss_price}")
        logger.debug(f"订单详情: {order}")
        return order

    async def _place_entry_order(self, order: Order):
        """下入场单"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        result = await self.place_order(
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            quantity=order.quantity,
            price=order.entry_price
        )
        
        if "orderId" in result:
            order.order_id = result["orderId"]
            
            weights = self.calculator.calculate_weights()
            weight_pct = weights[order.level - 1] * 100 if order.level <= len(weights) else weights[-1] * 100
            
            print(f"\n{'='*60}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 下单成功: A{order.level}")
            print(f"{'='*60}")
            print(f"  层级: A{order.level} / {self.config.get('max_entries', 4)}")
            print(f"  权重: {weight_pct:.2f}%")
            print(f"  入场价: {order.entry_price:.2f}")
            print(f"  数量: {order.quantity:.6f} BTC")
            print(f"  金额: {order.stake_amount:.2f} USDT")
            print(f"  止盈价: {order.take_profit_price:.2f} (+{float(self.config.get('exit_profit', Decimal('0.01')))*100:.1f}%)")
            print(f"  止损价: {order.stop_loss_price:.2f} (-{float(self.config.get('stop_loss', Decimal('0.08')))*100:.1f}%)")
            print(f"  订单ID: {order.order_id}")
            print(f"{'='*60}\n")
            
            logger.info(f"入场单下单成功: A{order.level}, orderId={order.order_id}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏳ 止盈止损单将在入场成交后下单...")
            
            notify_entry_order(order, self.config)
            self._save_state()
            
        else:
            logger.error(f"入场单下单失败: {result}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 下单失败: {result}")
            notify_error("入场单下单失败", str(result))

    async def _place_exit_orders(self, order: Order, place_tp: bool = True, place_sl: bool = True):
        """下止盈止损条件单 - 使用 Algo Order API"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        logger.info(f"[止盈止损下单] 为A{order.level}下止盈止损单 (TP={place_tp}, SL={place_sl})")
        logger.info(f"  入场价: {order.entry_price}")
        logger.info(f"  数量: {order.quantity:.3f}")
        logger.info(f"  止盈价: {order.take_profit_price} (+{float(self.config.get('exit_profit', Decimal('0.01')))*100:.1f}%)")
        logger.info(f"  止损价: {order.stop_loss_price} (-{float(self.config.get('stop_loss', Decimal('0.08')))*100:.1f}%)")
        
        if place_sl:
            sl_params = {
                "symbol": symbol,
                "side": "SELL",
                "type": "STOP_MARKET",
                "algoType": "CONDITIONAL",
                "quantity": f"{order.quantity:.3f}",
                "triggerPrice": f"{order.stop_loss_price:.1f}",
            }
            logger.info(f"[止损下单] 参数: symbol={symbol}, type=STOP_MARKET, triggerPrice={order.stop_loss_price}")
            logger.debug(f"[止损下单] 完整参数: {sl_params}")
            
            try:
                sl_result = await self._request("POST", "/fapi/v1/algoOrder", sl_params, signed=True)
                logger.debug(f"[止损下单] 响应: {sl_result}")
                
                if "algoId" in sl_result or "orderId" in sl_result:
                    order.sl_order_id = sl_result.get("algoId") or sl_result.get("orderId")
                    logger.info(f"[止损下单] 成功: A{order.level}, algoId={order.sl_order_id}")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 止损条件单已下: 触发价={order.stop_loss_price:.2f}, ID={order.sl_order_id}")
                else:
                    logger.error(f"[止损下单] 失败: {sl_result}")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ 止损条件单失败: {sl_result}")
            except Exception as e:
                logger.error(f"[止损下单] 异常: {e}", exc_info=True)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ 止损条件单异常: {e}")
        
        if place_tp:
            tp_params = {
                "symbol": symbol,
                "side": "SELL",
                "type": "TAKE_PROFIT_MARKET",
                "algoType": "CONDITIONAL",
                "quantity": f"{order.quantity:.3f}",
                "triggerPrice": f"{order.take_profit_price:.1f}",
            }
            logger.info(f"[止盈下单] 参数: symbol={symbol}, type=TAKE_PROFIT_MARKET, triggerPrice={order.take_profit_price}")
            logger.debug(f"[止盈下单] 完整参数: {tp_params}")
        
        try:
            tp_result = await self._request("POST", "/fapi/v1/algoOrder", tp_params, signed=True)
            logger.debug(f"[止盈下单] 响应: {tp_result}")
            
            if "algoId" in tp_result or "orderId" in tp_result:
                order.tp_order_id = tp_result.get("algoId") or tp_result.get("orderId")
                logger.info(f"[止盈下单] 成功: A{order.level}, algoId={order.tp_order_id}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 止盈条件单已下: 触发价={order.take_profit_price:.2f}, ID={order.tp_order_id}")
            else:
                logger.error(f"[止盈下单] 失败: {tp_result}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ 止盈条件单失败: {tp_result}")
        except Exception as e:
            logger.error(f"[止盈下单] 异常: {e}", exc_info=True)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ 止盈条件单异常: {e}")
        
        logger.info(f"[止盈止损下单] A{order.level} 完成: tp_order_id={order.tp_order_id}, sl_order_id={order.sl_order_id}")

    async def _cancel_all_orders(self):
        """取消所有挂单"""
        symbol = self.config.get("symbol", "BTCUSDT")
        logger.info(f"[取消所有订单] 开始, symbol={symbol}")
        
        cancelled_count = 0
        failed_count = 0
        
        for order in self.chain_state.orders:
            if order.state == "pending" and order.order_id:
                try:
                    logger.info(f"[取消所有订单] 取消 A{order.level}, orderId={order.order_id}")
                    await self.cancel_order(symbol, order.order_id)
                    cancelled_count += 1
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ 取消订单: A{order.level}")
                except Exception as e:
                    failed_count += 1
                    logger.error(f"[取消所有订单] 取消失败: A{order.level}, error={e}")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 取消失败: {e}")
        
        logger.info(f"[取消所有订单] 完成: 成功={cancelled_count}, 失败={failed_count}")

    def _save_state(self):
        """保存当前状态"""
        if self.chain_state:
            self.chain_state.save_to_file(STATE_FILE)
    
    def _load_state(self) -> Optional[ChainState]:
        """加载保存的状态"""
        return ChainState.load_from_file(STATE_FILE)
    
    async def _restore_orders(self, current_price: Decimal) -> bool:
        """
        恢复订单状态（从本地文件或 Binance 同步）
        
        Args:
            current_price: 当前价格
            
        Returns:
            bool: 是否需要创建新订单 (True=需要新订单, False=已有活跃订单)
        """
        symbol = self.config.get("symbol", "BTCUSDT")
        need_new_order = True
        
        saved_state = self._load_state()
        
        if saved_state and saved_state.orders:
            logger.info(f"[状态恢复] 发现本地保存的状态: {len(saved_state.orders)} 个订单")
            print(f"\n🔄 发现本地保存的状态: {len(saved_state.orders)} 个订单")
            self.chain_state = saved_state
            self.chain_state.base_price = current_price
            
            for order in self.chain_state.orders:
                logger.info(f"[订单恢复] A{order.level}: state={order.state}")
                logger.info(f"  主订单: order_id={order.order_id}, entry_price={order.entry_price}")
                if order.state == "filled":
                    logger.info(f"  止盈单: tp_order_id={order.tp_order_id}, trigger_price={order.take_profit_price}")
                    logger.info(f"  止损单: sl_order_id={order.sl_order_id}, trigger_price={order.stop_loss_price}")
                elif order.state == "pending":
                    logger.info(f"  止盈单: 未下单 (等待入场成交)")
                    logger.info(f"  止损单: 未下单 (等待入场成交)")
                elif order.state == "closed":
                    logger.info(f"  平仓原因: {order.close_reason}, 盈亏: {order.profit}")
                
                print(f"   A{order.level}: state={order.state}, order_id={order.order_id}, "
                      f"tp_id={order.tp_order_id}, sl_id={order.sl_order_id}")
            
            has_active_order = any(o.state in ["pending", "filled"] for o in self.chain_state.orders)
            if has_active_order:
                need_new_order = False
                
            notify_orders_recovered(self.chain_state.orders, self.config, current_price)
        else:
            print(f"\n🔄 本地无保存状态，尝试从 Binance 同步...")
            self.chain_state = await self.sync_orders_from_binance()
            
            if self.chain_state.orders:
                print(f"\n✅ 从 Binance 同步到 {len(self.chain_state.orders)} 个订单:")
                for order in self.chain_state.orders:
                    logger.info(f"[订单同步] A{order.level}: state={order.state}")
                    logger.info(f"  主订单: order_id={order.order_id}, entry_price={order.entry_price}")
                    if order.state == "filled":
                        logger.info(f"  止盈单: tp_order_id={order.tp_order_id}, trigger_price={order.take_profit_price}")
                        logger.info(f"  止损单: sl_order_id={order.sl_order_id}, trigger_price={order.stop_loss_price}")
                    elif order.state == "pending":
                        logger.info(f"  止盈单: 未下单 (等待入场成交)")
                        logger.info(f"  止损单: 未下单 (等待入场成交)")
                    elif order.state == "closed":
                        logger.info(f"  平仓原因: {order.close_reason}, 盈亏: {order.profit}")
                    
                    print(f"   A{order.level}: state={order.state}, order_id={order.order_id}, "
                          f"tp_id={order.tp_order_id}, sl_id={order.sl_order_id}")
                
                self._save_state()
                
                has_active_order = any(o.state in ["pending", "filled"] for o in self.chain_state.orders)
                if has_active_order:
                    need_new_order = False
                
                notify_orders_recovered(self.chain_state.orders, self.config, current_price)
            else:
                logger.info("[状态恢复] Binance 无订单，创建新订单")
                print(f"\n📋 Binance 无订单，创建新订单...")
                self.chain_state = ChainState(base_price=current_price)
                
                notify_startup(self.config, current_price)
        
        return need_new_order
    
    async def _check_and_supplement_orders(self):
        """
        检查并补充止盈止损单
        
        遍历所有已成交订单，检查是否有缺失的止盈止损单，
        先尝试从 Binance 匹配已有的条件单，如果没有则补下。
        """
        symbol = self.config.get("symbol", "BTCUSDT")
        algo_orders = await self.get_open_algo_orders(symbol)
        logger.info(f"[补单检查] 获取到 {len(algo_orders)} 个 Algo 条件单")
        
        for order in self.chain_state.orders:
            if order.state == "filled":
                if not order.tp_order_id:
                    for algo in algo_orders:
                        if algo.get("orderType") == "TAKE_PROFIT_MARKET":
                            algo_qty_str = algo.get("quantity") or algo.get("origQty", "0")
                            algo_trigger_str = algo.get("triggerPrice") or algo.get("stopPrice", "0")
                            algo_qty = Decimal(algo_qty_str) if algo_qty_str else Decimal("0")
                            algo_trigger = Decimal(algo_trigger_str) if algo_trigger_str else Decimal("0")
                            if abs(algo_qty - order.quantity) < Decimal("0.001") and \
                               abs(algo_trigger - order.take_profit_price) < Decimal("10"):
                                order.tp_order_id = algo.get("algoId")
                                logger.info(f"[补单检查] A{order.level} 匹配到已有止盈单: algoId={order.tp_order_id}")
                                break
                
                if not order.sl_order_id:
                    for algo in algo_orders:
                        if algo.get("orderType") == "STOP_MARKET":
                            algo_qty_str = algo.get("quantity") or algo.get("origQty", "0")
                            algo_trigger_str = algo.get("triggerPrice") or algo.get("stopPrice", "0")
                            algo_qty = Decimal(algo_qty_str) if algo_qty_str else Decimal("0")
                            algo_trigger = Decimal(algo_trigger_str) if algo_trigger_str else Decimal("0")
                            if abs(algo_qty - order.quantity) < Decimal("0.001") and \
                               abs(algo_trigger - order.stop_loss_price) < Decimal("10"):
                                order.sl_order_id = algo.get("algoId")
                                logger.info(f"[补单检查] A{order.level} 匹配到已有止损单: algoId={order.sl_order_id}")
                                break
                
                if not order.tp_order_id and not order.sl_order_id:
                    logger.info(f"[补单] A{order.level} 已成交但无止盈止损单，补下...")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 补下止盈止损单: A{order.level}")
                    await self._place_exit_orders(order)
                    self._save_state()
                elif not order.tp_order_id:
                    logger.warning(f"[补单] A{order.level} 只有止损单，补下止盈单...")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 补下止盈单: A{order.level}")
                    await self._place_exit_orders(order, place_sl=False)
                    self._save_state()
                elif not order.sl_order_id:
                    logger.warning(f"[补单] A{order.level} 只有止盈单，补下止损单...")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 补下止损单: A{order.level}")
                    await self._place_exit_orders(order, place_tp=False)
                    self._save_state()
                else:
                    logger.info(f"[补单检查] A{order.level} 已有止盈止损单，无需补单")

    def _print_summary(self):
        print(f"\n📊 当前统计:")
        print(f"   总交易: {self.results['total_trades']}, 盈利: {self.results['win_trades']}, 亏损: {self.results['loss_trades']}")
        print(f"   总盈利: {float(self.results['total_profit']):.2f}, 总亏损: {float(self.results['total_loss']):.2f}")
        print(f"   净收益: {float(self.results['total_profit'] - self.results['total_loss']):.2f} USDT\n")
        logger.info(f"统计: trades={self.results['total_trades']}, wins={self.results['win_trades']}, "
                    f"profit={self.results['total_profit']}, loss={self.results['total_loss']}")

    async def on_order_update(self, data: dict):
        """处理订单更新"""
        event_type = data.get("e")
        
        logger.debug(f"收到WebSocket事件: {event_type}")
        logger.debug(f"事件数据: {json.dumps(data, default=str)[:500]}")
        
        if event_type == "ALGO_UPDATE":
            logger.info("[事件处理] 收到ALGO_UPDATE事件")
            await self._handle_algo_update(data)
            return
        
        if event_type == "ACCOUNT_UPDATE":
            logger.info("[事件处理] 收到ACCOUNT_UPDATE事件")
            account_data = data.get('a', {})
            logger.debug(f"账户更新数据: {account_data}")
            if 'B' in account_data:
                for balance in account_data['B']:
                    logger.debug(f"  资产: {balance.get('a')}, 余额: {balance.get('wb')}")
            return
        
        if event_type == "listenKeyExpired":
            logger.warning("[事件处理] listenKey已过期, 需要重新获取")
            return
        
        if event_type != "ORDER_TRADE_UPDATE":
            logger.debug(f"[事件处理] 忽略事件: {event_type}")
            return
        
        order_data = data.get("o", {})
        order_status = order_data.get("X")
        order_id = order_data.get("i")
        symbol = order_data.get("s")
        order_type = order_data.get("o")
        execution_type = order_data.get("x")
        client_order_id = order_data.get("c", "")
        
        logger.info(f"[ORDER_TRADE_UPDATE] orderId={order_id}, status={order_status}, "
                   f"type={order_type}, execType={execution_type}, clientOrderId={client_order_id}")
        logger.debug(f"[ORDER_TRADE_UPDATE] 订单详情: {json.dumps(order_data, default=str)}")
        
        order = self.chain_state.get_order_by_order_id(order_id)
        if not order:
            logger.warning(f"[订单匹配] 未找到订单: orderId={order_id}")
            logger.debug(f"[订单匹配] 当前所有订单: {[f'A{o.level}(id={o.order_id})' for o in self.chain_state.orders]}")
            return
        
        logger.info(f"[订单匹配] 成功匹配: A{order.level}, 当前状态={order.state}")
        
        if order_status == "FILLED":
            order.set_state("filled", "入场成交")
            filled_price = Decimal(str(order_data.get("ap", order.entry_price)))
            filled_qty = Decimal(str(order_data.get("z", order.quantity)))
            commission = Decimal(str(order_data.get("n", "0")))
            commission_asset = order_data.get("N", "USDT")
            
            logger.info(f"[成交] A{order.level} 入场成交:")
            logger.info(f"  成交价格: {filled_price}")
            logger.info(f"  成交数量: {filled_qty}")
            logger.info(f"  手续费: {commission} {commission_asset}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ A{order.level} 成交: 价格={filled_price:.2f}")
            
            notify_entry_filled(order, filled_price, commission, self.config)
            
            await self._place_exit_orders(order)
            
            self._save_state()
            
            next_level = order.level + 1
            max_level = self.config.get("max_entries", 4)
            if next_level <= max_level:
                logger.info(f"[链式下单] 创建下一层级订单: A{next_level}")
                new_order = self._create_order(next_level, order.entry_price)
                await self._place_entry_order(new_order)
            else:
                logger.info(f"[链式下单] 已达到最大层级: {max_level}")
            
        elif order_status == "CANCELED":
            order.set_state("cancelled", "订单取消")
            logger.info(f"[取消] A{order.level} 订单已取消")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ A{order.level} 已取消")
        
        elif order_status == "NEW":
            logger.debug(f"[新建] A{order.level} 订单已创建")
        
        elif order_status == "PARTIALLY_FILLED":
            filled_qty = Decimal(str(order_data.get("z", "0")))
            remaining_qty = Decimal(str(order_data.get("q", "0"))) - filled_qty
            logger.info(f"[部分成交] A{order.level}: 已成交={filled_qty}, 剩余={remaining_qty}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📊 A{order.level} 部分成交: {float(filled_qty):.6f} BTC")
        
        elif order_status == "EXPIRED":
            order.set_state("expired", "订单过期")
            logger.warning(f"[过期] A{order.level} 订单已过期")
        
        elif order_status == "REJECTED":
            order.set_state("rejected", "订单被拒绝")
            logger.error(f"[拒绝] A{order.level} 订单被拒绝")
        
        if execution_type == "AMENDMENT":
            new_price = Decimal(str(order_data.get("p", "0")))
            new_qty = Decimal(str(order_data.get("q", "0")))
            old_price = order.entry_price
            old_qty = order.quantity
            
            logger.info(f"[AMENDMENT] A{order.level} 订单修改:")
            logger.info(f"  价格: {old_price} -> {new_price}")
            logger.info(f"  数量: {old_qty} -> {new_qty}")
            
            if new_price > 0 and new_price != old_price:
                logger.info(f"[AMENDMENT] A{order.level} 价格修改: {old_price} -> {new_price}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 A{order.level} 价格修改: {float(old_price):.2f} -> {float(new_price):.2f}")
                order.entry_price = new_price
                old_tp = order.take_profit_price
                old_sl = order.stop_loss_price
                order.take_profit_price = new_price * (Decimal("1") + self.config.get("exit_profit", Decimal("0.01")))
                order.stop_loss_price = new_price * (Decimal("1") - self.config.get("stop_loss", Decimal("0.08")))
                logger.info(f"[AMENDMENT] 止盈止损更新:")
                logger.info(f"  TP: {old_tp} -> {order.take_profit_price}")
                logger.info(f"  SL: {old_sl} -> {order.stop_loss_price}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}]    止盈价更新为: {float(order.take_profit_price):.2f}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}]    止损价更新为: {float(order.stop_loss_price):.2f}")
            
            if new_qty > 0 and new_qty != old_qty:
                logger.info(f"[AMENDMENT] A{order.level} 数量修改: {old_qty} -> {new_qty}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 A{order.level} 数量修改: {float(old_qty):.6f} -> {float(new_qty):.6f}")
                order.quantity = new_qty
                order.stake_amount = new_qty * order.entry_price
            
            if (new_price > 0 and new_price != old_price) or (new_qty > 0 and new_qty != old_qty):
                notify_order_amended(order, old_price, new_price, old_qty, new_qty, self.config)
                self._save_state()

    async def _handle_algo_update(self, data: dict):
        """处理 Algo 条件单更新事件"""
        algo_data = data.get("A", {})
        algo_id = algo_data.get("i")
        algo_status = algo_data.get("X")
        algo_type = algo_data.get("o")
        symbol = algo_data.get("s")
        algo_qty = algo_data.get("q")
        algo_trigger_price = algo_data.get("sp")
        execution_price = algo_data.get("p")
        
        logger.info(f"[ALGO_UPDATE] algoId={algo_id}, status={algo_status}, type={algo_type}")
        logger.info(f"[ALGO_UPDATE] symbol={symbol}, qty={algo_qty}, triggerPrice={algo_trigger_price}")
        logger.debug(f"[ALGO_UPDATE] 完整数据: {json.dumps(algo_data, default=str)}")
        
        order = self.chain_state.get_order_by_algo_id(algo_id)
        if not order:
            logger.warning(f"[ALGO匹配] 未找到对应的Algo订单: algoId={algo_id}")
            logger.debug(f"[ALGO匹配] 当前所有订单TP/SL: {[(f'A{o.level}', o.tp_order_id, o.sl_order_id) for o in self.chain_state.orders]}")
            return
        
        logger.info(f"[ALGO匹配] 成功匹配: A{order.level}")
        logger.info(f"  tp_order_id={order.tp_order_id}, sl_order_id={order.sl_order_id}")
        
        is_tp = (order.tp_order_id == algo_id)
        is_sl = (order.sl_order_id == algo_id)
        order_type_str = "止盈" if is_tp else ("止损" if is_sl else "未知")
        logger.info(f"[ALGO匹配] 订单类型: {order_type_str} (is_tp={is_tp}, is_sl={is_sl})")
        
        if is_tp and algo_status == "FILLED":
            logger.info(f"[止盈触发] A{order.level} 止盈订单已成交!")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 A{order.level} 止盈触发!")
            
            self.results["total_trades"] += 1
            self.results["win_trades"] += 1
            profit = order.stake_amount * self.config.get("exit_profit", Decimal("0.01"))
            self.results["total_profit"] += profit
            
            logger.info(f"[止盈触发] 盈利计算:")
            logger.info(f"  stake_amount={order.stake_amount}")
            logger.info(f"  exit_profit={self.config.get('exit_profit', Decimal('0.01'))}")
            logger.info(f"  profit={profit} USDT")
            print(f"   盈利: {float(profit):.2f} USDT")
            
            notify_take_profit(order, profit, self.config)
            
            if order.sl_order_id:
                logger.info(f"[止盈触发] 取消对应的止损单: algoId={order.sl_order_id}")
                try:
                    cancel_result = await self.cancel_algo_order(symbol, order.sl_order_id)
                    logger.info(f"[止盈触发] 止损单取消结果: {cancel_result}")
                except Exception as e:
                    logger.error(f"[止盈触发] 取消止损单失败: {e}")
            else:
                logger.info(f"[止盈触发] 无需取消止损单 (sl_order_id=None)")
            
            order.set_state("closed", "止盈成交")
            order.close_reason = "take_profit"
            order.close_price = Decimal(str(execution_price)) if execution_price else order.take_profit_price
            order.profit = profit
            self._save_state()
            self._print_summary()
            
        elif is_sl and algo_status == "FILLED":
            logger.info(f"[止损触发] A{order.level} 止损订单已成交!")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 A{order.level} 止损触发!")
            
            self.results["total_trades"] += 1
            self.results["loss_trades"] += 1
            loss = order.stake_amount * self.config.get("stop_loss", Decimal("0.08"))
            self.results["total_loss"] += loss
            
            logger.info(f"[止损触发] 亏损计算:")
            logger.info(f"  stake_amount={order.stake_amount}")
            logger.info(f"  stop_loss={self.config.get('stop_loss', Decimal('0.08'))}")
            logger.info(f"  loss={loss} USDT")
            print(f"   亏损: {float(loss):.2f} USDT")
            
            notify_stop_loss(order, loss, self.config)
            
            if order.tp_order_id:
                logger.info(f"[止损触发] 取消对应的止盈单: algoId={order.tp_order_id}")
                try:
                    cancel_result = await self.cancel_algo_order(symbol, order.tp_order_id)
                    logger.info(f"[止损触发] 止盈单取消结果: {cancel_result}")
                except Exception as e:
                    logger.error(f"[止损触发] 取消止盈单失败: {e}")
            else:
                logger.info(f"[止损触发] 无需取消止盈单 (tp_order_id=None)")
            
            order.set_state("closed", "止损成交")
            order.close_reason = "stop_loss"
            order.close_price = Decimal(str(execution_price)) if execution_price else order.stop_loss_price
            order.profit = -loss
            
            logger.info(f"[止损触发] 取消所有pending订单")
            self.chain_state.cancel_pending_orders()
            self._save_state()
            self._print_summary()
        
        elif algo_status == "NEW":
            logger.debug(f"[ALGO状态] 新建: algoId={algo_id}, type={order_type_str}")
        
        elif algo_status == "CANCELED":
            logger.info(f"[ALGO状态] 已取消: algoId={algo_id}, type={order_type_str}")
            if is_tp:
                order.tp_order_id = None
            elif is_sl:
                order.sl_order_id = None
        
        elif algo_status == "EXPIRED":
            logger.warning(f"[ALGO状态] 过期: algoId={algo_id}, type={order_type_str}")
        
        elif algo_status == "REJECTED":
            logger.error(f"[ALGO状态] 被拒绝: algoId={algo_id}, type={order_type_str}")
        
        else:
            logger.debug(f"[ALGO状态] 其他状态: algoId={algo_id}, status={algo_status}")

    async def run(self):
        """运行模拟器"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        logger.info("=" * 60)
        logger.info("Autofish V1 实时模拟测试启动")
        logger.info("=" * 60)
        logger.info(f"配置: {self.config}")
        
        print("=" * 60)
        print("Autofish V1 实时模拟测试（Binance API）")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {symbol}")
        print(f"  杠杆: {self.config.get('leverage', 10)}x")
        print(f"  网格间距: {float(self.config.get('grid_spacing', Decimal('0.01')))*100}%")
        print(f"  止盈: {float(self.config.get('exit_profit', Decimal('0.01')))*100}%")
        print(f"  止损: {float(self.config.get('stop_loss', Decimal('0.08')))*100}%")
        print(f"  测试网: {self.testnet}")
        print(f"  日志文件: {LOG_FILE}")
        print(f"  状态文件: {STATE_FILE}")
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            print(f"\n📊 获取账户信息...")
            balance = await self.get_account_balance()
            print(f"   账户余额: {balance}")
            
            current_price = await self.get_current_price(symbol)
            print(f"   当前价格: {current_price}")
            
            need_new_order = await self._restore_orders(current_price)
            
            print(f"\n🔗 连接用户数据流...")
            self.listen_key = await self.get_listen_key()
            print(f"   listenKey: {self.listen_key[:20]}...")
            
            if need_new_order:
                first_order = self.chain_state.orders[0] if self.chain_state.orders else self._create_order(1, current_price)
                await self._place_entry_order(first_order)
            else:
                print(f"\n📋 已有订单，等待WebSocket事件...")
                await self._check_and_supplement_orders()
            
            ws_uri = f"{self.ws_url}/{self.listen_key}"
            print(f"\n📡 连接 WebSocket...")
            logger.info(f"[WebSocket] 连接中: {ws_uri[:50]}...")
            logger.info(f"[WebSocket] ws_url={self.ws_url}, listen_key={self.listen_key[:20]}...")
            
            try:
                async with session.ws_connect(ws_uri) as websocket:
                    self.ws_connected = True
                    self.ws_last_message_time = datetime.now()
                    print("✅ 连接成功！开始监听订单状态...\n")
                    logger.info(f"[WebSocket] 连接成功! 时间={self.ws_last_message_time}")
                    
                    async def keepalive():
                        keepalive_count = 0
                        while True:
                            await asyncio.sleep(1800)
                            keepalive_count += 1
                            logger.info(f"[WebSocket] keepalive #{keepalive_count}, 已接收消息={self.ws_message_count}")
                            await self.keepalive_listen_key()
                    
                    asyncio.create_task(keepalive())
                    
                    async for message in websocket:
                        self.ws_message_count += 1
                        self.ws_last_message_time = datetime.now()
                        
                        if message.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(message.data)
                            event_type = data.get("e", "unknown")
                            logger.debug(f"[WebSocket] 消息#{self.ws_message_count} 类型={event_type}")
                            await self.on_order_update(data)
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            self.ws_error_count += 1
                            error = websocket.exception()
                            logger.error(f"[WebSocket] 错误#{self.ws_error_count}: {error}")
                            print(f"WebSocket 错误: {error}")
                            break
                        elif message.type == aiohttp.WSMsgType.CLOSED:
                            logger.warning(f"[WebSocket] 连接关闭, 总消息数={self.ws_message_count}")
                            break
                        elif message.type == aiohttp.WSMsgType.CLOSING:
                            logger.debug(f"[WebSocket] 正在关闭...")
                            
            except KeyboardInterrupt:
                print("\n\n⏹️ 停止模拟")
                logger.info(f"[WebSocket] 用户中断, 总消息={self.ws_message_count}, 错误={self.ws_error_count}")
                await self._cancel_all_orders()
                self._save_state()
                notify_shutdown(self.results)
                self._print_summary()
            except Exception as e:
                logger.error(f"[WebSocket] 运行错误: {e}", exc_info=True)
                print(f"\n❌ 错误: {e}")
                import traceback
                traceback.print_exc()
                notify_error("运行错误", str(e))
                self._save_state()
                self._print_summary()
            finally:
                self.ws_connected = False
                logger.info(f"[WebSocket] 连接结束, 总消息={self.ws_message_count}")


def load_api_keys() -> tuple:
    """从环境变量加载 API Key"""
    api_key = os.getenv("BINANCE_TESTNET_API_KEY")
    api_secret = os.getenv("BINANCE_TESTNET_SECRET_KEY")
    
    logger.info(f"加载API Key: {api_key[:10] if api_key else 'None'}...")
    return api_key, api_secret


async def main():
    api_key, api_secret = load_api_keys()
    
    if not api_key or not api_secret:
        print("❌ 未找到 API Key，请检查 .env 文件")
        logger.error("未找到API Key")
        return
    
    config = {
        "symbol": "BTCUSDT",
        "grid_spacing": Decimal("0.01"),
        "exit_profit": Decimal("0.01"),
        "stop_loss": Decimal("0.08"),
        "decay_factor": Decimal("0.5"),
        "total_amount_quote": Decimal("1200"),
        "leverage": Decimal("10"),
        "max_entries": 4,
    }
    
    simulator = BinanceAPISimulator(config, api_key, api_secret, testnet=True)
    await simulator.run()


if __name__ == '__main__':
    asyncio.run(main())
