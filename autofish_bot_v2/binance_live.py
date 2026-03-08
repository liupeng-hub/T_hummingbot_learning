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


# ============================================================================
# 常量定义
# ============================================================================

# 文件名常量
STATE_FILE = "binance_live_state.json"
LOG_FILE = "binance_live.log"
LOG_DIR = "logs"
MESSAGE_COUNTER_FILE = "message_counter.txt"


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


logger = logging.getLogger("autofish")


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
# 状态持久化仓库
# ============================================================================

class StateRepository:
    def __init__(self, file_path: str):
        self.file_path = file_path
    
    def save(self, data: Dict[str, Any]) -> None:
        temp_path = self.file_path + '.tmp'
        
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            
            os.replace(temp_path, self.file_path)
            logger.info(f"[状态保存] 成功保存到: {self.file_path}")
            
        except Exception as e:
            logger.error(f"[状态保存] 保存失败: {e}")
            
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            
            raise
    
    def load(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.file_path):
            logger.info(f"[状态加载] 文件不存在: {self.file_path}")
            return None
        
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            logger.info(f"[状态加载] 成功加载: {self.file_path}")
            return data
            
        except json.JSONDecodeError as e:
            logger.error(f"[状态加载] JSON 解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"[状态加载] 加载失败: {e}")
            return None
    
    def exists(self) -> bool:
        return os.path.exists(self.file_path)
    
    def delete(self) -> bool:
        if os.path.exists(self.file_path):
            try:
                os.remove(self.file_path)
                logger.info(f"[状态删除] 成功删除: {self.file_path}")
                return True
            except Exception as e:
                logger.error(f"[状态删除] 删除失败: {e}")
                return False
        return True
    
    def get_backup_path(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{self.file_path}.backup_{timestamp}"
    
    def backup(self) -> Optional[str]:
        if not os.path.exists(self.file_path):
            return None
        
        backup_path = self.get_backup_path()
        
        try:
            import shutil
            shutil.copy2(self.file_path, backup_path)
            logger.info(f"[状态备份] 成功备份到: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"[状态备份] 备份失败: {e}")
            return None


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


def send_wechat_notification(title: str, content: str):
    msg_num = get_next_message_number()
    content_with_num = f"> **消息号**: {msg_num}\n\n{content}"
    
    wechat_webhook = os.getenv("WECHAT_WEBHOOK")
    
    if not wechat_webhook:
        logger.warning("[通知发送] 未配置 WECHAT_WEBHOOK，跳过发送")
        return
    
    try:
        data = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"## {title}\n\n{content_with_num}"
            }
        }
        response = requests.post(wechat_webhook, json=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if result.get("errcode") == 0:
                logger.info(f"[通知发送] 微信机器人发送成功: {title}, 消息号={msg_num}")
            else:
                logger.warning(f"[通知发送] 微信机器人发送失败: {result}")
        else:
            logger.warning(f"[通知发送] 微信机器人请求失败: {response.status_code}")
    except Exception as e:
        logger.warning(f"[通知发送] 微信机器人发送异常: {e}")


def notify_entry_order(order, config: dict):
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


def notify_entry_order_supplement(order, config: dict):
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


def notify_entry_filled(order, filled_price: Decimal, commission: Decimal, config: dict):
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


def notify_take_profit(order, profit: Decimal, config: dict):
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""
            > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
            > **止盈价**: {order.take_profit_price:.2f} USDT
            > **盈亏**: +{profit:.2f} USDT
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification(f"🎯 止盈触发 A{order.level}", content)


def notify_stop_loss(order, profit: Decimal, config: dict):
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""
            > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
            > **止损价**: {order.stop_loss_price:.2f} USDT
            > **盈亏**: {profit:.2f} USDT
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification(f"🛑 止损触发 A{order.level}", content)


def notify_orders_recovered(orders: list, config: dict, current_price: Decimal, pnl_info: dict = None):
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
    send_wechat_notification("🔄 订单同步", content)


def notify_exit(reason: str, config: dict, cancelled_orders: list = None, remaining_orders: list = None, pnl_info: dict = None, current_price: Decimal = None):
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
    send_wechat_notification("⏹️ Autofish V2 退出", content)


def notify_startup(config: dict, current_price: Decimal):
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
    send_wechat_notification("🚀 Autofish V2 启动", content)


def notify_critical_error(error_msg: str, config: dict):
    """发送严重错误通知"""
    symbol = config.get('symbol', 'BTCUSDT')
    content = dedent(f"""
        > **错误类型**: 严重错误
        > **交易标的**: {symbol}
        > **错误信息**: {error_msg}
        > **状态**: 程序强制退出
        > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """).strip()
    send_wechat_notification("🚨 Autofish V2 严重错误", content)


def notify_warning(warning_msg: str, config: dict):
    """发送警告通知"""
    symbol = config.get('symbol', 'BTCUSDT')
    content = dedent(f"""
        > **通知类型**: 资金提醒
        > **交易标的**: {symbol}
        > **提醒内容**: {warning_msg}
        > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """).strip()
    send_wechat_notification("⚠️ Autofish 资金提醒", content)


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
                               reduce_only: bool = True) -> Dict[str, Any]:
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "algoType": "CONDITIONAL",
            "quantity": str(quantity),
            "triggerPrice": str(trigger_price),
        }
        
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
        outer_algo_id = algo_data.get("g") or algo_data.get("algoId")
        outer_status = algo_data.get("X") or algo_data.get("algoStatus")
        
        inner_data = algo_data.get("o", {})
        algo_id = inner_data.get("aid") or outer_algo_id
        algo_status = inner_data.get("X") or outer_status
        algo_type = inner_data.get("o") or algo_data.get("orderType")
        
        if not algo_id:
            logger.warning(f"[Algo事件] 数据格式异常: {algo_data}")
            return
        
        order = self._find_order_by_algo_id(algo_id)
        if not order:
            logger.warning(f"[Algo匹配] 未找到订单: algoId={algo_id}")
            return
        
        logger.info(f"[Algo事件] algoId={algo_id}, status={algo_status}, orderType={algo_type}")
        
        if algo_status in ["FINISHED", "finished"]:
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
        logger.info(f"[止盈触发] A{order.level}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 止盈触发 A{order.level}")
        
        order.state = "closed"
        order.close_reason = CloseReason.TAKE_PROFIT.value
        
        filled_price = Decimal(str(algo_data.get("avgPrice", order.entry_price)))
        profit = (order.take_profit_price - order.entry_price) * order.quantity
        order.profit = profit
        
        if order.sl_order_id:
            try:
                symbol = self.trader.config.get("symbol", "BTCUSDT")
                await self.trader.client.cancel_algo_order(symbol, order.sl_order_id)
                logger.info(f"[取消止损单] algoId={order.sl_order_id}")
            except Exception as e:
                logger.warning(f"[取消止损单] 失败: {e}")
        
        notify_take_profit(order, profit, self.trader.config)
        
        await self._cancel_next_level_and_restart(order)
        
        self._adjust_order_levels()
        
        self.trader._save_state()
    
    async def _handle_stop_loss(self, order: Any, algo_data: Dict[str, Any]) -> None:
        logger.info(f"[止损触发] A{order.level}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 止损触发 A{order.level}")
        
        order.state = "closed"
        order.close_reason = CloseReason.STOP_LOSS.value
        
        profit = (order.stop_loss_price - order.entry_price) * order.quantity
        order.profit = profit
        
        if order.tp_order_id:
            try:
                symbol = self.trader.config.get("symbol", "BTCUSDT")
                await self.trader.client.cancel_algo_order(symbol, order.tp_order_id)
                logger.info(f"[取消止盈单] algoId={order.tp_order_id}")
            except Exception as e:
                logger.warning(f"[取消止盈单] 失败: {e}")
        
        notify_stop_loss(order, profit, self.trader.config)
        
        await self._cancel_next_level(order)
        
        self._adjust_order_levels()
        
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
            notify_take_profit(order, profit, self.trader.config)
        else:
            order.state = "closed"
            order.close_reason = "stop_loss"
            self.trader.results["loss_trades"] += 1
            self.trader.results["total_loss"] += abs(profit)
            logger.info(f"[止损] A{order.level}: 亏损={profit:.2f}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 A{order.level} 止损: 亏损={profit:.2f} USDT")
            notify_stop_loss(order, profit, self.trader.config)
        
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
        state_repository: 状态持久化仓库
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
    
    def __init__(self, config: Dict[str, Any], testnet: bool = True):
        self.config = config
        self.testnet = testnet
        
        state_file = STATE_FILE
        self.chain_state: Optional[Any] = None
        self.state_repository = StateRepository(state_file)
        self.running = True
        self.exit_notified = False
        self._shutdown_event = asyncio.Event()
        
        from autofish_core import Autofish_WeightCalculator
        self.calculator = Autofish_WeightCalculator(Decimal(str(config.get("decay_factor", 0.5))))
        
        api_key = config.get("api_key", "")
        api_secret = config.get("api_secret", "")
        
        self.proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None
        
        self.client = BinanceClient(api_key, api_secret, testnet, proxy=self.proxy)
        
        self.algo_handler = AlgoHandler(self)
        
        self.price_precision = 2
        self.qty_precision = 3
        
        self.ws = None
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
        except Exception as e:
            logger.warning(f"[K线获取] 异常: {e}")
            return []
    
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
        min_notional = getattr(self, 'min_notional', Decimal("100"))
        total_amount = Decimal(str(self.config.get('total_amount_quote', 1200)))
        max_entries = self.config.get('max_entries', 4)
        
        results = []
        all_satisfied = True
        
        for level in range(1, max_entries + 1):
            weight_pct = self.calculator.get_weight_percentage(level)
            weight = Decimal(str(weight_pct)) / Decimal("100")
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
        
        min_weight = min(r['weight'] for r in results)
        suggested_min_amount = min_notional / Decimal(str(min_weight))
        
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
            notify_critical_error(error_msg, self.config)
            
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
            notify_warning(warning_msg, self.config)
            
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
            send_wechat_notification("✅ Autofish V2 配置确认", content)
            
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
        if self.chain_state:
            try:
                self.state_repository.save(self.chain_state.to_dict())
            except Exception as e:
                logger.error(f"[状态保存] 保存失败: {e}")
    
    def _load_state(self) -> Optional[Dict[str, Any]]:
        return self.state_repository.load()
    
    async def _create_order(self, level: int, base_price: Decimal, klines: List[Dict] = None) -> Any:
        from autofish_core import Autofish_OrderCalculator, EntryPriceStrategyFactory
        
        # 从配置创建入场价格策略
        strategy_config = self.config.get("entry_price_strategy", {"name": "fixed"})
        strategy = EntryPriceStrategyFactory.create(
            strategy_config.get("name", "fixed"),
            **strategy_config.get("params", {})
        )
        
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=self.config.get("grid_spacing", Decimal("0.01")),
            exit_profit=self.config.get("exit_profit", Decimal("0.01")),
            stop_loss=self.config.get("stop_loss", Decimal("0.08")),
            entry_strategy=strategy
        )
        
        order = order_calculator.create_order(
            level=level,
            base_price=base_price,
            total_amount=self.config.get("total_amount_quote", Decimal("1200")),
            weight_calculator=self.calculator,
            klines=klines
        )
        
        order.quantity = self._adjust_quantity(order.quantity, order.entry_price)
        order.entry_price = self._adjust_price(order.entry_price)
        order.take_profit_price = self._adjust_price(order.take_profit_price)
        order.stop_loss_price = self._adjust_price(order.stop_loss_price)
        
        return order
    
    def _setup_signal_handlers(self) -> None:
        def signal_handler(signum, frame):
            signal_name = signal.Signals(signum).name
            logger.info(f"[信号处理] 收到信号 {signal_name}")
            print(f"\n\n⏹️ 收到信号 {signal_name}，程序即将退出")
            
            if self.exit_notified:
                raise KeyboardInterrupt(f"收到信号 {signal_name}")
            
            self.running = False
            self._shutdown_event.set()
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    
    async def _handle_exit(self, reason: str) -> None:
        """处理程序退出
        
        执行退出前的清理工作：
        1. 取消所有挂单
        2. 保存当前状态
        3. 发送退出通知
        
        参数:
            reason: 退出原因
        """
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
            
            notify_exit(reason, self.config, cancelled_orders, remaining_orders, 
                       pnl_info, current_price)
            
        except Exception as e:
            logger.error(f"[退出处理] 处理失败: {e}")
    
    async def _place_entry_order(self, order: Any, is_supplement: bool = False) -> None:
        """下单入场单
        
        创建并提交一个限价买入订单。如果订单金额小于 Binance 最小要求（100 USDT），
        会自动调整数量以满足要求。
        
        参数:
            order: 订单对象，包含入场价、数量等信息
            is_supplement: 是否为补下订单（状态恢复时补下）
        
        副作用:
            - 更新 order.order_id
            - 更新 order.quantity（可能被调整）
            - 更新 order.stake_amount
            - 保存状态到文件
            - 发送微信通知
        """
        symbol = self.config.get("symbol", "BTCUSDT")
        
        price = self._adjust_price(order.entry_price)
        quantity = self._adjust_quantity(order.quantity, price)
        
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
            
            weight_pct = self.calculator.get_weight_percentage(order.level)
            
            if not is_supplement:
                print(f"\n{'='*60}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 下单成功: A{order.level}")
                print(f"{'='*60}")
            
            print(f"  层级: A{order.level} / {self.config.get('max_entries', 4)}")
            print(f"  权重: {weight_pct:.2f}%")
            print(f"  入场价: {price:.{self.price_precision}f}")
            print(f"  数量: {order.quantity:.6f} BTC")
            print(f"  金额: {order.stake_amount:.2f} USDT")
            print(f"  止盈价: {order.take_profit_price:.2f}")
            print(f"  止损价: {order.stop_loss_price:.2f}")
            print(f"  订单ID: {order.order_id}")
            print(f"{'='*60}\n")
            
            if is_supplement:
                logger.info(f"入场单补下成功: A{order.level}, orderId={order.order_id}")
                notify_entry_order_supplement(order, self.config)
            else:
                logger.info(f"入场单下单成功: A{order.level}, orderId={order.order_id}")
                notify_entry_order(order, self.config)
            
            self._save_state()
        else:
            error_msg = "补下失败" if is_supplement else "下单失败"
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
        
        if place_tp:
            tp_trigger_price = self._adjust_price(order.take_profit_price)
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
        
        if place_sl:
            sl_trigger_price = self._adjust_price(order.stop_loss_price)
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
        
        self._save_state()
    
    async def _cancel_all_orders(self) -> List[Any]:
        cancelled_orders = []
        symbol = self.config.get("symbol", "BTCUSDT")
        
        for order in self.chain_state.orders:
            if order.state == "pending" and order.order_id:
                try:
                    await self.client.cancel_order(symbol, order.order_id)
                    cancelled_orders.append(order)
                    logger.info(f"[取消订单] A{order.level} orderId={order.order_id}")
                except Exception as e:
                    logger.warning(f"[取消订单] 失败 A{order.level}: {e}")
        
        return cancelled_orders
    
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
        
        程序重启后从本地文件恢复订单状态，并与 Binance 同步。
        
        主要流程：
        1. 加载本地保存的状态
        2. 查询 Binance 订单状态
        3. 同步本地状态（检测成交、取消等）
        4. 检查止盈止损单是否存在
        5. 补充缺失的止盈止损单
        
        参数:
            current_price: 当前价格
        
        返回:
            bool: 是否需要创建新订单（如果没有恢复到任何订单）
        
        副作用:
            - 更新 self.chain_state
            - 保存状态到文件
            - 发送通知
        """
        symbol = self.config.get("symbol", "BTCUSDT")
        state_data = self._load_state()
        need_new_order = True
        
        if state_data:
            from autofish_core import Autofish_ChainState
            saved_state = Autofish_ChainState.from_dict(state_data)
            
            if saved_state and saved_state.orders:
                logger.info(f"[状态恢复] 发现本地保存的状态: {len(saved_state.orders)} 个订单")
                print(f"\n🔄 发现本地保存的状态: {len(saved_state.orders)} 个订单")
                
                self.chain_state = saved_state
                self.chain_state.base_price = current_price
                
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
                                logger.error(f"[状态同步] 查询 Binance 订单状态失败: {e}")
                    
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
                
                if self.chain_state.orders:
                    self.chain_state.orders.sort(key=lambda o: o.level)
                    for new_level, order in enumerate(self.chain_state.orders, start=1):
                        old_level = order.level
                        if old_level != new_level:
                            order.level = new_level
                            logger.info(f"[级别调整] A{old_level} -> A{new_level}")
                            print(f"   📊 A{old_level} 级别调整为 A{new_level}")
                
                self._save_state()
                
                for order, filled_price in orders_need_process:
                    await self._process_order_filled(order, filled_price, is_recovery=True)
                
                if self.chain_state.orders:
                    pnl_info = await self._get_pnl_info()
                    notify_orders_recovered(self.chain_state.orders, self.config, current_price, pnl_info or {})
                
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
            
            order.state = "closed"
            order.close_reason = reason
            logger.info(f"[市价平仓] A{order.level} 成功: orderId={result.get('orderId')}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 A{order.level} 市价平仓成功")
            
            self._save_state()
            
        except Exception as e:
            logger.error(f"[市价平仓] A{order.level} 失败: {e}")
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
            from autofish_core import Autofish_ChainState
            order = await self._create_order(1, current_price, klines)
            self.chain_state = Autofish_ChainState(base_price=current_price, orders=[order])
            await self._place_entry_order(order)
    
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
        print(f"  日志文件: {LOG_DIR}/{LOG_FILE}")
        print(f"  状态文件: {STATE_FILE}")
        print(f"{'='*60}\n")
        
        logger.info(f"[启动] 交易对={self.config.get('symbol')}, 测试网={self.testnet}, 总投入={self.config.get('total_amount')}")
        
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        
        try:
            while self.running:
                try:
                    await self._init_precision()
                    
                    current_price = await self._get_current_price()
                    
                    # 发送启动通知
                    notify_startup(self.config, current_price)
                    
                    # 预检查资金是否充足
                    if not await self._check_fund_sufficiency():
                        await self.client.close()
                        return
                    
                    need_new_order = await self._restore_orders(current_price)
                    
                    # 处理入场单补充
                    await self._handle_entry_supplement(current_price, need_new_order)
                    
                    self.consecutive_errors = 0
                    
                    await self._ws_loop()
                    
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
                    logger.error(f"[运行] 发生异常 ({self.consecutive_errors}/{self.max_consecutive_errors}): {e}")
                    
                    if self.consecutive_errors >= self.max_consecutive_errors:
                        logger.error(f"[运行] 连续错误 {self.consecutive_errors} 次，退出")
                        await self._handle_exit(f"连续错误 {self.consecutive_errors} 次: {e}")
                        break
                    else:
                        notify_critical_error(str(e), self.config)
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
                logger.error(f"[WebSocket] 连接错误: {e}")
                
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
        
        根据事件类型分发处理：
        - ORDER_TRADE_UPDATE: 订单状态变化
        - listenKeyExpired: listen key 过期
        
        参数:
            data: WebSocket 消息数据
        """
        event_type = data.get("e")
        
        if event_type == "ORDER_TRADE_UPDATE":
            order_data = data.get("o", {})
            await self._handle_order_update(order_data)
        
        elif event_type == "listenKeyExpired":
            logger.warning("[WebSocket] listen key 过期")
            self.ws_connected = False
    
    async def _handle_order_update(self, order_data: Dict[str, Any]) -> None:
        """处理订单状态更新
        
        根据 Binance 订单状态执行相应处理：
        - FILLED: 订单成交，下止盈止损单，发通知，下下一级订单
        - CANCELED/EXPIRED: 订单取消，删除本地订单
        
        参数:
            order_data: Binance 订单数据
        """
        order_id = order_data.get("orderId")
        order_status = order_data.get("orderStatus")
        
        order = None
        for o in self.chain_state.orders:
            if o.order_id == order_id:
                order = o
                break
        
        if not order:
            return
        
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
        if is_recovery:
            logger.info(f"[状态恢复] A{order.level} 检测到成交，执行后续处理")
            print(f"   ⚡ A{order.level} 检测到成交，执行后续处理")
        
        order.state = "filled"
        order.entry_price = filled_price
        
        await self._place_exit_orders(order)
        
        commission = Decimal("0")
        notify_entry_filled(order, filled_price, commission, self.config)
        
        await self._place_next_level_order(order)
        
        self._save_state()
    
    async def _handle_order_filled(self, order: Any, order_data: Dict[str, Any]) -> None:
        """WebSocket 实时成交处理"""
        logger.info(f"[订单成交] A{order.level}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 入场成交 A{order.level}")
        
        filled_price = Decimal(str(order_data.get("avgPrice", order.entry_price)))
        await self._process_order_filled(order, filled_price)
    
    async def _handle_order_cancelled(self, order: Any, order_data: Dict[str, Any]) -> None:
        logger.info(f"[订单取消] A{order.level}")
        
        await self._cancel_algo_orders_for_order(order)
        
        self.chain_state.orders.remove(order)
        
        self._save_state()
    
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
        next_level = order.level + 1
        max_level = self.config.get("max_entries", 4)
        
        if next_level > max_level:
            return
        
        has_next = any(o.level == next_level for o in self.chain_state.orders)
        if has_next:
            return
        
        current_price = await self._get_current_price()
        klines = await self._get_recent_klines()
        new_order = await self._create_order(next_level, current_price, klines)
        self.chain_state.orders.append(new_order)
        
        await self._place_entry_order(new_order)

