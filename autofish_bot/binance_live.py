"""
Autofish V1 Binance 实盘交易模块

使用 Binance API 进行实盘交易

运行方式：
    cd hummingbot_learning
    source autofish_bot/venv/bin/activate
    python3 -m autofish_bot.binance_live --symbol BTCUSDT

环境变量配置 (.env):
    BINANCE_TESTNET_API_KEY=your_testnet_api_key
    BINANCE_TESTNET_SECRET_KEY=your_testnet_secret_key
    BINANCE_API_KEY=your_mainnet_api_key
    BINANCE_SECRET_KEY=your_mainnet_secret_key
"""

import argparse
import asyncio
import json
import hmac
import hashlib
import time
import logging
import os
import signal
import requests
from decimal import Decimal
from typing import List, Optional, Dict, Any
from datetime import datetime
from textwrap import dedent
import aiohttp
from dotenv import load_dotenv

from .autofish_core import (
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
LOG_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(LOG_DIR, ".env")
load_dotenv(ENV_FILE)
LOG_FILE = os.path.join(LOG_DIR, "binance_live.log")
STATE_FILE = os.path.join(LOG_DIR, "binance_live_state.json")

WECHAT_WEBHOOK = os.getenv("WECHAT_WEBHOOK", "")
HTTP_PROXY = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")

file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)

class FlushFileHandler(logging.FileHandler):
    """每次写入后自动刷新的 FileHandler"""
    def emit(self, record):
        super().emit(record)
        self.flush()

for i, handler in enumerate(logging.getLogger().handlers):
    if isinstance(handler, logging.FileHandler) and not isinstance(handler, FlushFileHandler):
        flush_handler = FlushFileHandler(LOG_FILE, mode='a', encoding='utf-8')
        flush_handler.setLevel(handler.level)
        flush_handler.setFormatter(handler.formatter)
        logging.getLogger().handlers[i] = flush_handler

MESSAGE_COUNTER_FILE = os.path.join(LOG_DIR, "message_counter.txt")


def get_next_message_number() -> int:
    """获取下一个消息号"""
    try:
        if os.path.exists(MESSAGE_COUNTER_FILE):
            with open(MESSAGE_COUNTER_FILE, 'r') as f:
                counter = int(f.read().strip() or '0')
        else:
            counter = 0
        counter += 1
        with open(MESSAGE_COUNTER_FILE, 'w') as f:
            f.write(str(counter))
        return counter
    except Exception as e:
        logger.error(f"[消息号] 获取失败: {e}")
        return 1


