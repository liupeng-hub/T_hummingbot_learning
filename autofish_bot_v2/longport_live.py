"""
LongPort 交易所模块

整合 LongPort 股票交易的所有功能：
- LongPortClient: API 客户端（行情、交易、订单管理）
- LongPortLiveTrader: 实盘交易者（链式挂单策略）
- 自定义异常类
- 日志配置
- 重试机制
- 状态管理
- 通知服务

注意：LongPort 不支持服务器端条件单，需要客户端监控价格触发止盈止损。
"""

import os
import json
import asyncio
import functools
import logging
import signal
import sys
import requests
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Optional, Dict, Any, List, Callable, Tuple, Type

from longport.openapi import Config, QuoteContext, TradeContext, OrderType, OrderSide, TimeInForceType


# ============================================================================
# 日志配置
# ============================================================================

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class FlushFileHandler(logging.FileHandler):
    """每次写入后自动刷新的 FileHandler"""
    def emit(self, record):
        super().emit(record)
        self.flush()


def setup_logger(
    name: str = "autofish",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    log_dir: str = "logs",
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
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


class LoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = self.extra or {}
        prefix = " | ".join(f"{k}={v}" for k, v in extra.items())
        if prefix:
            return f"[{prefix}] {msg}", kwargs
        return msg, kwargs


logger = logging.getLogger(__name__)


# ============================================================================
# 自定义异常类
# ============================================================================

class NetworkError(Exception):
    def __init__(self, message: str, original_error: Exception = None):
        self.message = message
        self.original_error = original_error
        super().__init__(f"Network Error: {message}")


class OrderError(Exception):
    def __init__(self, level: int, order_id: str, message: str):
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
            > **入场价**: {order.entry_price:.2f}
            > **数量**: {order.quantity} 股
            > **金额**: {order.stake_amount:.2f}""").strip()
    
    def format_order_prices(self, order) -> str:
        return dedent(f"""\
            > **止盈价**: {order.take_profit_price:.2f} (+{self.exit_profit_pct:.1f}%)
            > **止损价**: {order.stop_loss_price:.2f} (-{self.stop_loss_pct:.1f}%)""").strip()
    
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
                lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl} ({roi_prefix}{roi}%)")
            elif unrealized_pnl:
                pnl_prefix = "+" if float(unrealized_pnl) > 0 else ""
                lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl}")
            else:
                lines.append(f"> **未实现盈亏**: N/A")
            
            lines.append(f"> **已实现盈亏**: {pnl_info.get('realized_pnl', 'N/A')}")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_timestamp() -> str:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def send_wechat_notification(title: str, content: str):
    wechat_bot_key = os.getenv("WECHAT_BOT_KEY")
    serverchan_key = os.getenv("SERVERCHAN_KEY")
    
    if wechat_bot_key:
        try:
            webhook_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={wechat_bot_key}"
            data = {
                "msgtype": "markdown",
                "markdown": {
                    "content": f"# {title}\n\n{content}"
                }
            }
            response = requests.post(webhook_url, json=data, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    logger.info(f"[通知发送] 微信机器人发送成功: {title}")
                else:
                    logger.warning(f"[通知发送] 微信机器人发送失败: {result}")
            else:
                logger.warning(f"[通知发送] 微信机器人请求失败: {response.status_code}")
        except Exception as e:
            logger.warning(f"[通知发送] 微信机器人发送异常: {e}")
    
    if serverchan_key:
        try:
            url = f"https://sctapi.ftqq.com/{serverchan_key}.send"
            data = {
                "title": title,
                "desp": content
            }
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    logger.info(f"[通知发送] Server酱发送成功: {title}")
                else:
                    logger.warning(f"[通知发送] Server酱发送失败: {result}")
            else:
                logger.warning(f"[通知发送] Server酱请求失败: {response.status_code}")
        except Exception as e:
            logger.warning(f"[通知发送] Server酱发送异常: {e}")
    
    if not wechat_bot_key and not serverchan_key:
        logger.warning("[通知发送] 未配置微信通知 Key，跳过发送")


def notify_entry_order(order, config: dict):
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""\
        > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
        > **入场价**: {order.entry_price:.2f}
        > **数量**: {order.quantity} 股
        > **金额**: {order.stake_amount:.2f}
        > **止盈价**: {order.take_profit_price:.2f} (+{float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%)
        > **止损价**: {order.stop_loss_price:.2f} (-{float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%)
        > **订单ID**: {order.order_id}
        > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}""").strip()
    
    send_wechat_notification(f"🟢 入场单下单 A{order.level}", content)


