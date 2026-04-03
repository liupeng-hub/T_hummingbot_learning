"""
Binance 交易所模块

整合 BinanceClient、BinanceLiveTrader、AlgoHandler 到单一文件。

提供 Binance Futures 的完整交易功能：
- REST API 请求
- WebSocket 连接
- Algo 条件单管理
- 链式挂单交易策略
- 自定义异常类
- 日志配置
- 重试机制
- 状态管理
- 通知服务
- 常量定义
"""

import os
import json
import aiohttp
import asyncio
import functools
import hashlib
import hmac
import logging
import signal
import sys
import time
import requests
from aiolimiter import AsyncLimiter
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from enum import Enum
from pathlib import Path
from textwrap import dedent
from typing import Optional, Dict, Any, List, Callable, Tuple, Type
from urllib.parse import urlencode

from market_status_detector import MarketStatusDetector, MarketStatus, StatusResult
from database.live_trading_db import LiveTradingDB

# 在模块导入时加载环境变量（确保通知服务能获取 WECHAT_WEBHOOK）
from dotenv import load_dotenv
load_dotenv()


# ============================================================================
# 常量定义
# ============================================================================

# 文件名常量
LOG_FILE = "binance_live.log"
LOG_DIR = "logs"
MESSAGE_COUNTER_DB = "database/test_results.db"


class OrderState(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class CloseReason(str, Enum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    UNKNOWN = "unknown"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class AlgoStatus(str, Enum):
    TRIGGERING = "TRIGGERING"
    TRIGGERED = "TRIGGERED"
    FINISHED = "FINISHED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


# ============================================================================
# 日志配置
# ============================================================================

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(
    name: str = "autofish",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    log_dir: str = "logs",
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    
    if logger.handlers:
        return logger
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    if log_file:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        file_handler = FlushFileHandler(log_path / log_file, mode='a', encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(console_formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = "autofish") -> logging.Logger:
    return logging.getLogger(name)


class FlushFileHandler(logging.FileHandler):
    """每次写入后自动刷新的 FileHandler"""
    def emit(self, record):
        super().emit(record)
        self.flush()


class LoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = self.extra or {}
        prefix = " | ".join(f"{k}={v}" for k, v in extra.items())
        if prefix:
            return f"[{prefix}] {msg}", kwargs
        return msg, kwargs


def get_logger() -> logging.Logger:
    return logging.getLogger("autofish")


# 在模块导入时配置日志（确保 Web 服务导入时日志也能正确输出）
logger = setup_logger(name="autofish", log_file=LOG_FILE, log_dir=LOG_DIR)


# ============================================================================
# 自定义异常类
# ============================================================================

class BinanceAPIError(Exception):
    def __init__(self, code: int, message: str, response: dict = None):
        self.code = code
        self.message = message
        self.response = response or {}
        super().__init__(f"Binance API Error [{code}]: {message}")


class NetworkError(Exception):
    def __init__(self, message: str, original_error: Exception = None):
        self.message = message
        self.original_error = original_error
        super().__init__(f"Network Error: {message}")


class OrderError(Exception):
    def __init__(self, level: int, order_id: int, message: str):
        self.level = level
        self.order_id = order_id
        self.message = message
        super().__init__(f"Order Error [A{level}, orderId={order_id}]: {message}")


class StateError(Exception):
    def __init__(self, message: str, file_path: str = None):
        self.message = message
        self.file_path = file_path
        if file_path:
            super().__init__(f"State Error [{file_path}]: {message}")
        else:
            super().__init__(f"State Error: {message}")


# ============================================================================
# 重试机制
# ============================================================================

@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    exceptions: Tuple[Type[Exception], ...] = (Exception,)


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    delay = config.base_delay * (config.exponential_base ** (attempt - 1))
    return min(delay, config.max_delay)


def retry_on_exception(
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[Exception, int], Any]] = None,
):
    if config is None:
        config = RetryConfig()
    
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(1, config.max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except config.exceptions as e:
                    last_exception = e
                    
                    if attempt < config.max_attempts:
                        delay = calculate_delay(attempt, config)
                        logger.warning(
                            f"[重试] {func.__name__} 第{attempt}次失败: {e}, "
                            f"{delay:.1f}秒后重试"
                        )
                        
                        if on_retry:
                            on_retry(e, attempt)
                        
                        await asyncio.sleep(delay)
            
            logger.error(
                f"[重试失败] {func.__name__} 已重试{config.max_attempts}次, "
                f"最后错误: {last_exception}"
            )
            raise last_exception
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            import time as time_module
            
            last_exception = None
            
            for attempt in range(1, config.max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except config.exceptions as e:
                    last_exception = e
                    
                    if attempt < config.max_attempts:
                        delay = calculate_delay(attempt, config)
                        logger.warning(
                            f"[重试] {func.__name__} 第{attempt}次失败: {e}, "
                            f"{delay:.1f}秒后重试"
                        )
                        
                        if on_retry:
                            on_retry(e, attempt)
                        
                        time_module.sleep(delay)
            
            logger.error(
                f"[重试失败] {func.__name__} 已重试{config.max_attempts}次, "
                f"最后错误: {last_exception}"
            )
            raise last_exception
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


NETWORK_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=10.0,
    exceptions=(ConnectionError, TimeoutError, OSError),
)

API_RETRY = RetryConfig(
    max_attempts=5,
    base_delay=2.0,
    max_delay=60.0,
    exceptions=(Exception,),
)


# ============================================================================
# 通知服务
# ============================================================================

class NotificationTemplate:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.max_entries = config.get('max_entries', 4)
        self.exit_profit_pct = float(config.get('exit_profit', Decimal('0.01'))) * 100
        self.stop_loss_pct = float(config.get('stop_loss', Decimal('0.08'))) * 100
    
    def format_level(self, level: int) -> str:
        return f"A{level} (第{level}层/共{self.max_entries}层)"
    
    def format_order_basic(self, order) -> str:
        return dedent(f"""\
            > **层级**: {self.format_level(order.level)}
            > **入场价**: {order.entry_price:.2f} USDT
            > **数量**: {order.quantity:.6f} BTC
            > **金额**: {order.stake_amount:.2f} USDT""").strip()
    
    def format_order_prices(self, order) -> str:
        return dedent(f"""\
            > **止盈价**: {order.take_profit_price:.2f} USDT (+{self.exit_profit_pct:.1f}%)
            > **止损价**: {order.stop_loss_price:.2f} USDT (-{self.stop_loss_pct:.1f}%)""").strip()
    
    def format_order_full(self, order, include_order_id: bool = False) -> str:
        lines = [
            self.format_order_basic(order),
            self.format_order_prices(order),
        ]
        
        if include_order_id and order.order_id:
            lines.append(f"> **订单ID**: {order.order_id}")
        
        lines.append(f"> **时间**: {self.format_timestamp()}")
        
        return "\n".join(lines)
    
    def format_pnl_info(self, pnl_info: Dict[str, Any]) -> str:
        lines = []
        
        position_qty = pnl_info.get('position_qty', '0')
        if position_qty and position_qty != '0':
            lines.append(f"> **持仓数量**: {position_qty}")
            lines.append(f"> **持仓均价**: {pnl_info.get('entry_price', 'N/A')}")
            
            unrealized_pnl = pnl_info.get('unrealized_pnl')
            roi = pnl_info.get('roi')
            
            if unrealized_pnl and roi:
                pnl_prefix = "+" if float(unrealized_pnl) > 0 else ""
                roi_prefix = "+" if float(roi) > 0 else ""
                lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl} USDT ({roi_prefix}{roi}%)")
            elif unrealized_pnl:
                pnl_prefix = "+" if float(unrealized_pnl) > 0 else ""
                lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl} USDT")
            else:
                lines.append(f"> **未实现盈亏**: N/A")
            
            lines.append(f"> **已实现盈亏**: {pnl_info.get('realized_pnl', 'N/A')} USDT")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_timestamp() -> str:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def send_wechat_notification(title: str, content: str, session_id: int, db, msg_type: str = None):
    """发送微信通知并保存到数据库

    Args:
        title: 通知标题
        content: 通知内容
        session_id: 会话 ID（用于按 session 计数消息ID）
        db: 数据库实例
        msg_type: 消息类型（可选，如 entry, exit, warning）
    """
    logger.info(f"[通知] 开始发送通知: title={title}, session_id={session_id}, msg_type={msg_type}")

    # 对于错误类通知，记录详细内容方便排查
    if msg_type in ('error', 'exit') or '错误' in title:
        logger.info(f"[通知] 详细内容:\n{content}")

    # 获取消息ID（按 session）
    msg_num = db.get_next_message_number(session_id)
    logger.info(f"[通知] 消息ID: msg_num={msg_num}")

    # 构造完整的请求数据
    content_with_num = f"> **实例ID**: {session_id}\n> **消息ID**: {msg_num}\n\n{content}"
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": f"## {title}\n\n{content_with_num}"
        }
    }
    payload_str = json.dumps(payload, ensure_ascii=False)

    # 发送到微信（可选）
    wechat_webhook = os.getenv("WECHAT_WEBHOOK")
    logger.info(f"[通知] WECHAT_WEBHOOK 配置: {'已配置' if wechat_webhook else '未配置'}")

    if not wechat_webhook:
        # 未配置 webhook，保存为 skipped 状态
        notification_id = db.save_notification(session_id, msg_num, msg_type or "general", title, content, 'skipped', payload_str)
        logger.info(f"[通知] 未配置 webhook，已保存为 skipped: notification_id={notification_id}")
        return

    # 先保存为 pending 状态
    notification_id = db.save_notification(session_id, msg_num, msg_type or "general", title, content, 'pending', payload_str)
    logger.info(f"[通知] 已保存为 pending: notification_id={notification_id}")

    try:
        logger.info(f"[通知] 发送请求到微信 webhook...")
        # 微信 webhook 不需要代理，直接连接
        response = requests.post(wechat_webhook, json=payload, timeout=30, proxies={'http': None, 'https': None})
        logger.info(f"[通知] 微信响应: status_code={response.status_code}")
        if response.status_code == 200:
            result = response.json()
            logger.info(f"[通知] 微信响应内容: {result}")
            if result.get("errcode") == 0:
                db.update_notification_status(notification_id, 'sent')
                logger.info(f"[通知发送] 微信机器人发送成功: {title}, 消息ID={msg_num}")
            else:
                error_msg = result.get('errmsg', str(result))
                db.update_notification_status(notification_id, 'failed', error_msg)
                logger.warning(f"[通知发送] 微信机器人发送失败: {error_msg}")
        else:
            error_msg = f"HTTP {response.status_code}"
            db.update_notification_status(notification_id, 'failed', error_msg)
            logger.warning(f"[通知发送] 微信机器人请求失败: {error_msg}")
    except Exception as e:
        db.update_notification_status(notification_id, 'failed', str(e))
        logger.error(f"[通知发送] 微信机器人发送异常: {e}", exc_info=True)


def notify_entry_order(order, config: dict, session_id: int, db):
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

    send_wechat_notification(f"🟢 入场单下单 A{order.level}", content, session_id, db, "entry")


def notify_entry_order_supplement(order, config: dict, session_id: int, db):
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

    send_wechat_notification(f"📥 入场单补下 A{order.level}", content, session_id, db, "entry")


def notify_entry_filled(order, filled_price: Decimal, commission: Decimal, config: dict, session_id: int, db):
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
    send_wechat_notification(f"✅ 入场成交 A{order.level}", content, session_id, db, "filled")


def notify_take_profit(order, profit: Decimal, config: dict, session_id: int, db):
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""
            > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
            > **止盈价**: {order.take_profit_price:.2f} USDT
            > **盈亏**: +{profit:.2f} USDT
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification(f"🎯 止盈触发 A{order.level}", content, session_id, db, "take_profit")


def notify_stop_loss(order, profit: Decimal, config: dict, session_id: int, db):
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""
            > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
            > **止损价**: {order.stop_loss_price:.2f} USDT
            > **盈亏**: {profit:.2f} USDT
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification(f"🛑 止损触发 A{order.level}", content, session_id, db, "stop_loss")


