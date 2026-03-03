"""
Autofish V1 实盘交易模块

使用 Binance API 进行实盘交易

运行方式：

    python3 -m autofish_bot.live
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
from datetime import datetime
import aiohttp
from dotenv import load_dotenv

from .core import (
    Order,
    ChainState,
    WeightCalculator,
    create_order,
    calculate_profit,
    calculate_order_prices,
    get_default_config,
)
from .amplitude_analyzer import AmplitudeConfig


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(PROJECT_DIR, ".env")
load_dotenv(ENV_FILE)

LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, "live.log")
STATE_FILE = os.path.join(LOG_DIR, "live_state.json")

WECHAT_WEBHOOK = os.getenv("WECHAT_WEBHOOK", "")
HTTP_PROXY = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")

logging.basicConfig(
    level=logging.INFO,
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


def notify_entry_order(order: Order, config: dict):
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


def notify_entry_filled(order: Order, filled_price: Decimal, commission: Decimal, config: dict):
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


def notify_take_profit(order: Order, profit: Decimal, config: dict):
    """通知止盈触发"""
    max_entries = config.get('max_entries', 4)
    content = f"""> **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
> **止盈价**: {order.take_profit_price:.2f} USDT
> **盈亏**: +{profit:.2f} USDT
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    send_wechat_notification(f"🎯 止盈触发 A{order.level}", content)


def notify_stop_loss(order: Order, profit: Decimal, config: dict):
    """通知止损触发"""
    max_entries = config.get('max_entries', 4)
    content = f"""> **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
> **止损价**: {order.stop_loss_price:.2f} USDT
> **盈亏**: {profit:.2f} USDT
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    send_wechat_notification(f"🛑 止损触发 A{order.level}", content)


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
    symbol = config.get('symbol', 'BTCUSDT')
    content = f"""> **交易对**: {symbol}
> **当前价格**: {current_price:.2f} USDT
> **网格间距**: {float(config.get('grid_spacing', Decimal('0.01')))*100}%
> **止盈**: {float(config.get('exit_profit', Decimal('0.01')))*100}%
> **止损**: {float(config.get('stop_loss', Decimal('0.08')))*100}%
> **杠杆**: {config.get('leverage', 10)}x
> **启动时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    send_wechat_notification("🚀 Autofish V1 启动", content)