def notify_entry_filled(order, filled_price: Decimal, commission: Decimal, config: dict):
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""
            > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
            > **成交价**: {filled_price:.2f}
            > **数量**: {order.quantity} 股
            > **金额**: {order.stake_amount:.2f}
            > **止盈价**: {order.take_profit_price:.2f} (+{float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%)
            > **止损价**: {order.stop_loss_price:.2f} (-{float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%)
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification(f"✅ 入场成交 A{order.level}", content)


def notify_take_profit(order, profit: Decimal, config: dict):
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""
            > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
            > **止盈价**: {order.take_profit_price:.2f}
            > **盈亏**: +{profit:.2f}
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification(f"🎯 止盈触发 A{order.level}", content)


def notify_stop_loss(order, profit: Decimal, config: dict):
    max_entries = config.get('max_entries', 4)
    content = dedent(f"""
            > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
            > **止损价**: {order.stop_loss_price:.2f}
            > **盈亏**: {profit:.2f}
            > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification(f"🛑 止损触发 A{order.level}", content)


def notify_orders_recovered(orders: list, config: dict, current_price: Decimal, pnl_info: dict = None):
    max_entries = config.get('max_entries', 4)
    symbol = config.get('symbol', '700.HK')
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
                > 入场价: {order.entry_price:.2f}
                > 止盈价: {order.take_profit_price:.2f} (+{exit_profit_pct:.1f}%)
                > 止损价: {order.stop_loss_price:.2f} (-{stop_loss_pct:.1f}%)
                > 订单ID: {order.order_id}"""))
        elif order.state == 'filled':
            order_lines.append(dedent(f"""\
                **A{order.level}** `{state_text}` `{level_text}`
                > 入场价: {order.entry_price:.2f}
                > 止盈价: {order.take_profit_price:.2f} (+{exit_profit_pct:.1f}%)
                > 止损价: {order.stop_loss_price:.2f} (-{stop_loss_pct:.1f}%)"""))
        elif order.state == 'closed':
            close_reason = "止盈" if order.close_reason == "take_profit" else "止损"
            profit_text = f"+{order.profit:.2f}" if order.profit and order.profit > 0 else f"{order.profit:.2f}" if order.profit else "0.00"
            order_lines.append(dedent(f"""\
                **A{order.level}** `{state_text}` `{level_text}` ({close_reason})
                > 入场价: {order.entry_price:.2f}
                > 盈亏: {profit_text}"""))
        else:
            order_lines.append(dedent(f"""\
                **A{order.level}** `{state_text}` `{level_text}`"""))
    
    orders_content = "\n\n".join(order_lines)
    
    content_lines = [
        f"> **交易标的**: {symbol}",
        f"> **当前价格**: {current_price:.2f}",
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
                content_lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl} ({roi_prefix}{roi}%)")
            elif unrealized_pnl:
                pnl_prefix = "+" if float(unrealized_pnl) > 0 else ""
                content_lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl}")
            else:
                content_lines.append(f"> **未实现盈亏**: N/A")
            
            content_lines.append(f"> **已实现盈亏**: {pnl_info.get('realized_pnl', 'N/A')}")
    
    content = "\n".join(content_lines)
    send_wechat_notification("🔄 订单同步", content)