def send_wechat_notification(title: str, content: str) -> bool:
    """发送微信通知"""
    msg_num = get_next_message_number()
    content_with_num = f"> **消息号**: {msg_num}\n\n{content}"
    
    message = {
        "msgtype": "markdown",
        "markdown": {
            "content": f"## {title}\n\n{content_with_num}"
        }
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            timeout = 30 if attempt == 0 else 60
            response = requests.post(WECHAT_WEBHOOK, json=message, timeout=timeout)
            result = response.json()
            if result.get("errcode") == 0:
                logger.info(f"[微信通知] 发送成功: {title}, 消息号={msg_num}")
                return True
            else:
                logger.warning(f"[微信通知] 发送失败: {result}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return False
        except Exception as e:
            logger.error(f"[微信通知] 发送异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return False
    
    return False


def notify_entry_order(order: Order, config: dict):
    """通知入场单下单"""
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""\
        > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
        > **入场价**: {order.entry_price:.2f} USDT
        > **数量**: {order.quantity:.6f} BTC
        > **金额**: {order.stake_amount:.2f} USDT
        > **止盈价**: {order.take_profit_price:.2f} USDT (+{float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%)
        > **止损价**: {order.stop_loss_price:.2f} USDT (-{float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%)
        > **订单ID**: {order.order_id}
        > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}""").strip()
    
    send_wechat_notification(f"🟢 入场单下单 A{order.level}", content)


def notify_entry_order_supplement(order: Order, config: dict):
    """通知入场单补下（恢复过程中）"""
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""\
        > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
        > **入场价**: {order.entry_price:.2f} USDT
        > **数量**: {order.quantity:.6f} BTC
        > **金额**: {order.stake_amount:.2f} USDT
        > **止盈价**: {order.take_profit_price:.2f} USDT (+{float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%)
        > **止损价**: {order.stop_loss_price:.2f} USDT (-{float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%)
        > **订单ID**: {order.order_id}
        > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}""").strip()
    
    send_wechat_notification(f"📥 入场单补下 A{order.level}", content)


def notify_entry_filled(order: Order, filled_price: Decimal, commission: Decimal, config: dict):
    """通知入场成交"""
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""
            > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
            > **成交价**: {filled_price:.2f} USDT
            > **数量**: {order.quantity:.6f} BTC
            > **金额**: {order.stake_amount:.2f} USDT
            > **止盈价**: {order.take_profit_price:.2f} USDT (+{float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%)
            > **止损价**: {order.stop_loss_price:.2f} USDT (-{float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%)
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification(f"✅ 入场成交 A{order.level}", content)


def notify_take_profit(order: Order, profit: Decimal, config: dict):
    """通知止盈触发"""
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""
            > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
            > **止盈价**: {order.take_profit_price:.2f} USDT
            > **盈亏**: +{profit:.2f} USDT
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification(f"🎯 止盈触发 A{order.level}", content)


def notify_stop_loss(order: Order, profit: Decimal, config: dict):
    """通知止损触发"""
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""
            > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
            > **止损价**: {order.stop_loss_price:.2f} USDT
            > **盈亏**: {profit:.2f} USDT
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification(f"🛑 止损触发 A{order.level}", content)


def notify_orders_recovered(orders: list, config: dict, current_price: Decimal, pnl_info: dict = None):
    """通知订单同步"""
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
            order_lines.append(dedent(f"""\
                **A{order.level}** `{state_text}` `{level_text}`
                > 入场价: {order.entry_price:.2f} USDT
                > 止盈价: {order.take_profit_price:.2f} USDT (+{exit_profit_pct:.1f}%)
                > 止损价: {order.stop_loss_price:.2f} USDT (-{stop_loss_pct:.1f}%)
                > 订单ID: {order.order_id}"""))
        elif order.state == 'filled':
            extra_lines = []
            if order.tp_supplemented and order.tp_order_id:
                extra_lines.append(f"> 止盈ID: {order.tp_order_id}（补）")
            if order.sl_supplemented and order.sl_order_id:
                extra_lines.append(f"> 止损ID: {order.sl_order_id}（补）")
            
            order_lines.append(dedent(f"""\
                **A{order.level}** `{state_text}` `{level_text}`
                > 入场价: {order.entry_price:.2f} USDT
                > 止盈价: {order.take_profit_price:.2f} USDT (+{exit_profit_pct:.1f}%)
                > 止损价: {order.stop_loss_price:.2f} USDT (-{stop_loss_pct:.1f}%)"""))
            
            if extra_lines:
                order_lines[-1] += "\n" + "\n".join(extra_lines)
        elif order.state == 'closed':
            close_reason = "止盈" if order.close_reason == "take_profit" else "止损"
            profit_text = f"+{order.profit:.2f}" if order.profit and order.profit > 0 else f"{order.profit:.2f}" if order.profit else "0.00"
            order_lines.append(dedent(f"""\
                **A{order.level}** `{state_text}` `{level_text}` ({close_reason})
                > 入场价: {order.entry_price:.2f} USDT
                > 盈亏: {profit_text} USDT"""))
        else:
            order_lines.append(dedent(f"""\
                **A{order.level}** `{state_text}` `{level_text}`"""))
    
    orders_content = "\n\n".join(order_lines)
    
    content_lines = [
        f"> **交易标的**: {symbol}",
        f"> **当前价格**: {current_price:.2f} USDT",
        f"> **恢复时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"### 📋 订单列表 (共{len(orders)}个)",
        "",
        orders_content
    ]
    
    if pnl_info:
        position_qty = pnl_info.get('position_qty', '0')
        if position_qty and position_qty != '0':
            content_lines.append("")
            content_lines.append("### 💰 盈亏信息")
            content_lines.append(f"> **持仓数量**: {position_qty}")
            content_lines.append(f"> **持仓均价**: {pnl_info.get('entry_price', 'N/A')}")
            
            unrealized_pnl = pnl_info.get('unrealized_pnl')
            roi = pnl_info.get('roi')
            if unrealized_pnl and roi:
                pnl_prefix = "+" if float(unrealized_pnl) > 0 else ""
                roi_prefix = "+" if float(roi) > 0 else ""
                content_lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl} USDT ({roi_prefix}{roi}%)")
            elif unrealized_pnl:
                pnl_prefix = "+" if float(unrealized_pnl) > 0 else ""
                content_lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl} USDT")
            else:
                content_lines.append(f"> **未实现盈亏**: N/A")
            
            content_lines.append(f"> **已实现盈亏**: {pnl_info.get('realized_pnl', 'N/A')} USDT")
    
    content = "\n".join(content_lines)
    send_wechat_notification("🔄 订单同步", content)


def notify_exit(reason: str, config: dict, cancelled_orders: list = None, remaining_orders: list = None, pnl_info: dict = None, current_price: Decimal = None):
    """通知程序退出"""
    symbol = config.get('symbol', 'BTCUSDT')
    max_level = config.get('max_entries', 4)
    
    reason_details = {
        "用户手动停止": "用户按下 Ctrl+C",
        "WebSocket 重连失败 (10 次)": "网络重连失败",
        "收到信号 SIGTERM": "系统进程 killed",
    }
    
    display_reason = reason_details.get(reason, reason)
    
    content_lines = [
        f"> **交易标的**: {symbol}",
        f"> **退出时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> **退出原因**: {display_reason}",
    ]
    
    if current_price:
        content_lines.append(f"> **当前价格**: {current_price:.2f} USDT")
    
    if cancelled_orders:
        content_lines.append("")
        content_lines.append("### 📋 已取消的挂单")
        for order in cancelled_orders:
            level_text = f"第{order.level}层/共{max_level}层"
            content_lines.append(dedent(f"""\
                **A{order.level}** `已取消` `{level_text}`
                > 入场价: {order.entry_price:.2f} USDT
                > 金额: {order.stake_amount:.2f} USDT
                > 数量: {order.quantity:.6f} BTC
                > 订单ID: {order.order_id}"""))
    
    filled_orders = [o for o in (remaining_orders or []) if o.state == "filled"]
    if filled_orders:
        content_lines.append("")
        content_lines.append("### 📊 剩余订单列表")
        for order in filled_orders:
            state_text = {"filled": "已成交"}.get(order.state, order.state)
            level_text = f"第{order.level}层/共{max_level}层"
            exit_profit = config.get('exit_profit', Decimal('0.01'))
            stop_loss = config.get('stop_loss', Decimal('0.08'))
            exit_profit_pct = float(exit_profit) * 100
            stop_loss_pct = float(stop_loss) * 100
            content_lines.append(dedent(f"""\
                **A{order.level}** `{state_text}` `{level_text}`
                > 入场价: {order.entry_price:.2f} USDT
                > 止盈价: {order.take_profit_price:.2f} USDT (+{exit_profit_pct:.1f}%)
                > 止损价: {order.stop_loss_price:.2f} USDT (-{stop_loss_pct:.1f}%)"""))
    
    if pnl_info:
        position_qty = pnl_info.get('position_qty', '0')
        if position_qty and position_qty != '0':
            content_lines.append("")
            content_lines.append("### 💰 盈亏信息")
            content_lines.append(f"> **持仓数量**: {position_qty}")
            content_lines.append(f"> **持仓均价**: {pnl_info.get('entry_price', 'N/A')}")
            
            unrealized_pnl = pnl_info.get('unrealized_pnl')
            roi = pnl_info.get('roi')
            if unrealized_pnl and roi:
                pnl_prefix = "+" if float(unrealized_pnl) > 0 else ""
                roi_prefix = "+" if float(roi) > 0 else ""
                content_lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl} USDT ({roi_prefix}{roi}%)")
            elif unrealized_pnl:
                pnl_prefix = "+" if float(unrealized_pnl) > 0 else ""
                content_lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl} USDT")
            else:
                content_lines.append(f"> **未实现盈亏**: N/A")
            
            content_lines.append(f"> **已实现盈亏**: {pnl_info.get('realized_pnl', 'N/A')} USDT")
    
    content_lines.append("")
    content_lines.append("请检查程序状态并手动重启。")
    
    content = "\n".join(content_lines)
    send_wechat_notification("⏹️ Autofish V1 退出", content)


def notify_startup(config: dict, current_price: Decimal, amplitude_config: Optional['AmplitudeConfig'] = None, weights: Optional[Dict[int, Decimal]] = None):
    """通知程序启动"""
    symbol = config.get('symbol', 'BTCUSDT')
    
    weights_str = ""
    if weights:
        weights_str = "> **振幅权重**: " + ", ".join([f"A{k}: {float(v)*100:.1f}%" for k, v in sorted(weights.items())])
    
    content = dedent(f"""
            > **交易标的**: {symbol}
            > **当前价格**: {current_price:.2f} USDT
            > **杠杆倍数**: {config.get('leverage', 10)}x
            > **资金投入**: {config.get('total_amount_quote', 1200)} USDT
            > **网格间距**: {float(config.get('grid_spacing', Decimal('0.01')))*100:.1f}%
            > **止盈比例**: {float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%
            > **止损比例**: {float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%
            > **衰减因子**: {config.get('decay_factor', 0.5)}
            > **最大层级**: {config.get('max_entries', 4)}
            {weights_str}
            > **启动时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
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
                logger.info(f"  配置文件: {self.amplitude_config.config_path}")
                logger.info(f"  交易对: {self.config.get('symbol')}")
                logger.info(f"  杠杆: {self.config['leverage']}x")
                logger.info(f"  总投入: {self.config['total_amount_quote']} USDT")
                logger.info(f"  网格间距: {float(self.config['grid_spacing'])*100:.1f}%")
                logger.info(f"  止盈比例: {float(self.config['exit_profit'])*100:.1f}%")
                logger.info(f"  止损比例: {float(self.config['stop_loss'])*100:.1f}%")
                logger.info(f"  衰减因子: {self.config.get('decay_factor', 0.5)}")
                logger.info(f"  最大层级: {self.config['max_entries']}")
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
        self.exit_notified = False
        
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
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        signature = hmac.new(
            self.api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _sync_request(self, method: str, endpoint: str, params: dict = None, signed: bool = False) -> dict:
        """同步发送请求（用于信号处理器）"""
        url = f"{self.base_url}{endpoint}"
        headers = {"X-MBX-APIKEY": self.api_key}
        
        if params is None:
            params = {}
        
        if signed:
            params["timestamp"] = str(int(time.time() * 1000))
            params["signature"] = self._sign(params)
        
        proxies = None
        if self.proxy:
            proxies = {"http": self.proxy, "https": self.proxy}
        
        try:
            if method == "GET":
                response = requests.get(url, params=params, headers=headers, proxies=proxies, timeout=10)
            elif method == "POST":
                response = requests.post(url, params=params, headers=headers, proxies=proxies, timeout=10)
            elif method == "DELETE":
                response = requests.delete(url, params=params, headers=headers, proxies=proxies, timeout=10)
            else:
                return {}
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def sync_get_positions(self, symbol: str) -> list:
        """同步获取持仓（用于信号处理器）"""
        return self._sync_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol}, signed=True)
    
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
            price = (price / Decimal("0.1")).quantize(Decimal("1")) * Decimal("0.1")
            params["price"] = f"{price:.1f}"
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
    
    async def get_order_status(self, symbol: str, order_id: int) -> dict:
        """查询订单状态"""
        return await self._request("GET", "/fapi/v1/order", {
            "symbol": symbol,
            "orderId": order_id,
        }, signed=True)
    
    async def get_open_algo_orders(self, symbol: str) -> list:
        """获取 Algo 条件单"""
        data = await self._request("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol}, signed=True)
        if isinstance(data, list):
            return data
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
    
    async def get_all_orders(self, symbol: str, limit: int = 100) -> list:
        """查询历史普通订单"""
        return await self._request("GET", "/fapi/v1/allOrders", {
            "symbol": symbol,
            "limit": limit,
        }, signed=True)
    
    async def get_all_algo_orders(self, symbol: str, limit: int = 100) -> list:
        """查询历史 Algo 条件单"""
        data = await self._request("GET", "/fapi/v1/allAlgoOrders", {
            "symbol": symbol,
            "limit": limit,
        }, signed=True)
        if isinstance(data, list):
            return data
        return data.get("orders", [])
    
    async def get_my_trades(self, symbol: str, limit: int = 100) -> list:
        """查询历史成交记录"""
        return await self._request("GET", "/fapi/v1/userTrades", {
            "symbol": symbol,
            "limit": limit,
        }, signed=True)
    
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
    
    async def _place_entry_order_supplement(self, order: Order):
        """下入场单（恢复过程中补下）"""
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
            
            print(f"  层级: A{order.level} / {self.config.get('max_entries', 4)}")
            print(f"  权重: {weight_pct:.2f}%")
            print(f"  入场价: {order.entry_price:.2f}")
            print(f"  数量: {order.quantity:.6f} BTC")
            print(f"  金额: {order.stake_amount:.2f} USDT")
            print(f"  止盈价: {order.take_profit_price:.2f}")
            print(f"  止损价: {order.stop_loss_price:.2f}")
            print(f"  订单ID: {order.order_id}")
            print(f"{'='*60}\n")
            
            logger.info(f"入场单补下成功: A{order.level}, orderId={order.order_id}")
            
            notify_entry_order_supplement(order, self.config)
            self._save_state()
        else:
            logger.error(f"入场单补下失败: {result}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 补下失败: {result}")
    
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
    
    async def _cancel_all_orders(self) -> list:
        """取消所有挂单（只取消 pending 入场单，保留止盈止损单）
        
        Returns:
            list: 已取消的订单列表
        """
        symbol = self.config.get("symbol", "BTCUSDT")
        print(f"\n📋 取消所有挂单...")
        
        cancelled_orders = []
        cancel_failed = []
        
        for order in self.chain_state.orders:
            if order.state == "pending" and order.order_id:
                try:
                    await self.cancel_order(symbol, order.order_id)
                    logger.info(f"[取消订单] A{order.level} 入场单 orderId={order.order_id}")
                    print(f"   ✅ A{order.level} 入场单已取消")
                    cancelled_orders.append(order)
                except Exception as e:
                    logger.error(f"[取消订单] 失败: {e}")
                    print(f"   ❌ A{order.level} 入场单取消失败: {e}")
                    cancel_failed.append(f"A{order.level} 入场单 (orderId={order.order_id})")
        
        if cancel_failed:
            failed_list = "\n".join([f"- {item}" for item in cancel_failed])
            content = dedent(f"""\
                > **交易标的**: {symbol}
                > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                
                以下订单取消失败，请人工取消：
                
                {failed_list}""").strip()
            send_wechat_notification("⚠️ 订单取消失败告警", content)
        
        return cancelled_orders
    
    async def _restore_orders(self, current_price: Decimal) -> bool:
        """恢复订单状态，同步 Binance 实际状态"""
        symbol = self.config.get("symbol", "BTCUSDT")
        saved_state = self._load_state()
        need_new_order = True
        
        if saved_state and saved_state.orders:
            logger.info(f"[状态恢复] 发现本地保存的状态: {len(saved_state.orders)} 个订单")
            print(f"\n🔄 发现本地保存的状态: {len(saved_state.orders)} 个订单")
            
            notify_startup(self.config, current_price, self.amplitude_config, self.custom_weights)
            
            self.chain_state = saved_state
            self.chain_state.base_price = current_price
            
            algo_orders = await self.get_open_algo_orders(symbol)
            algo_ids = {o.get("algoId") for o in algo_orders if o.get("algoId")}
            logger.info(f"[状态恢复] Binance 上有 {len(algo_ids)} 个 Algo 条件单")
            
            positions = await self.get_positions(symbol)
            has_position = any(
                Decimal(p.get('positionAmt', '0')) != Decimal('0')
                for p in positions
            )
            logger.info(f"[状态恢复] 当前仓位状态: {'有仓位' if has_position else '无仓位'}")
            
            algo_history = await self.get_all_algo_orders(symbol, limit=100)
            algo_status_map = {algo.get('algoId'): algo for algo in algo_history if algo.get('algoId')}
            logger.info(f"[状态恢复] 获取到 {len(algo_status_map)} 个历史 Algo 条件单")
            
            orders_to_remove = []
            algo_ids_to_cancel = []
            
            for order in self.chain_state.orders:
                logger.info(f"[订单恢复] A{order.level}: state={order.state}")
                logger.info(f"  主订单: order_id={order.order_id}, entry_price={order.entry_price}")
                
                if order.state == "closed":
                    orders_to_remove.append(order)
                    logger.info(f"[订单清理] A{order.level} 已平仓，删除本地记录")
                    print(f"   🗑️ A{order.level} 已平仓，删除本地记录")
                    continue
                
                if order.state == "cancelled":
                    orders_to_remove.append(order)
                    logger.info(f"[订单清理] A{order.level} 已取消，删除本地记录")
                    print(f"   🗑️ A{order.level} 已取消，删除本地记录")
                    continue
                
                if order.state == "pending" and order.order_id:
                    try:
                        binance_order = await self.get_order_status(symbol, order.order_id)
                        binance_status = binance_order.get("status")
                        logger.info(f"  Binance 状态: {binance_status}")
                        
                        if binance_status == "FILLED":
                            filled_price = Decimal(str(binance_order.get("avgPrice", order.entry_price)))
                            order.set_state("filled", "程序重启同步-已成交")
                            order.entry_price = filled_price
                            logger.info(f"[状态同步] A{order.level} 已在 Binance 成交，更新本地状态")
                            print(f"   ⚡ A{order.level} 已在 Binance 成交，同步状态")
                        elif binance_status == "CANCELED" or binance_status == "EXPIRED":
                            if order.tp_order_id:
                                algo_ids_to_cancel.append(order.tp_order_id)
                            if order.sl_order_id:
                                algo_ids_to_cancel.append(order.sl_order_id)
                            orders_to_remove.append(order)
                            logger.info(f"[状态同步] A{order.level} 在 Binance 已取消，将删除本地订单")
                            print(f"   🗑️ A{order.level} 在 Binance 已取消，将删除")
                        elif binance_status == "NEW" or binance_status == "PARTIALLY_FILLED":
                            logger.info(f"[状态同步] A{order.level} 在 Binance 仍挂单中")
                        else:
                            logger.info(f"[状态同步] A{order.level} Binance 状态: {binance_status}")
                    except Exception as e:
                        error_msg = str(e)
                        if "Order does not exist" in error_msg or "-2013" in error_msg:
                            if order.tp_order_id:
                                algo_ids_to_cancel.append(order.tp_order_id)
                            if order.sl_order_id:
                                algo_ids_to_cancel.append(order.sl_order_id)
                            orders_to_remove.append(order)
                            logger.warning(f"[状态同步] A{order.level} 在 Binance 不存在，将删除本地订单")
                            print(f"   ❌ A{order.level} 在 Binance 不存在，将删除")
                        else:
                            logger.error(f"[状态同步] 查询 Binance 订单状态失败: {e}")
                
                if order.state == "filled":
                    tp_exists = order.tp_order_id in algo_ids if order.tp_order_id else False
                    sl_exists = order.sl_order_id in algo_ids if order.sl_order_id else False
                    
                    logger.info(f"  止盈单: tp_order_id={order.tp_order_id}, 存在={tp_exists}")
                    logger.info(f"  止损单: sl_order_id={order.sl_order_id}, 存在={sl_exists}")
                    
                    if tp_exists:
                        order.tp_supplemented = False
                    if sl_exists:
                        order.sl_supplemented = False
                    
                    if has_position:
                        if not tp_exists:
                            logger.warning(f"  止盈单不存在，需要补单")
                            print(f"   ⚠️ A{order.level} 止盈单在 Binance 不存在，需要补单")
                            order.tp_order_id = None
                        
                        if not sl_exists:
                            logger.warning(f"  止损单不存在，需要补单")
                            print(f"   ⚠️ A{order.level} 止损单在 Binance 不存在，需要补单")
                            order.sl_order_id = None
                    else:
                        close_reason = None
                        
                        if order.tp_order_id and not tp_exists:
                            if order.sl_order_id and sl_exists:
                                algo_ids_to_cancel.append(order.sl_order_id)
                            close_reason = "take_profit"
                            logger.info(f"[平仓检测] A{order.level} 止盈已成交，取消残留止损单")
                        elif order.sl_order_id and not sl_exists:
                            if order.tp_order_id and tp_exists:
                                algo_ids_to_cancel.append(order.tp_order_id)
                            close_reason = "stop_loss"
                            logger.info(f"[平仓检测] A{order.level} 止损已成交，取消残留止盈单")
                        elif not order.tp_order_id and not order.sl_order_id:
                            close_reason = "unknown"
                            logger.info(f"[平仓检测] A{order.level} 无止盈止损单记录，标记为已平仓")
                        else:
                            if order.tp_order_id and order.tp_order_id in algo_status_map:
                                algo_info = algo_status_map[order.tp_order_id]
                                if algo_info.get('status') in ['TRIGGERED', 'FINISHED']:
                                    if order.sl_order_id and sl_exists:
                                        algo_ids_to_cancel.append(order.sl_order_id)
                                    close_reason = "take_profit"
                            if not close_reason and order.sl_order_id and order.sl_order_id in algo_status_map:
                                algo_info = algo_status_map[order.sl_order_id]
                                if algo_info.get('status') in ['TRIGGERED', 'FINISHED']:
                                    if order.tp_order_id and tp_exists:
                                        algo_ids_to_cancel.append(order.tp_order_id)
                                    close_reason = "stop_loss"
                        
                        if close_reason:
                            orders_to_remove.append(order)
                            print(f"   ✅ A{order.level} 已平仓，原因: {close_reason}，删除本地订单")
                
                if order not in orders_to_remove:
                    print(f"   A{order.level}: state={order.state}, order_id={order.order_id}, "
                          f"tp_id={order.tp_order_id}, sl_id={order.sl_order_id}")
            
            for algo_id in algo_ids_to_cancel:
                if algo_id in algo_ids:
                    try:
                        await self.cancel_algo_order(symbol, algo_id)
                        logger.info(f"[取消残留条件单] algoId={algo_id}")
                    except Exception as e:
                        logger.warning(f"[取消残留条件单] 失败 algoId={algo_id}: {e}")
            
            for order in orders_to_remove:
                for i, o in enumerate(self.chain_state.orders):
                    if o.order_id == order.order_id and o.level == order.level and o.state == order.state:
                        self.chain_state.orders.pop(i)
                        logger.info(f"[删除订单] A{order.level} (order_id={order.order_id}, state={order.state}) 已从本地删除")
                        break
            
            # 调整订单级别：确保级别从 A1 开始连续编号
            if self.chain_state.orders:
                # 按原级别排序
                self.chain_state.orders.sort(key=lambda o: o.level)
                # 重新分配级别
                for new_level, order in enumerate(self.chain_state.orders, start=1):
                    old_level = order.level
                    if old_level != new_level:
                        order.level = new_level
                        logger.info(f"[级别调整] A{old_level} -> A{new_level}")
                        print(f"   📊 A{old_level} 级别调整为 A{new_level}")
            
            self._save_state()
            
            if self.chain_state.orders:
                pnl_info = {}
                try:
                    symbol = self.config.get("symbol", "BTCUSDT")
                    positions = await self.get_positions(symbol)
                    if positions:
                        pos = positions[0]
                        position_qty = Decimal(pos.get("positionAmt", "0"))
                        entry_price = Decimal(pos.get("entryPrice", "0"))
                        unrealized_pnl = Decimal(pos.get("unRealizedProfit", "0"))
                        
                        roi = None
                        if entry_price > 0 and position_qty != 0:
                            roi = float(unrealized_pnl / (entry_price * abs(position_qty)) * 100)
                        
                        pnl_info = {
                            "position_qty": str(position_qty),
                            "entry_price": f"{entry_price:.2f}",
                            "unrealized_pnl": f"{unrealized_pnl:.2f}",
                            "roi": f"{roi:.2f}" if roi is not None else None,
                            "realized_pnl": "N/A"
                        }
                except Exception as e:
                    logger.warning(f"[获取盈亏信息] 失败: {e}")
                
                notify_orders_recovered(self.chain_state.orders, self.config, current_price, pnl_info)
            
            has_active_order = any(o.state in ["pending", "filled"] for o in self.chain_state.orders)
            if has_active_order:
                need_new_order = False
        else:
            self.chain_state = ChainState(base_price=current_price)
            notify_startup(self.config, current_price, self.amplitude_config, self.custom_weights)
        
        return need_new_order
    
    async def _check_and_supplement_orders(self):
        """检查并补充止盈止损单"""
        symbol = self.config.get("symbol", "BTCUSDT")
        algo_orders = await self.get_open_algo_orders(symbol)
        logger.info(f"[补单检查] 获取到 {len(algo_orders)} 个 Algo 条件单")
        
        current_price = await self._get_current_price(symbol)
        
        for order in self.chain_state.orders:
            if order.state == "filled":
                need_tp = not order.tp_order_id
                need_sl = not order.sl_order_id
                
                if need_sl:
                    sl_exceeded = current_price <= order.stop_loss_price
                    if sl_exceeded:
                        logger.warning(f"[补止损] A{order.level} 当前价 {current_price} 已跌破止损价 {order.stop_loss_price}，市价止损")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ A{order.level} 当前价已跌破止损价，市价止损")
                        await self._market_close_order(order, "stop_loss")
                        continue
                    else:
                        logger.info(f"[补止损] A{order.level} 下止损单: 触发价={order.stop_loss_price}")
                        await self._place_sl_order(order)
                
                if need_tp:
                    tp_exceeded = current_price >= order.take_profit_price
                    if tp_exceeded:
                        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
                        new_tp_price = current_price * (Decimal("0.5") * grid_spacing + Decimal("1"))
                        logger.warning(f"[补止盈] A{order.level} 当前价 {current_price} 已超过止盈价 {order.take_profit_price}，调整止盈价为 {new_tp_price}")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ A{order.level} 当前价已超过止盈价，调整止盈价为 {new_tp_price:.2f}")
                        order.take_profit_price = new_tp_price
                    
                    logger.info(f"[补止盈] A{order.level} 下止盈单: 触发价={order.take_profit_price}")
                    await self._place_tp_order(order)
                
                if not need_tp and not need_sl:
                    logger.info(f"[补单检查] A{order.level} 已有止盈止损单，无需补单")
    
    async def _place_tp_order(self, order: Order):
        """单独下止盈单"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        tp_result = await self.place_algo_order(
            symbol=symbol,
            side="SELL",
            order_type="TAKE_PROFIT_MARKET",
            quantity=order.quantity,
            trigger_price=order.take_profit_price
        )
        if "algoId" in tp_result:
            order.tp_order_id = tp_result["algoId"]
            order.tp_supplemented = True
            logger.info(f"[止盈下单] 成功: algoId={order.tp_order_id}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 止盈条件单已下（补）: 触发价={order.take_profit_price:.2f}, ID={order.tp_order_id}")
            self._save_state()
    
    async def _place_sl_order(self, order: Order):
        """单独下止损单"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        sl_result = await self.place_algo_order(
            symbol=symbol,
            side="SELL",
            order_type="STOP_MARKET",
            quantity=order.quantity,
            trigger_price=order.stop_loss_price
        )
        if "algoId" in sl_result:
            order.sl_order_id = sl_result["algoId"]
            order.sl_supplemented = True
            logger.info(f"[止损下单] 成功: algoId={order.sl_order_id}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 止损条件单已下（补）: 触发价={order.stop_loss_price:.2f}, ID={order.sl_order_id}")
            self._save_state()
    
    async def _get_current_price(self, symbol: str) -> Decimal:
        """获取当前价格"""
        ticker = await self._request("GET", "/fapi/v1/ticker/price", {"symbol": symbol})
        return Decimal(str(ticker.get("price", "0")))
    
    async def _market_close_order(self, order: Order, reason: str):
        """市价平仓"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        try:
            result = await self._request("POST", "/fapi/v1/order", {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": str(order.quantity),
            }, signed=True)
            
            order.set_state("closed", reason)
            logger.info(f"[市价平仓] A{order.level} 成功: orderId={result.get('orderId')}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 A{order.level} 市价平仓成功")
            
            self._save_state()
            
        except Exception as e:
            logger.error(f"[市价平仓] A{order.level} 失败: {e}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ A{order.level} 市价平仓失败: {e}")
    
    async def _handle_order_update(self, data: dict):
        """处理订单更新"""
        event_type = data.get("e")
        
        if event_type == "ORDER_TRADE_UPDATE":
            order_data = data.get("o", {})
            order_status = order_data.get("X")
            order_id = order_data.get("i")
            
            order = self.chain_state.get_order_by_order_id(order_id)
            if not order:
                logger.debug(f"[订单事件] 非入场单订单: orderId={order_id}, status={order_status}")
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
            
            elif order_status == "EXPIRED":
                logger.info(f"[订单过期] A{order.level} 入场单已过期")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏰ A{order.level} 入场单已过期")
                
                if order.tp_order_id or order.sl_order_id:
                    algo_ids_to_cancel = []
                    if order.tp_order_id:
                        algo_ids_to_cancel.append(order.tp_order_id)
                    if order.sl_order_id:
                        algo_ids_to_cancel.append(order.sl_order_id)
                    
                    for algo_id in algo_ids_to_cancel:
                        try:
                            await self.cancel_algo_order(self.config.get("symbol", "BTCUSDT"), algo_id)
                            logger.info(f"[取消关联条件单] algoId={algo_id}")
                        except Exception as e:
                            logger.warning(f"[取消关联条件单] 失败 algoId={algo_id}: {e}")
                
                self.chain_state.orders.remove(order)
                logger.info(f"[删除订单] A{order.level} 已从本地删除")
                self._save_state()
            
            elif order_status == "TRADE_PREVENT":
                prevent_reason = order_data.get("V", "STP触发")
                logger.info(f"[STP触发] A{order.level} 订单因自成交保护被取消: {prevent_reason}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ A{order.level} 订单因STP被取消: {prevent_reason}")
                
                if order.tp_order_id or order.sl_order_id:
                    algo_ids_to_cancel = []
                    if order.tp_order_id:
                        algo_ids_to_cancel.append(order.tp_order_id)
                    if order.sl_order_id:
                        algo_ids_to_cancel.append(order.sl_order_id)
                    
                    for algo_id in algo_ids_to_cancel:
                        try:
                            await self.cancel_algo_order(self.config.get("symbol", "BTCUSDT"), algo_id)
                            logger.info(f"[取消关联条件单] algoId={algo_id}")
                        except Exception as e:
                            logger.warning(f"[取消关联条件单] 失败 algoId={algo_id}: {e}")
                
                self.chain_state.orders.remove(order)
                logger.info(f"[删除订单] A{order.level} 已从本地删除")
                self._save_state()
            
            elif order_status == "AMENDMENT":
                new_price = Decimal(str(order_data.get("p", order.entry_price)))
                new_qty = Decimal(str(order_data.get("q", order.quantity)))
                price_changed = new_price != order.entry_price
                qty_changed = new_qty != order.quantity
                
                if price_changed or qty_changed:
                    old_price = order.entry_price
                    old_qty = order.quantity
                    
                    if price_changed:
                        order.entry_price = new_price
                        
                        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
                        stop_loss = self.config.get("stop_loss", Decimal("0.08"))
                        
                        order.take_profit_price = new_price * (Decimal("1") + exit_profit)
                        order.stop_loss_price = new_price * (Decimal("1") - stop_loss)
                    
                    if qty_changed:
                        order.quantity = new_qty
                    
                    logger.info(f"[手动修改] A{order.level} 入场单已更新: 价格 {old_price:.2f} -> {new_price:.2f}, 数量 {old_qty:.6f} -> {new_qty:.6f}")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✏️ A{order.level} 入场单已手动修改:")
                    if price_changed:
                        print(f"   价格: {old_price:.2f} -> {new_price:.2f}")
                        print(f"   止盈价: {order.take_profit_price:.2f}, 止损价: {order.stop_loss_price:.2f}")
                    if qty_changed:
                        print(f"   数量: {old_qty:.6f} -> {new_qty:.6f}")
                    self._save_state()
        
        elif event_type == "ALGO_UPDATE":
            await self._handle_algo_update(data)
    
    async def _handle_algo_update(self, data: dict):
        """处理 Algo 条件单更新"""
        outer_algo_id = data.get("g") or data.get("algoId")
        outer_status = data.get("X") or data.get("algoStatus")
        
        inner_data = data.get("o", {})
        algo_id = inner_data.get("aid") or outer_algo_id
        algo_status = inner_data.get("X") or outer_status
        order_type = inner_data.get("o") or data.get("orderType")
        
        if not algo_id:
            logger.warning(f"[Algo事件] 数据格式异常: {data}")
            return
        
        order = self.chain_state.get_order_by_algo_id(algo_id)
        if not order:
            logger.warning(f"[Algo匹配] 未找到订单: algoId={algo_id}")
            return
        
        logger.info(f"[Algo事件] algoId={algo_id}, status={algo_status}, orderType={order_type}")
        
        # Algo 条件单状态说明:
        # - TRIGGERING: 触发中（中间状态，不处理）
        # - TRIGGERED: 已触发（中间状态，不处理，等待 FINISHED）
        # - FINISHED: 已完成（最终状态，处理止盈/止损）
        # - CANCELED: 已取消（用户手动取消）
        # - EXPIRED: 已过期（需要补单）
        # - REJECTED: 被拒绝（需要补单）
        # 注意: 只处理 FINISHED 状态，避免重复处理 TRIGGERED 和 FINISHED 两个事件
        if algo_status in ["FINISHED", "finished"]:
            # 防止重复处理：如果订单已经是 closed 状态，跳过
            if order.state == "closed":
                logger.info(f"[Algo事件] A{order.level} 已处理过，跳过")
                return
            
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
            
            # 取消下一级挂单（level + 1）
            # 例如：A1 止盈 → 取消 A2 挂单 → 重新下 A1
            # 例如：A2 止盈 → 取消 A3 挂单 → 重新下 A2
            # 注意：下一级订单是 pending 状态（挂单中），还没有成交，所以不会有止盈止损单
            symbol = self.config.get("symbol", "BTCUSDT")
            next_level = order.level + 1
            next_order = None
            for o in self.chain_state.orders:
                if o.level == next_level and o.state == "pending":
                    next_order = o
                    break
            
            if next_order and next_order.order_id:
                try:
                    await self.cancel_order(symbol, next_order.order_id)
                    logger.info(f"[取消下一级挂单] A{next_order.level} 入场单已取消")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ A{next_order.level} 下一级挂单已取消")
                except Exception as e:
                    logger.warning(f"[取消下一级挂单] A{next_order.level} 取消失败: {e}")
                
                # 删除下一级订单的本地记录
                self.chain_state.orders.remove(next_order)
                logger.info(f"[删除下一级订单] A{next_order.level} 已删除")
            
            self._save_state()
            
            current_price = await self.get_current_price(self.config.get("symbol", "BTCUSDT"))
            new_order = self._create_order(order.level, current_price)
            self.chain_state.orders.append(new_order)
            await self._place_entry_order(new_order)
        
        elif algo_status in ["CANCELED", "canceled"]:
            is_tp = (order.tp_order_id == algo_id)
            if is_tp:
                order.tp_order_id = None
                order.tp_supplemented = False
                logger.info(f"[手动取消] A{order.level} 止盈单已取消")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ A{order.level} 止盈单已手动取消")
            else:
                order.sl_order_id = None
                order.sl_supplemented = False
                logger.info(f"[手动取消] A{order.level} 止损单已取消")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ A{order.level} 止损单已手动取消")
            
            self._save_state()
        
        elif algo_status in ["EXPIRED", "expired"]:
            is_tp = (order.tp_order_id == algo_id)
            if is_tp:
                order.tp_order_id = None
                order.tp_supplemented = False
                logger.info(f"[条件单过期] A{order.level} 止盈单已过期，需要补单")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏰ A{order.level} 止盈单已过期，需要补单")
            else:
                order.sl_order_id = None
                order.sl_supplemented = False
                logger.info(f"[条件单过期] A{order.level} 止损单已过期，需要补单")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏰ A{order.level} 止损单已过期，需要补单")
            
            self._save_state()
        
        elif algo_status in ["REJECTED", "rejected"]:
            is_tp = (order.tp_order_id == algo_id)
            reject_reason = inner_data.get("r", "未知原因")
            if is_tp:
                order.tp_order_id = None
                order.tp_supplemented = False
                logger.info(f"[条件单拒绝] A{order.level} 止盈单被拒绝: {reject_reason}，需要补单")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ A{order.level} 止盈单被拒绝: {reject_reason}，需要补单")
            else:
                order.sl_order_id = None
                order.sl_supplemented = False
                logger.info(f"[条件单拒绝] A{order.level} 止损单被拒绝: {reject_reason}，需要补单")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ A{order.level} 止损单被拒绝: {reject_reason}，需要补单")
            
            self._save_state()
        
        elif algo_status in ["NEW", "new"]:
            symbol = inner_data.get("s") or data.get("symbol")
            trigger_price = Decimal(str(inner_data.get("tp") or inner_data.get("sp") or 0))
            order_type_str = inner_data.get("o") or order_type
            
            if symbol != self.config.get("symbol", "BTCUSDT"):
                return
            
            is_tp_order = order_type_str in ["TAKE_PROFIT_MARKET", "TAKE_PROFIT"]
            is_sl_order = order_type_str in ["STOP_MARKET", "STOP_LOSS"]
            
            if is_tp_order and order.tp_order_id == algo_id:
                if trigger_price != order.take_profit_price:
                    old_price = order.take_profit_price
                    order.take_profit_price = trigger_price
                    logger.info(f"[手动修改] A{order.level} 止盈单价格已更新: {old_price:.2f} -> {trigger_price:.2f}")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✏️ A{order.level} 止盈单已手动修改: {old_price:.2f} -> {trigger_price:.2f}")
                    self._save_state()
            
            if is_sl_order and order.sl_order_id == algo_id:
                if trigger_price != order.stop_loss_price:
                    old_price = order.stop_loss_price
                    order.stop_loss_price = trigger_price
                    logger.info(f"[手动修改] A{order.level} 止损单价格已更新: {old_price:.2f} -> {trigger_price:.2f}")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✏️ A{order.level} 止损单已手动修改: {old_price:.2f} -> {trigger_price:.2f}")
                    self._save_state()
            
            for o in self.chain_state.orders:
                if o.state != "filled":
                    continue
                
                if is_tp_order and not o.tp_order_id:
                    expected_tp_price = o.take_profit_price
                    price_diff = abs(trigger_price - expected_tp_price)
                    if price_diff < expected_tp_price * Decimal("0.001"):
                        o.tp_order_id = algo_id
                        o.take_profit_price = trigger_price
                        logger.info(f"[手动修改] A{o.level} 止盈单已更新: algoId={algo_id}, 价格={trigger_price}")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✏️ A{o.level} 止盈单已手动修改: 价格={trigger_price:.2f}")
                        self._save_state()
                        break
                
                if is_sl_order and not o.sl_order_id:
                    expected_sl_price = o.stop_loss_price
                    price_diff = abs(trigger_price - expected_sl_price)
                    if price_diff < expected_sl_price * Decimal("0.001"):
                        o.sl_order_id = algo_id
                        o.stop_loss_price = trigger_price
                        logger.info(f"[手动修改] A{o.level} 止损单已更新: algoId={algo_id}, 价格={trigger_price}")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✏️ A{o.level} 止损单已手动修改: 价格={trigger_price:.2f}")
                        self._save_state()
                        break
    
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
        
        connector = None
        if self.proxy:
            connector = aiohttp.TCPConnector(ssl=False)
        
        async with aiohttp.ClientSession(connector=connector) as session:
            self.session = session
            
            print(f"\n📊 获取账户信息...")
            balance = await self.get_account_balance()
            print(f"   账户余额: {balance:.2f} USDT")
            
            current_price = await self.get_current_price(symbol)
            print(f"   当前价格: {current_price}")
            
            need_new_order = await self._restore_orders(current_price)
            
            if not need_new_order:
                await self._check_and_supplement_orders()
                
                filled_orders = [o for o in self.chain_state.orders if o.state == "filled"]
                pending_orders = [o for o in self.chain_state.orders if o.state == "pending"]
                
                if filled_orders:
                    max_filled_level = max(o.level for o in filled_orders)
                    max_level = self.config.get("max_entries", 4)
                    next_level = max_filled_level + 1
                    
                    has_next_pending = any(o.level == next_level for o in pending_orders)
                    
                    if next_level <= max_level and not has_next_pending:
                        new_order = self._create_order(next_level, current_price)
                        self.chain_state.orders.append(new_order)
                        print(f"\n{'='*60}")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📥 入场单补下: A{next_level}")
                        print(f"{'='*60}")
                        await self._place_entry_order_supplement(new_order)
            
            print(f"\n🔗 连接用户数据流...")
            self.listen_key = await self.get_listen_key()
            print(f"   listenKey: {self.listen_key[:20]}...")
            
            if need_new_order:
                first_order = self._create_order(1, current_price)
                self.chain_state.orders.append(first_order)
                await self._place_entry_order(first_order)
            else:
                print(f"\n📋 已有订单，等待WebSocket事件...")
            
            max_reconnect_attempts = 10
            reconnect_delay = 5
            reconnect_attempts = 0
            
            while True:
                ws_uri = f"{self.ws_url}/{self.listen_key}"
                print(f"\n📡 连接 WebSocket...")
                print(f"   代理: {self.proxy or '无'}")
                
                try:
                    ws_kwargs = {}
                    if self.proxy:
                        ws_kwargs["proxy"] = self.proxy
                    
                    async with session.ws_connect(ws_uri, **ws_kwargs) as websocket:
                        self.ws_connected = True
                        reconnect_attempts = 0
                        print("✅ 连接成功！开始监听订单状态...\n")
                        
                        async def keepalive():
                            while self.ws_connected:
                                await asyncio.sleep(1800)
                                try:
                                    await self.keepalive_listen_key()
                                except Exception as e:
                                    logger.error(f"[keepalive] 续期失败: {e}")
                        
                        keepalive_task = asyncio.create_task(keepalive())
                        
                        try:
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
                                elif message.type == aiohttp.WSMsgType.CLOSED:
                                    logger.warning(f"[WebSocket] 连接关闭")
                                    break
                        except asyncio.CancelledError:
                            logger.info("[WebSocket] 收到取消信号")
                            raise
                        finally:
                            keepalive_task.cancel()
                            self.ws_connected = False
                
                except KeyboardInterrupt:
                    if self.exit_notified:
                        break
                    self.exit_notified = True
                    
                    print("\n\n⏹️ 停止交易")
                    cancelled_orders = await self._cancel_all_orders()
                    self._save_state()
                    
                    remaining_orders = [o for o in self.chain_state.orders if o.state in ["filled", "pending"]]
                    
                    current_price = None
                    pnl_info = {}
                    try:
                        symbol = self.config.get("symbol", "BTCUSDT")
                        current_price = await self._get_current_price(symbol)
                        positions = await self.get_positions(symbol)
                        if positions:
                            pos = positions[0]
                            position_qty = Decimal(pos.get("positionAmt", "0"))
                            entry_price = Decimal(pos.get("entryPrice", "0"))
                            unrealized_pnl = Decimal(pos.get("unRealizedProfit", "0"))
                            
                            roi = None
                            if entry_price > 0 and position_qty != 0:
                                roi = float(unrealized_pnl / (entry_price * abs(position_qty)) * 100)
                            
                            pnl_info = {
                                "position_qty": str(position_qty),
                                "entry_price": f"{entry_price:.2f}",
                                "unrealized_pnl": f"{unrealized_pnl:.2f}",
                                "roi": f"{roi:.2f}" if roi is not None else None,
                                "realized_pnl": "N/A"
                            }
                    except Exception as e:
                        logger.warning(f"[获取盈亏信息] 失败: {e}")
                    
                    notify_exit("用户手动停止", self.config, cancelled_orders, remaining_orders, pnl_info, current_price)
                    break
                except asyncio.CancelledError:
                    if self.exit_notified:
                        raise
                    self.exit_notified = True
                    
                    print("\n\n⏹️ 程序被取消")
                    try:
                        cancelled_orders = await self._cancel_all_orders()
                        self._save_state()
                        
                        remaining_orders = [o for o in self.chain_state.orders if o.state in ["filled", "pending"]]
                        
                        current_price = None
                        pnl_info = {}
                        try:
                            symbol = self.config.get("symbol", "BTCUSDT")
                            current_price = await self._get_current_price(symbol)
                            positions = await self.get_positions(symbol)
                            if positions:
                                pos = positions[0]
                                position_qty = Decimal(pos.get("positionAmt", "0"))
                                entry_price = Decimal(pos.get("entryPrice", "0"))
                                unrealized_pnl = Decimal(pos.get("unRealizedProfit", "0"))
                                
                                roi = None
                                if entry_price > 0 and position_qty != 0:
                                    roi = float(unrealized_pnl / (entry_price * abs(position_qty)) * 100)
                                
                                pnl_info = {
                                    "position_qty": str(position_qty),
                                    "entry_price": f"{entry_price:.2f}",
                                    "unrealized_pnl": f"{unrealized_pnl:.2f}",
                                    "roi": f"{roi:.2f}" if roi is not None else None,
                                    "realized_pnl": "N/A"
                                }
                        except Exception as e:
                            logger.warning(f"[获取盈亏信息] 失败: {e}")
                        
                        notify_exit("用户手动停止", self.config, cancelled_orders, remaining_orders, pnl_info, current_price)
                    except Exception as e:
                        logger.error(f"[退出处理] 失败: {e}")
                    raise
                except Exception as e:
                    self.ws_connected = False
                    reconnect_attempts += 1
                    logger.error(f"[WebSocket] 连接错误: {e}", exc_info=True)
                    
                    if reconnect_attempts >= max_reconnect_attempts:
                        print(f"\n❌ 重连失败次数超过上限 ({max_reconnect_attempts})，程序退出")
                        
                        remaining_orders = [o for o in self.chain_state.orders if o.state in ["filled", "pending"]]
                        
                        current_price = None
                        pnl_info = {}
                        try:
                            symbol = self.config.get("symbol", "BTCUSDT")
                            current_price = await self._get_current_price(symbol)
                            positions = await self.get_positions(symbol)
                            if positions:
                                pos = positions[0]
                                position_qty = Decimal(pos.get("positionAmt", "0"))
                                entry_price = Decimal(pos.get("entryPrice", "0"))
                                unrealized_pnl = Decimal(pos.get("unRealizedProfit", "0"))
                                
                                roi = None
                                if entry_price > 0 and position_qty != 0:
                                    roi = float(unrealized_pnl / (entry_price * abs(position_qty)) * 100)
                                
                                pnl_info = {
                                    "position_qty": str(position_qty),
                                    "entry_price": f"{entry_price:.2f}",
                                    "unrealized_pnl": f"{unrealized_pnl:.2f}",
                                    "roi": f"{roi:.2f}" if roi is not None else None,
                                    "realized_pnl": "N/A"
                                }
                        except Exception as ex:
                            logger.warning(f"[获取盈亏信息] 失败: {ex}")
                        
                        notify_exit(f"WebSocket 重连失败 ({max_reconnect_attempts} 次)", self.config, [], remaining_orders, pnl_info, current_price)
                        break
                    
                    print(f"\n⚠️ WebSocket 连接断开，{reconnect_delay}秒后重连... (尝试 {reconnect_attempts}/{max_reconnect_attempts})")
                    await asyncio.sleep(reconnect_delay)
                    
                    try:
                        self.listen_key = await self.get_listen_key()
                        logger.info(f"[WebSocket] 重新获取 listenKey: {self.listen_key[:20]}...")
                    except Exception as e:
                        logger.error(f"[WebSocket] 获取 listenKey 失败: {e}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Autofish V1 实盘交易")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对 (默认: BTCUSDT)")
    parser.add_argument("--testnet", action="store_true", default=True, help="使用测试网 (默认: True)")
    parser.add_argument("--no-testnet", dest="testnet", action="store_false", help="使用主网")
    args = parser.parse_args()
    
    config = get_default_config()
    config["symbol"] = args.symbol
    config.update({
        "stop_loss": Decimal("0.08"),
        "total_amount_quote": Decimal("1200"),
    })
    
    trader = BinanceLiveTrader(config, testnet=args.testnet)
    
    def signal_handler(signum, frame):
        """信号处理函数"""
        signal_name = signal.Signals(signum).name
        print(f"\n\n⏹️ 收到信号 {signal_name}，程序即将退出")
        logger.info(f"[信号处理] 收到信号 {signal_name}")
        
        if trader.exit_notified:
            raise KeyboardInterrupt(f"收到信号 {signal_name}")
        
        trader.exit_notified = True
        
        remaining_orders = [o for o in trader.chain_state.orders if o.state in ["filled", "pending"]]
        
        pnl_info = None
        try:
            symbol = config.get("symbol", "BTCUSDT")
            logger.info(f"[信号处理] 开始同步获取持仓信息...")
            positions = trader.sync_get_positions(symbol)
            logger.info(f"[信号处理] 获取到 {len(positions) if positions else 0} 个持仓")
            if positions and isinstance(positions, list):
                pos = positions[0]
                position_qty = Decimal(pos.get("positionAmt", "0"))
                entry_price = Decimal(pos.get("entryPrice", "0"))
                unrealized_pnl = Decimal(pos.get("unRealizedProfit", "0"))
                
                roi = None
                if entry_price > 0 and position_qty != 0:
                    roi = float(unrealized_pnl / (entry_price * abs(position_qty)) * 100)
                
                pnl_info = {
                    "position_qty": str(position_qty),
                    "entry_price": f"{entry_price:.2f}",
                    "unrealized_pnl": f"{unrealized_pnl:.2f}",
                    "roi": f"{roi:.2f}" if roi is not None else None,
                    "realized_pnl": "N/A"
                }
                logger.info(f"[信号处理] 盈亏信息: {pnl_info}")
        except Exception as e:
            import traceback
            logger.warning(f"[信号处理] 获取盈亏信息失败: {e}\n{traceback.format_exc()}")
            pnl_info = None
        
        try:
            if signum == signal.SIGINT:
                exit_reason = "用户手动停止"
            else:
                exit_reason = f"收到信号 {signal_name}"
            
            notify_exit(exit_reason, config, [], remaining_orders, pnl_info, None)
        except Exception as e:
            logger.error(f"[信号处理] 发送退出通知失败: {e}")
        
        raise KeyboardInterrupt(f"收到信号 {signal_name}")
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        await trader.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n\n⏹️ 程序被中断")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⏹️ 程序已退出")