class BinanceLiveTrader:
    """Binance 实盘交易器"""
    
    def __init__(self, config: dict, testnet: bool = True, use_amplitude_config: bool = True):
        self.config = config
        self.testnet = testnet
        self.use_amplitude_config = use_amplitude_config
        self.amplitude_config: Optional[AmplitudeConfig] = None
        self.custom_weights: Optional[Dict[int, Decimal]] = None
        
        if use_amplitude_config:
            symbol = config.get("symbol", "BTCUSDT")
            self.amplitude_config = AmplitudeConfig.load_latest(symbol)
            if self.amplitude_config:
                decay_factor = Decimal(str(config.get("decay_factor", 0.5)))
                self.custom_weights = self.amplitude_config.get_weights(decay_factor)
                
                self.config["leverage"] = self.amplitude_config.get_leverage()
                self.config["grid_spacing"] = self.amplitude_config.get_grid_spacing()
                self.config["exit_profit"] = self.amplitude_config.get_exit_profit()
                self.config["stop_loss"] = self.amplitude_config.get_stop_loss()
                self.config["total_amount_quote"] = self.amplitude_config.get_total_amount_quote()
                self.config["max_entries"] = self.amplitude_config.get_max_entries()
                
                logger.info(f"[配置加载] 使用振幅分析配置: {symbol}")
                logger.info(f"  杠杆: {self.config['leverage']}x")
                logger.info(f"  权重: {self.custom_weights}")
            else:
                logger.warning("[配置加载] 未找到振幅分析配置，使用默认权重")
        
        self.calculator = WeightCalculator(Decimal(str(self.config.get("decay_factor", 0.5))))
        self.chain_state: Optional[ChainState] = None
        
        if testnet:
            self.base_url = "https://testnet.binancefuture.com"
            self.ws_url = "wss://stream.binancefuture.com/ws"
            self.api_key = os.getenv("BINANCE_TESTNET_API_KEY")
            self.api_secret = os.getenv("BINANCE_TESTNET_SECRET_KEY")
        else:
            self.base_url = "https://fapi.binance.com"
            self.ws_url = "wss://fstream.binance.com/ws"
            self.api_key = os.getenv("BINANCE_API_KEY")
            self.api_secret = os.getenv("BINANCE_SECRET_KEY")
        
        self.proxy = HTTPS_PROXY or HTTP_PROXY or None
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.listen_key: Optional[str] = None
        self.ws_connected = False
        self.ws_message_count = 0
        self.ws_error_count = 0
        self.ws_last_message_time: Optional[datetime] = None
        
        self.results = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "total_profit": Decimal("0"),
            "total_loss": Decimal("0"),
        }
        
        logger.info(f"初始化实盘交易器: testnet={testnet}, base_url={self.base_url}, proxy={self.proxy}")
    
    def _sign(self, params: dict) -> str:
        """签名"""
        query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        signature = hmac.new(
            self.api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    async def _request(self, method: str, endpoint: str, params: dict = None, signed: bool = False) -> dict:
        """发送请求"""
        url = f"{self.base_url}{endpoint}"
        headers = {"X-MBX-APIKEY": self.api_key}
        
        if params is None:
            params = {}
        
        if signed:
            params["timestamp"] = str(int(time.time() * 1000))
            params["signature"] = self._sign(params)
        
        logger.debug(f"[API请求] {method}-{endpoint}-{params.get('timestamp', 'N/A')}")
        
        try:
            kwargs = {"params": params, "headers": headers}
            if self.proxy:
                kwargs["proxy"] = self.proxy
            
            if method == "GET":
                async with self.session.get(url, **kwargs) as response:
                    data = await response.json()
            elif method == "POST":
                async with self.session.post(url, **kwargs) as response:
                    data = await response.json()
            elif method == "DELETE":
                async with self.session.delete(url, **kwargs) as response:
                    data = await response.json()
            else:
                data = {}
            
            logger.debug(f"[API响应] {method}-{endpoint} 成功")
            return data
        except Exception as e:
            logger.error(f"[API请求] 异常: {e}")
            return {"error": str(e)}
    
    async def get_current_price(self, symbol: str) -> Decimal:
        """获取当前价格"""
        data = await self._request("GET", "/fapi/v1/ticker/price", {"symbol": symbol})
        price = Decimal(data.get("price", "0"))
        logger.debug(f"当前价格: {symbol}={price}")
        return price
    
    async def get_account_balance(self) -> Decimal:
        """获取账户余额"""
        data = await self._request("GET", "/fapi/v2/balance", signed=True)
        for item in data:
            if item.get("asset") == "USDT":
                return Decimal(item.get("availableBalance", "0"))
        return Decimal("0")
    
    async def get_listen_key(self) -> str:
        """获取 listenKey"""
        data = await self._request("POST", "/fapi/v1/listenKey")
        return data.get("listenKey", "")
    
    async def keepalive_listen_key(self):
        """续期 listenKey"""
        await self._request("PUT", "/fapi/v1/listenKey")
        logger.info("[listenKey] 续期成功")
    
    async def place_order(self, symbol: str, side: str, order_type: str, quantity: Decimal, price: Decimal = None) -> dict:
        """下单"""
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": f"{quantity:.3f}",
        }
        if price:
            params["price"] = f"{price:.2f}"
            params["timeInForce"] = "GTC"
        
        return await self._request("POST", "/fapi/v1/order", params, signed=True)
    
    async def cancel_order(self, symbol: str, order_id: int) -> dict:
        """取消订单"""
        return await self._request("DELETE", "/fapi/v1/order", {
            "symbol": symbol,
            "orderId": order_id,
        }, signed=True)
    
    async def get_open_orders(self, symbol: str) -> list:
        """获取挂单"""
        return await self._request("GET", "/fapi/v1/openOrders", {"symbol": symbol}, signed=True)
    
    async def get_open_algo_orders(self, symbol: str) -> list:
        """获取 Algo 条件单"""
        data = await self._request("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol}, signed=True)
        return data.get("orders", [])
    
    async def place_algo_order(self, symbol: str, side: str, order_type: str, quantity: Decimal, trigger_price: Decimal) -> dict:
        """下 Algo 条件单"""
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "algoType": "CONDITIONAL",
            "quantity": f"{quantity:.3f}",
            "triggerPrice": f"{trigger_price:.1f}",
        }
        return await self._request("POST", "/fapi/v1/algoOrder", params, signed=True)
    
    async def cancel_algo_order(self, symbol: str, algo_id: int) -> dict:
        """取消 Algo 条件单"""
        return await self._request("DELETE", "/fapi/v1/algoOrder", {
            "symbol": symbol,
            "algoId": algo_id,
        }, signed=True)
    
    async def get_positions(self, symbol: str) -> list:
        """获取持仓"""
        return await self._request("GET", "/fapi/v2/positionRisk", {"symbol": symbol}, signed=True)
    
    def _save_state(self):
        """保存状态"""
        if self.chain_state:
            self.chain_state.save_to_file(STATE_FILE)
    
    def _load_state(self) -> Optional[ChainState]:
        """加载状态"""
        return ChainState.load_from_file(STATE_FILE)
    
    def _create_order(self, level: int, base_price: Decimal) -> Order:
        """创建订单"""
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.08"))
        total_amount = self.config.get("total_amount_quote", Decimal("1200"))
        
        return create_order(
            level=level,
            base_price=base_price,
            grid_spacing=grid_spacing,
            exit_profit=exit_profit,
            stop_loss=stop_loss,
            total_amount=total_amount,
            calculator=self.calculator
        )
    
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
            
            weight_pct = self.calculator.get_weight_percentage(order.level)
            
            print(f"\n{'='*60}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 下单成功: A{order.level}")
            print(f"{'='*60}")
            print(f"  层级: A{order.level} / {self.config.get('max_entries', 4)}")
            print(f"  权重: {weight_pct:.2f}%")
            print(f"  入场价: {order.entry_price:.2f}")
            print(f"  数量: {order.quantity:.6f} BTC")
            print(f"  金额: {order.stake_amount:.2f} USDT")
            print(f"  止盈价: {order.take_profit_price:.2f}")
            print(f"  止损价: {order.stop_loss_price:.2f}")
            print(f"  订单ID: {order.order_id}")
            print(f"{'='*60}\n")
            
            logger.info(f"入场单下单成功: A{order.level}, orderId={order.order_id}")
            
            notify_entry_order(order, self.config)
            self._save_state()
        else:
            logger.error(f"入场单下单失败: {result}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 下单失败: {result}")
    
    async def _place_exit_orders(self, order: Order, place_tp: bool = True, place_sl: bool = True):
        """下止盈止损条件单"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        logger.info(f"[止盈止损下单] 为A{order.level}下止盈止损单 (TP={place_tp}, SL={place_sl})")
        
        if place_sl:
            sl_result = await self.place_algo_order(
                symbol=symbol,
                side="SELL",
                order_type="STOP_MARKET",
                quantity=order.quantity,
                trigger_price=order.stop_loss_price
            )
            if "algoId" in sl_result:
                order.sl_order_id = sl_result["algoId"]
                logger.info(f"[止损下单] 成功: algoId={order.sl_order_id}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 止损条件单已下: 触发价={order.stop_loss_price:.2f}, ID={order.sl_order_id}")
        
        if place_tp:
            tp_result = await self.place_algo_order(
                symbol=symbol,
                side="SELL",
                order_type="TAKE_PROFIT_MARKET",
                quantity=order.quantity,
                trigger_price=order.take_profit_price
            )
            if "algoId" in tp_result:
                order.tp_order_id = tp_result["algoId"]
                logger.info(f"[止盈下单] 成功: algoId={order.tp_order_id}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 止盈条件单已下: 触发价={order.take_profit_price:.2f}, ID={order.tp_order_id}")
        
        self._save_state()
    
    async def _cancel_all_orders(self):
        """取消所有订单"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        for order in self.chain_state.orders:
            if order.state == "pending" and order.order_id:
                try:
                    await self.cancel_order(symbol, order.order_id)
                    logger.info(f"[取消订单] A{order.level} orderId={order.order_id}")
                except Exception as e:
                    logger.error(f"[取消订单] 失败: {e}")
            
            if order.tp_order_id:
                try:
                    await self.cancel_algo_order(symbol, order.tp_order_id)
                except:
                    pass
            if order.sl_order_id:
                try:
                    await self.cancel_algo_order(symbol, order.sl_order_id)
                except:
                    pass
    
    async def _restore_orders(self, current_price: Decimal) -> bool:
        """恢复订单状态"""
        saved_state = self._load_state()
        need_new_order = True
        
        if saved_state and saved_state.orders:
            logger.info(f"[状态恢复] 发现本地保存的状态: {len(saved_state.orders)} 个订单")
            print(f"\n🔄 发现本地保存的状态: {len(saved_state.orders)} 个订单")
            self.chain_state = saved_state
            self.chain_state.base_price = current_price
            
            for order in self.chain_state.orders:
                logger.info(f"[订单恢复] A{order.level}: state={order.state}")
                logger.info(f"  主订单: order_id={order.order_id}, entry_price={order.entry_price}")
                if order.state == "filled":
                    logger.info(f"  止盈单: tp_order_id={order.tp_order_id}")
                    logger.info(f"  止损单: sl_order_id={order.sl_order_id}")
                
                print(f"   A{order.level}: state={order.state}, order_id={order.order_id}, "
                      f"tp_id={order.tp_order_id}, sl_id={order.sl_order_id}")
            
            has_active_order = any(o.state in ["pending", "filled"] for o in self.chain_state.orders)
            if has_active_order:
                need_new_order = False
            
            notify_orders_recovered(self.chain_state.orders, self.config, current_price)
        else:
            self.chain_state = ChainState(base_price=current_price)
            notify_startup(self.config, current_price)
        
        return need_new_order
    
    async def _check_and_supplement_orders(self):
        """检查并补充止盈止损单"""
        symbol = self.config.get("symbol", "BTCUSDT")
        algo_orders = await self.get_open_algo_orders(symbol)
        logger.info(f"[补单检查] 获取到 {len(algo_orders)} 个 Algo 条件单")
        
        for order in self.chain_state.orders:
            if order.state == "filled":
                if not order.tp_order_id and not order.sl_order_id:
                    logger.info(f"[补单] A{order.level} 已成交但无止盈止损单，补下...")
                    await self._place_exit_orders(order)
                else:
                    logger.info(f"[补单检查] A{order.level} 已有止盈止损单，无需补单")
    
    async def _handle_order_update(self, data: dict):
        """处理订单更新"""
        event_type = data.get("e")
        
        if event_type == "ORDER_TRADE_UPDATE":
            order_data = data.get("o", {})
            order_status = order_data.get("X")
            order_id = order_data.get("i")
            
            order = self.chain_state.get_order_by_order_id(order_id)
            if not order:
                logger.warning(f"[订单匹配] 未找到订单: orderId={order_id}")
                return
            
            if order_status == "FILLED":
                order.set_state("filled", "入场成交")
                filled_price = Decimal(str(order_data.get("ap", order.entry_price)))
                
                logger.info(f"[成交] A{order.level} 入场成交: 价格={filled_price}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ A{order.level} 成交: 价格={filled_price:.2f}")
                
                notify_entry_filled(order, filled_price, Decimal("0"), self.config)
                
                await self._place_exit_orders(order)
                
                next_level = order.level + 1
                max_level = self.config.get("max_entries", 4)
                if next_level <= max_level:
                    new_order = self._create_order(next_level, order.entry_price)
                    self.chain_state.orders.append(new_order)
                    await self._place_entry_order(new_order)
            
            elif order_status == "CANCELED":
                order.set_state("cancelled", "订单取消")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ A{order.level} 已取消")
        
        elif event_type == "ALGO_UPDATE":
            await self._handle_algo_update(data)
    
    async def _handle_algo_update(self, data: dict):
        """处理 Algo 条件单更新"""
        algo_id = data.get("algoId")
        algo_status = data.get("algoStatus")
        order_type = data.get("orderType")
        
        order = self.chain_state.get_order_by_algo_id(algo_id)
        if not order:
            logger.warning(f"[Algo匹配] 未找到订单: algoId={algo_id}")
            return
        
        if algo_status == "FILLED":
            is_tp = (order.tp_order_id == algo_id)
            close_price = order.take_profit_price if is_tp else order.stop_loss_price
            
            leverage = self.config.get("leverage", Decimal("10"))
            profit = calculate_profit(order, close_price, leverage)
            order.profit = profit
            order.close_price = close_price
            
            if is_tp:
                order.set_state("closed", "take_profit")
                self.results["win_trades"] += 1
                self.results["total_profit"] += profit
                logger.info(f"[止盈] A{order.level}: 盈利={profit:.2f}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 A{order.level} 止盈: 盈利={profit:.2f} USDT")
                notify_take_profit(order, profit, self.config)
            else:
                order.set_state("closed", "stop_loss")
                self.results["loss_trades"] += 1
                self.results["total_loss"] += abs(profit)
                logger.info(f"[止损] A{order.level}: 亏损={profit:.2f}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 A{order.level} 止损: 亏损={profit:.2f} USDT")
                notify_stop_loss(order, profit, self.config)
            
            self.results["total_trades"] += 1
            
            if is_tp and order.sl_order_id:
                await self.cancel_algo_order(self.config.get("symbol", "BTCUSDT"), order.sl_order_id)
            elif not is_tp and order.tp_order_id:
                await self.cancel_algo_order(self.config.get("symbol", "BTCUSDT"), order.tp_order_id)
            
            self._save_state()
            
            current_price = await self.get_current_price(self.config.get("symbol", "BTCUSDT"))
            new_order = self._create_order(order.level, current_price)
            self.chain_state.orders.append(new_order)
            await self._place_entry_order(new_order)
    
    async def run(self):
        """运行实盘交易"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        logger.info("=" * 60)
        logger.info("Autofish V1 实盘交易启动")
        logger.info("=" * 60)
        
        print("=" * 60)
        print("Autofish V1 实盘交易")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {symbol}")
        print(f"  测试网: {self.testnet}")
        print(f"  日志文件: {LOG_FILE}")
        print(f"  状态文件: {STATE_FILE}")
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            print(f"\n📊 获取账户信息...")
            balance = await self.get_account_balance()
            print(f"   账户余额: {balance:.2f} USDT")
            
            current_price = await self.get_current_price(symbol)
            print(f"   当前价格: {current_price}")
            
            need_new_order = await self._restore_orders(current_price)
            
            print(f"\n🔗 连接用户数据流...")
            self.listen_key = await self.get_listen_key()
            print(f"   listenKey: {self.listen_key[:20]}...")
            
            if need_new_order:
                first_order = self._create_order(1, current_price)
                self.chain_state.orders.append(first_order)
                await self._place_entry_order(first_order)
            else:
                print(f"\n📋 已有订单，等待WebSocket事件...")
                await self._check_and_supplement_orders()
            
            ws_uri = f"{self.ws_url}/{self.listen_key}"
            print(f"\n📡 连接 WebSocket...")
            print(f"   代理: {self.proxy or '无'}")
            
            try:
                ws_kwargs = {}
                if self.proxy:
                    connector = aiohttp.TCPConnector(ssl=False)
                    ws_kwargs["connector"] = connector
                    ws_kwargs["proxy"] = self.proxy
                
                async with session.ws_connect(ws_uri, **ws_kwargs) as websocket:
                    self.ws_connected = True
                    print("✅ 连接成功！开始监听订单状态...\n")
                    
                    async def keepalive():
                        while True:
                            await asyncio.sleep(1800)
                            await self.keepalive_listen_key()
                    
                    asyncio.create_task(keepalive())
                    
                    async for message in websocket:
                        self.ws_message_count += 1
                        self.ws_last_message_time = datetime.now()
                        
                        if message.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(message.data)
                            await self._handle_order_update(data)
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            self.ws_error_count += 1
                            logger.error(f"[WebSocket] 错误: {websocket.exception()}")
                            break
            
            except KeyboardInterrupt:
                print("\n\n⏹️ 停止交易")
                await self._cancel_all_orders()
                self._save_state()
            except Exception as e:
                logger.error(f"[WebSocket] 运行错误: {e}", exc_info=True)
                print(f"\n❌ 错误: {e}")
            finally:
                self.ws_connected = False


async def main():
    """主函数"""
    config = get_default_config()
    config.update({
        "stop_loss": Decimal("0.08"),
        "total_amount_quote": Decimal("1200"),
    })
    
    trader = BinanceLiveTrader(config, testnet=True)
    await trader.run()


if __name__ == "__main__":
    asyncio.run(main())