def notify_exit(reason: str, config: dict, cancelled_orders: list = None, remaining_orders: list = None, pnl_info: dict = None, current_price: Decimal = None):
    symbol = config.get('symbol', '700.HK')
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
        content_lines.append(f"> **当前价格**: {current_price:.2f}")
    
    if cancelled_orders:
        content_lines.append("")
        content_lines.append("### 📋 已取消的挂单")
        for order in cancelled_orders:
            level_text = f"第{order.level}层/共{max_level}层"
            content_lines.append(dedent(f"""\
                **A{order.level}** `已取消` `{level_text}`
                > 入场价: {order.entry_price:.2f}
                > 金额: {order.stake_amount:.2f}
                > 数量: {order.quantity} 股
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
                > 入场价: {order.entry_price:.2f}
                > 止盈价: {order.take_profit_price:.2f} (+{exit_profit_pct:.1f}%)
                > 止损价: {order.stop_loss_price:.2f} (-{stop_loss_pct:.1f}%)"""))
    
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
                content_lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl} ({roi_prefix}{roi}%)")
            elif unrealized_pnl:
                pnl_prefix = "+" if float(unrealized_pnl) > 0 else ""
                content_lines.append(f"> **未实现盈亏**: {pnl_prefix}{unrealized_pnl}")
            else:
                content_lines.append(f"> **未实现盈亏**: N/A")
            
            content_lines.append(f"> **已实现盈亏**: {pnl_info.get('realized_pnl', 'N/A')}")
    
    content_lines.append("")
    content_lines.append("请检查程序状态并手动重启。")
    
    content = "\n".join(content_lines)
    send_wechat_notification("⏹️ Autofish V1 退出", content)


def notify_startup(config: dict, current_price: Decimal):
    symbol = config.get('symbol', '700.HK')
    currency = _get_currency_from_symbol(symbol)
    
    weights_str = ""
    weights = config.get('weights', [])
    if weights:
        weights_str = "> **网格权重**: " + ", ".join([f"A{i+1}: {w*100:.1f}%" for i, w in enumerate(weights)])
    
    content = dedent(f"""
            > **交易标的**: {symbol}
            > **当前价格**: {current_price:.2f} {currency}
            > **资金投入**: {config.get('total_amount_quote', 1200)} {currency}
            > **网格间距**: {float(config.get('grid_spacing', Decimal('0.01')))*100:.1f}%
            > **止盈比例**: {float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%
            > **止损比例**: {float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%
            > **衰减因子**: {config.get('decay_factor', 0.5)}
            > **最大层级**: {config.get('max_entries', 4)}
            {weights_str}
            > **启动时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """).strip()
    send_wechat_notification("🚀 Autofish V2 启动", content)


# ============================================================================
# LongPort 客户端
# ============================================================================