async def main():
    """主函数"""
    import argparse
    from dotenv import load_dotenv
    from autofish_core import Autofish_AmplitudeConfig, Autofish_OrderCalculator
    
    parser = argparse.ArgumentParser(description="Autofish V2 Binance 实盘交易")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对 (默认: BTCUSDT)")
    parser.add_argument("--testnet", action="store_true", help="使用测试网")
    parser.add_argument("--no-testnet", action="store_true", help="使用主网")
    parser.add_argument("--stop-loss", type=float, default=0.08, help="止损比例 (默认: 0.08)")
    parser.add_argument("--total-amount", type=float, default=10000, help="总投入金额 USDT (默认: 10000)")
    parser.add_argument("--decay-factor", type=float, default=0.5, help="衰减因子 (默认: 0.5)")
    
    args = parser.parse_args()
    
    load_dotenv()
    
    setup_logger(name="autofish", log_file=LOG_FILE)
    
    testnet = not args.no_testnet if args.no_testnet else args.testnet
    if testnet:
        api_key = os.getenv("BINANCE_TESTNET_API_KEY", "")
        api_secret = os.getenv("BINANCE_TESTNET_SECRET_KEY", "")
    else:
        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_SECRET_KEY", "")
    
    decay_factor = Decimal(str(args.decay_factor))
    amplitude_config = Autofish_AmplitudeConfig.load_latest(args.symbol, decay_factor=decay_factor)
    if amplitude_config:
        config = {
            "symbol": amplitude_config.get_symbol(),
            "leverage": amplitude_config.get_leverage(),
            "grid_spacing": amplitude_config.get_grid_spacing(),
            "exit_profit": amplitude_config.get_exit_profit(),
            "stop_loss": amplitude_config.get_stop_loss(),
            "total_amount_quote": amplitude_config.get_total_amount_quote(),
            "max_entries": amplitude_config.get_max_entries(),
            "decay_factor": amplitude_config.get_decay_factor(),
            "weights": amplitude_config.get_weights(),
            "valid_amplitudes": amplitude_config.get_valid_amplitudes(),
            "total_expected_return": amplitude_config.get_total_expected_return(),
            "entry_price_strategy": amplitude_config.get_entry_price_strategy(),
        }
        config_file = amplitude_config.config_path
    else:
        config = Autofish_OrderCalculator.get_default_config("binance")
        config["symbol"] = args.symbol
        config["decay_factor"] = decay_factor
        config.update({
            "stop_loss": Decimal(str(args.stop_loss)),
            "total_amount_quote": Decimal(str(args.total_amount)),
        })
        config_file = "无（使用内置默认配置）"
    
    config["api_key"] = api_key
    config["api_secret"] = api_secret
    
    logger.info(f"[配置加载] {'使用振幅分析配置' if amplitude_config else '使用默认配置'}: {args.symbol}")
    logger.info(f"  配置文件: {config_file}")
    logger.info(f"  交易标的: {config.get('symbol')}")
    logger.info(f"  交易杠杆: {config['leverage']}x")
    logger.info(f"  资金投入: {config['total_amount_quote']} USDT")
    logger.info(f"  网格间距: {float(config['grid_spacing'])*100:.1f}%")
    logger.info(f"  止盈比例: {float(config['exit_profit'])*100:.1f}%")
    logger.info(f"  止损比例: {float(config['stop_loss'])*100:.1f}%")
    logger.info(f"  衰减因子: {float(decay_factor)}")
    logger.info(f"  最大层级: {config['max_entries']}")
    logger.info(f"  网格权重: {config.get('weights', [])}")
    
    trader = BinanceLiveTrader(config, testnet=testnet)
    await trader.run()


if __name__ == "__main__":
    asyncio.run(main())


__all__ = [
    "BinanceClient",           # API 客户端类
    "BinanceLiveTrader",       # 实盘交易者类
    "AlgoHandler",             # Algo 条件单处理器
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
    "StateRepository",         # 状态仓库类
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
    "get_next_message_number", # 消息计数器
]