def notify_withdrawal(withdrawal_info: dict, config: dict, session_id: int, db):
    """通知提现触发"""
    content = dedent(f"""
            > **提现金额**: {withdrawal_info.get('withdrawal_amount', 0):.2f} USDT
            > **利润池余额**: {withdrawal_info.get('profit_pool', 0):.2f} USDT
            > **交易资金**: {withdrawal_info.get('trading_capital', 0):.2f} USDT
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification("💰 提现触发", content, session_id, db, "withdrawal")


def notify_liquidation(liquidation_info: dict, config: dict, session_id: int, db):
    """通知爆仓恢复"""
    content = dedent(f"""
            > **交易资金**: {liquidation_info.get('trading_capital', 0):.2f} USDT
            > **利润池余额**: {liquidation_info.get('profit_pool', 0):.2f} USDT
            > **爆仓次数**: {liquidation_info.get('liquidation_count', 0)}
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification("⚠️ 爆仓恢复", content, session_id, db, "liquidation")


def notify_orders_recovered(orders: list, config: dict, current_price: Decimal, pnl_info: dict, session_id: int, db):
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
            content_lines.append("### 💰 当前盈亏信息")
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
    send_wechat_notification("🔄 订单同步", content, session_id, db, "sync")


def notify_exit(reason: str, config: dict, session_id: int, db, cancelled_orders: list = None, remaining_orders: list = None, pnl_info: dict = None, current_price: Decimal = None):
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
    send_wechat_notification("⏹️ Autofish V2 退出", content, session_id, db, "exit")


def notify_startup(config: dict, current_price: Decimal, session_id: int, db):
    symbol = config.get('symbol', 'BTCUSDT')
    
    weights_str = ""
    weights = config.get('weights', [])
    if weights:
        weights_str = "> **网格权重**: " + ", ".join([f"A{i+1}: {w*100:.1f}%" for i, w in enumerate(weights)])
    
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
    send_wechat_notification("🚀 Autofish V2 启动", content, session_id, db, "startup")


def notify_critical_error(error_msg: str, config: dict, session_id: int, db):
    """发送严重错误通知"""
    symbol = config.get('symbol', 'BTCUSDT')
    content = dedent(f"""
        > **错误类型**: 严重错误
        > **交易标的**: {symbol}
        > **错误信息**: {error_msg}
        > **状态**: 程序强制退出
        > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """).strip()
    send_wechat_notification("🚨 Autofish V2 严重错误", content, session_id, db, "error")


def notify_warning(warning_msg: str, config: dict, session_id: int, db):
    """发送警告通知"""
    symbol = config.get('symbol', 'BTCUSDT')
    content = dedent(f"""
        > **通知类型**: 资金提醒
        > **交易标的**: {symbol}
        > **提醒内容**: {warning_msg}
        > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """).strip()
    send_wechat_notification("⚠️ Autofish 资金提醒", content, session_id, db, "warning")


def notify_market_status(old_status: str, new_status: str, reason: str, config: dict, session_id: int, db):
    """发送行情状态变化通知"""
    symbol = config.get('symbol', 'BTCUSDT')
    content = dedent(f"""
        > **通知类型**: 行情状态变化
        > **交易标的**: {symbol}
        > **旧状态**: {old_status}
        > **新状态**: {new_status}
        > **原因**: {reason}
        > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """).strip()
    send_wechat_notification("🔄 行情状态变化", content, session_id, db, "market")


def notify_first_entry_timeout_refresh(old_order, new_order: dict, current_price: Decimal, timeout_minutes: int, config: dict, session_id: int, db):
    """发送第一笔入场订单超时重挂通知"""
    symbol = config.get('symbol', 'BTCUSDT')
    max_entries = config.get('max_entries', 4)
    
    old_entry = old_order.get('entry_price', 0) if isinstance(old_order, dict) else getattr(old_order, 'entry_price', 0)
    old_order_id = old_order.get('order_id', 'N/A') if isinstance(old_order, dict) else getattr(old_order, 'order_id', 'N/A')
    old_created = old_order.get('created_at', 'N/A') if isinstance(old_order, dict) else getattr(old_order, 'created_at', 'N/A')
    
    new_entry = new_order.get('entry_price', 0) if isinstance(new_order, dict) else getattr(new_order, 'entry_price', 0)
    new_order_id = new_order.get('order_id', 'N/A') if isinstance(new_order, dict) else getattr(new_order, 'order_id', 'N/A')
    new_quantity = new_order.get('quantity', 0) if isinstance(new_order, dict) else getattr(new_order, 'quantity', 0)
    new_stake = new_order.get('stake_amount', 0) if isinstance(new_order, dict) else getattr(new_order, 'stake_amount', 0)
    new_tp = new_order.get('take_profit_price', 0) if isinstance(new_order, dict) else getattr(new_order, 'take_profit_price', 0)
    new_sl = new_order.get('stop_loss_price', 0) if isinstance(new_order, dict) else getattr(new_order, 'stop_loss_price', 0)
    new_level = new_order.get('level', 1) if isinstance(new_order, dict) else getattr(new_order, 'level', 1)
    
    price_diff = abs(float(new_entry) - float(old_entry))
    price_diff_pct = price_diff / float(old_entry) * 100 if float(old_entry) > 0 else 0
    
    content = dedent(f"""\
        > **层级**: A{new_level} (第{new_level}层/共{max_entries}层)
        > **触发原因**: A1 挂单超过 {timeout_minutes} 分钟未成交
        > **当前价格**: {float(current_price):.2f} USDT
        > 
        > **原订单**:
        >   入场价: {float(old_entry):.2f} USDT
        >   订单ID: {old_order_id}
        >   创建时间: {old_created}
        > 
        > **新订单**:
        >   入场价: {float(new_entry):.2f} USDT
        >   数量: {float(new_quantity):.6f} BTC
        >   金额: {float(new_stake):.2f} USDT
        >   止盈价: {float(new_tp):.2f} USDT (+{float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%)
        >   止损价: {float(new_sl):.2f} USDT (-{float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%)
        >   订单ID: {new_order_id}
        > 
        > **价格调整**: {price_diff:.2f} ({price_diff_pct:.2f}%)
        > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}""").strip()
    send_wechat_notification(f"⏰ A1 超时重挂", content, session_id, db, "timeout")


# ============================================================================
# Binance 客户端
# ============================================================================

class BinanceClient:
    """Binance Futures API 客户端
    
    提供 Binance Futures 的 REST API 和 WebSocket 接口封装。
    
    主要功能：
    - REST API 请求（签名、限流、重试）
    - WebSocket 连接（用户数据流）
    - Algo 条件单管理（止盈止损单）
    - 订单管理（下单、撤单、查询）
    - 仓位和账户查询
    
    Attributes:
        api_key: Binance API Key
        api_secret: Binance API Secret
        testnet: 是否使用测试网
        base_url: REST API 基础 URL
        ws_url: WebSocket URL
        session: aiohttp 会话
        rate_limiter: 请求限流器（1000 请求/60 秒）
    
    示例:
        >>> client = BinanceClient(api_key, api_secret, testnet=True)
        >>> await client.place_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000)
    """
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True, proxy: str = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.proxy = proxy
        
        if testnet:
            self.base_url = "https://testnet.binancefuture.com"
            self.ws_url = "wss://stream.binancefuture.com/ws"
        else:
            self.base_url = "https://fapi.binance.com"
            self.ws_url = "wss://fstream.binance.com/ws"
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter = AsyncLimiter(1000, 60)
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.ws_connected = False
        self.listen_key: Optional[str] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            connector = None
            if self.proxy:
                connector = aiohttp.TCPConnector(ssl=False)
            self.session = aiohttp.ClientSession(connector=connector)
        return self.session
    
    def _sign(self, params: Dict[str, Any]) -> str:
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _sync_request(self, method: str, endpoint: str, params: Dict[str, Any] = None, signed: bool = False) -> Dict[str, Any]:
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
                return {"error": f"Unsupported HTTP method: {method}"}
            
            data = response.json()
            
            if "code" in data and data["code"] != 200:
                raise BinanceAPIError(
                    code=data.get("code", -1),
                    message=data.get("msg", "Unknown error"),
                    response=data
                )
            
            return data
        except Exception as e:
            return {"error": str(e)}
    
    async def _request(self, method: str, endpoint: str, params: Dict[str, Any] = None, signed: bool = False) -> Dict[str, Any]:
        async with self.rate_limiter:
            session = await self._get_session()
            url = f"{self.base_url}{endpoint}"
            headers = {"X-MBX-APIKEY": self.api_key}
            
            if params is None:
                params = {}
            
            if signed:
                params["timestamp"] = str(int(time.time() * 1000))
                params["signature"] = self._sign(params)
            
            kwargs = {"params": params, "headers": headers}
            if self.proxy:
                kwargs["proxy"] = self.proxy
            
            try:
                if method == "GET":
                    async with session.get(url, **kwargs, timeout=30) as response:
                        data = await response.json()
                elif method == "POST":
                    async with session.post(url, **kwargs, timeout=30) as response:
                        data = await response.json()
                elif method == "PUT":
                    async with session.put(url, **kwargs, timeout=30) as response:
                        data = await response.json()
                elif method == "DELETE":
                    async with session.delete(url, **kwargs, timeout=30) as response:
                        data = await response.json()
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                if "code" in data and data["code"] != 200:
                    raise BinanceAPIError(
                        code=data.get("code", -1),
                        message=data.get("msg", "Unknown error"),
                        response=data
                    )
                
                return data
            
            except aiohttp.ClientError as e:
                raise NetworkError(f"Request failed: {e}", e)
            except asyncio.TimeoutError:
                raise NetworkError("Request timeout")
    
    async def place_order(self, symbol: str, side: str, order_type: str,
                         quantity: Decimal, price: Decimal = None,
                         reduce_only: bool = False) -> Dict[str, Any]:
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": str(quantity),
        }
        
        if order_type == "LIMIT":
            params["price"] = str(price)
            params["timeInForce"] = "GTC"
        
        if reduce_only:
            params["reduceOnly"] = "true"
        
        return await self._request("POST", "/fapi/v1/order", params, signed=True)
    
    async def place_algo_order(self, symbol: str, side: str, order_type: str,
                               quantity: Decimal, trigger_price: Decimal,
                               reduce_only: bool = True,
                               position_side: str = None) -> Dict[str, Any]:
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "algoType": "CONDITIONAL",
            "quantity": str(quantity),
            "triggerPrice": str(trigger_price),
        }

        # 双向持仓模式下需要指定 positionSide
        if position_side:
            params["positionSide"] = position_side

        return await self._request("POST", "/fapi/v1/algoOrder", params, signed=True)
    
    async def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        params = {
            "symbol": symbol,
            "orderId": order_id,
        }
        return await self._request("DELETE", "/fapi/v1/order", params, signed=True)
    
    async def cancel_algo_order(self, symbol: str, algo_id: int) -> Dict[str, Any]:
        params = {
            "symbol": symbol,
            "algoId": algo_id,
        }
        return await self._request("DELETE", "/fapi/v1/algoOrder", params, signed=True)
    
    async def get_positions(self, symbol: str = None) -> List[Dict[str, Any]]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        
        result = await self._request("GET", "/fapi/v2/positionRisk", params, signed=True)
        return result if isinstance(result, list) else [result]
    
    async def get_open_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        
        return await self._request("GET", "/fapi/v1/openOrders", params, signed=True)
    
    async def get_open_algo_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        
        result = await self._request("GET", "/fapi/v1/openAlgoOrders", params, signed=True)
        if isinstance(result, list):
            return result
        return result.get("orders", [])
    
    async def get_current_price(self, symbol: str) -> Decimal:
        params = {"symbol": symbol}
        result = await self._request("GET", "/fapi/v1/ticker/price", params)
        return Decimal(result["price"])
    
    async def get_exchange_info(self, symbol: str) -> Dict[str, Any]:
        params = {"symbol": symbol}
        result = await self._request("GET", "/fapi/v1/exchangeInfo", params)
        return result
    
    def _get_symbol_precision(self, exchange_info: Dict[str, Any], symbol: str) -> Dict[str, int]:
        for s in exchange_info.get("symbols", []):
            if s.get("symbol") == symbol:
                price_precision = 0
                qty_precision = 0
                for f in s.get("filters", []):
                    if f.get("filterType") == "PRICE_FILTER":
                        tick_size = Decimal(f.get("tickSize", "0.01"))
                        price_precision = abs(tick_size.as_tuple().exponent)
                    elif f.get("filterType") == "LOT_SIZE":
                        step_size = Decimal(f.get("stepSize", "0.001"))
                        qty_precision = abs(step_size.as_tuple().exponent)
                return {"price_precision": price_precision, "qty_precision": qty_precision}
        return {"price_precision": 2, "qty_precision": 3}
    
    async def create_listen_key(self) -> str:
        result = await self._request("POST", "/fapi/v1/listenKey")
        self.listen_key = result["listenKey"]
        return self.listen_key
    
    async def keepalive_listen_key(self) -> None:
        await self._request("PUT", "/fapi/v1/listenKey")
    
    async def close_listen_key(self) -> None:
        await self._request("DELETE", "/fapi/v1/listenKey")
        self.listen_key = None
    
    async def get_account_balance(self) -> Decimal:
        result = await self._request("GET", "/fapi/v2/balance", {}, signed=True)
        usdt_balance = Decimal("0")
        for asset in result:
            if asset.get("asset") == "USDT":
                usdt_balance = Decimal(asset.get("availableBalance", "0"))
                break
        return usdt_balance
    
    async def get_order_status(self, symbol: str, order_id: int) -> Dict[str, Any]:
        params = {
            "symbol": symbol,
            "orderId": order_id,
        }
        return await self._request("GET", "/fapi/v1/order", params, signed=True)
    
    async def get_all_orders(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        params = {
            "symbol": symbol,
            "limit": limit,
        }
        return await self._request("GET", "/fapi/v1/allOrders", params, signed=True)
    
    async def get_all_algo_orders(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        params = {
            "symbol": symbol,
            "limit": limit,
        }
        result = await self._request("GET", "/fapi/v1/allAlgoOrders", params, signed=True)
        if isinstance(result, list):
            return result
        return result.get("orders", [])
    
    async def get_my_trades(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        params = {
            "symbol": symbol,
            "limit": limit,
        }
        return await self._request("GET", "/fapi/v1/userTrades", params, signed=True)
    
    async def close(self) -> None:
        if self.ws:
            await self.ws.close()
            self.ws = None
        
        if self.session:
            await self.session.close()
            self.session = None
        
        self.ws_connected = False
        self.listen_key = None
    
    def sync_get_positions(self, symbol: str) -> List[Dict[str, Any]]:
        """同步获取持仓（用于信号处理器）"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        result = self._sync_request("GET", "/fapi/v2/positionRisk", params, signed=True)
        if isinstance(result, list):
            return result
        return [result]
    
    def sync_get_pnl_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """同步获取盈亏信息（用于信号处理器）"""
        try:
            positions = self.sync_get_positions(symbol)
            if positions and isinstance(positions, list):
                pos = positions[0]
                position_qty = Decimal(pos.get("positionAmt", "0"))
                entry_price = Decimal(pos.get("entryPrice", "0"))
                unrealized_pnl = Decimal(pos.get("unRealizedProfit", "0"))
                
                roi = None
                if entry_price > 0 and position_qty != 0:
                    roi = float(unrealized_pnl / (entry_price * abs(position_qty)) * 100)
                
                return {
                    "position_qty": str(position_qty),
                    "entry_price": f"{entry_price:.2f}",
                    "unrealized_pnl": f"{unrealized_pnl:.2f}",
                    "roi": f"{roi:.2f}" if roi is not None else None,
                    "realized_pnl": "N/A"
                }
        except Exception as e:
            logger.warning(f"[同步获取盈亏信息] 失败: {e}")
        
        return None


# ============================================================================
# Algo 条件单处理器
# ============================================================================

class AlgoHandler:
    """Algo 条件单处理器
    
    处理 Binance Algo 条件单（止盈止损单）的状态变化事件。
    
    主要功能：
    - 监听 Algo 条件单状态变化
    - 处理止盈单触发（TRIGGERED）
    - 处理止损单触发（TRIGGERED）
    - 更新订单状态和发送通知
    
    Flow:
        WebSocket 事件 -> handle_algo_update() -> 
        查找对应订单 -> 检查触发类型 -> 
        更新状态 -> 发送通知 -> 下下一级订单
    
    Attributes:
        trader: BinanceLiveTrader 实例
    """
    
    def __init__(self, trader):
        self.trader = trader
    
    async def handle_algo_update(self, algo_data: Dict[str, Any]) -> None:
        logger.info(f"[Algo事件] 收到消息: {algo_data}")
        
        # Binance ALGO_UPDATE 消息格式：
        # - aid: algoId（直接在顶层）
        # - X: 状态（直接在顶层）
        # - o: 订单类型（字符串，如 'TAKE_PROFIT_MARKET'）
        # 有时候 o 是嵌套字典，需要兼容处理
        
        algo_id = algo_data.get("aid") or algo_data.get("g") or algo_data.get("algoId")
        algo_status = algo_data.get("X") or algo_data.get("algoStatus")
        
        # 处理 o 字段：可能是字符串（订单类型）或字典（嵌套数据）
        inner_data = algo_data.get("o", {})
        if isinstance(inner_data, dict):
            # 嵌套格式
            algo_id = inner_data.get("aid") or algo_id
            algo_status = inner_data.get("X") or algo_status
            algo_type = inner_data.get("o") or algo_data.get("orderType")
        else:
            # 扁平格式，o 是订单类型字符串
            algo_type = inner_data or algo_data.get("orderType")
        
        if not algo_id:
            logger.warning(f"[Algo事件] 数据格式异常: {algo_data}")
            return
        
        order = self._find_order_by_algo_id(algo_id)
        if not order:
            logger.warning(f"[Algo匹配] 未找到订单: algoId={algo_id}")
            return
        
        logger.info(f"[Algo事件] algoId={algo_id}, status={algo_status}, orderType={algo_type}")
        
        if algo_status in ["TRIGGERING", "triggering"]:
            # 止盈/止损触发中
            if algo_type == "TAKE_PROFIT_MARKET":
                await self._handle_take_profit(order, algo_data)
            elif algo_type == "STOP_MARKET":
                await self._handle_stop_loss(order, algo_data)
        elif algo_status in ["FINISHED", "finished"]:
            await self._handle_finished(order, algo_data, algo_id, algo_type)
        elif algo_status in ["CANCELED", "canceled"]:
            await self._handle_canceled(order, algo_id, algo_type)
        elif algo_status in ["EXPIRED", "expired"]:
            await self._handle_expired(order, algo_id, algo_type)
        elif algo_status in ["REJECTED", "rejected"]:
            await self._handle_rejected(order, algo_data, algo_id, algo_type)
        elif algo_status in ["NEW", "new"]:
            await self._handle_new(order, algo_data, algo_id, algo_type)
    
    def _find_order_by_algo_id(self, algo_id: int) -> Optional[Any]:
        if not self.trader.chain_state:
            return None
        
        for order in self.trader.chain_state.orders:
            if order.tp_order_id == algo_id or order.sl_order_id == algo_id:
                return order
        
        return None
    
    async def _handle_take_profit(self, order: Any, algo_data: Dict[str, Any]) -> None:
        # === 事件处理锁：确保顺序处理 ===
        async with self.trader._event_lock:
            # 检查订单是否已处理
            if order.state == "closed":
                logger.info(f"[止盈] A{order.level} 已处理，跳过")
                return

            logger.info(f"[止盈触发] A{order.level}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 止盈触发 A{order.level}")

            order.state = "closed"
            order.close_reason = CloseReason.TAKE_PROFIT.value
            order.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            order.close_price = order.take_profit_price

            # === 计算盈亏（含杠杆）===
            leverage = self.trader.config.get('leverage', 10)
            profit = (order.take_profit_price - order.entry_price) * order.quantity * leverage
            order.profit = profit

            # 订单状态变更日志
            logger.info(f"[订单状态] A{order.level}: filled -> closed, 原因=take_profit, 盈亏={profit:.2f}")

            # === 更新资金池 ===
            result = self.trader.capital_pool.update_capital(profit)
            logger.info(f"[资金池更新] A{order.level} 止盈: 盈亏={profit:.2f}, "
                        f"trading_capital={self.trader.capital_pool.trading_capital:.2f}, "
                        f"profit_pool={getattr(self.trader.capital_pool, 'profit_pool', 0):.2f}")

            # === 更新统计 ===
            self.trader.results['total_trades'] += 1
            self.trader.results['win_trades'] += 1
            self.trader.results['total_profit'] += profit

            # === 检查提现 ===
            withdrawal = self.trader.capital_pool.check_withdrawal()
            if withdrawal:
                logger.info(f"[提现触发] 金额={withdrawal['withdrawal_amount']:.2f}")
                notify_withdrawal(withdrawal, self.trader.config, self.trader.session_id, self.trader.db)

            # === 检查爆仓 ===
            if self.trader.capital_pool.check_liquidation():
                logger.warning(f"[爆仓恢复] 已从利润池恢复")

            # === 保存交易记录到数据库 ===
            if self.trader.session_id:
                self.trader.db.save_trade(
                    session_id=self.trader.session_id,
                    order=order,
                    trade_type='take_profit',
                    leverage=leverage
                )
                # 保存资金历史
                self.trader.db.save_capital_history(
                    session_id=self.trader.session_id,
                    event_type='take_profit',
                    old_capital=float(self.trader.capital_pool.trading_capital - profit),
                    new_capital=float(self.trader.capital_pool.trading_capital),
                    profit_pool=float(getattr(self.trader.capital_pool, 'profit_pool', 0)),
                    amount=float(profit),
                    related_order_id=order.order_id
                )
                # 更新会话统计
                self.trader.db.update_session_stats(self.trader.session_id, {
                    'total_trades': self.trader.results['total_trades'],
                    'win_trades': self.trader.results['win_trades'],
                    'loss_trades': self.trader.results['loss_trades'],
                    'total_profit': float(self.trader.results['total_profit']),
                    'total_loss': float(self.trader.results['total_loss']),
                    'final_capital': float(self.trader.capital_pool.trading_capital)
                })

            # === 记录统计指标 ===
            # 计算持仓时长
            if order.filled_at and order.closed_at:
                filled_time = datetime.strptime(order.filled_at, '%Y-%m-%d %H:%M:%S')
                closed_time = datetime.strptime(order.closed_at, '%Y-%m-%d %H:%M:%S')
                holding_seconds = int((closed_time - filled_time).total_seconds())
                self.trader._record_holding_time(holding_seconds)

            self.trader._record_profit(float(profit), 'take_profit')
            self.trader._save_metrics()

            if order.sl_order_id:
                try:
                    symbol = self.trader.config.get("symbol", "BTCUSDT")
                    await self.trader.client.cancel_algo_order(symbol, order.sl_order_id)
                    logger.info(f"[取消止损单] algoId={order.sl_order_id}")
                except Exception as e:
                    logger.warning(f"[取消止损单] 失败: {e}")

            self.trader._log_order_closed(order, "止盈")

            notify_take_profit(order, profit, self.trader.config, self.trader.session_id, self.trader.db)

            await self._cancel_next_level_and_restart(order)

            # self._adjust_order_levels()  # 注释：移除层级调整，保持原始层级

            self.trader._save_state()
    
    async def _handle_stop_loss(self, order: Any, algo_data: Dict[str, Any]) -> None:
        # === 事件处理锁：确保顺序处理 ===
        async with self.trader._event_lock:
            # 检查订单是否已处理
            if order.state == "closed":
                logger.info(f"[止损] A{order.level} 已处理，跳过")
                return

            logger.info(f"[止损触发] A{order.level}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 止损触发 A{order.level}")

            order.state = "closed"
            order.close_reason = CloseReason.STOP_LOSS.value
            order.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            order.close_price = order.stop_loss_price

            # === 计算盈亏（含杠杆）===
            leverage = self.trader.config.get('leverage', 10)
            profit = (order.stop_loss_price - order.entry_price) * order.quantity * leverage
            order.profit = profit

            # 订单状态变更日志
            logger.info(f"[订单状态] A{order.level}: filled -> closed, 原因=stop_loss, 盈亏={profit:.2f}")

            # === 更新资金池 ===
            result = self.trader.capital_pool.update_capital(profit)
            logger.info(f"[资金池更新] A{order.level} 止损: 盈亏={profit:.2f}, "
                        f"trading_capital={self.trader.capital_pool.trading_capital:.2f}, "
                        f"profit_pool={getattr(self.trader.capital_pool, 'profit_pool', 0):.2f}")

            # === 更新统计 ===
            self.trader.results['total_trades'] += 1
            self.trader.results['loss_trades'] += 1
            self.trader.results['total_loss'] += profit

            # === 检查爆仓 ===
            if self.trader.capital_pool.check_liquidation():
                logger.warning(f"[爆仓触发] 交易资金不足")
                recovered = self.trader.capital_pool.recover_from_liquidation()
                if recovered:
                    logger.info(f"[爆仓恢复] 已从利润池恢复资金")
                else:
                    logger.error(f"[爆仓恢复] 利润池不足，无法恢复")

            # === 保存交易记录到数据库 ===
            if self.trader.session_id:
                self.trader.db.save_trade(
                    session_id=self.trader.session_id,
                    order=order,
                    trade_type='stop_loss',
                    leverage=leverage
                )
                # 保存资金历史
                self.trader.db.save_capital_history(
                    session_id=self.trader.session_id,
                    event_type='stop_loss',
                    old_capital=float(self.trader.capital_pool.trading_capital - profit),
                    new_capital=float(self.trader.capital_pool.trading_capital),
                    profit_pool=float(getattr(self.trader.capital_pool, 'profit_pool', 0)),
                    amount=float(profit),
                    related_order_id=order.order_id
                )
                # 更新会话统计
                self.trader.db.update_session_stats(self.trader.session_id, {
                    'total_trades': self.trader.results['total_trades'],
                    'win_trades': self.trader.results['win_trades'],
                    'loss_trades': self.trader.results['loss_trades'],
                    'total_profit': float(self.trader.results['total_profit']),
                    'total_loss': float(self.trader.results['total_loss']),
                    'final_capital': float(self.trader.capital_pool.trading_capital)
                })

            # === 记录统计指标 ===
            # 计算持仓时长
            if order.filled_at and order.closed_at:
                filled_time = datetime.strptime(order.filled_at, '%Y-%m-%d %H:%M:%S')
                closed_time = datetime.strptime(order.closed_at, '%Y-%m-%d %H:%M:%S')
                holding_seconds = int((closed_time - filled_time).total_seconds())
                self.trader._record_holding_time(holding_seconds)

            self.trader._record_profit(float(profit), 'stop_loss')
            self.trader._save_metrics()

            if order.tp_order_id:
                try:
                    symbol = self.trader.config.get("symbol", "BTCUSDT")
                    await self.trader.client.cancel_algo_order(symbol, order.tp_order_id)
                    logger.info(f"[取消止盈单] algoId={order.tp_order_id}")
                except Exception as e:
                    logger.warning(f"[取消止盈单] 失败: {e}")

            self.trader._log_order_closed(order, "止损")

            notify_stop_loss(order, profit, self.trader.config, self.trader.session_id, self.trader.db)

            await self._cancel_next_level(order)

            # self._adjust_order_levels()  # 注释：移除层级调整，保持原始层级

            self.trader._save_state()
    
    async def _cancel_next_level_and_restart(self, order: Any) -> None:
        symbol = self.trader.config.get("symbol", "BTCUSDT")
        next_level = order.level + 1
        max_level = self.trader.config.get("max_entries", 4)
        
        next_order = None
        for o in self.trader.chain_state.orders:
            if o.level == next_level and o.state == "pending":
                next_order = o
                break
        
        if next_order and next_order.order_id:
            try:
                await self.trader.client.cancel_order(symbol, next_order.order_id)
                logger.info(f"[取消下一级挂单] A{next_order.level}")
            except Exception as e:
                logger.warning(f"[取消下一级挂单] 失败: {e}")
            
            self.trader.chain_state.orders.remove(next_order)
        
        if order.level == 1:
            current_price = await self.trader._get_current_price()
            klines = await self.trader._get_recent_klines()
            new_order = await self.trader._create_order(1, current_price, klines)
            self.trader.chain_state.orders.append(new_order)
            
            print(f"\n{'='*60}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📥 重新下 A1")
            print(f"{'='*60}")
            await self.trader._place_entry_order(new_order, is_supplement=False)
    
    async def _cancel_next_level(self, order: Any) -> None:
        symbol = self.trader.config.get("symbol", "BTCUSDT")
        next_level = order.level + 1
        
        next_order = None
        for o in self.trader.chain_state.orders:
            if o.level == next_level and o.state == "pending":
                next_order = o
                break
        
        if next_order and next_order.order_id:
            try:
                await self.trader.client.cancel_order(symbol, next_order.order_id)
                logger.info(f"[取消下一级挂单] A{next_order.level}")
            except Exception as e:
                logger.warning(f"[取消下一级挂单] 失败: {e}")
            
            self.trader.chain_state.orders.remove(next_order)
    
    def _adjust_order_levels(self) -> None:
        if not self.trader.chain_state:
            return
        
        valid_orders = [o for o in self.trader.chain_state.orders 
                       if o.state != "closed"]
        
        valid_orders.sort(key=lambda o: o.level)
        
        for i, order in enumerate(valid_orders, start=1):
            if order.level != i:
                logger.info(f"[级别调整] A{order.level} -> A{i}")
                order.level = i
        
        self.trader.chain_state.orders = valid_orders
    
    async def _handle_finished(self, order: Any, algo_data: Dict[str, Any], 
                                algo_id: int, algo_type: str) -> None:
        if order.state == "closed":
            logger.info(f"[Algo事件] A{order.level} 已处理过，跳过")
            return
        
        is_tp = (order.tp_order_id == algo_id)
        close_price = order.take_profit_price if is_tp else order.stop_loss_price
        
        leverage = self.trader.config.get("leverage", Decimal("10"))
        profit = (close_price - order.entry_price) * order.quantity * leverage
        order.profit = profit
        order.close_price = close_price
        
        self.trader.results["total_trades"] += 1
        
        if is_tp:
            order.state = "closed"
            order.close_reason = "take_profit"
            self.trader.results["win_trades"] += 1
            self.trader.results["total_profit"] += profit
            logger.info(f"[止盈] A{order.level}: 盈利={profit:.2f}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 A{order.level} 止盈: 盈利={profit:.2f} USDT")
            notify_take_profit(order, profit, self.trader.config, self.trader.session_id, self.trader.db)
        else:
            order.state = "closed"
            order.close_reason = "stop_loss"
            self.trader.results["loss_trades"] += 1
            self.trader.results["total_loss"] += abs(profit)
            logger.info(f"[止损] A{order.level}: 亏损={profit:.2f}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 A{order.level} 止损: 亏损={profit:.2f} USDT")
            notify_stop_loss(order, profit, self.trader.config, self.trader.session_id, self.trader.db)
        
        if is_tp and order.sl_order_id:
            await self.trader.client.cancel_algo_order(
                self.trader.config.get("symbol", "BTCUSDT"), order.sl_order_id)
        elif not is_tp and order.tp_order_id:
            await self.trader.client.cancel_algo_order(
                self.trader.config.get("symbol", "BTCUSDT"), order.tp_order_id)
        
        symbol = self.trader.config.get("symbol", "BTCUSDT")
        next_level = order.level + 1
        next_order = None
        for o in self.trader.chain_state.orders:
            if o.level == next_level and o.state == "pending":
                next_order = o
                break
        
        if next_order and next_order.order_id:
            try:
                await self.trader.client.cancel_order(symbol, next_order.order_id)
                logger.info(f"[取消下一级挂单] A{next_order.level} 入场单已取消")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ A{next_order.level} 下一级挂单已取消")
            except Exception as e:
                logger.warning(f"[取消下一级挂单] A{next_order.level} 取消失败: {e}")
            
            if next_order in self.trader.chain_state.orders:
                self.trader.chain_state.orders.remove(next_order)
                logger.info(f"[删除下一级订单] A{next_order.level} 已删除")
        
        self.trader._save_state()
        
        current_price = await self.trader._get_current_price()
        klines = await self.trader._get_recent_klines()
        new_order = await self.trader._create_order(order.level, current_price, klines)
        self.trader.chain_state.orders.append(new_order)
        await self.trader._place_entry_order(new_order)
    
    async def _handle_canceled(self, order: Any, algo_id: int, algo_type: str) -> None:
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
        
        self.trader._save_state()
    
    async def _handle_expired(self, order: Any, algo_id: int, algo_type: str) -> None:
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
        
        self.trader._save_state()
    
    async def _handle_rejected(self, order: Any, algo_data: Dict[str, Any], 
                               algo_id: int, algo_type: str) -> None:
        inner_data = algo_data.get("o", {})
        reject_reason = inner_data.get("r", "未知原因")
        is_tp = (order.tp_order_id == algo_id)
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
        
        self.trader._save_state()
    
    async def _handle_new(self, order: Any, algo_data: Dict[str, Any], algo_id: int, algo_type: str) -> None:
        inner_data = algo_data.get("o", {})
        symbol = inner_data.get("s") or algo_data.get("symbol")
        trigger_price = Decimal(str(inner_data.get("tp") or inner_data.get("sp") or 0))
        order_type_str = inner_data.get("o") or algo_type
        
        if symbol != self.trader.config.get("symbol", "BTCUSDT"):
            return
        
        is_tp_order = order_type_str in ["TAKE_PROFIT_MARKET", "TAKE_PROFIT"]
        is_sl_order = order_type_str in ["STOP_MARKET", "STOP_LOSS"]
        
        if is_tp_order and order.tp_order_id == algo_id:
            if trigger_price != order.take_profit_price:
                old_price = order.take_profit_price
                order.take_profit_price = trigger_price
                logger.info(f"[手动修改] A{order.level} 止盈单价格已更新: {old_price:.2f} -> {trigger_price:.2f}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✏️ A{order.level} 止盈单已手动修改: {old_price:.2f} -> {trigger_price:.2f}")
                self.trader._save_state()
        
        if is_sl_order and order.sl_order_id == algo_id:
            if trigger_price != order.stop_loss_price:
                old_price = order.stop_loss_price
                order.stop_loss_price = trigger_price
                logger.info(f"[手动修改] A{order.level} 止损单价格已更新: {old_price:.2f} -> {trigger_price:.2f}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✏️ A{order.level} 止损单已手动修改: {old_price:.2f} -> {trigger_price:.2f}")
                self.trader._save_state()
        
        for o in self.trader.chain_state.orders:
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
                    self.trader._save_state()
                    break
            
            if is_sl_order and not o.sl_order_id:
                expected_sl_price = o.stop_loss_price
                price_diff = abs(trigger_price - expected_sl_price)
                if price_diff < expected_sl_price * Decimal("1.001"):
                    o.sl_order_id = algo_id
                    o.stop_loss_price = trigger_price
                    logger.info(f"[手动修改] A{o.level} 止损单已更新: algoId={algo_id}, 价格={trigger_price}")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✏️ A{o.level} 止损单已手动修改: 价格={trigger_price:.2f}")
                    self.trader._save_state()
                    break


# ============================================================================
# Binance 实盘交易者
# ============================================================================

class BinanceLiveTrader:
    """Binance 实盘交易器
    
    实现链式挂单策略的实盘交易，是整个系统的核心类。
    
    主要功能：
    1. 状态恢复：程序重启后从本地文件恢复订单状态，与 Binance 同步
    2. 订单同步：检测 Binance 订单状态变化，更新本地状态
    3. 补单机制：检测并补充缺失的止盈止损单
    4. WebSocket 监听：实时监听订单状态变化
    5. 异常处理：错误重试、通知和恢复
    
    交易流程：
        启动 -> 初始化精度 -> 状态恢复 -> 补单检查 -> 
        下入场单 -> WebSocket 监听 -> 处理事件 -> 循环
    
    订单生命周期：
        pending（挂单中）-> filled（已成交）-> closed（已平仓）
        
        成交后：
        1. 下止盈止损条件单
        2. 发送成交通知
        3. 下下一级入场单
        
        平仓后：
        1. 取消另一个条件单
        2. 发送平仓通知
        3. 更新盈亏统计
    
    Attributes:
        config: 配置字典（symbol, total_amount, leverage 等）
        testnet: 是否使用测试网
        chain_state: 链式挂单状态（包含所有订单）
        running: 运行标志
        client: BinanceClient 实例
        algo_handler: AlgoHandler 实例
        calculator: 权重计算器
        price_precision: 价格精度
        qty_precision: 数量精度
    
    示例:
        >>> config = {"symbol": "BTCUSDT", "total_amount": 1200, ...}
        >>> trader = BinanceLiveTrader(config, testnet=True)
        >>> await trader.run()
    """

    def __init__(self, symbol: str, amplitude: Dict, market: Dict, entry: Dict, timeout: Dict, capital: Dict, testnet: bool = True, recover_session_id: int = None):
        """初始化实盘交易器

        Args:
            symbol: 交易对，如 "BTCUSDT"
            amplitude: 振幅参数（decay_factor, stop_loss, leverage, max_entries, grid_spacing, exit_profit, valid_amplitudes, weights）
            market: 行情配置（algorithm, trading_statuses, 及算法特定参数）
            entry: 入场策略（strategy, 及策略特定参数）
            timeout: 超时参数（a1_timeout_minutes）
            capital: 资金池配置（total_amount_quote, strategy, entry_mode, 及策略特定参数）
            testnet: 是否使用测试网
            recover_session_id: 恢复模式时使用的现有 session_id

        注意：参数由调用方保证完整性，内部不做默认值处理
        """
        # 存储原始参数（用于日志和调试）
        self.symbol = symbol
        self.amplitude = amplitude
        self.market = market
        self.entry = entry
        self.timeout = timeout
        self.capital = capital
        self.testnet = testnet

        # total_amount_quote 从 capital 读取（统一设计），兼容旧配置从 amplitude 读取
        total_amount_quote = capital.get("total_amount_quote") or amplitude.get("total_amount_quote", 10000)

        # 兼容旧代码的 config 属性（关键数值参数转换为 Decimal）
        self.config = {
            "symbol": symbol,
            # 振幅参数 - Decimal 类型
            "grid_spacing": Decimal(str(amplitude.get("grid_spacing", 0.01))),
            "exit_profit": Decimal(str(amplitude.get("exit_profit", 0.01))),
            "stop_loss": Decimal(str(amplitude.get("stop_loss", 0.08))),
            "decay_factor": amplitude.get("decay_factor", 0.5),
            "total_amount_quote": total_amount_quote,
            "leverage": amplitude.get("leverage", 10),
            "max_entries": amplitude.get("max_entries", 4),
            "valid_amplitudes": amplitude.get("valid_amplitudes", []),
            "weights": amplitude.get("weights", []),
            # 其他配置
            "market_config": market,
            "entry_price_strategy": entry,
            "a1_timeout_minutes": timeout.get("a1_timeout_minutes", 0),
            "capital": capital
        }

        # === 振幅参数 ===
        self.a1_timeout_minutes = timeout.get("a1_timeout_minutes", 0)
        self.min_refresh_price_diff = Decimal(str(timeout.get("min_refresh_price_diff", "0.0167")))  # 最小重挂价格差异阈值
        self.max_timeout_count = timeout.get("max_timeout_count", 10)  # 最大超时次数限制，0 表示不限制
        self.last_first_entry_check_time: Optional[datetime] = None

        # === 行情配置 ===
        self.market_aware = bool(market)
        self.market_algorithm = market.get("algorithm", "dual_thrust")
        # 算法参数直接从 market[algorithm] 获取
        self.market_algorithm_params = market.get(self.market_algorithm, {})
        self.market_config = market
        self.market_detector: Optional[MarketStatusDetector] = None
        self.current_market_status: MarketStatus = MarketStatus.UNKNOWN
        self.market_check_interval = self.market_algorithm_params.get("check_interval", 60)
        self.last_market_check_time: Optional[datetime] = None

        # === 状态管理 ===
        self.case_id: Optional[int] = None  # 关联的配置 ID（由外部设置）
        self.chain_state: Optional[Any] = None
        self.running = True
        self.paused = False
        self.exit_notified = False
        self._shutdown_event = asyncio.Event()
        self._exit_lock = asyncio.Lock()
        self._event_lock = asyncio.Lock()
        self._pause_lock = asyncio.Lock()

        # === 权重计算器 ===
        from autofish_core import Autofish_WeightCalculator, CapitalPoolFactory, EntryCapitalStrategyFactory
        self.calculator = Autofish_WeightCalculator(Decimal(str(amplitude.get("decay_factor", 0.5))))

        # === 资金池初始化 ===
        self.initial_capital = Decimal(str(total_amount_quote))
        self.stop_loss_ratio = float(amplitude.get("stop_loss", 0.08))
        self.leverage = int(amplitude.get("leverage", 10))

        self.capital_pool = CapitalPoolFactory.create(
            initial_capital=self.initial_capital,
            capital_config=capital,
            stop_loss=self.stop_loss_ratio,
            leverage=self.leverage
        )

        # === 入场资金策略初始化 ===
        entry_mode = capital.get("entry_mode", "compound")
        self.capital_strategy = EntryCapitalStrategyFactory.create_strategy(entry_mode)

        # === API credentials（从环境变量读取）===
        if self.testnet:
            api_key = os.getenv("BINANCE_TESTNET_API_KEY", "")
            api_secret = os.getenv("BINANCE_TESTNET_SECRET_KEY", "")
        else:
            api_key = os.getenv("BINANCE_API_KEY", "")
            api_secret = os.getenv("BINANCE_SECRET_KEY", "")

        self.proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None

        self.client = BinanceClient(api_key, api_secret, testnet, proxy=self.proxy)

        self.algo_handler = AlgoHandler(self)

        self.price_precision = 2
        self.qty_precision = 3

        self.ws = None
        self.ws_connected = False
        self.ws_error_count = 0
        self.ws_last_message_time: Optional[datetime] = None

        # === 启动信息（用于日志）===
        self._proxy_logged = False

        self.results = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "total_profit": Decimal("0"),
            "total_loss": Decimal("0"),
        }

        # === 数据库存储 ===
        self.db = LiveTradingDB()
        self.session_id: Optional[int] = None
        self.recover_session_id: Optional[int] = recover_session_id  # 恢复模式
        # state_repository 已废弃：不再使用快照表
        self.market_case_id: Optional[int] = None
        self._current_bands: Optional[Dict] = None  # 当前轨道数据缓存

        # === 统计指标 ===
        self._metrics = {
            'execution_times': [],           # 累计执行时间列表（分钟）- 从首次挂单到成交
            'single_execution_times': [],    # 单次执行时间列表（分钟）- 最近一次挂单到成交
            'holding_times': [],             # 持仓时间列表（分钟）
            'profits': [],                   # 盈亏列表
            'order_timeout_counts': [],      # 每个成交订单的超时重挂次数
            'tp_trigger_count': 0,           # 止盈触发次数
            'sl_trigger_count': 0,           # 止损触发次数
            'timeout_refresh_count': 0,      # A1 超时重挂次数
            'skipped_refresh_count': 0,      # 因价格差异不足跳过的重挂次数
            'supplement_count': 0,           # 止盈止损单补充次数
            'start_time': None,              # 运行开始时间
            'pause_start_time': None,        # 暂停开始时间
            'total_paused_minutes': 0,       # 总暂停时长
            'max_level_reached': 0,          # 最大层级达到
            'order_group_count': 0,          # 订单组数（轮次）
        }
    
    async def _init_precision(self) -> None:
        symbol = self.config.get("symbol", "BTCUSDT")
        try:
            exchange_info = await self.client.get_exchange_info(symbol)
            precision = self.client._get_symbol_precision(exchange_info, symbol)
            self.price_precision = precision["price_precision"]
            self.qty_precision = precision["qty_precision"]
            
            for s in exchange_info.get("symbols", []):
                if s.get("symbol") == symbol:
                    for f in s.get("filters", []):
                        if f.get("filterType") == "PRICE_FILTER":
                            self.tick_size = Decimal(f.get("tickSize", "0.01"))
                        elif f.get("filterType") == "LOT_SIZE":
                            self.step_size = Decimal(f.get("stepSize", "0.001"))
                        elif f.get("filterType") == "MIN_NOTIONAL":
                            self.min_notional = Decimal(f.get("notional", "100"))
                    break
            
            if not hasattr(self, 'min_notional'):
                self.min_notional = Decimal("100")
            
            logger.info(f"[精度初始化] {symbol}: 价格精度={self.price_precision}位小数, 数量精度={self.qty_precision}位小数, 价格步长={self.tick_size}, 数量步长={self.step_size}, 最小金额={self.min_notional} USDT")
        except Exception as e:
            logger.warning(f"[精度初始化] 获取精度失败，使用默认值: {e}")
            self.tick_size = Decimal("0.1")
            self.step_size = Decimal("0.001")
            self.min_notional = Decimal("100")
    
    async def _get_recent_klines(self, limit: int = 30) -> List[Dict]:
        """获取最近 N 根 K 线
        
        参数:
            limit: K 线数量，默认 30 根
            
        返回:
            K 线数据列表
        """
        symbol = self.config.get('symbol', 'BTCUSDT')
        url = f"{self.client.base_url}/fapi/v1/klines"
        params = {
            'symbol': symbol,
            'interval': '1h',
            'limit': limit
        }
        
        try:
            async with self.client.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    klines = [{
                        'timestamp': item[0],
                        'open': Decimal(item[1]),
                        'high': Decimal(item[2]),
                        'low': Decimal(item[3]),
                        'close': Decimal(item[4]),
                        'volume': Decimal(item[5]),
                    } for item in data]
                    logger.info(f"[K线获取] 成功获取 {len(klines)} 根 1h K线")
                    return klines
                else:
                    text = await response.text()
                    logger.warning(f"[K线获取] 失败: {response.status} - {text}")
                    return []
        except asyncio.TimeoutError:
            logger.warning(f"[K线获取] 超时: 请求 {symbol} K线超时")
            return []
        except aiohttp.ClientError as e:
            logger.warning(f"[K线获取] 网络错误: {type(e).__name__} - {e}")
            return []
        except Exception as e:
            logger.warning(f"[K线获取] 异常: {type(e).__name__} - {e}")
            return []
    
    async def _init_market_detector(self) -> None:
        """初始化行情检测器"""
        if not self.market_aware:
            logger.info("[行情检测] 行情感知功能未启用")
            return
        
        # 使用解析后的算法参数
        detector_config = self.market_algorithm_params.copy()
        detector_config['algorithm'] = self.market_algorithm

        # 使用 MarketStatusDetector.ALGORITHMS 字典获取正确的算法类
        algorithm_class = MarketStatusDetector.ALGORITHMS.get(self.market_algorithm)
        if algorithm_class:
            algorithm_instance = algorithm_class(detector_config)
            self.market_detector = MarketStatusDetector(algorithm=algorithm_instance, config=detector_config)
        else:
            logger.warning(f"[行情检测] 未知的算法: {self.market_algorithm}, 使用默认 RealTimeStatusAlgorithm")
            self.market_detector = MarketStatusDetector(config=detector_config)
        
        trading_statuses = self.market_config.get('trading_statuses', ['ranging'])
        logger.info(f"[行情检测] 初始化完成, 算法: {self.market_algorithm}, 交易状态: {trading_statuses}")
        print(f"  行情感知: 启用 (算法: {self.market_algorithm}, 只做: {trading_statuses})")
    
    async def _check_market_status(self, current_price: Decimal) -> Optional[StatusResult]:
        """检测当前行情状态

        参数:
            current_price: 当前价格

        返回:
            行情判断结果，如果检测失败返回 None
        """
        if not self.market_aware or not self.market_detector:
            return None

        now = datetime.now()
        if self.last_market_check_time:
            elapsed = (now - self.last_market_check_time).total_seconds()
            if elapsed < self.market_check_interval:
                return None

        self.last_market_check_time = now

        try:
            klines = await self._get_recent_klines(limit=100)
            if not klines or len(klines) < 20:
                logger.warning("[行情检测] K线数据不足")
                return None

            result = self.market_detector.algorithm.calculate(klines, self.market_detector.config)
            logger.info(f"[行情检测] 状态={result.status.value}, 置信度={result.confidence:.2f}, 原因={result.reason}")

            # === 保存行情结果到数据库 ===
            if self.session_id:
                # 确保 market_case 存在
                if not self.market_case_id:
                    self.market_case_id = self.db.create_market_case(
                        session_id=self.session_id,
                        symbol=self.config.get('symbol', 'BTCUSDT'),
                        algorithm=self.market_algorithm,
                        algorithm_config=self.market_algorithm_params,
                        check_interval=self.market_check_interval
                    )

                # 获取最新的 K 线数据用于保存
                latest_kline = klines[-1] if klines else {}
                self.db.save_market_result(
                    case_id=self.market_case_id,
                    result={
                        'check_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                        'market_status': result.status.value,
                        'confidence': result.confidence,
                        'reason': result.reason,
                        'open_price': float(latest_kline.get('open', 0)),
                        'close_price': float(latest_kline.get('close', 0)),
                        'high_price': float(latest_kline.get('high', 0)),
                        'low_price': float(latest_kline.get('low', 0)),
                        'volume': float(latest_kline.get('volume', 0)),
                    }
                )

            return result
        except Exception as e:
            logger.warning(f"[行情检测] 检测失败: {e}")
            return None
    
    async def _handle_market_status_change(self, old_status: MarketStatus, new_status: MarketStatus, 
                                            current_price: Decimal) -> None:
        """处理行情状态变化
        
        参数:
            old_status: 旧状态
            new_status: 新状态
            current_price: 当前价格
        """
        from autofish_core import Autofish_ChainState
        
        logger.info(f"[行情变化] {old_status.value} -> {new_status.value}")
        print(f"\n{'='*60}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 行情变化")
        print(f"{'='*60}")
        print(f"  旧状态: {old_status.value}")
        print(f"  新状态: {new_status.value}")
        print(f"  当前价格: {current_price:.2f}")
        
        trading_statuses_str = self.market_config.get('trading_statuses', ['ranging'])
        trading_statuses = []
        for status_str in trading_statuses_str:
            if status_str == 'ranging':
                trading_statuses.append(MarketStatus.RANGING)
            elif status_str == 'trending_up':
                trading_statuses.append(MarketStatus.TRENDING_UP)
            elif status_str == 'trending_down':
                trading_statuses.append(MarketStatus.TRENDING_DOWN)
        
        is_trading_status = new_status in trading_statuses
        was_trading_status = old_status in trading_statuses

        # 当前是非交易状态，且有活跃订单（pending 或 filled），需要取消/平仓
        if not is_trading_status:
            if self.chain_state and self.chain_state.orders:
                has_pending = any(o.state == "pending" for o in self.chain_state.orders)
                has_filled = any(o.state == "filled" for o in self.chain_state.orders)
                if has_pending or has_filled:
                    print(f"  ⚠️ 非交易状态，取消挂单并平仓")
                    # 取消所有挂单（pending 状态）
                    symbol = self.config.get('symbol', 'BTCUSDT')
                    for order in self.chain_state.orders:
                        if order.state == "pending" and order.order_id:
                            try:
                                await self.client.cancel_order(symbol, order.order_id)
                                logger.info(f"[行情变化] 取消挂单 A{order.level}: orderId={order.order_id}")
                                print(f"   取消挂单 A{order.level}")
                                order.state = "cancelled"
                                # 同步更新数据库订单状态
                                if self.session_id:
                                    self.db.update_order(self.session_id, order)
                            except Exception as e:
                                logger.warning(f"[行情变化] 取消挂单失败: {e}")
                    # 平仓所有持仓订单（filled 状态）
                    await self._close_all_positions(current_price, "market_status_change")
                    self.chain_state.is_active = False
                    self._save_state()
                    notify_market_status(old_status.value, new_status.value, f"非交易状态({new_status.value})，停止交易", self.config, self.session_id, self.db)
        
        elif is_trading_status and not was_trading_status:
            # 进入可交易状态，检查是否需要清理旧订单后重新开始
            if self.chain_state and self.chain_state.orders:
                # 有旧订单（可能是 pending 状态），先取消
                symbol = self.config.get('symbol', 'BTCUSDT')
                for order in self.chain_state.orders:
                    if order.state == "pending" and order.order_id:
                        try:
                            await self.client.cancel_order(symbol, order.order_id)
                            logger.info(f"[行情变化] 取消旧挂单 A{order.level}: orderId={order.order_id}")
                            print(f"   取消旧挂单 A{order.level}")
                            order.state = "cancelled"
                            # 同步更新数据库订单状态
                            if self.session_id:
                                self.db.update_order(self.session_id, order)
                        except Exception as e:
                            logger.warning(f"[行情变化] 取消旧挂单失败: {e}")
                # 清理已取消的订单
                self.chain_state.orders = [o for o in self.chain_state.orders if o.state != "cancelled"]
                self._save_state()

            if not self.chain_state or not self.chain_state.orders:
                print(f"  ✅ 进入可交易状态，开始交易")
                klines = await self._get_recent_klines()
                first_order = await self._create_order(1, current_price, klines)
                self.chain_state = Autofish_ChainState(base_price=current_price, orders=[first_order])
                await self._place_entry_order(first_order)
                self._save_state()
                notify_market_status(old_status.value, new_status.value, "可交易状态，开始交易", self.config, self.session_id, self.db)
        
        print(f"{'='*60}\n")
    
    def _adjust_price(self, price: Decimal) -> Decimal:
        tick_size = getattr(self, 'tick_size', Decimal("0.1"))
        adjusted = (price // tick_size) * tick_size
        return adjusted
    
    def _adjust_quantity(self, quantity: Decimal, price: Decimal = None) -> Decimal:
        """调整数量精度，并确保满足最小金额要求
        
        参数:
            quantity: 原始数量
            price: 入场价格（用于检查最小金额要求）
        
        返回:
            调整后的数量
        """
        step_size = getattr(self, 'step_size', Decimal("0.001"))
        adjusted = (quantity // step_size) * step_size
        
        if adjusted <= 0:
            adjusted = step_size
        
        min_notional = getattr(self, 'min_notional', Decimal("100"))
        
        if price and price > 0:
            current_notional = adjusted * price
            if current_notional < min_notional:
                min_quantity = (min_notional / price // step_size + 1) * step_size
                logger.warning(f"[数量调整] 订单金额 {current_notional:.2f} USDT < 最小要求 {min_notional} USDT，"
                              f"数量从 {adjusted:.6f} 调整为 {min_quantity:.6f}")
                print(f"   ⚠️ 订单金额不足，数量调整为 {min_quantity:.6f} (金额: {min_quantity * price:.2f} USDT)")
                adjusted = min_quantity
        
        return adjusted
    
    def _ceil_amount(self, amount: float) -> int:
        """金额向上取整
        
        参数:
            amount: 原始金额
        
        返回:
            向上取整后的金额
        """
        return int(amount) + 1 if amount != int(amount) else int(amount)
    
    def _print_level_check_results(self, results: List[Dict], show_status: bool = True) -> None:
        """打印各层级检查结果
        
        参数:
            results: 各层级检查结果列表
            show_status: 是否显示状态图标
        """
        for r in results:
            if show_status:
                status = "✅" if r['satisfied'] else "❌"
                print(f"    A{r['level']}: {self._ceil_amount(r['stake'])} USDT ({r['weight']*100:.1f}%) {status}")
            else:
                print(f"    A{r['level']}: {self._ceil_amount(r['stake'])} USDT ({r['weight']*100:.1f}%)")
    
    def _check_min_notional(self) -> Tuple[bool, Dict]:
        """检查配置是否满足最小金额要求
        
        返回:
            (是否满足, 检查结果详情)
        """
        from autofish_core import normalize_weights
        
        min_notional = getattr(self, 'min_notional', Decimal("100"))
        total_amount = Decimal(str(self.config.get('total_amount_quote', 1200)))
        max_entries = self.config.get('max_entries', 4)
        weights = [Decimal(str(w)) for w in self.config.get('weights', [])]
        
        # 归一化权重
        normalized_weights = normalize_weights(weights, max_entries)
        
        results = []
        all_satisfied = True
        
        for level in range(1, max_entries + 1):
            if level <= len(normalized_weights):
                weight = normalized_weights[level - 1]
            else:
                weight = Decimal("0")
            stake = total_amount * weight
            
            satisfied = stake >= min_notional
            if not satisfied:
                all_satisfied = False
            
            results.append({
                'level': level,
                'weight': float(weight),
                'stake': float(stake),
                'satisfied': satisfied
            })
        
        min_weight = min(r['weight'] for r in results) if results else Decimal("1")
        suggested_min_amount = min_notional / Decimal(str(min_weight)) if min_weight > 0 else min_notional
        
        return all_satisfied, {
            'results': results,
            'min_notional': float(min_notional),
            'total_amount': float(total_amount),
            'suggested_min_amount': float(suggested_min_amount)
        }
    
    async def _check_fund_sufficiency(self) -> bool:
        """检查资金是否充足
        
        返回:
            True: 资金满足要求，继续运行
            False: 资金不满足要求，需要退出
        """
        satisfied, check_result = self._check_min_notional()
        
        if not satisfied:
            suggested_min_ceil = self._ceil_amount(check_result['suggested_min_amount'])
            logger.error(f"[预检查] 配置不满足最小金额要求，程序退出 - 当前资金: {check_result['total_amount']} USDT，需要: {suggested_min_ceil} USDT")
            
            error_msg = f"总资金 {check_result['total_amount']} USDT 不满足最小金额要求，建议最小总资金: {suggested_min_ceil} USDT"
            notify_critical_error(error_msg, self.config, self.session_id, self.db)
            
            print(f"\n{'='*60}")
            print(f"❌ 配置预检查失败，程序退出")
            print(f"{'='*60}")
            print(f"  最小金额要求: {check_result['min_notional']} USDT")
            print(f"  当前总资金: {check_result['total_amount']} USDT")
            print(f"  建议最小总资金: {suggested_min_ceil} USDT")
            print(f"\n  各层级检查:")
            self._print_level_check_results(check_result['results'])
            print(f"\n  请增加总资金或减少最大层级数量")
            print(f"{'='*60}\n")
            
            return False
        
        suggested_amount_1_5x = check_result['suggested_min_amount'] * 1.5
        suggested_amount_1_5x_ceil = self._ceil_amount(suggested_amount_1_5x)
        suggested_min_ceil = self._ceil_amount(check_result['suggested_min_amount'])
        
        if check_result['total_amount'] < suggested_amount_1_5x:
            logger.warning(f"[预检查] 资金储备可能不足 - 当前资金: {check_result['total_amount']} USDT，最小资金: {suggested_min_ceil} USDT，建议资金: {suggested_amount_1_5x_ceil} USDT")
            
            warning_msg = f"当前总资金 {check_result['total_amount']} USDT，建议资金储备: {suggested_amount_1_5x_ceil} USDT（最小资金的1.5倍）"
            notify_warning(warning_msg, self.config, self.session_id, self.db)
            
            print(f"\n{'='*60}")
            print(f"⚠️ 资金储备提醒")
            print(f"{'='*60}")
            print(f"  当前总资金: {check_result['total_amount']} USDT")
            print(f"  策略所需最小资金: {suggested_min_ceil} USDT")
            print(f"  建议资金储备: {suggested_amount_1_5x_ceil} USDT（最小资金的1.5倍）")
            print(f"\n  各层级检查:")
            self._print_level_check_results(check_result['results'])
            print(f"\n  资金储备可能不足，建议增加资金以提高策略稳定性")
            print(f"{'='*60}\n")
        else:
            logger.info(f"[预检查] 资金配置检查通过 - 当前资金: {check_result['total_amount']} USDT，最小资金: {suggested_min_ceil} USDT，建议资金: {suggested_amount_1_5x_ceil} USDT")
            
            levels_info = "\n".join([
                f"> A{r['level']}: {self._ceil_amount(r['stake'])} USDT ({r['weight']*100:.1f}%)"
                for r in check_result['results']
            ])
            
            content = dedent(f"""
                > **通知类型**: 配置确认
                > **交易标的**: {self.config.get('symbol', 'BTCUSDT')}
                > **当前总资金**: {check_result['total_amount']} USDT
                > 
                > **各层级分配**:
                {levels_info}
                > 
                > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """).strip()
            send_wechat_notification("✅ Autofish V2 配置确认", content, self.session_id, self.db, "config_confirm")
            
            print(f"\n{'='*60}")
            print(f"✅ 资金配置检查通过")
            print(f"{'='*60}")
            print(f"  当前总资金: {check_result['total_amount']} USDT")
            print(f"  策略所需最小资金: {suggested_min_ceil} USDT")
            print(f"  建议资金储备: {suggested_amount_1_5x_ceil} USDT（最小资金的1.5倍）")
            print(f"\n  各层级分配:")
            self._print_level_check_results(check_result['results'], show_status=False)
            print(f"{'='*60}\n")
        
        return True
    
    def _save_state(self) -> None:
        """保存状态到数据库

        简化版本：不再写入 live_state_snapshots 快照表，
        所有数据已通过专用方法保存到对应的专用表：
        - 订单 → live_orders (save_order/update_order)
        - 资金池 → live_capital_statistics (save_statistics)
        - 统计 → live_sessions (update_session_stats)

        此处只更新 live_sessions 中的 base_price 和 group_id
        """
        if self.chain_state and self.session_id:
            try:
                self.db.update_session_stats(self.session_id, {
                    'base_price': float(self.chain_state.base_price),
                    'group_id': self.chain_state.group_id,
                })
            except Exception as e:
                logger.error(f"[状态保存] 保存失败: {e}", exc_info=True)

    # ==================== 统计指标记录方法 ====================

    def _record_execution_time(self, order: Any) -> None:
        """记录订单执行时间（挂单到成交）

        同时记录：
        - 累计执行时间：从首次挂单到成交（first_created_at → filled_at）
        - 单次执行时间：从最近挂单到成交（created_at → filled_at）
        - 超时重挂次数：订单经历过多少次超时重挂

        Args:
            order: 订单对象（需有 created_at、first_created_at、filled_at、timeout_count）
        """
        if not order.filled_at:
            return

        try:
            filled = datetime.strptime(order.filled_at, '%Y-%m-%d %H:%M:%S')

            # 1. 累计执行时间（从首次挂单开始）
            first_created = order.first_created_at or order.created_at
            if first_created:
                first_created_dt = datetime.strptime(first_created, '%Y-%m-%d %H:%M:%S')
                cumulative_time = (filled - first_created_dt).total_seconds() / 60
                self._metrics['execution_times'].append(cumulative_time)

            # 2. 单次执行时间（从最近挂单开始）
            if order.created_at:
                created_dt = datetime.strptime(order.created_at, '%Y-%m-%d %H:%M:%S')
                single_time = (filled - created_dt).total_seconds() / 60
                self._metrics['single_execution_times'].append(single_time)

            # 3. 记录超时重挂次数
            timeout_count = getattr(order, 'timeout_count', 0) or 0
            self._metrics['order_timeout_counts'].append(timeout_count)

            # 日志记录
            timeout_str = f", 超时{timeout_count}次" if timeout_count > 0 else ""
            if first_created and order.created_at and first_created != order.created_at:
                logger.debug(f"[指标记录] 累计执行: {cumulative_time:.2f}分钟, 单次执行: {single_time:.2f}分钟{timeout_str}")
            else:
                single = self._metrics['single_execution_times'][-1] if self._metrics['single_execution_times'] else 0
                logger.debug(f"[指标记录] 执行时间: {single:.2f}分钟{timeout_str}")

        except Exception as e:
            logger.warning(f"[指标记录] 执行时间计算失败: {e}")

    def _record_holding_time(self, holding_seconds: int) -> None:
        """记录持仓时间

        Args:
            holding_seconds: 持仓时长（秒）
        """
        holding_time = holding_seconds / 60  # 分钟
        self._metrics['holding_times'].append(holding_time)
        logger.debug(f"[指标记录] 持仓时间: {holding_time:.2f} 分钟")

    def _record_profit(self, profit: float, reason: str) -> None:
        """记录盈亏和触发类型

        Args:
            profit: 盈亏金额
            reason: 平仓原因（take_profit, stop_loss 等）
        """
        self._metrics['profits'].append(profit)

        # 更新触发计数
        if reason == 'take_profit':
            self._metrics['tp_trigger_count'] += 1
        elif reason == 'stop_loss':
            self._metrics['sl_trigger_count'] += 1

        logger.debug(f"[指标记录] 盈亏: {profit:.4f}, 原因: {reason}")

    def _record_timeout_refresh(self) -> None:
        """记录 A1 超时重挂"""
        self._metrics['timeout_refresh_count'] += 1

    def _record_skipped_refresh(self) -> None:
        """记录跳过重挂（价格差异不足）"""
        self._metrics['skipped_refresh_count'] += 1

    def _should_refresh_order(self, old_order, new_entry_price: Decimal) -> tuple[bool, str]:
        """评估是否应该重挂订单

        Args:
            old_order: 旧订单对象
            new_entry_price: 新入场价格

        Returns:
            (should_refresh: bool, reason: str) - 是否应该重挂和原因说明
        """
        if not old_order:
            return True, "无旧订单"

        # 检查最大超时次数限制
        if self.max_timeout_count > 0 and old_order.timeout_count >= self.max_timeout_count:
            return False, f"已达到最大超时次数 {self.max_timeout_count} 次，停止重挂"

        old_entry_price = old_order.entry_price
        price_diff_pct = (new_entry_price - old_entry_price) / old_entry_price

        if price_diff_pct < self.min_refresh_price_diff:
            return False, f"价格差异 {price_diff_pct:.3%} < 阈值 {self.min_refresh_price_diff:.3%}"

        return True, f"价格差异 {price_diff_pct:.3%} >= 阈值 {self.min_refresh_price_diff:.3%}"

    def _record_supplement(self) -> None:
        """记录止盈止损单补充"""
        self._metrics['supplement_count'] += 1

    def _record_level_reached(self, level: int) -> None:
        """记录达到的最大层级"""
        if level > self._metrics['max_level_reached']:
            self._metrics['max_level_reached'] = level

    def _get_metrics_summary(self) -> Dict:
        """获取统计指标摘要

        Returns:
            统计指标字典，用于保存到数据库
        """
        exec_times = self._metrics['execution_times']          # 累计执行时间
        single_exec_times = self._metrics['single_execution_times']  # 单次执行时间
        hold_times = self._metrics['holding_times']
        profits = self._metrics['profits']
        timeout_counts = self._metrics['order_timeout_counts']  # 订单超时次数

        # 计算盈亏比
        total_profit = sum(p for p in profits if p > 0)
        total_loss = sum(p for p in profits if p < 0)
        profit_factor = 0
        if total_loss != 0 and total_profit != 0:
            profit_factor = abs(total_profit / total_loss)

        # 计算运行时长
        total_runtime_minutes = 0
        if self._metrics['start_time']:
            total_runtime_minutes = (datetime.now() - self._metrics['start_time']).total_seconds() / 60

        # 计算超时次数统计
        orders_with_timeout = sum(1 for c in timeout_counts if c > 0)  # 有超时的订单数
        avg_timeout_count = sum(timeout_counts) / len(timeout_counts) if timeout_counts else 0
        max_timeout_count = max(timeout_counts) if timeout_counts else 0

        return {
            # 累计执行时间统计（从首次挂单到成交）
            'avg_execution_time': sum(exec_times) / len(exec_times) if exec_times else 0,
            'min_execution_time': min(exec_times) if exec_times else 0,
            'max_execution_time': max(exec_times) if exec_times else 0,
            'total_execution_time': sum(exec_times),
            'execution_count': len(exec_times),

            # 单次执行时间统计（从最近挂单到成交）
            'avg_single_execution_time': sum(single_exec_times) / len(single_exec_times) if single_exec_times else 0,
            'min_single_execution_time': min(single_exec_times) if single_exec_times else 0,
            'max_single_execution_time': max(single_exec_times) if single_exec_times else 0,
            'total_single_execution_time': sum(single_exec_times),
            'single_execution_count': len(single_exec_times),

            # 持仓时间统计
            'avg_holding_time': sum(hold_times) / len(hold_times) if hold_times else 0,
            'min_holding_time': min(hold_times) if hold_times else 0,
            'max_holding_time': max(hold_times) if hold_times else 0,
            'total_holding_time': sum(hold_times),
            'holding_count': len(hold_times),

            # 盈亏分布统计
            'max_profit_trade': max(profits) if profits else 0,
            'max_loss_trade': min(profits) if profits else 0,
            'profit_factor': profit_factor,

            # 订单层级统计
            'order_group_count': self.chain_state.group_id if self.chain_state else 0,
            'max_level_reached': self._metrics['max_level_reached'],
            'tp_trigger_count': self._metrics['tp_trigger_count'],
            'sl_trigger_count': self._metrics['sl_trigger_count'],

            # 超时统计
            'timeout_refresh_count': self._metrics['timeout_refresh_count'],
            'skipped_refresh_count': self._metrics['skipped_refresh_count'],
            'supplement_count': self._metrics['supplement_count'],
            'orders_with_timeout': orders_with_timeout,  # 有超时的订单数
            'avg_timeout_count': avg_timeout_count,       # 平均超时次数
            'max_timeout_count': max_timeout_count,       # 最大超时次数

            # 时间统计
            'total_runtime_minutes': total_runtime_minutes,
            'paused_time_minutes': self._metrics['total_paused_minutes'],
        }

    def _save_metrics(self) -> None:
        """保存统计指标到数据库"""
        if self.session_id:
            metrics = self._get_metrics_summary()
            self.db.save_session_metrics(self.session_id, metrics)
            logger.debug(f"[指标保存] 已保存统计指标到数据库: session_id={self.session_id}")

    def _load_state(self) -> Optional[Dict[str, Any]]:
        """加载状态（已废弃）

        已废弃：恢复流程现在从专用表读取数据：
        - live_sessions: base_price, group_id, 统计数据
        - live_capital_statistics: 资金池状态
        - live_orders: 订单列表

        此方法保留仅供向后兼容，不应再使用。
        """
        # 已废弃：不再从快照表读取
        # return self.state_repository.load()
        return None
    
    async def _create_order(self, level: int, base_price: Decimal, klines: List[Dict] = None,
                            group_id: int = None) -> Any:
        from autofish_core import Autofish_OrderCalculator

        order_calculator = Autofish_OrderCalculator(
            grid_spacing=self.config.get("grid_spacing", Decimal("0.01")),
            exit_profit=self.config.get("exit_profit", Decimal("0.01")),
            stop_loss=self.config.get("stop_loss", Decimal("0.08"))
        )

        # 从配置文件获取权重
        weights = [Decimal(str(w)) for w in self.config.get("weights", [])]
        max_entries = self.config.get('max_entries', 4)

        # === 使用入场资金策略计算总金额 ===
        entry_capital = self.capital_strategy.calculate_entry_capital(
            self.capital_pool, level, self.chain_state
        )
        entry_total_capital = self.capital_strategy.calculate_entry_total_capital(
            self.capital_pool, level, self.chain_state
        )

        # 空值保护：如果计算结果为 None，使用默认值
        if entry_capital is None:
            entry_capital = self.initial_capital
            logger.warning(f"[入场资金] calculate_entry_capital 返回 None，使用初始资金: {entry_capital}")
        if entry_total_capital is None:
            entry_total_capital = self.initial_capital
            logger.warning(f"[入场总资金] calculate_entry_total_capital 返回 None，使用初始资金: {entry_total_capital}")

        order = order_calculator.create_order(
            level=level,
            base_price=base_price,
            total_amount=entry_total_capital,
            weights=weights,
            max_entries=max_entries,
            klines=klines
        )

        order.quantity = self._adjust_quantity(order.quantity, order.entry_price)
        order.entry_price = self._adjust_price(order.entry_price)
        order.take_profit_price = self._adjust_price(order.take_profit_price)
        order.stop_loss_price = self._adjust_price(order.stop_loss_price)

        # === 设置入场资金和 group_id ===
        order.entry_capital = entry_capital
        order.entry_total_capital = entry_total_capital

        if group_id is None:
            if level == 1:
                # A1 下单时，group_id = chain_state.group_id + 1
                # 但不更新 chain_state.group_id，等 A1 成交时再确认
                actual_group_id = (self.chain_state.group_id if self.chain_state else 0) + 1
                logger.info(f"[新轮次] A1 下单，group_id={actual_group_id}（待成交确认）")
            else:
                # A2, A3, A4 使用当前 chain_state.group_id
                actual_group_id = self.chain_state.group_id if self.chain_state else 1
        else:
            actual_group_id = group_id

        order.group_id = actual_group_id

        logger.info(f"[创建订单] A{level}: 入场价={order.entry_price:.2f}, "
                    f"止盈价={order.take_profit_price:.2f}, 止损价={order.stop_loss_price:.2f}, "
                    f"数量={order.quantity:.6f}, 金额={order.stake_amount:.2f}, group_id={actual_group_id}")

        return order
    
    def _setup_signal_handlers(self) -> None:
        """设置信号处理器（仅在主线程中生效）"""
        import threading

        # 信号处理器只能在主线程中设置
        if threading.current_thread() is not threading.main_thread():
            return

        def signal_handler(signum, frame):
            signal_name = signal.Signals(signum).name
            logger.info(f"[信号处理] 收到信号 {signal_name}")
            print(f"\n\n收到信号 {signal_name}，程序即将退出")

            if self.exit_notified:
                raise KeyboardInterrupt(f"收到信号 {signal_name}")

            self.running = False
            self._shutdown_event.set()

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    
    async def _close_all_positions(self, close_price: Decimal, reason: str) -> None:
        """平仓所有持仓订单

        参数:
            close_price: 平仓价格
            reason: 平仓原因
        """
        if not self.chain_state or not self.chain_state.orders:
            return

        symbol = self.config.get('symbol', 'BTCUSDT')

        # 计算总持仓数量（所有filled订单的数量之和）
        total_quantity = Decimal("0")
        filled_orders = []
        for order in self.chain_state.orders:
            if order.state == "filled":
                filled_orders.append(order)
                total_quantity += order.quantity

        if not filled_orders:
            return

        # 取消所有止盈止损单
        for order in filled_orders:
            if order.tp_order_id:
                try:
                    await self.client.cancel_algo_order(symbol, order.tp_order_id)
                    logger.info(f"[平仓] 取消止盈单: algoId={order.tp_order_id}")
                except Exception as e:
                    logger.warning(f"[平仓] 取消止盈单失败: {e}")
            if order.sl_order_id:
                try:
                    await self.client.cancel_algo_order(symbol, order.sl_order_id)
                    logger.info(f"[平仓] 取消止损单: algoId={order.sl_order_id}")
                except Exception as e:
                    logger.warning(f"[平仓] 取消止损单失败: {e}")

        # 执行市价平仓（SELL）
        try:
            adjusted_quantity = self._adjust_quantity(total_quantity, close_price)
            logger.info(f"[平仓] 市价卖出: symbol={symbol}, quantity={adjusted_quantity:.6f}")
            print(f"  市价平仓: 数量={adjusted_quantity:.6f}")

            result = await self.client.place_order(
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                quantity=float(adjusted_quantity)
            )

            # 获取成交价格
            actual_close_price = close_price
            if "avgPrice" in result and result["avgPrice"]:
                actual_close_price = Decimal(str(result["avgPrice"]))
            elif "executedQty" in result and "cumQty" in result:
                # 计算平均成交价
                executed_qty = Decimal(str(result.get("executedQty", 0)))
                cum_qty = Decimal(str(result.get("cumQty", executed_qty)))
                if cum_qty > 0:
                    actual_close_price = close_price  # 使用传入的价格作为备用

            logger.info(f"[平仓] 成功: orderId={result.get('orderId')}, 成交价={actual_close_price:.2f}")
            print(f"  平仓成功: 成交价={actual_close_price:.2f}")

        except Exception as e:
            logger.error(f"[平仓] 市价卖出失败: {e}", exc_info=True)
            print(f"  ⚠️ 平仓失败: {e}")
            # 如果市价平仓失败，仍然标记订单为closed，避免阻塞
            actual_close_price = close_price

        # 更新所有订单状态
        for order in filled_orders:
            order.state = "closed"
            order.close_price = actual_close_price
            order.close_reason = reason
            order.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # 每个订单独立计算盈亏：盈亏 = (平仓价 - 入场价) × 数量
            order_profit = (actual_close_price - order.entry_price) * order.quantity
            order.profit = float(order_profit)

            logger.info(f"[平仓] A{order.level}: 入场价={order.entry_price:.2f}, 出场价={actual_close_price:.2f}, 盈亏={order_profit:.2f}")
            print(f"  A{order.level}: 入场价={order.entry_price:.2f}, 盈亏={order_profit:.2f} USDT")
    
    async def _handle_exit(self, reason: str) -> None:
        """处理程序退出
        
        执行退出前的清理工作：
        1. 取消所有挂单
        2. 保存当前状态
        3. 发送退出通知
        
        参数:
            reason: 退出原因
        """
        async with self._exit_lock:
            if self.exit_notified:
                return
            
            self.exit_notified = True
            self.running = False
        
        print(f"\n\n⏹️ 停止交易: {reason}")
        
        try:
            cancelled_orders = await self._cancel_all_orders()
            self._save_state()
            
            remaining_orders = []
            if self.chain_state:
                remaining_orders = [o for o in self.chain_state.orders 
                                   if o.state in ["filled", "pending"]]
            
            current_price = None
            pnl_info = None
            try:
                current_price = await self._get_current_price()
                pnl_info = await self._get_pnl_info()
            except Exception as e:
                logger.warning(f"[退出处理] 获取价格/盈亏失败: {e}")
            
            notify_exit(reason, self.config, self.session_id, self.db, cancelled_orders, remaining_orders,
                       pnl_info, current_price)

            # === 结束数据库会话 ===
            if self.session_id:
                # 保存资金统计
                if hasattr(self.capital_pool, 'profit_pool'):
                    stats = {
                        'strategy': getattr(self.capital_pool, 'strategy', 'guding'),
                        'initial_capital': float(self.initial_capital),
                        'final_capital': float(self.capital_pool.trading_capital),
                        'trading_capital': float(self.capital_pool.trading_capital),
                        'profit_pool': float(getattr(self.capital_pool, 'profit_pool', 0)),
                        'total_return': float(getattr(self.capital_pool, 'profit_pool', 0) / self.initial_capital * 100) if self.initial_capital > 0 else 0,
                        'total_profit': float(self.results['total_profit']),
                        'total_loss': float(self.results['total_loss']),
                        'max_capital': float(getattr(self.capital_pool, 'max_capital', self.initial_capital)),
                        'max_drawdown': float(getattr(self.capital_pool, 'max_drawdown', 0)),
                        'withdrawal_count': getattr(self.capital_pool, 'withdrawal_count', 0),
                        'liquidation_count': getattr(self.capital_pool, 'liquidation_count', 0),
                        'total_trades': self.results['total_trades'],
                        'profit_trades': self.results['win_trades'],
                        'loss_trades': self.results['loss_trades'],
                        'win_rate': self.results['win_trades'] / self.results['total_trades'] * 100 if self.results['total_trades'] > 0 else 0,
                    }
                    self.db.save_statistics(self.session_id, stats)

                # 结束会话
                self.db.end_session(
                    session_id=self.session_id,
                    status='stopped',
                    final_capital=float(self.capital_pool.trading_capital)
                )
                logger.info(f"[数据库] 会话已结束: session_id={self.session_id}")

        except Exception as e:
            logger.error(f"[退出处理] 处理失败: {e}", exc_info=True)
    
    async def _place_entry_order(self, order: Any, is_supplement: bool = False,
                                   is_timeout_refresh: bool = False,
                                   old_order: Any = None,
                                   timeout_minutes: int = 0,
                                   current_price: Decimal = None) -> None:
        """下单入场单

        创建并提交一个限价买入订单。如果订单金额小于 Binance 最小要求（100 USDT），
        会自动调整数量以满足要求。

        参数:
            order: 订单对象，包含入场价、数量等信息
            is_supplement: 是否为补下订单（状态恢复时补下）
            is_timeout_refresh: 是否为超时重挂订单
            old_order: 原订单对象（超时重挂时使用）
            timeout_minutes: 超时时间（超时重挂时使用）
            current_price: 当前价格（超时重挂时使用）

        副作用:
            - 更新 order.order_id
            - 更新 order.quantity（可能被调整）
            - 更新 order.stake_amount
            - 保存状态到文件
            - 发送微信通知
        """
        # 暂停检查：如果已暂停且不是补下订单，跳过下单
        if self.paused and not is_supplement:
            logger.info(f"[下单] 已暂停，跳过新订单: level={order.level}")
            return

        symbol = self.config.get("symbol", "BTCUSDT")

        price = self._adjust_price(order.entry_price)
        quantity = self._adjust_quantity(order.quantity, price)

        # 下单请求日志
        logger.debug(f"[下单请求] symbol={symbol}, side=BUY, type=LIMIT, "
                     f"price={price:.2f}, quantity={quantity:.6f}")

        result = await self.client.place_order(
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            quantity=float(quantity),
            price=float(price)
        )

        if "orderId" in result:
            order.order_id = result["orderId"]
            order.quantity = quantity
            order.stake_amount = quantity * price

            # 下单成功日志
            logger.info(f"[下单成功] A{order.level}: orderId={order.order_id}, "
                        f"价格={price:.2f}, 数量={quantity:.6f}, 金额={order.stake_amount:.2f}")

            # === 设置创建时间 ===
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            order.created_at = now_str

            # === 设置首次创建时间（累计执行时间） ===
            if is_timeout_refresh and old_order and old_order.first_created_at:
                # 超时重挂：保留首次创建时间
                order.first_created_at = old_order.first_created_at
                logger.debug(f"[超时重挂] 保留首次创建时间: {order.first_created_at}")
            else:
                # 新订单：首次创建时间 = 当前时间
                order.first_created_at = now_str

            weight_pct = self.calculator.get_weight_percentage(order.level)
            
            if not is_supplement and not is_timeout_refresh:
                print(f"\n{'='*60}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 下单成功: A{order.level}")
                print(f"{'='*60}")
            
            if is_timeout_refresh:
                print(f"\n{'='*60}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏰ A1 超时重挂成功")
                print(f"{'='*60}")
                print(f"  层级: A{order.level} / {self.config.get('max_entries', 4)}")
                print(f"  入场价: {price:.{self.price_precision}f}")
                print(f"  数量: {order.quantity:.6f} BTC")
                print(f"  金额: {order.stake_amount:.2f} USDT")
                print(f"  止盈价: {order.take_profit_price:.2f}")
                print(f"  止损价: {order.stop_loss_price:.2f}")
                print(f"  订单ID: {order.order_id}")
                print(f"  原订单ID: {old_order.order_id if old_order else 'N/A'}")
                print(f"{'='*60}\n")
            else:
                print(f"  层级: A{order.level} / {self.config.get('max_entries', 4)}")
                print(f"  权重: {weight_pct:.2f}%")
                print(f"  入场价: {price:.{self.price_precision}f}")
                print(f"  数量: {order.quantity:.6f} BTC")
                print(f"  金额: {order.stake_amount:.2f} USDT")
                print(f"  止盈价: {order.take_profit_price:.2f}")
                print(f"  止损价: {order.stop_loss_price:.2f}")
                print(f"  订单ID: {order.order_id}")
                print(f"{'='*60}\n")
            
            if is_timeout_refresh:
                logger.info(f"A1 超时重挂成功: orderId={order.order_id}, oldOrderId={old_order.order_id if old_order else 'N/A'}")
                notify_first_entry_timeout_refresh(old_order, order, current_price, timeout_minutes, self.config, self.session_id, self.db)
            elif is_supplement:
                logger.info(f"入场单补下成功: A{order.level}, orderId={order.order_id}")
                notify_entry_order_supplement(order, self.config, self.session_id, self.db)
            else:
                logger.info(f"入场单下单成功: A{order.level}, orderId={order.order_id}")
                notify_entry_order(order, self.config, self.session_id, self.db)

            # === 保存订单到数据库 ===
            if self.session_id:
                self.db.save_order(self.session_id, order)
                logger.debug(f"[数据库] 保存订单: session_id={self.session_id}, level=A{order.level}, "
                             f"state={order.state}, orderId={order.order_id}")

            self._save_state()
        else:
            if is_timeout_refresh:
                error_msg = "超时重挂失败"
            elif is_supplement:
                error_msg = "补下失败"
            else:
                error_msg = "下单失败"
            logger.error(f"入场单{error_msg}: {result}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ {error_msg}: {result}")
    
    async def _place_exit_orders(self, order: Any, place_tp: bool = True, 
                                  place_sl: bool = True) -> None:
        """下止盈止损条件单
        
        为已成交的入场单创建止盈和止损条件单。
        
        参数:
            order: 已成交的订单对象
            place_tp: 是否下止盈单
            place_sl: 是否下止损单
        
        副作用:
            - 更新 order.tp_order_id
            - 更新 order.sl_order_id
            - 保存状态到文件
        """
        symbol = self.config.get("symbol", "BTCUSDT")

        quantity = self._adjust_quantity(order.quantity, order.entry_price)

        current_price = await self._get_current_price()
        logger.info(f"[止盈止损下单] A{order.level}: 数量={quantity:.6f}, "
                    f"止盈触发价={order.take_profit_price:.2f}, 止损触发价={order.stop_loss_price:.2f}")

        if place_tp:
            if current_price >= order.take_profit_price:
                logger.warning(f"[止盈止损] A{order.level} 当前价 {current_price:.2f} 已超过止盈价 {order.take_profit_price:.2f}，市价止盈")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ A{order.level} 当前价已超过止盈价，市价止盈")
                await self._market_close_order(order, "take_profit")
                return

            tp_trigger_price = self._adjust_price(order.take_profit_price)
            logger.debug(f"[止盈单请求] symbol={symbol}, type=TAKE_PROFIT_MARKET, "
                         f"triggerPrice={tp_trigger_price:.2f}, quantity={quantity:.6f}")
            tp_result = await self.client.place_algo_order(
                symbol=symbol,
                side="SELL",
                order_type="TAKE_PROFIT_MARKET",
                quantity=float(quantity),
                trigger_price=float(tp_trigger_price)
            )
            if "algoId" in tp_result:
                order.tp_order_id = tp_result["algoId"]
                logger.info(f"[止盈单] A{order.level} algoId={order.tp_order_id}")
            else:
                logger.warning(f"[止盈单] A{order.level} 下单失败: {tp_result}")

        if place_sl:
            if current_price <= order.stop_loss_price:
                logger.warning(f"[止盈止损] A{order.level} 当前价 {current_price:.2f} 已跌破止损价 {order.stop_loss_price:.2f}，市价止损")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ A{order.level} 当前价已跌破止损价，市价止损")
                await self._market_close_order(order, "stop_loss")
                return

            sl_trigger_price = self._adjust_price(order.stop_loss_price)
            logger.debug(f"[止损单请求] symbol={symbol}, type=STOP_MARKET, "
                         f"triggerPrice={sl_trigger_price:.2f}, quantity={quantity:.6f}")
            sl_result = await self.client.place_algo_order(
                symbol=symbol,
                side="SELL",
                order_type="STOP_MARKET",
                quantity=float(quantity),
                trigger_price=float(sl_trigger_price)
            )
            if "algoId" in sl_result:
                order.sl_order_id = sl_result["algoId"]
                logger.info(f"[止损单] A{order.level} algoId={order.sl_order_id}")
            else:
                logger.warning(f"[止损单] A{order.level} 下单失败: {sl_result}")
        
        self._save_state()
    
    async def _cancel_all_orders(self) -> List[Any]:
        cancelled_orders = []
        symbol = self.config.get("symbol", "BTCUSDT")

        if not self.chain_state:
            return cancelled_orders

        for order in self.chain_state.orders:
            if order.state == "pending" and order.order_id:
                try:
                    await self.client.cancel_order(symbol, order.order_id)
                    cancelled_orders.append(order)
                    logger.info(f"[取消订单] A{order.level} orderId={order.order_id}")
                except Exception as e:
                    error_msg = str(e)
                    if "-2011" in error_msg:
                        logger.info(f"[取消订单] A{order.level} 订单已不存在（可能已成交或取消）")
                    else:
                        logger.warning(f"[取消订单] 失败 A{order.level}: {e}")
        
        return cancelled_orders

    async def _sync_orders_from_exchange(self) -> Dict[str, Any]:
        """从交易所同步订单状态

        用于恢复交易时，检查暂停期间订单状态的变化。

        返回:
            同步结果统计
        """
        symbol = self.config.get("symbol", "BTCUSDT")
        sync_result = {
            'checked': 0,
            'updated': 0,
            'filled': 0,
            'closed': 0,
            'cancelled': 0,
        }

        if not self.chain_state:
            return sync_result

        for order in self.chain_state.orders:
            if not order.order_id:
                continue

            sync_result['checked'] += 1

            try:
                # 查询订单状态
                order_info = await self.client.get_order(symbol, order.order_id)
                status = order_info.get('status', '')

                # 检查入场订单状态
                if order.state == 'pending' and status == 'FILLED':
                    logger.info(f"[同步] A{order.level} 入场单已成交")
                    order.state = 'filled'
                    order.filled_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    sync_result['filled'] += 1
                    sync_result['updated'] += 1

                    # 需要下止盈止损单
                    await self._place_take_profit_and_stop_loss(order)
                    await self._update_capital_after_entry(order)

                elif order.state == 'pending' and status == 'CANCELED':
                    logger.info(f"[同步] A{order.level} 入场单已取消")
                    order.state = 'cancelled'
                    sync_result['cancelled'] += 1
                    sync_result['updated'] += 1

                # 检查止盈止损单状态（通过查询 algo 订单）
                if order.tp_order_id:
                    try:
                        algo_orders = await self.algo_handler.query_algo_order(symbol, order.tp_order_id)
                        if algo_orders and algo_orders.get('status') == 'FINISHED':
                            # 止盈单已触发
                            logger.info(f"[同步] A{order.level} 止盈单已触发")
                            if order.state == 'filled':
                                await self._process_order_closed(order, 'take_profit')
                                sync_result['closed'] += 1
                                sync_result['updated'] += 1
                    except Exception as e:
                        logger.warning(f"[同步] 查询止盈单失败: {e}")

                if order.sl_order_id:
                    try:
                        algo_orders = await self.algo_handler.query_algo_order(symbol, order.sl_order_id)
                        if algo_orders and algo_orders.get('status') == 'FINISHED':
                            # 止损单已触发
                            logger.info(f"[同步] A{order.level} 止损单已触发")
                            if order.state == 'filled':
                                await self._process_order_closed(order, 'stop_loss')
                                sync_result['closed'] += 1
                                sync_result['updated'] += 1
                    except Exception as e:
                        logger.warning(f"[同步] 查询止损单失败: {e}")

            except Exception as e:
                logger.warning(f"[同步] 查询订单 {order.order_id} 失败: {e}")

        # 保存同步后的状态
        if sync_result['updated'] > 0:
            self._save_state()

        return sync_result

    async def _sync_capital_from_exchange(self) -> Dict[str, Any]:
        """从交易所同步资金池状态

        用于恢复交易时，检查暂停期间的资金变化。

        返回:
            同步结果
        """
        symbol = self.config.get("symbol", "BTCUSDT")
        sync_result = {
            'balance_checked': False,
            'position_checked': False,
        }

        try:
            # 查询账户余额
            balance = await self.client.get_balance()
            if balance:
                sync_result['balance_checked'] = True
                sync_result['available_balance'] = balance
                logger.info(f"[同步] 可用余额: {balance}")

            # 查询持仓
            positions = await self.client.get_positions(symbol)
            if positions:
                sync_result['position_checked'] = True
                pos = positions[0]
                position_qty = Decimal(pos.get("positionAmt", "0"))
                if position_qty != 0:
                    sync_result['position_qty'] = str(position_qty)
                    sync_result['unrealized_pnl'] = pos.get("unRealizedProfit", "0")
                    logger.info(f"[同步] 持仓: {position_qty}, 未实现盈亏: {pos.get('unRealizedProfit', '0')}")

        except Exception as e:
            logger.warning(f"[同步资金] 失败: {e}")

        return sync_result

    async def resume_from_pause(self) -> Dict[str, Any]:
        """从暂停状态恢复

        执行以下步骤：
        1. 同步交易所订单状态
        2. 同步资金池状态
        3. 恢复交易

        返回:
            恢复结果
        """
        logger.info("[恢复] 开始从暂停状态恢复")

        result = {
            'success': True,
            'order_sync': None,
            'capital_sync': None,
        }

        try:
            # 1. 同步订单状态
            result['order_sync'] = await self._sync_orders_from_exchange()

            # 2. 同步资金状态
            result['capital_sync'] = await self._sync_capital_from_exchange()

            # 3. 恢复交易
            async with self._pause_lock:
                self.paused = False

            logger.info("[恢复] 已恢复正常交易")

        except Exception as e:
            result['success'] = False
            result['error'] = str(e)
            logger.error(f"[恢复] 恢复失败: {e}", exc_info=True)

        return result
    
    async def _get_current_price(self) -> Decimal:
        symbol = self.config.get("symbol", "BTCUSDT")
        return await self.client.get_current_price(symbol)
    
    async def _get_pnl_info(self) -> Optional[Dict[str, Any]]:
        try:
            symbol = self.config.get("symbol", "BTCUSDT")
            positions = await self.client.get_positions(symbol)
            if positions:
                pos = positions[0]
                position_qty = Decimal(pos.get("positionAmt", "0"))
                entry_price = Decimal(pos.get("entryPrice", "0"))
                unrealized_pnl = Decimal(pos.get("unRealizedProfit", "0"))
                
                roi = None
                if entry_price > 0 and position_qty != 0:
                    roi = float(unrealized_pnl / (entry_price * abs(position_qty)) * 100)
                
                return {
                    "position_qty": str(position_qty),
                    "entry_price": f"{entry_price:.2f}",
                    "unrealized_pnl": f"{unrealized_pnl:.2f}",
                    "roi": f"{roi:.2f}" if roi is not None else None,
                    "realized_pnl": "N/A"
                }
        except Exception as e:
            logger.warning(f"[获取盈亏信息] 失败: {e}")
        
        return None
    
    async def _restore_orders(self, current_price: Decimal) -> bool:
        """恢复订单状态

        程序重启后从数据库恢复状态，并与 Binance 同步。

        主要流程：
        1. 从数据库加载 session 状态（base_price, group_id, 统计数据）
        2. 从数据库加载资金池状态（live_capital_statistics）
        3. 从数据库加载订单（live_orders）
        4. 查询 Binance 订单状态，同步本地状态
        5. 检查止盈止损单是否存在，补充缺失的止盈止损单

        参数:
            current_price: 当前价格

        返回:
            bool: 是否需要创建新订单（如果没有恢复到任何订单）

        副作用:
            - 更新 self.chain_state
            - 更新 self.capital_pool
            - 更新 self.results
        """
        symbol = self.config.get("symbol", "BTCUSDT")
        need_new_order = True

        # === 1. 从 live_sessions 加载 session 状态 ===
        session_data = None
        if self.session_id:
            session_data = self.db.get_session(self.session_id)
            if session_data:
                # 恢复统计结果
                self.results['total_trades'] = session_data.get('total_trades', 0)
                self.results['win_trades'] = session_data.get('win_trades', 0)
                self.results['loss_trades'] = session_data.get('loss_trades', 0)
                self.results['total_profit'] = Decimal(str(session_data.get('total_profit', 0)))
                self.results['total_loss'] = Decimal(str(session_data.get('total_loss', 0)))
                logger.info(f"[session恢复] total_trades={self.results['total_trades']}")

        # === 2. 从 live_capital_statistics 加载资金池状态 ===
        if self.session_id:
            stats = self.db.get_statistics(self.session_id)
            if stats:
                self.capital_pool.trading_capital = Decimal(str(stats.get('trading_capital', self.initial_capital)))
                if hasattr(self.capital_pool, 'profit_pool'):
                    self.capital_pool.profit_pool = Decimal(str(stats.get('profit_pool', 0)))
                if hasattr(self.capital_pool, 'total_profit'):
                    self.capital_pool.total_profit = Decimal(str(stats.get('total_profit', 0)))
                if hasattr(self.capital_pool, 'total_loss'):
                    self.capital_pool.total_loss = Decimal(str(stats.get('total_loss', 0)))
                if hasattr(self.capital_pool, 'withdrawal_count'):
                    self.capital_pool.withdrawal_count = stats.get('withdrawal_count', 0)
                if hasattr(self.capital_pool, 'liquidation_count'):
                    self.capital_pool.liquidation_count = stats.get('liquidation_count', 0)
                logger.info(f"[资金池恢复] trading_capital={self.capital_pool.trading_capital}")

        # === 3. 从数据库加载订单（单一数据源）===
        from autofish_core import Autofish_Order, Autofish_ChainState
        db_orders = self.db.get_orders(self.session_id) if self.session_id else []
        orders = []

        if db_orders:
            for row in db_orders:
                # 只恢复未关闭的订单
                if row['state'] in ('closed', 'cancelled'):
                    continue

                order = Autofish_Order(
                    level=row['level'],
                    entry_price=Decimal(str(row['entry_price'])),
                    quantity=Decimal(str(row['quantity'])),
                    stake_amount=Decimal(str(row['stake_amount'])),
                    take_profit_price=Decimal(str(row['take_profit_price'])),
                    stop_loss_price=Decimal(str(row['stop_loss_price'])),
                    state=row['state'],
                    order_id=row['order_id'] if row['order_id'] else None,
                    tp_order_id=row['tp_order_id'] if row['tp_order_id'] else None,
                    sl_order_id=row['sl_order_id'] if row['sl_order_id'] else None,
                    group_id=row['group_id'] if row['group_id'] else 0,
                    created_at=row['created_at'],
                    filled_at=row['filled_at'],
                )
                orders.append(order)

            logger.info(f"[数据库恢复] 从 live_orders 表恢复 {len(orders)} 个订单")
            print(f"\n🔄 从数据库恢复 {len(orders)} 个订单")

        # === 4. 创建 chain_state，使用数据库中的 base_price 和 group_id ===
        base_price = current_price
        group_id = 0
        if session_data:
            if session_data.get('base_price'):
                base_price = Decimal(str(session_data['base_price']))
                logger.info(f"[base_price恢复] base_price={base_price}")
            if session_data.get('group_id'):
                group_id = session_data['group_id']
                logger.info(f"[group_id恢复] group_id={group_id}")

        self.chain_state = Autofish_ChainState(base_price=base_price, orders=orders)
        self.chain_state.group_id = group_id

        if orders:
            algo_orders = await self.client.get_open_algo_orders(symbol)
            algo_ids = {o.get("algoId") for o in algo_orders if o.get("algoId")}
            logger.info(f"[状态恢复] Binance 上有 {len(algo_ids)} 个 Algo 条件单")

            positions = await self.client.get_positions(symbol)
            has_position = any(
                Decimal(p.get('positionAmt', '0')) != Decimal('0')
                for p in positions
            )
            logger.info(f"[状态恢复] 当前仓位状态: {'有仓位' if has_position else '无仓位'}")

            algo_history = await self.client.get_all_algo_orders(symbol, limit=100)
            algo_status_map = {algo.get('algoId'): algo for algo in algo_history if algo.get('algoId')}
            logger.info(f"[状态恢复] 获取到 {len(algo_status_map)} 个历史 Algo 条件单")

            orders_to_remove = []
            algo_ids_to_cancel = []
            orders_need_process = []

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
                        binance_order = await self.client.get_order_status(symbol, order.order_id)
                        binance_status = binance_order.get("status")
                        binance_avg_price = binance_order.get("avgPrice", "0")
                        binance_qty = binance_order.get("executedQty", "0")
                        binance_side = binance_order.get("side", "")
                        binance_type = binance_order.get("type", "")

                        logger.info(f"  Binance 订单查询: orderId={order.order_id}, status={binance_status}, "
                                   f"side={binance_side}, type={binance_type}, avgPrice={binance_avg_price}, "
                                   f"executedQty={binance_qty}")
                        print(f"   📋 Binance: orderId={order.order_id}, status={binance_status}, "
                              f"avgPrice={binance_avg_price}, qty={binance_qty}")

                        if binance_status == "FILLED":
                            filled_price = Decimal(str(binance_order.get("avgPrice", order.entry_price)))
                            order.entry_price = filled_price
                            orders_need_process.append((order, filled_price))
                            logger.info(f"[状态同步] A{order.level} 已在 Binance 成交，记录待处理")
                            print(f"   ⚡ A{order.level} 已在 Binance 成交，待处理")
                        elif binance_status in ["CANCELED", "EXPIRED"]:
                            if order.tp_order_id:
                                algo_ids_to_cancel.append(order.tp_order_id)
                            if order.sl_order_id:
                                algo_ids_to_cancel.append(order.sl_order_id)
                            orders_to_remove.append(order)
                            logger.info(f"[状态同步] A{order.level} 在 Binance 已取消，将删除本地订单")
                            print(f"   🗑️ A{order.level} 在 Binance 已取消，将删除")
                        elif binance_status in ["NEW", "PARTIALLY_FILLED"]:
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
                            logger.error(f"[状态同步] 查询 Binance 订单状态失败: {e}", exc_info=True)

                elif order.state == "pending" and not order.order_id:
                    if has_position:
                        order.state = "filled"
                        logger.info(f"[状态同步] A{order.level} 无 order_id 但有仓位，标记为已成交")
                        print(f"   ⚡ A{order.level} 无 order_id 但有仓位，标记为已成交")
                    else:
                        orders_to_remove.append(order)
                        logger.info(f"[状态同步] A{order.level} 无 order_id 且无仓位，删除本地订单")
                        print(f"   🗑️ A{order.level} 无 order_id 且无仓位，删除本地订单")

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
                            order.state = "closed"
                            order.close_reason = close_reason
                            orders_to_remove.append(order)
                            print(f"   ✅ A{order.level} 已平仓，原因: {close_reason}，删除本地订单")

                if order not in orders_to_remove:
                    print(f"   A{order.level}: state={order.state}, order_id={order.order_id}, "
                          f"tp_id={order.tp_order_id}, sl_id={order.sl_order_id}")

            for algo_id in algo_ids_to_cancel:
                if algo_id in algo_ids:
                    try:
                        await self.client.cancel_algo_order(symbol, algo_id)
                        logger.info(f"[取消残留条件单] algoId={algo_id}")
                    except Exception as e:
                        logger.warning(f"[取消残留条件单] 失败 algoId={algo_id}: {e}")

            for order in orders_to_remove:
                if order in self.chain_state.orders:
                    self.chain_state.orders.remove(order)
                    logger.info(f"[删除订单] A{order.level} (order_id={order.order_id}, state={order.state}) 已从本地删除")

            # 注释：移除层级调整，保持原始层级
            # if self.chain_state.orders:
            #     self.chain_state.orders.sort(key=lambda o: o.level)
            #     for new_level, order in enumerate(self.chain_state.orders, start=1):
            #         old_level = order.level
            #         if old_level != new_level:
            #             order.level = new_level
            #             logger.info(f"[级别调整] A{old_level} -> A{new_level}")
            #             print(f"   📊 A{old_level} 级别调整为 A{new_level}")

            self._save_state()

            for order, filled_price in orders_need_process:
                await self._process_order_filled(order, filled_price, is_recovery=True)

            if self.chain_state.orders and self._is_first_connection:
                pnl_info = await self._get_pnl_info()
                notify_orders_recovered(self.chain_state.orders, self.config, current_price, pnl_info or {}, self.session_id, self.db)
                self._is_first_connection = False

            has_active_order = any(o.state in ["pending", "filled"] for o in self.chain_state.orders)
            if has_active_order:
                need_new_order = False
        else:
            from autofish_core import Autofish_ChainState
            self.chain_state = Autofish_ChainState(base_price=current_price, orders=[])

        return need_new_order
    
    async def _check_and_supplement_orders(self) -> None:
        """检查并补充缺失的止盈止损单
        
        遍历所有已成交订单，检查止盈止损单是否存在：
        - 如果止盈单缺失，补充下止盈单
        - 如果止损单缺失，补充下止损单
        - 如果当前价已超过止盈/止损价，执行市价平仓
        
        副作用:
            - 更新 order.tp_order_id
            - 更新 order.sl_order_id
            - 保存状态到文件
        """
        symbol = self.config.get("symbol", "BTCUSDT")
        algo_orders = await self.client.get_open_algo_orders(symbol)
        logger.info(f"[补单检查] 获取到 {len(algo_orders)} 个 Algo 条件单")
        
        current_price = await self._get_current_price()
        
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
    
    async def _place_tp_order(self, order: Any) -> None:
        symbol = self.config.get("symbol", "BTCUSDT")
        
        quantity = self._adjust_quantity(order.quantity, order.take_profit_price)
        trigger_price = self._adjust_price(order.take_profit_price)
        
        tp_result = await self.client.place_algo_order(
            symbol=symbol,
            side="SELL",
            order_type="TAKE_PROFIT_MARKET",
            quantity=float(quantity),
            trigger_price=float(trigger_price)
        )
        if "algoId" in tp_result:
            order.tp_order_id = tp_result["algoId"]
            order.tp_supplemented = True
            logger.info(f"[止盈下单] 成功: algoId={order.tp_order_id}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 止盈条件单已下（补）: 触发价={trigger_price:.{self.price_precision}f}, ID={order.tp_order_id}")
            # 记录补单
            self._record_supplement()
            self._save_state()
    
    async def _place_sl_order(self, order: Any) -> None:
        symbol = self.config.get("symbol", "BTCUSDT")

        quantity = self._adjust_quantity(order.quantity, order.stop_loss_price)
        trigger_price = self._adjust_price(order.stop_loss_price)

        sl_result = await self.client.place_algo_order(
            symbol=symbol,
            side="SELL",
            order_type="STOP_MARKET",
            quantity=float(quantity),
            trigger_price=float(trigger_price)
        )
        if "algoId" in sl_result:
            order.sl_order_id = sl_result["algoId"]
            order.sl_supplemented = True
            logger.info(f"[止损下单] 成功: algoId={order.sl_order_id}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 止损条件单已下（补）: 触发价={trigger_price:.{self.price_precision}f}, ID={order.sl_order_id}")
            # 记录补单
            self._record_supplement()
            self._save_state()
    
    async def _market_close_order(self, order: Any, reason: str) -> None:
        symbol = self.config.get("symbol", "BTCUSDT")
        
        try:
            quantity = self._adjust_quantity(order.quantity, order.entry_price)
            
            result = await self.client.place_order(
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                quantity=float(quantity)
            )
            
            filled_price = Decimal(str(result.get("avgPrice", order.entry_price)))
            order.state = "closed"
            order.close_reason = reason
            order.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            order.close_price = filled_price
            
            if reason == "take_profit":
                profit = (filled_price - order.entry_price) * order.quantity
            else:
                profit = (filled_price - order.entry_price) * order.quantity
            order.profit = profit
            
            logger.info(f"[市价平仓] A{order.level} 成功: orderId={result.get('orderId')}, 成交价={filled_price:.2f}, 盈亏={profit:.2f}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 A{order.level} 市价平仓成功, 成交价={filled_price:.2f}")
            
            if reason == "take_profit":
                notify_take_profit(order, profit, self.config, self.session_id, self.db)
            else:
                notify_stop_loss(order, profit, self.config, self.session_id, self.db)
            
            await self._cancel_next_level_and_restart(order)
            
            self._adjust_order_levels()
            
            self._save_state()
            
        except Exception as e:
            logger.error(f"[市价平仓] A{order.level} 失败: {e}", exc_info=True)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ A{order.level} 市价平仓失败: {e}")
    
    async def _handle_entry_supplement(self, current_price: Decimal, need_new_order: bool) -> None:
        """处理入场单补充逻辑
        
        参数:
            current_price: 当前价格
            need_new_order: 是否需要新订单
        """
        klines = await self._get_recent_klines()
        
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
                    new_order = await self._create_order(next_level, current_price, klines)
                    self.chain_state.orders.append(new_order)
                    print(f"\n{'='*60}")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📥 入场单补下: A{next_level}")
                    print(f"{'='*60}")
                    await self._place_entry_order(new_order, is_supplement=True)
        
        if need_new_order:
            # 暂停检查：不启动新轮次
            if self.paused:
                logger.info("[交易] 已暂停，不启动新轮次")
                return

            from autofish_core import Autofish_ChainState
            order = await self._create_order(1, current_price, klines)
            self.chain_state = Autofish_ChainState(base_price=current_price, orders=[order])
            await self._place_entry_order(order)
    
    async def _check_and_handle_first_entry_timeout(self, current_price: Decimal) -> None:
        """检查并处理第一笔入场订单超时
        
        参数:
            current_price: 当前价格
        """
        if self.a1_timeout_minutes <= 0:
            return
        
        now = datetime.now()
        
        if self.last_first_entry_check_time:
            if (now - self.last_first_entry_check_time).total_seconds() < 300:
                return
        
        self.last_first_entry_check_time = now
        
        if not self.chain_state:
            return
        
        timeout_first_entry = self.chain_state.check_first_entry_timeout(now, self.a1_timeout_minutes)
        if not timeout_first_entry:
            return
        
        logger.info(f"[A1 超时] A1 挂单已超过 {self.a1_timeout_minutes} 分钟未成交")
        print(f"\n{'='*60}")
        print(f"[{now.strftime('%H:%M:%S')}] ⏰ A1 超时检查")
        print(f"{'='*60}")

        symbol = self.config.get("symbol", "BTCUSDT")

        # === 评估是否应该重挂 ===
        klines = await self._get_recent_klines()
        new_first_entry = await self._create_order(1, current_price, klines)

        should_refresh, reason = self._should_refresh_order(
            timeout_first_entry,
            new_first_entry.entry_price
        )

        print(f"   旧入场价: {timeout_first_entry.entry_price:.2f}")
        print(f"   新入场价: {new_first_entry.entry_price:.2f}")
        print(f"   价格差异: {(new_first_entry.entry_price - timeout_first_entry.entry_price) / timeout_first_entry.entry_price:.3%}")
        print(f"   阈值: {self.min_refresh_price_diff:.3%}")

        if not should_refresh:
            logger.info(f"[A1 超时] 跳过重挂: {reason}")
            print(f"   ⏭️ 跳过重挂: {reason}")
            print(f"   继续等待原订单成交...")

            # 重置计时器，继续等待
            timeout_first_entry.created_at = now
            self._record_skipped_refresh()
            return

        print(f"   ✅ {reason}")
        print(f"   开始重挂流程...")

        cancel_success = True
        if timeout_first_entry.order_id:
            try:
                await self.client.cancel_order(symbol, timeout_first_entry.order_id)
                logger.info(f"[取消 A1] orderId={timeout_first_entry.order_id}")
                print(f"   ✅ 已取消原 A1 订单: {timeout_first_entry.order_id}")
            except Exception as e:
                logger.warning(f"[取消 A1] 失败: {e}")
                print(f"   ⚠️ 取消原 A1 失败: {e}")
                cancel_success = False
                
                try:
                    order_info = await self.client.get_order_status(symbol, timeout_first_entry.order_id)
                    order_status = order_info.get("status", "")
                    logger.info(f"[A1 状态检查] orderId={timeout_first_entry.order_id}, status={order_status}")
                    
                    if order_status == "FILLED":
                        logger.info(f"[A1 已成交] 取消失败原因是订单已成交，执行成交处理")
                        filled_price = Decimal(str(order_info.get("avgPrice", timeout_first_entry.entry_price)))
                        await self._process_order_filled(timeout_first_entry, filled_price)
                        return
                except Exception as check_error:
                    logger.warning(f"[A1 状态检查] 查询订单状态失败: {check_error}")
        
        if not cancel_success:
            logger.warning("[A1 超时] 取消订单失败且无法确认状态，跳过重挂")
            return
        
        if timeout_first_entry.tp_order_id:
            try:
                await self.client.cancel_algo_order(symbol, timeout_first_entry.tp_order_id)
            except:
                pass
        if timeout_first_entry.sl_order_id:
            try:
                await self.client.cancel_algo_order(symbol, timeout_first_entry.sl_order_id)
            except:
                pass
        
        self.chain_state.orders.remove(timeout_first_entry)

        # 删除数据库中的订单记录
        if self.session_id:
            order_ids_to_delete = []
            if timeout_first_entry.order_id:
                order_ids_to_delete.append(timeout_first_entry.order_id)
            # 注意：止盈止损单的 algoId 不存储在 live_orders 表中
            # 它们存储在 order 记录的 tp_order_id/sl_order_id 字段中
            if order_ids_to_delete:
                self.db.delete_orders_by_ids(self.session_id, order_ids_to_delete)
                logger.info(f"[超时清理] 已删除数据库订单记录: order_ids={order_ids_to_delete}")

        # === 传递超时次数（累加） ===
        # new_first_entry 已在评估阶段创建
        new_first_entry.timeout_count = timeout_first_entry.timeout_count + 1
        new_first_entry.first_created_at = timeout_first_entry.first_created_at

        self.chain_state.orders.append(new_first_entry)
        self.chain_state.base_price = current_price

        logger.info(f"[新 A1] 入场价={new_first_entry.entry_price:.2f}, 超时次数={new_first_entry.timeout_count}")
        
        await self._place_entry_order(
            new_first_entry,
            is_supplement=False,
            is_timeout_refresh=True,
            old_order=timeout_first_entry,
            timeout_minutes=self.a1_timeout_minutes,
            current_price=current_price
        )

        # 记录超时重挂
        self._record_timeout_refresh()

        self._save_state()
    
    async def run(self) -> None:
        from autofish_core import Autofish_ChainState

        self._setup_signal_handlers()

        print(f"\n{'='*60}")
        print(f"🚀 Autofish V2 启动")
        print(f"{'='*60}")
        print(f"  交易对: {self.config.get('symbol', 'BTCUSDT')}")
        print(f"  测试网: {self.testnet}")
        print(f"  总投入: {self.config.get('total_amount_quote', 1200)} USDT")
        print(f"  最大层级: {self.config.get('max_entries', 4)}")
        print(f"  止盈比例: {self.config.get('take_profit_pct', 0.01) * 100}%")
        print(f"  止损比例: {self.config.get('stop_loss_pct', 0.08) * 100}%")
        print(f"  衰减因子: {self.config.get('decay_factor', 0.5)}")
        print(f"  A1 超时: {self.a1_timeout_minutes} 分钟")
        if self.a1_timeout_minutes > 0:
            print(f"    最小重挂差异: {self.min_refresh_price_diff:.2%}")
            print(f"    最大超时次数: {self.max_timeout_count if self.max_timeout_count > 0 else '不限制'}")
        print(f"  行情感知: {'启用' if self.market_aware else '禁用'}")
        print(f"  日志文件: {LOG_DIR}/{LOG_FILE}")
        print(f"{'='*60}\n")

        logger.info("[启动] Autofish V2 启动")
        logger.info(f"[启动] 交易对: {self.config.get('symbol')}, 测试网: {self.testnet}")
        if not self._proxy_logged:
            logger.info(f"[启动] 代理配置: {self.proxy if self.proxy else '未配置'}")
            self._proxy_logged = True

        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        self._startup_notified = False
        self._is_first_connection = True  # 区分首次启动和重连，避免重连时重复发送订单同步通知

        # === 创建数据库会话 ===
        # 如果没有 case_id，自动创建一个 case 记录
        if self.case_id is None:
            from database.live_trading_db import LiveCase

            # Decimal 序列化处理
            def json_default(obj):
                if isinstance(obj, Decimal):
                    return float(obj)
                raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

            case = LiveCase(
                name=f"{self.symbol}-自动创建",
                symbol=self.symbol,
                testnet=1 if self.testnet else 0,
                amplitude=json.dumps(self.amplitude, default=json_default),
                market=json.dumps(self.market, default=json_default),
                entry=json.dumps(self.entry, default=json_default),
                timeout=json.dumps(self.timeout, default=json_default),
                capital=json.dumps(self.capital, default=json_default),
                status='active'
            )
            self.case_id = self.db.create_case(case)
            if not self.case_id:
                logger.error("[数据库] 自动创建配置失败")
                return
            logger.info(f"[数据库] 自动创建配置: case_id={self.case_id}")

        # === 创建/恢复数据库会话 ===
        if self.recover_session_id:
            # 恢复模式：使用现有 session_id
            self.session_id = self.recover_session_id
            logger.info(f"[恢复模式] 绑定到现有 session_id={self.session_id}")
            print(f"[恢复] session_id={self.session_id} (恢复模式)")
        else:
            # 正常模式：创建新会话
            self.session_id = self.db.create_session_legacy(
                symbol=self.config.get('symbol', 'BTCUSDT'),
                initial_capital=float(self.initial_capital),
                config=self.config,
                case_id=self.case_id
            )
            if not self.session_id:
                logger.error("[数据库] 创建会话失败")
                return
            logger.info(f"[数据库] 创建会话: session_id={self.session_id}, case_id={self.case_id}")
            print(f"[启动] session_id={self.session_id}, case_id={self.case_id}")

        # === 状态仓库已废弃 ===
        # 不再使用 live_state_snapshots 快照表，状态通过专用表管理
        # self.state_repository = DbStateRepository(self.db, self.session_id)

        # === 创建 market_case（如果启用行情感知）===
        if self.market_aware:
            self.market_case_id = self.db.create_market_case(
                session_id=self.session_id,
                symbol=self.symbol,
                algorithm=self.market_algorithm,
                algorithm_config=self.market_algorithm_params,
                check_interval=0  # 事件驱动模式，不再需要 check_interval
            )
            logger.info(f"[数据库] 创建 market_case: case_id={self.market_case_id}")

        # === 初始化统计指标 ===
        self._metrics['start_time'] = datetime.now()

        try:
            while self.running:
                try:
                    logger.info("[启动] 开始初始化精度...")
                    await self._init_precision()
                    logger.info("[启动] 精度初始化完成")

                    logger.info("[启动] 开始初始化行情检测器...")
                    await self._init_market_detector()
                    logger.info("[启动] 行情检测器初始化完成")

                    logger.info("[启动] 获取当前价格...")
                    current_price = await self._get_current_price()
                    logger.info(f"[启动] 当前价格: {current_price}")

                    if not self._startup_notified:
                        logger.info(f"[通知] 准备发送启动通知: session_id={self.session_id}")
                        try:
                            notify_startup(self.config, current_price, self.session_id, self.db)
                            logger.info("[通知] 启动通知发送完成")
                            self._startup_notified = True
                        except Exception as e:
                            logger.error(f"[通知] 启动通知发送失败: {e}", exc_info=True)

                        # 初始化行情轨道（从历史日线计算）
                        if self.market_aware and self.market_detector:
                            try:
                                await self._initialize_market_bands()
                                print(f"  初始行情: {self.current_market_status.value}")
                            except Exception as e:
                                logger.error(f"[行情] 初始化轨道失败: {e}", exc_info=True)
                    
                    if not await self._check_fund_sufficiency():
                        await self.client.close()
                        return
                    
                    listen_key = await self.client.create_listen_key()

                    # 构建组合流 URL（K线 + 用户数据）
                    if self.market_aware:
                        kline_interval = self.market_detector.algorithm.get_kline_interval() if self.market_detector else '1d'
                        symbol_lower = self.symbol.lower()
                        streams = f"{symbol_lower}@kline_{kline_interval}/{listen_key}"
                        ws_url = f"{self.client.ws_url}/stream?streams={streams}"
                        logger.info(f"[WebSocket] 订阅组合流: {streams}")
                    else:
                        ws_url = f"{self.client.ws_url}/{listen_key}"
                    
                    session = await self.client._get_session()
                    
                    ws_kwargs = {}
                    if self.client.proxy:
                        ws_kwargs["proxy"] = self.client.proxy
                    
                    async with session.ws_connect(ws_url, **ws_kwargs) as ws:
                        self.ws = ws
                        self.ws_connected = True
                        
                        logger.info("[WebSocket] 连接成功")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔗 WebSocket 连接成功")
                        
                        need_new_order = await self._restore_orders(current_price)
                        
                        await self._handle_entry_supplement(current_price, need_new_order)
                        
                        self.consecutive_errors = 0
                        
                        keepalive_task = asyncio.create_task(self._keepalive_loop())
                        
                        try:
                            while self.running:
                                try:
                                    msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
                                    
                                    if msg.type == aiohttp.WSMsgType.TEXT:
                                        data = json.loads(msg.data)
                                        await self._handle_ws_message(data)
                                    elif msg.type == aiohttp.WSMsgType.ERROR:
                                        logger.error(f"[WebSocket] 错误: {ws.exception()}")
                                        break
                                    elif msg.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING]:
                                        logger.info("[WebSocket] 连接关闭")
                                        break
                                except asyncio.TimeoutError:
                                    current_price = await self._get_current_price()
                                    await self._check_and_handle_first_entry_timeout(current_price)

                                    continue
                        finally:
                            keepalive_task.cancel()
                            self.ws_connected = False
                        
                        if not self.running:
                            await self._handle_exit("用户停止")
                            break
                        
                except KeyboardInterrupt:
                    logger.info("[运行] 收到 KeyboardInterrupt")
                    await self._handle_exit("用户中断 (Ctrl+C)")
                    break
                except asyncio.CancelledError:
                    logger.info("[运行] 收到 CancelledError")
                    await self._handle_exit("任务取消")
                    break
                except Exception as e:
                    self.consecutive_errors += 1
                    logger.error(f"[运行] 发生异常 ({self.consecutive_errors}/{self.max_consecutive_errors}): {e}", exc_info=True)
                    
                    if self.consecutive_errors >= self.max_consecutive_errors:
                        logger.error(f"[运行] 连续错误 {self.consecutive_errors} 次，退出")
                        await self._handle_exit(f"连续错误 {self.consecutive_errors} 次: {e}")
                        break
                    else:
                        notify_critical_error(str(e), self.config, self.session_id, self.db)
                        print(f"\n{'='*60}")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ 发生异常，等待重试...")
                        print(f"  错误: {e}")
                        print(f"  连续错误: {self.consecutive_errors}/{self.max_consecutive_errors}")
                        print(f"{'='*60}\n")
                        await asyncio.sleep(10)
        finally:
            await self.client.close()
    
    async def _ws_loop(self) -> None:
        """WebSocket 主循环
        
        建立 WebSocket 连接，监听用户数据流事件：
        - ORDER_TRADE_UPDATE: 订单状态变化
        - listenKeyExpired: listen key 过期
        
        支持自动重连，最多重连 10 次。
        
        副作用:
            - 更新订单状态
            - 触发止盈止损处理
            - 发送通知
        """
        max_reconnect_attempts = 10
        reconnect_attempts = 0
        
        while self.running and reconnect_attempts < max_reconnect_attempts:
            try:
                listen_key = await self.client.create_listen_key()
                ws_url = f"{self.client.ws_url}/{listen_key}"
                
                session = await self.client._get_session()
                
                ws_kwargs = {}
                if self.client.proxy:
                    ws_kwargs["proxy"] = self.client.proxy
                
                async with session.ws_connect(ws_url, **ws_kwargs) as ws:
                    self.ws = ws
                    self.ws_connected = True
                    reconnect_attempts = 0
                    
                    logger.info("[WebSocket] 连接成功")
                    
                    keepalive_task = asyncio.create_task(self._keepalive_loop())
                    
                    try:
                        while self.running:
                            try:
                                msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
                                
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(msg.data)
                                    await self._handle_ws_message(data)
                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    logger.error(f"[WebSocket] 错误: {ws.exception()}")
                                    break
                                elif msg.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING]:
                                    logger.info("[WebSocket] 连接关闭")
                                    break
                            except asyncio.TimeoutError:
                                continue
                    finally:
                        keepalive_task.cancel()
                        self.ws_connected = False
            
            except Exception as e:
                self.ws_connected = False
                reconnect_attempts += 1
                logger.error(f"[WebSocket] 连接错误: {e}", exc_info=True)
                
                if reconnect_attempts < max_reconnect_attempts:
                    await asyncio.sleep(5)
    
    async def _keepalive_loop(self) -> None:
        while self.running and self.ws_connected:
            try:
                await asyncio.sleep(30 * 60)
                await self.client.keepalive_listen_key()
                logger.info("[WebSocket] listen key 已续期")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[WebSocket] 续期失败: {e}")
    
    async def _handle_ws_message(self, data: Dict[str, Any]) -> None:
        """处理 WebSocket 消息

        支持组合流格式：
        - K线事件: {"stream": "btcusdt@kline_1d", "data": {...}}
        - 用户数据: {"stream": "<listenKey>", "data": {...}} 或原格式

        根据事件类型分发处理：
        - kline: K线更新事件
        - ORDER_TRADE_UPDATE: 普通订单状态变化
        - ALGO_UPDATE: ALGO 条件单（止盈止损）状态变化
        - listenKeyExpired: listen key 过期

        参数:
            data: WebSocket 消息数据
        """
        # 类型检查：确保 data 是字典
        if not isinstance(data, dict):
            logger.warning(f"[WebSocket] 收到非字典消息: {type(data)}, 内容: {data}")
            return

        # 检查是否是组合流格式
        stream = data.get('stream', '')
        if stream and 'data' in data:
            # 组合流格式
            if 'kline' in stream:
                # K线事件
                await self._handle_kline_event(data['data'])
                return
            else:
                # 用户数据事件，提取实际数据
                data = data['data']

        event_type = data.get("e")

        # 打印收到的消息类型和内容（调试用）
        logger.debug(f"[WebSocket] 收到消息: event_type={event_type}, data={data}")

        # 如果没有事件类型，可能是其他消息，忽略
        if not event_type:
            logger.debug(f"[WebSocket] 收到无事件类型消息: {data}")
            return

        if event_type == "ORDER_TRADE_UPDATE":
            order_data = data.get("o", {})
            # 详细调试日志
            logger.debug(f"[WebSocket] ORDER_TRADE_UPDATE: orderId={order_data.get('i')}, "
                         f"status={order_data.get('X')}, executedQty={order_data.get('z')}, "
                         f"avgPrice={order_data.get('ap')}, symbol={order_data.get('s')}")
            logger.info(f"[WebSocket] ORDER_TRADE_UPDATE: {order_data}")
            if not isinstance(order_data, dict):
                logger.warning(f"[WebSocket] ORDER_TRADE_UPDATE order_data 不是字典: {type(order_data)}, 内容: {order_data}")
                return
            await self._handle_order_update(order_data)

        elif event_type == "ALGO_UPDATE":
            # 详细调试日志
            logger.debug(f"[WebSocket] ALGO_UPDATE: algoId={data.get('algoId')}, "
                         f"status={data.get('algoStatus')}, type={data.get('orderType')}, "
                         f"symbol={data.get('symbol')}")
            logger.info(f"[WebSocket] ALGO_UPDATE: {data}")
            await self.algo_handler.handle_algo_update(data)

        elif event_type == "kline":
            # K线事件（可能是直接推送或组合流格式）
            await self._handle_kline_event(data)

        elif event_type == "listenKeyExpired":
            logger.warning("[WebSocket] listen key 过期")
            self.ws_connected = False

        else:
            logger.info(f"[WebSocket] 未处理的事件类型: {event_type}, data={data}")

    async def _handle_kline_event(self, kline_data: Dict[str, Any]) -> None:
        """处理 K线事件

        Binance K线事件格式:
        {
            "e": "kline",
            "k": {
                "t": 1672531200000,  // K线开始时间
                "T": 1672617599999,  // K线结束时间
                "s": "BTCUSDT",      // 交易对
                "i": "1d",           // 周期
                "o": "16800.0",      // 开盘价
                "c": "16950.0",      // 收盘价（实时更新）
                "h": "17000.0",      // 最高价
                "l": "16750.0",      // 最低价
                "v": "1000.0",       // 成交量
                "x": false           // 是否已收盘
            }
        }

        参数:
            kline_data: K线事件数据
        """
        if not self.market_aware:
            return

        kline = kline_data.get('k', {})
        if not kline:
            return

        symbol = kline.get('s', '')
        is_closed = kline.get('x', False)

        # 检查 symbol 是否匹配
        if symbol.upper() != self.symbol.upper():
            return

        try:
            if is_closed:
                # 日线收盘，重新计算轨道
                await self._on_daily_kline_closed(kline)
            else:
                # 盘中更新，检查突破
                await self._on_kline_update(kline)
        except Exception as e:
            logger.error(f"[K线事件] 处理失败: {e}", exc_info=True)

    async def _initialize_market_bands(self) -> None:
        """初始化行情轨道（启动时从历史日线计算）"""
        from binance_kline_fetcher import KlineFetcher
        from datetime import timedelta

        logger.info("[行情] 初始化轨道...")

        # 1. 从缓存获取历史日线
        fetcher = KlineFetcher()
        n_days = self.market_algorithm_params.get('n_days', 4)

        # 计算时间范围：过去 n_days + 1 天
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=n_days + 2)).timestamp() * 1000)

        klines = await fetcher.fetch_kline(
            symbol=self.symbol,
            interval='1d',
            start_time=start_time,
            end_time=end_time
        )

        if len(klines) < n_days + 1:
            logger.warning(f"[行情] 日线数据不足: {len(klines)} < {n_days + 1}")
            self.current_market_status = MarketStatus.RANGING
            return

        # 只取最近 n_days + 1 根 K线
        klines = klines[-(n_days + 1):]

        # 2. 计算 Dual Thrust 轨道
        result = self.market_detector.algorithm.calculate(klines, {})

        # 3. 缓存轨道数据
        self._current_bands = {
            'upper': result.indicators.get('upper_band'),
            'lower': result.indicators.get('lower_band'),
            'range': result.indicators.get('range'),
            'today_open': result.indicators.get('today_open'),
            'hh': result.indicators.get('hh'),
            'll': result.indicators.get('ll'),
            'hc': result.indicators.get('hc'),
            'lc': result.indicators.get('lc'),
        }

        # 4. 设置当前状态
        self.current_market_status = result.status

        logger.info(f"[行情] 初始化完成: Upper={self._current_bands.get('upper', 0):.2f}, "
                    f"Lower={self._current_bands.get('lower', 0):.2f}, 状态={result.status.value}")

    async def _on_daily_kline_closed(self, kline: Dict) -> None:
        """日线收盘时重新计算轨道

        参数:
            kline: 收盘的 K线数据
        """
        from binance_kline_fetcher import KlineFetcher
        from datetime import timedelta

        logger.info(f"[行情] 日线收盘，重新计算轨道")

        # 1. 从缓存获取历史日线
        fetcher = KlineFetcher()
        n_days = self.market_algorithm_params.get('n_days', 4)

        # 计算时间范围：过去 n_days + 1 天
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=n_days + 2)).timestamp() * 1000)

        klines = await fetcher.fetch_kline(
            symbol=self.symbol,
            interval='1d',
            start_time=start_time,
            end_time=end_time
        )

        if len(klines) < n_days + 1:
            logger.warning(f"[行情] 日线数据不足: {len(klines)} < {n_days + 1}")
            return

        # 只取最近 n_days + 1 根 K线
        klines = klines[-(n_days + 1):]

        # 2. 计算 Dual Thrust 轨道
        result = self.market_detector.algorithm.calculate(klines, {})

        # 3. 缓存轨道数据
        self._current_bands = {
            'upper': result.indicators.get('upper_band'),
            'lower': result.indicators.get('lower_band'),
            'range': result.indicators.get('range'),
            'today_open': result.indicators.get('today_open'),
            'hh': result.indicators.get('hh'),
            'll': result.indicators.get('ll'),
            'hc': result.indicators.get('hc'),
            'lc': result.indicators.get('lc'),
        }

        # 4. 更新当前状态
        old_status = self.current_market_status
        self.current_market_status = result.status

        # 5. 保存到数据库
        if self.session_id:
            kline_date = datetime.fromtimestamp(kline.get('t', 0) / 1000).strftime('%Y-%m-%d')
            self.db.save_dual_thrust_bands(
                session_id=self.session_id,
                bands={
                    'calc_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'kline_date': kline_date,
                    'upper_band': self._current_bands.get('upper', 0),
                    'lower_band': self._current_bands.get('lower', 0),
                    'range_value': self._current_bands.get('range', 0),
                    'today_open': self._current_bands.get('today_open', 0),
                    'hh': self._current_bands.get('hh', 0),
                    'll': self._current_bands.get('ll', 0),
                    'hc': self._current_bands.get('hc', 0),
                    'lc': self._current_bands.get('lc', 0),
                }
            )

            # 保存行情结果
            if self.market_case_id:
                self.db.save_market_result(
                    case_id=self.market_case_id,
                    result={
                        'check_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'market_status': result.status.value,
                        'confidence': result.confidence,
                        'reason': result.reason,
                        'event_type': 'daily_close',
                        'indicators': result.indicators,
                        'open_price': float(kline.get('o', 0)),
                        'close_price': float(kline.get('c', 0)),
                        'high_price': float(kline.get('h', 0)),
                        'low_price': float(kline.get('l', 0)),
                        'volume': float(kline.get('v', 0)),
                    }
                )

        # 6. 状态变化时触发回调
        if result.status != old_status:
            current_price = Decimal(str(kline.get('c', 0)))
            await self._handle_market_status_change(old_status, result.status, current_price)

        logger.info(f"[行情] 新轨道: Upper={self._current_bands.get('upper', 0):.2f}, "
                    f"Lower={self._current_bands.get('lower', 0):.2f}, 状态={result.status.value}")

    async def _on_kline_update(self, kline: Dict) -> None:
        """盘中 K线更新，检查突破

        参数:
            kline: K线数据
        """
        if not self._current_bands:
            # 首次需要先计算轨道（可能在启动时还未收到收盘事件）
            await self._on_daily_kline_closed(kline)
            return

        current_price = Decimal(str(kline.get('c', 0)))
        upper = self._current_bands.get('upper')
        lower = self._current_bands.get('lower')

        if not upper or not lower:
            return

        # 判断突破
        old_status = self.current_market_status

        if current_price > Decimal(str(upper)):
            new_status = MarketStatus.TRENDING_UP
        elif current_price < Decimal(str(lower)):
            new_status = MarketStatus.TRENDING_DOWN
        else:
            new_status = MarketStatus.RANGING

        # 状态变化时触发回调
        if new_status != old_status:
            self.current_market_status = new_status
            await self._handle_market_status_change(old_status, new_status, current_price)

            # 保存到数据库
            if self.market_case_id:
                self.db.save_market_result(
                    case_id=self.market_case_id,
                    result={
                        'check_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'market_status': new_status.value,
                        'confidence': 1.0,
                        'reason': f"价格突破轨道: {current_price:.2f} vs [{lower:.2f}, {upper:.2f}]",
                        'event_type': 'breakthrough',
                        'indicators': {
                            'upper_band': upper,
                            'lower_band': lower,
                            'current_price': float(current_price),
                        },
                        'close_price': float(current_price),
                    }
                )

            logger.info(f"[行情] 突破检测: 价格={current_price:.2f}, "
                        f"轨道=[{lower:.2f}, {upper:.2f}], 新状态={new_status.value}")

    async def _handle_order_update(self, order_data: Dict[str, Any]) -> None:
        """处理订单状态更新

        根据 Binance 订单状态执行相应处理：
        - FILLED: 订单成交，下止盈止损单，发通知，下下一级订单
        - CANCELED/EXPIRED: 订单取消，删除本地订单

        Binance ORDER_TRADE_UPDATE 字段:
        - 'i': orderId（订单ID）
        - 'X': orderStatus（订单状态: NEW, FILLED, CANCELED 等）

        参数:
            order_data: Binance 订单数据
        """
        # Binance 字段映射: 'i' 是 orderId, 'X' 是 orderStatus
        order_id = order_data.get("i") or order_data.get("orderId")
        order_status = order_data.get("X") or order_data.get("orderStatus")

        # 前置检查：无效的订单数据
        if not order_id:
            logger.warning(f"[订单更新] 收到无效订单数据（无orderId）: {order_data}")
            return

        if not self.chain_state:
            return

        order = None
        for o in self.chain_state.orders:
            if o.order_id == order_id:
                order = o
                break

        if not order:
            logger.warning(f"[订单更新] 未找到本地订单: orderId={order_id}, status={order_status}, 当前订单列表: {[o.order_id for o in self.chain_state.orders]}")
            return

        logger.info(f"[订单更新] 找到订单: orderId={order_id}, status={order_status}, level=A{order.level}")
        
        if order_status == "FILLED":
            await self._handle_order_filled(order, order_data)
        elif order_status in ["CANCELED", "EXPIRED", "TRADE_PREVENT"]:
            await self._handle_order_cancelled(order, order_data)
    
    async def _process_order_filled(self, order: Any, filled_price: Decimal, is_recovery: bool = False) -> None:
        """处理订单成交后的通用逻辑

        参数:
            order: 订单对象
            filled_price: 成交价格
            is_recovery: 是否为状态恢复时的处理
        """
        logger.info(f"[成交处理] 开始 A{order.level}: 成交价={filled_price:.2f}, is_recovery={is_recovery}")

        if order.state == "closed":
            logger.info(f"[状态恢复] A{order.level} 已是 closed 状态，跳过处理")
            return

        if is_recovery:
            logger.info(f"[状态恢复] A{order.level} 检测到成交，执行后续处理")
            print(f"   ⚡ A{order.level} 检测到成交，执行后续处理")

        # 订单状态变更: pending -> filled
        logger.info(f"[订单状态] A{order.level}: {order.state} -> filled, orderId={order.order_id}")
        order.state = "filled"
        order.entry_price = filled_price
        order.filled_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # === 更新 group_id (A1 成交时开启新轮次) ===
        if order.level == 1:
            old_group_id = self.chain_state.group_id if self.chain_state else 0
            self.chain_state.group_id = order.group_id
            logger.info(f"[新轮次] group_id: {old_group_id} -> {order.group_id}")

        # === 记录入场资金 ===
        entry_capital = self.capital_strategy.calculate_entry_capital(
            self.capital_pool, order.level, self.chain_state
        )
        entry_total_capital = self.capital_strategy.calculate_entry_total_capital(
            self.capital_pool, order.level, self.chain_state
        )

        # 空值保护：如果计算结果为 None，使用默认值
        if entry_capital is None:
            entry_capital = self.initial_capital
            logger.warning(f"[入场资金] calculate_entry_capital 返回 None，使用初始资金: {entry_capital}")
        if entry_total_capital is None:
            entry_total_capital = self.initial_capital
            logger.warning(f"[入场总资金] calculate_entry_total_capital 返回 None，使用初始资金: {entry_total_capital}")

        order.entry_capital = entry_capital
        order.entry_total_capital = entry_total_capital
        logger.debug(f"[成交处理] 入场资金: entry_capital={entry_capital:.2f}, entry_total_capital={entry_total_capital:.2f}")

        # === 下止盈止损单 ===
        logger.info(f"[成交处理] 开始下止盈止损单...")
        await self._place_exit_orders(order)

        commission = Decimal("0")
        notify_entry_filled(order, filled_price, commission, self.config, self.session_id, self.db)

        # === 下下一级订单 ===
        logger.info(f"[成交处理] 开始下下一级订单...")
        await self._place_next_level_order(order)

        # === 更新订单状态到数据库 ===
        if self.session_id:
            self.db.update_order(self.session_id, order)
            logger.debug(f"[数据库] 更新订单: session_id={self.session_id}, level=A{order.level}, "
                         f"state={order.state}, tp_order_id={order.tp_order_id}, sl_order_id={order.sl_order_id}")

        # === 记录统计指标 ===
        self._record_execution_time(order)
        self._record_level_reached(order.level)

        self._save_state()
    
    async def _handle_order_filled(self, order: Any, order_data: Dict[str, Any]) -> None:
        """WebSocket 实时成交处理

        Binance ORDER_TRADE_UPDATE 字段:
        - 'ap': averagePrice（平均成交价）
        - 'L': lastFilledPrice（最后成交价）
        """
        logger.info(f"[订单成交] A{order.level}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 入场成交 A{order.level}")

        # Binance 字段: 'ap' 是 averagePrice, 'L' 是 lastFilledPrice
        filled_price = Decimal(str(order_data.get("ap") or order_data.get("L") or order.entry_price))
        await self._process_order_filled(order, filled_price)
    
    async def _handle_order_cancelled(self, order: Any, order_data: Dict[str, Any]) -> None:
        logger.info(f"[订单取消] A{order.level}")

        await self._cancel_algo_orders_for_order(order)

        if self.chain_state and order in self.chain_state.orders:
            self.chain_state.orders.remove(order)

        self._save_state()
    
    def _log_order_closed(self, order: Any, reason: str) -> None:
        """打印订单关闭信息到日志"""
        logger.info(f"[订单关闭] A{order.level} {reason}")
        logger.info(f"  入场价格: {order.entry_price:.2f}")
        logger.info(f"  入场时间: {order.filled_at or '未知'}")
        logger.info(f"  平仓价格: {order.close_price:.2f}")
        logger.info(f"  平仓时间: {order.closed_at or '未知'}")
        logger.info(f"  平仓原因: {order.close_reason}")
        logger.info(f"  数量: {order.quantity:.6f}")
        logger.info(f"  金额: {order.stake_amount:.2f} USDT")
        logger.info(f"  盈亏: {order.profit:.2f} USDT")
        logger.info(f"  持仓时长: {self._calculate_holding_duration(order)}")
    
    def _calculate_holding_duration(self, order: Any) -> str:
        """计算持仓时长"""
        if not order.filled_at or not order.closed_at:
            return "未知"
        
        try:
            filled_time = datetime.strptime(order.filled_at, '%Y-%m-%d %H:%M:%S')
            closed_time = datetime.strptime(order.closed_at, '%Y-%m-%d %H:%M:%S')
            duration = closed_time - filled_time
            
            total_seconds = int(duration.total_seconds())
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            
            if days > 0:
                return f"{days}天{hours}小时{minutes}分钟"
            elif hours > 0:
                return f"{hours}小时{minutes}分钟"
            else:
                return f"{minutes}分钟"
        except Exception:
            return "未知"
    
    async def _cancel_algo_orders_for_order(self, order: Any) -> None:
        symbol = self.config.get("symbol", "BTCUSDT")
        
        algo_ids = []
        if order.tp_order_id:
            algo_ids.append(order.tp_order_id)
        if order.sl_order_id:
            algo_ids.append(order.sl_order_id)
        
        for algo_id in algo_ids:
            try:
                await self.client.cancel_algo_order(symbol, algo_id)
                logger.info(f"[取消关联条件单] algoId={algo_id}")
            except Exception as e:
                logger.warning(f"[取消关联条件单] 失败 algoId={algo_id}: {e}")
    
    async def _place_next_level_order(self, order: Any) -> None:
        """下下一级入场单

        当前订单成交后，创建下一级入场单。

        参数:
            order: 当前已成交的订单

        副作用:
            - 创建新订单并添加到 chain_state.orders
            - 下入场单
            - 保存状态
        """
        if not self.chain_state:
            logger.warning("[下一级订单] chain_state 为空，无法下单")
            return

        next_level = order.level + 1
        max_level = self.config.get("max_entries", 4)

        logger.info(f"[下一级订单] 检查: 当前 A{order.level}, 下一级 A{next_level}, max_level={max_level}")

        if next_level > max_level:
            logger.info(f"[下一级订单] 超过最大层级 {max_level}，不下单")
            return

        has_next = any(o.level == next_level for o in self.chain_state.orders)
        if has_next:
            logger.info(f"[下一级订单] A{next_level} 已存在，跳过")
            return

        try:
            current_price = await self._get_current_price()
            klines = await self._get_recent_klines()
            new_order = await self._create_order(next_level, current_price, klines)
            self.chain_state.orders.append(new_order)

            logger.info(f"[下一级订单] 创建 A{next_level}: 入场价={new_order.entry_price:.2f}, 数量={new_order.quantity}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 下 A{next_level} 入场单: 入场价={new_order.entry_price:.{self.price_precision}f}")

            await self._place_entry_order(new_order)
        except Exception as e:
            logger.error(f"[下一级订单] A{next_level} 下单失败: {e}", exc_info=True)

async def main():
    """主函数"""
    import argparse
    from autofish_core import Autofish_ConfigLoader

    parser = argparse.ArgumentParser(description="Autofish V2 Binance 实盘交易")
    parser.add_argument("--case-id", type=int, default=None, help="从数据库加载配置 (case_id)")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径 (默认: out/autofish/example_strategy.json)")

    args = parser.parse_args()

    # === 加载配置 ===
    if args.case_id is not None:
        # 从数据库加载
        try:
            config = Autofish_ConfigLoader.load_from_case_id(args.case_id)
            config_source = f"数据库 case_id={args.case_id}"
            logger.info(f"[配置加载] 从数据库加载配置: case_id={args.case_id}")
        except Exception as e:
            logger.error(f"[配置加载] 加载 case_id={args.case_id} 失败: {e}", exc_info=True)
            return
    elif args.config:
        # 从配置文件加载
        try:
            config = Autofish_ConfigLoader.load_from_file(args.config)
            config_source = f"配置文件 {args.config}"
            logger.info(f"[配置加载] 从文件加载配置: {args.config}")
        except Exception as e:
            logger.error(f"[配置加载] 加载配置文件失败: {e}", exc_info=True)
            return
    else:
        # 使用默认配置
        config = Autofish_ConfigLoader.load_default_config()
        config_source = "默认配置"
        logger.info("[配置加载] 使用默认配置")

    # === 启动日志 ===
    logger.info("=" * 60)
    logger.info("Autofish V2 Binance Live Trading 启动")
    logger.info("=" * 60)
    logger.info(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  交易对: {config.get('symbol')}")
    logger.info(f"  网络: {'测试网' if config.get('testnet', True) else '主网'}")
    logger.info(f"  配置来源: {config_source}")
    logger.info("=" * 60)

    # 配置详情日志
    amplitude = config.get('amplitude', {})
    capital = config.get('capital', {})
    total_amount = capital.get('total_amount_quote') or amplitude.get('total_amount_quote', 10000)
    logger.info(f"  交易杠杆: {amplitude.get('leverage', 10)}x")
    logger.info(f"  资金投入: {total_amount} USDT")
    logger.info(f"  网格间距: {float(amplitude.get('grid_spacing', 0.01))*100:.1f}%")
    logger.info(f"  止盈比例: {float(amplitude.get('exit_profit', 0.01))*100:.1f}%")
    logger.info(f"  止损比例: {float(amplitude.get('stop_loss', 0.08))*100:.1f}%")
    logger.info(f"  衰减因子: {amplitude.get('decay_factor', 0.5)}")
    logger.info(f"  最大层级: {amplitude.get('max_entries', 4)}")
    logger.info("=" * 60)

    # === 创建并运行交易器 ===
    trader = BinanceLiveTrader(
        symbol=config["symbol"],
        amplitude=config.get("amplitude", {}),
        market=config.get("market", {}),
        entry=config.get("entry", {}),
        timeout=config.get("timeout", {}),
        capital=config.get("capital", {}),
        testnet=config.get("testnet", True)
    )

    if args.case_id is not None:
        trader.case_id = args.case_id

    await trader.run()


if __name__ == "__main__":
    asyncio.run(main())


# ============================================================================
# LiveTraderManager - 多实例管理器（供 Web 服务使用）
# ============================================================================

class LiveTraderManager:
    """实盘交易实例管理器

    用于管理多个实盘交易实例，支持：
    - 从配置创建并启动实例
    - 实时监控实例状态
    - 停止指定实例
    - 获取所有实例状态

    使用方式:
        manager = LiveTraderManager()

        # 从 case_id 创建实例
        trader = await manager.create_trader_from_case(case_id=1)

        # 获取所有实例
        traders = manager.get_all_traders()

        # 停止实例
        await manager.stop_trader(session_id=1)
    """

    def __init__(self):
        self._traders: Dict[int, BinanceLiveTrader] = {}  # session_id -> trader
        self._tasks: Dict[int, asyncio.Task] = {}  # session_id -> task
        self._lock = asyncio.Lock()

    async def create_trader_from_config(self, symbol: str, amplitude: Dict, market: Dict, entry: Dict, timeout: Dict, capital: Dict, testnet: bool = True) -> BinanceLiveTrader:
        """从结构化配置创建交易实例

        Args:
            symbol: 交易对
            amplitude: 振幅参数
            market: 行情配置
            entry: 入场策略
            timeout: 超时参数
            capital: 资金池配置
            testnet: 是否使用测试网

        Returns:
            BinanceLiveTrader 实例
        """
        trader = BinanceLiveTrader(symbol, amplitude, market, entry, timeout, capital, testnet=testnet)
        return trader

    async def create_trader_from_case(self, case_id: int) -> Optional[BinanceLiveTrader]:
        """从 case_id 创建交易实例

        参数:
            case_id: 实盘配置 ID

        返回:
            BinanceLiveTrader 实例，失败返回 None
        """
        from autofish_core import Autofish_ConfigLoader

        try:
            # 使用 Autofish_ConfigLoader 从 case_id 加载配置
            config = Autofish_ConfigLoader.load_from_case_id(case_id)

            trader = await self.create_trader_from_config(
                symbol=config["symbol"],
                amplitude=config["amplitude"],
                market=config["market"],
                entry=config["entry"],
                timeout=config["timeout"],
                capital=config["capital"],
                testnet=config["testnet"]
            )
            trader.case_id = case_id  # 标记来源

            return trader
        except Exception as e:
            logger.error(f"[TraderManager] 创建交易实例失败: {e}", exc_info=True)
            return None

    async def recover_trader(self, session_id: int) -> Optional[BinanceLiveTrader]:
        """恢复指定 session 的交易实例

        参数:
            session_id: 要恢复的会话 ID

        返回:
            BinanceLiveTrader 实例，失败返回 None
        """
        from database.live_trading_db import LiveTradingDB

        db = LiveTradingDB()

        # 获取 session 信息
        session = db.get_session(session_id)
        if not session:
            logger.error(f"[恢复] Session 不存在: {session_id}")
            return None

        if session['status'] != 'running':
            logger.error(f"[恢复] Session 状态不是 running: {session['status']}")
            return None

        # 检查是否已在内存中运行
        if self.get_trader(session_id) is not None:
            logger.warning(f"[恢复] Session 已在运行: {session_id}")
            return None

        # 获取关联的 case_id
        case_id = session.get('case_id')
        if not case_id:
            logger.error(f"[恢复] Session 无 case_id: {session_id}")
            return None

        # 从 case_id 创建 trader
        trader = await self.create_trader_from_case(case_id)
        if not trader:
            logger.error(f"[恢复] 无法从 case_id={case_id} 创建 trader")
            return None

        # 设置恢复模式
        trader.recover_session_id = session_id
        logger.info(f"[恢复] 已创建恢复实例: session_id={session_id}, case_id={case_id}")

        return trader

    async def start_trader(self, trader: BinanceLiveTrader) -> int:
        """启动交易实例（后台运行）

        参数:
            trader: BinanceLiveTrader 实例

        返回:
            session_id
        """
        logger.info(f"[TraderManager] 开始启动交易实例: symbol={trader.symbol}")
        async with self._lock:
            # 创建任务
            task = asyncio.create_task(trader.run())
            logger.info(f"[TraderManager] 已创建运行任务，等待 session_id...")

            # 等待 session_id 生成（最多等待 5 秒）
            for i in range(50):
                if trader.session_id:
                    logger.info(f"[TraderManager] 获取到 session_id: {trader.session_id}")
                    break
                await asyncio.sleep(0.1)
                if i % 10 == 9:
                    logger.info(f"[TraderManager] 等待 session_id... ({i+1}/50)")

            if not trader.session_id:
                # 检查任务是否有异常
                if task.done():
                    try:
                        task.result()  # 这会抛出异常
                    except Exception as e:
                        logger.error(f"[TraderManager] 实例运行异常: {e}", exc_info=True)
                else:
                    logger.error("[TraderManager] 启动超时：未获取到 session_id")
                task.cancel()
                return 0

            self._traders[trader.session_id] = trader
            self._tasks[trader.session_id] = task

            logger.info(f"[TraderManager] 实例已启动: session_id={trader.session_id}")
            return trader.session_id

    async def stop_trader(self, session_id: int) -> bool:
        """停止交易实例

        参数:
            session_id: 会话 ID

        返回:
            是否成功
        """
        async with self._lock:
            trader = self._traders.get(session_id)
            task = self._tasks.get(session_id)

            if not trader and not task:
                logger.warning(f"[TraderManager] session_id={session_id} 不存在")
                return False

            # 停止 trader
            if trader:
                trader.running = False
                logger.info(f"[TraderManager] 已设置停止标志: session_id={session_id}")

            # 取消任务
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # 清理
            self._traders.pop(session_id, None)
            self._tasks.pop(session_id, None)

            logger.info(f"[TraderManager] 实例已停止: session_id={session_id}")
            return True

    async def pause_trader(self, session_id: int) -> bool:
        """暂停交易实例

        暂停后：
        - WebSocket 保持连接
        - 继续处理订单事件（止盈/止损）
        - 不下新订单

        参数:
            session_id: 会话 ID

        返回:
            是否成功
        """
        async with self._lock:
            trader = self._traders.get(session_id)

            if not trader:
                logger.warning(f"[TraderManager] session_id={session_id} 不存在")
                return False

            if trader.paused:
                logger.warning(f"[TraderManager] session_id={session_id} 已经是暂停状态")
                return True

            trader.paused = True
            logger.info(f"[TraderManager] 实例已暂停: session_id={session_id}")
            return True

    async def resume_trader(self, session_id: int) -> Dict[str, Any]:
        """恢复交易实例

        恢复前会同步交易所状态：
        - 同步订单状态（处理暂停期间的成交）
        - 同步资金池状态

        参数:
            session_id: 会话 ID

        返回:
            恢复结果
        """
        async with self._lock:
            trader = self._traders.get(session_id)

            if not trader:
                logger.warning(f"[TraderManager] session_id={session_id} 不存在")
                return {'success': False, 'error': 'Trader not found'}

            if not trader.paused:
                logger.warning(f"[TraderManager] session_id={session_id} 未处于暂停状态")
                return {'success': True, 'message': 'Not paused'}

            # 调用 trader 的恢复方法（会同步状态）
            result = await trader.resume_from_pause()

            if result['success']:
                logger.info(f"[TraderManager] 实例已恢复: session_id={session_id}")
            else:
                logger.error(f"[TraderManager] 恢复失败: session_id={session_id}, error={result.get('error')}")

            return result

    def get_trader(self, session_id: int) -> Optional[BinanceLiveTrader]:
        """获取交易实例"""
        return self._traders.get(session_id)

    def get_all_traders(self) -> Dict[int, BinanceLiveTrader]:
        """获取所有交易实例"""
        return self._traders.copy()

    def get_running_sessions(self) -> List[int]:
        """获取所有运行中的 session_id"""
        return list(self._traders.keys())

    async def list_traders(self) -> List[Dict[str, Any]]:
        """获取所有交易实例的信息列表

        返回:
            实例信息列表，每个包含:
            - session_id
            - case_id
            - symbol
            - testnet
            - running
            - current_status (如果可用)
        """
        result = []
        for session_id, trader in self._traders.items():
            # 获取市场状态，转换为字符串以便 JSON 序列化
            market_status = getattr(trader, 'current_market_status', None)
            if market_status is not None:
                market_status = market_status.value if hasattr(market_status, 'value') else str(market_status)

            info = {
                'session_id': session_id,
                'case_id': getattr(trader, 'case_id', 0),
                'symbol': trader.symbol,
                'testnet': trader.testnet,
                'running': trader.running,
                'paused': getattr(trader, 'paused', False),
                'ws_connected': getattr(trader, 'ws_connected', False),
                'current_market_status': market_status,
            }
            # 获取当前状态
            if hasattr(trader, 'chain_state') and trader.chain_state:
                info['active_orders'] = len([o for o in trader.chain_state.orders if o.state == 'filled'])
                info['pending_orders'] = len([o for o in trader.chain_state.orders if o.state == 'pending'])
                info['group_id'] = trader.chain_state.group_id
            result.append(info)
        return result

    async def get_trader_info(self, session_id: int) -> Optional[Dict[str, Any]]:
        """获取指定交易实例的详细信息

        参数:
            session_id: 会话 ID

        返回:
            实例详细信息，包含:
            - 基本信息同 list_traders
            - chain_state 状态快照
            - 当前订单列表
            - 资金池状态
        """
        trader = self._traders.get(session_id)
        if not trader:
            return None

        # 获取市场状态，转换为字符串以便 JSON 序列化
        market_status = getattr(trader, 'current_market_status', None)
        if market_status is not None:
            market_status = market_status.value if hasattr(market_status, 'value') else str(market_status)
        else:
            market_status = 'unknown'

        info = {
            'session_id': session_id,
            'case_id': getattr(trader, 'case_id', 0),
            'symbol': trader.symbol,
            'testnet': trader.testnet,
            'running': trader.running,
            'ws_connected': getattr(trader, 'ws_connected', False),
            'current_market_status': market_status,
        }

        # 获取链式订单状态
        if hasattr(trader, 'chain_state') and trader.chain_state:
            info['group_id'] = trader.chain_state.group_id
            info['base_price'] = trader.chain_state.base_price

            # 订单列表
            orders_info = []
            for order in trader.chain_state.orders:
                order_dict = {
                    'level': order.level,
                    'entry_price': str(order.entry_price),
                    'quantity': str(order.quantity),
                    'stake_amount': order.stake_amount,
                    'take_profit_price': str(order.take_profit_price),
                    'stop_loss_price': str(order.stop_loss_price),
                    'state': order.state,
                    'order_id': order.order_id,
                    'created_at': str(order.created_at) if order.created_at else None,
                    'filled_at': str(order.filled_at) if order.filled_at else None,
                    'profit': order.profit,
                    'close_reason': order.close_reason,
                }
                orders_info.append(order_dict)
            info['orders'] = orders_info

            # 资金池状态
            if hasattr(trader.chain_state, 'capital_tracker'):
                tracker = trader.chain_state.capital_tracker
                info['capital_pool'] = {
                    'trading_capital': tracker.trading_capital,
                    'profit_pool': tracker.profit_pool,
                    'total_profit': tracker.total_profit,
                    'total_loss': tracker.total_loss,
                    'withdrawal_count': tracker.withdrawal_count,
                    'liquidation_count': tracker.liquidation_count,
                }

        # 获取统计结果
        if hasattr(trader, 'results'):
            info['results'] = trader.results

        return info

    async def stop_all(self):
        """停止所有实例"""
        session_ids = list(self._traders.keys())
        for session_id in session_ids:
            await self.stop_trader(session_id)


__all__ = [
    "BinanceClient",           # API 客户端类
    "BinanceLiveTrader",       # 实盘交易者类
    "AlgoHandler",             # Algo 条件单处理器
    "LiveTraderManager",       # 多实例管理器
    "BinanceAPIError",         # API 异常类
    "NetworkError",            # 网络异常类
    "OrderError",              # 订单异常类
    "StateError",              # 状态异常类
    "RetryConfig",             # 重试配置类
    "retry_on_exception",      # 重试装饰器
    "NETWORK_RETRY",           # 网络重试配置
    "API_RETRY",               # API 重试配置
    "setup_logger",            # 日志设置函数
    "get_logger",              # 获取日志器函数
    "LoggerAdapter",           # 日志适配器类
    "FlushFileHandler",        # 刷新文件处理器类
    "OrderState",              # 订单状态枚举
    "CloseReason",             # 平仓原因枚举
    "OrderType",               # 订单类型枚举
    "AlgoStatus",              # Algo 状态枚举
    "NotificationTemplate",    # 通知模板类
    "send_wechat_notification", # 发送微信通知
    "notify_entry_order",      # 入场单通知
    "notify_entry_order_supplement", # 补单通知
    "notify_entry_filled",     # 入场成交通知
    "notify_take_profit",      # 止盈通知
    "notify_stop_loss",        # 止损通知
    "notify_orders_recovered", # 订单恢复通知
    "notify_exit",             # 退出通知
    "notify_startup",          # 启动通知
]