class LongPortClient:
    """LongPort API 客户端
    
    封装 LongPort SDK 的行情和交易接口。
    
    主要功能：
    - 行情查询（实时价格、K线数据）
    - 订单管理（下单、撤单、查询）
    - 仓位查询
    - 账户查询
    
    注意：LongPort 不支持服务器端条件单，需要客户端监控价格触发止盈止损。
    
    Attributes:
        app_key: LongPort App Key
        app_secret: LongPort App Secret
        access_token: LongPort Access Token
        quote_ctx: 行情上下文
        trade_ctx: 交易上下文
    
    示例:
        >>> client = LongPortClient(app_key, app_secret, access_token)
        >>> await client.connect()
        >>> price = await client.get_current_price("700.HK")
    """
    
    def __init__(self, app_key: str, app_secret: str, access_token: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token
        
        self.quote_ctx: Optional[QuoteContext] = None
        self.trade_ctx: Optional[TradeContext] = None
    
    async def connect(self) -> None:
        config = Config.from_env()
        self.quote_ctx = QuoteContext(config)
        self.trade_ctx = TradeContext(config)
        logger.info("[LongPort] 连接成功")
    
    async def place_order(self, symbol: str, side: OrderSide, order_type: OrderType,
                         quantity: int, price: Decimal, remark: str = None) -> Dict[str, Any]:
        if self.trade_ctx is None:
            await self.connect()
        
        result = self.trade_ctx.submit_order(
            symbol=symbol,
            order_type=order_type,
            side=side,
            submitted_quantity=Decimal(str(quantity)),
            submitted_price=price,
            time_in_force=TimeInForceType.Day,
            remark=remark,
        )
        
        return {"order_id": result.order_id}
    
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if self.trade_ctx is None:
            await self.connect()
        
        self.trade_ctx.cancel_order(order_id)
        return {"success": True}
    
    async def get_positions(self, symbol: str = None) -> List[Dict[str, Any]]:
        if self.trade_ctx is None:
            await self.connect()
        
        positions = self.trade_ctx.stock_positions()
        
        result = []
        for pos in positions:
            if symbol and pos.symbol != symbol:
                continue
            
            result.append({
                "symbol": pos.symbol,
                "quantity": str(pos.quantity),
                "available_quantity": str(pos.available_quantity),
                "average_price": str(pos.cost_price) if pos.cost_price else "0",
            })
        
        return result
    
    async def get_open_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        if self.trade_ctx is None:
            await self.connect()
        
        orders = self.trade_ctx.today_orders()
        
        result = []
        for order in orders:
            if symbol and order.symbol != symbol:
                continue
            
            result.append({
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": str(order.side),
                "order_type": str(order.order_type),
                "quantity": str(order.quantity),
                "price": str(order.price) if order.price else None,
                "status": str(order.status),
            })
        
        return result
    
    async def get_current_price(self, symbol: str) -> Decimal:
        if self.quote_ctx is None:
            await self.connect()
        
        quotes = self.quote_ctx.quotes([symbol])
        if quotes:
            return Decimal(str(quotes[0].last_done))
        return Decimal("0")
    
    async def get_account_balance(self, currency: str = None) -> List[Dict[str, Any]]:
        if self.trade_ctx is None:
            await self.connect()
        
        balance = self.trade_ctx.account_balance()
        
        result = []
        for item in balance:
            if currency and item.currency != currency:
                continue
            
            result.append({
                "currency": item.currency,
                "available_cash": str(item.available_cash) if item.available_cash else "0",
                "frozen_cash": str(item.frozen_cash) if item.frozen_cash else "0",
            })
        
        return result
    
    async def close(self) -> None:
        if self.quote_ctx:
            self.quote_ctx = None
        
        if self.trade_ctx:
            self.trade_ctx = None
        
        logger.info("[LongPort] 连接已关闭")


# ============================================================================
# LongPort 实盘交易者
# ============================================================================

def _get_currency_from_symbol(symbol: str) -> str:
    if ".HK" in symbol.upper():
        return "HKD"
    elif ".US" in symbol.upper():
        return "USD"
    elif ".SH" in symbol.upper() or ".SZ" in symbol.upper():
        return "CNY"
    return "USD"


class LongPortLiveTrader:
    """LongPort 实盘交易器
    
    实现链式挂单策略的股票实盘交易，支持港股、美股、A股。
    
    主要功能：
    1. 状态恢复：程序重启后从本地文件恢复订单状态
    2. 价格监控：客户端监控价格触发止盈止损（LongPort 不支持服务器端条件单）
    3. 补单机制：检测并补充缺失的止盈止损单
    4. 异常处理：错误重试、通知和恢复
    
    与 Binance 版本的主要区别：
    - LongPort 不支持服务器端条件单，需要客户端轮询价格
    - 股票交易有最小交易单位（港股 100 股/手）
    - 股票交易无杠杆
    
    Attributes:
        config: 配置字典（symbol, total_amount, lot_size 等）
        client: LongPortClient 实例
        chain_state: 链式挂单状态
        state_repository: 状态持久化仓库
        running: 运行标志
        lot_size: 最小交易单位（港股 100，美股 1）
        calculator: 权重计算器
    
    示例:
        >>> config = {"symbol": "700.HK", "total_amount": 12000, ...}
        >>> trader = LongPortLiveTrader(config)
        >>> await trader.run()
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        state_file = f"longport_live_state_{config.get('symbol', '700.HK')}.json"
        self.chain_state: Optional[Any] = None
        self.state_repository = StateRepository(state_file)
        self.running = True
        self.exit_notified = False
        self._shutdown_event = asyncio.Event()
        
        from autofish_core import Autofish_WeightCalculator
        self.calculator = Autofish_WeightCalculator(Decimal(str(config.get("decay_factor", 0.5))))
        
        app_key = config.get("app_key", "")
        app_secret = config.get("app_secret", "")
        access_token = config.get("access_token", "")
        self.client = LongPortClient(app_key, app_secret, access_token)
        
        symbol = config.get("symbol", "700.HK")
        if ".HK" in symbol.upper():
            self.lot_size = 100
        elif ".US" in symbol.upper():
            self.lot_size = 1
        elif ".SH" in symbol.upper() or ".SZ" in symbol.upper():
            self.lot_size = 100
        else:
            self.lot_size = config.get("lot_size", 100)
        
        self.results = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "total_profit": Decimal("0"),
            "total_loss": Decimal("0"),
        }
    
    def _get_currency(self) -> str:
        return _get_currency_from_symbol(self.config.get("symbol", "700.HK"))
    
    def _get_weights(self) -> Dict[int, Decimal]:
        """获取权重"""
        weights_list = self.config.get("weights", [])
        if not weights_list:
            return {}
        weights = {}
        for i, w in enumerate(weights_list):
            weights[i + 1] = Decimal(str(w))
        return weights
    
    def _save_state(self) -> None:
        if self.chain_state:
            try:
                self.state_repository.save(self.chain_state.to_dict())
            except Exception as e:
                logger.error(f"[状态保存] 保存失败: {e}")
    
    def _load_state(self) -> Optional[Dict[str, Any]]:
        return self.state_repository.load()
    
    def _create_order(self, level: int, base_price: Decimal) -> Any:
        from autofish_core import Autofish_OrderCalculator
        
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=self.config.get("grid_spacing", Decimal("0.01")),
            exit_profit=self.config.get("exit_profit", Decimal("0.01")),
            stop_loss=self.config.get("stop_loss", Decimal("0.08"))
        )
        
        return order_calculator.create_order(
            level=level,
            base_price=base_price,
            total_amount=self.config.get("total_amount_quote", Decimal("1200")),
            weight_calculator=self.calculator
        )
    
    def _setup_signal_handlers(self) -> None:
        def signal_handler(signum, frame):
            logger.info(f"[信号处理] 收到信号 {signum}")
            self.running = False
            self._shutdown_event.set()
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    
    async def _handle_exit(self, reason: str) -> None:
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
    
    def _get_quantity(self, stake_amount: Decimal, price: Decimal) -> int:
        """获取股票数量（股票交易需要整数股）"""
        quantity = stake_amount / price
        return int(quantity // self.lot_size) * self.lot_size
    
    def _adjust_quantity(self, quantity: Decimal) -> int:
        shares = int(quantity / self.lot_size) * self.lot_size
        return max(shares, self.lot_size)
    
    async def _place_entry_order(self, order: Any, is_supplement: bool = False) -> None:
        symbol = self.config.get("symbol", "700.HK")
        currency = self._get_currency()
        
        quantity = self._adjust_quantity(order.quantity)
        
        result = await self.client.place_order(
            symbol=symbol,
            side=OrderSide.Buy,
            order_type=OrderType.LO,
            quantity=quantity,
            price=order.entry_price,
            remark=f"Autofish A{order.level}"
        )
        
        if "order_id" in result:
            order.order_id = result["order_id"]
            order.quantity = Decimal(str(quantity))
            
            weight_pct = self.calculator.get_weight_percentage(order.level)
            
            if not is_supplement:
                print(f"\n{'='*60}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 下单成功: A{order.level}")
                print(f"{'='*60}")
            
            print(f"  层级: A{order.level} / {self.config.get('max_entries', 4)}")
            print(f"  权重: {weight_pct:.2f}%")
            print(f"  入场价: {order.entry_price:.2f} {currency}")
            print(f"  数量: {quantity} 股")
            print(f"  金额: {order.stake_amount:.2f} {currency}")
            print(f"  止盈价: {order.take_profit_price:.2f} {currency}")
            print(f"  止损价: {order.stop_loss_price:.2f} {currency}")
            print(f"  订单ID: {order.order_id}")
            print(f"{'='*60}\n")
            
            if is_supplement:
                logger.info(f"入场单补下成功: A{order.level}, orderId={order.order_id}")
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
        logger.info(f"[止盈止损设置] A{order.level}: TP={order.take_profit_price}, SL={order.stop_loss_price}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📋 止盈止损已记录: A{order.level}")
        print(f"  止盈价: {order.take_profit_price:.2f}")
        print(f"  止损价: {order.stop_loss_price:.2f}")
        print(f"  （客户端监控中...）")
        
        self._save_state()
    
    async def _cancel_all_orders(self) -> List[Any]:
        cancelled_orders = []
        
        for order in self.chain_state.orders:
            if order.state == "pending" and order.order_id:
                try:
                    await self.client.cancel_order(order.order_id)
                    cancelled_orders.append(order)
                    logger.info(f"[取消订单] A{order.level} orderId={order.order_id}")
                except Exception as e:
                    logger.warning(f"[取消订单] 失败 A{order.level}: {e}")
        
        return cancelled_orders
    
    async def _get_current_price(self) -> Decimal:
        symbol = self.config.get("symbol", "700.HK")
        return await self.client.get_current_price(symbol)
    
    async def _get_pnl_info(self) -> Optional[Dict[str, Any]]:
        try:
            symbol = self.config.get("symbol", "700.HK")
            positions = await self.client.get_positions(symbol)
            if positions:
                pos = positions[0]
                quantity = Decimal(pos.get("quantity", "0"))
                avg_price = Decimal(pos.get("average_price", "0"))
                
                current_price = await self._get_current_price()
                unrealized_pnl = (current_price - avg_price) * quantity
                
                roi = None
                if avg_price > 0 and quantity > 0:
                    roi = float(unrealized_pnl / (avg_price * quantity) * 100)
                
                return {
                    "position_qty": str(quantity),
                    "entry_price": f"{avg_price:.2f}",
                    "unrealized_pnl": f"{unrealized_pnl:.2f}",
                    "roi": f"{roi:.2f}" if roi is not None else None,
                    "realized_pnl": "N/A"
                }
        except Exception as e:
            logger.warning(f"[获取盈亏信息] 失败: {e}")
        
        return None
    
    async def _execute_entry(self, order: Any, current_price: Decimal) -> None:
        """执行入场成交"""
        order.state = "filled"
        
        logger.info(f"[入场成交] A{order.level}: 价格={current_price:.2f}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ A{order.level} 成交: 价格={current_price:.2f}")
        
        notify_entry_filled(order, current_price, Decimal("0"), self.config)
        
        await self._place_exit_orders(order)
        
        next_level = order.level + 1
        max_level = self.config.get("max_entries", 4)
        if next_level <= max_level:
            new_order = self._create_order(next_level, order.entry_price)
            self.chain_state.orders.append(new_order)
            await self._place_entry_order(new_order)
        
        self._save_state()
    
    async def _monitor_prices(self) -> None:
        while self.running:
            try:
                current_price = await self._get_current_price()
                
                for order in self.chain_state.orders:
                    if order.state == "pending":
                        if current_price <= order.entry_price:
                            await self._execute_entry(order, current_price)
                            break
                    
                    elif order.state == "filled":
                        if order.take_profit_price and current_price >= order.take_profit_price:
                            await self._execute_take_profit(order, current_price)
                            break
                        
                        elif order.stop_loss_price and current_price <= order.stop_loss_price:
                            await self._execute_stop_loss(order, current_price)
                            break
                
                await asyncio.sleep(1)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[价格监控] 错误: {e}")
                await asyncio.sleep(5)
    
    async def _execute_take_profit(self, order: Any, current_price: Decimal) -> None:
        logger.info(f"[止盈触发] A{order.level}")
        currency = self._get_currency()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 止盈触发 A{order.level}")
        
        symbol = self.config.get("symbol", "700.HK")
        quantity = self._adjust_quantity(order.quantity)
        
        await self.client.place_order(
            symbol=symbol,
            side=OrderSide.Sell,
            order_type=OrderType.MO,
            quantity=quantity,
            price=Decimal("0"),
            remark=f"Autofish TP A{order.level}"
        )
        
        profit = (order.take_profit_price - order.entry_price) * order.quantity
        order.profit = profit
        order.close_price = order.take_profit_price
        order.state = "closed"
        order.close_reason = "take_profit"
        
        self.results["win_trades"] += 1
        self.results["total_profit"] += profit
        self.results["total_trades"] += 1
        
        logger.info(f"[止盈] A{order.level}: 盈利={profit:.2f} {currency}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 A{order.level} 止盈: 盈利={profit:.2f} {currency}")
        
        notify_take_profit(order, profit, self.config)
        
        await self._cancel_next_level(order)
        
        self._adjust_order_levels()
        
        new_order = self._create_order(order.level, current_price)
        self.chain_state.orders.append(new_order)
        await self._place_entry_order(new_order, is_supplement=True)
        
        self._save_state()
    
    async def _execute_stop_loss(self, order: Any, current_price: Decimal) -> None:
        logger.info(f"[止损触发] A{order.level}")
        currency = self._get_currency()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 止损触发 A{order.level}")
        
        symbol = self.config.get("symbol", "700.HK")
        quantity = self._adjust_quantity(order.quantity)
        
        await self.client.place_order(
            symbol=symbol,
            side=OrderSide.Sell,
            order_type=OrderType.MO,
            quantity=quantity,
            price=Decimal("0"),
            remark=f"Autofish SL A{order.level}"
        )
        
        profit = (order.stop_loss_price - order.entry_price) * order.quantity
        order.profit = profit
        order.close_price = order.stop_loss_price
        order.state = "closed"
        order.close_reason = "stop_loss"
        
        self.results["loss_trades"] += 1
        self.results["total_loss"] += abs(profit)
        self.results["total_trades"] += 1
        
        logger.info(f"[止损] A{order.level}: 亏损={profit:.2f} {currency}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 A{order.level} 止损: 亏损={profit:.2f} {currency}")
        
        notify_stop_loss(order, profit, self.config)
        
        await self._cancel_next_level(order)
        
        self._adjust_order_levels()
        
        new_order = self._create_order(order.level, current_price)
        self.chain_state.orders.append(new_order)
        await self._place_entry_order(new_order, is_supplement=True)
        
        self._save_state()
    
    async def _cancel_next_level(self, order: Any) -> None:
        next_level = order.level + 1
        
        for o in self.chain_state.orders:
            if o.level == next_level and o.state == "pending" and o.order_id:
                try:
                    await self.client.cancel_order(o.order_id)
                    logger.info(f"[取消下一级挂单] A{o.level}")
                    self.chain_state.orders.remove(o)
                except Exception as e:
                    logger.warning(f"[取消下一级挂单] 失败: {e}")
    
    def _adjust_order_levels(self) -> None:
        if not self.chain_state:
            return
        
        valid_orders = [o for o in self.chain_state.orders if o.state != "closed"]
        valid_orders.sort(key=lambda o: o.level)
        
        for i, order in enumerate(valid_orders, start=1):
            if order.level != i:
                logger.info(f"[级别调整] A{order.level} -> A{i}")
                order.level = i
        
        self.chain_state.orders = valid_orders
    
    async def run(self) -> None:
        from autofish_core import Autofish_ChainState
        
        self._setup_signal_handlers()
        
        await self.client.connect()
        
        current_price = await self._get_current_price()
        currency = self._get_currency()
        
        print("\n" + "=" * 60)
        print("Autofish V1 LongPort 实盘交易")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {self.config.get('symbol', '700.HK')}")
        print(f"  当前价格: {current_price:.2f} {currency}")
        
        try:
            balance = await self.client.get_account_balance(currency)
            if balance:
                available_cash = balance[0].get("available_cash", "0")
                print(f"  账户余额: {available_cash} {currency}")
        except Exception as e:
            logger.warning(f"[账户余额] 获取失败: {e}")
        
        print(f"  网格间距: {float(self.config.get('grid_spacing', Decimal('0.01')))*100:.1f}%")
        print(f"  止盈比例: {float(self.config.get('exit_profit', Decimal('0.01')))*100:.1f}%")
        print(f"  止损比例: {float(self.config.get('stop_loss', Decimal('0.08')))*100:.1f}%")
        print(f"  最大层级: {self.config.get('max_entries', 4)}")
        print("=" * 60 + "\n")
        
        notify_startup(self.config, current_price)
        
        state_data = self._load_state()
        if state_data:
            self.chain_state = ChainState.from_dict(state_data)
            logger.info(f"[状态恢复] 从本地加载 {len(self.chain_state.orders)} 个订单")
            
            pnl_info = await self._get_pnl_info()
            notify_orders_recovered(self.chain_state.orders, self.config,
                                   current_price, pnl_info or {})
        
        if not self.chain_state or not self.chain_state.orders:
            order = self._create_order(1, current_price)
            self.chain_state = ChainState(orders=[order])
            await self._place_entry_order(order)
        
        await self._monitor_prices()
        
        await self.client.close()


async def main():
    """主函数"""
    import argparse
    from dotenv import load_dotenv
    from autofish_core import Autofish_AmplitudeConfig, Autofish_OrderCalculator
    
    parser = argparse.ArgumentParser(description="Autofish V2 LongPort 实盘交易")
    parser.add_argument("--symbol", type=str, default="700.HK", help="交易对 (默认: 700.HK)")
    parser.add_argument("--decay-factor", type=float, default=0.5, help="衰减因子 (默认: 0.5)")
    
    args = parser.parse_args()
    
    load_dotenv()
    
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
        config = Autofish_OrderCalculator.get_default_config("longport")
        config["symbol"] = args.symbol
        config["decay_factor"] = decay_factor
        config_file = "无（使用内置默认配置）"
    
    config["app_key"] = os.getenv("LONGPORT_APP_KEY", "")
    config["app_secret"] = os.getenv("LONGPORT_APP_SECRET", "")
    config["access_token"] = os.getenv("LONGPORT_ACCESS_TOKEN", "")
    
    currency = _get_currency_from_symbol(args.symbol)
    logger.info(f"[配置加载] {'使用振幅分析配置' if amplitude_config else '使用默认配置'}: {args.symbol}")
    logger.info(f"  配置文件: {config_file}")
    logger.info(f"  交易标的: {config.get('symbol')}")
    logger.info(f"  资金投入: {config['total_amount_quote']} {currency}")
    logger.info(f"  网格间距: {float(config['grid_spacing'])*100:.1f}%")
    logger.info(f"  止盈比例: {float(config['exit_profit'])*100:.1f}%")
    logger.info(f"  止损比例: {float(config['stop_loss'])*100:.1f}%")
    logger.info(f"  衰减因子: {float(decay_factor)}")
    logger.info(f"  最大层级: {config['max_entries']}")
    logger.info(f"  网格权重: {config.get('weights', [])}")
    
    trader = LongPortLiveTrader(config)
    await trader.run()


if __name__ == "__main__":
    asyncio.run(main())


__all__ = [
    "LongPortClient",
    "LongPortLiveTrader",
    "NetworkError",
    "OrderError",
    "StateError",
    "RetryConfig",
    "retry_on_exception",
    "NETWORK_RETRY",
    "API_RETRY",
    "setup_logger",
    "get_logger",
    "LoggerAdapter",
    "StateRepository",
    "NotificationTemplate",
    "send_wechat_notification",
    "notify_entry_order",
    "notify_entry_filled",
    "notify_take_profit",
    "notify_stop_loss",
    "notify_orders_recovered",
    "notify_exit",
    "notify_startup",
]
