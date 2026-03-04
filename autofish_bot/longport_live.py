"""
Autofish V1 LongPort 实盘交易模块

使用 LongPort OpenAPI SDK 进行股票实盘交易
支持港股、美股、A股

运行方式：
    cd hummingbot_learning
    source autofish_bot/venv/bin/activate
    python3 -m autofish_bot.longport_live --symbol 700.HK

环境变量配置 (.env):
    LONGPORT_APP_KEY=your_app_key
    LONGPORT_APP_SECRET=your_app_secret
    LONGPORT_ACCESS_TOKEN=your_access_token
"""

import argparse
import asyncio
import json
import logging
import os
import requests
from decimal import Decimal
from typing import List, Optional, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

from longport.openapi import (
    Config,
    QuoteContext,
    TradeContext,
    OrderType,
    OrderSide,
    TimeInForceType,
    Period,
    AdjustType,
    PushOrderChanged,
)

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

LOG_FILE = os.path.join(LOG_DIR, "longport_live.log")
STATE_FILE = os.path.join(LOG_DIR, "longport_live_state.json")

WECHAT_WEBHOOK = os.getenv("WECHAT_WEBHOOK", "")

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
    if not WECHAT_WEBHOOK:
        return False
    
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
    currency = _get_currency_from_symbol(config.get('symbol', '700.HK'))
    content = f"""> **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
> **入场价**: {order.entry_price:.2f} {currency}
> **数量**: {order.quantity:.4f} 股
> **金额**: {order.stake_amount:.2f} {currency}
> **止盈价**: {order.take_profit_price:.2f} {currency} (+{float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%)
> **止损价**: {order.stop_loss_price:.2f} {currency} (-{float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%)
> **订单ID**: {order.order_id}
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    send_wechat_notification(f"🟢 入场单下单 A{order.level}", content)


def notify_entry_filled(order: Order, filled_price: Decimal, config: dict):
    """通知入场成交"""
    max_entries = config.get('max_entries', 4)
    currency = _get_currency_from_symbol(config.get('symbol', '700.HK'))
    content = f"""> **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
> **成交价**: {filled_price:.2f} {currency}
> **数量**: {order.quantity:.4f} 股
> **金额**: {order.stake_amount:.2f} {currency}
> **止盈价**: {order.take_profit_price:.2f} {currency}
> **止损价**: {order.stop_loss_price:.2f} {currency}
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    send_wechat_notification(f"✅ 入场成交 A{order.level}", content)


def notify_take_profit(order: Order, profit: Decimal, config: dict):
    """通知止盈触发"""
    max_entries = config.get('max_entries', 4)
    currency = _get_currency_from_symbol(config.get('symbol', '700.HK'))
    content = f"""> **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
> **止盈价**: {order.take_profit_price:.2f} {currency}
> **盈亏**: +{profit:.2f} {currency}
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    send_wechat_notification(f"🎯 止盈触发 A{order.level}", content)


def notify_stop_loss(order: Order, profit: Decimal, config: dict):
    """通知止损触发"""
    max_entries = config.get('max_entries', 4)
    currency = _get_currency_from_symbol(config.get('symbol', '700.HK'))
    content = f"""> **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
> **止损价**: {order.stop_loss_price:.2f} {currency}
> **盈亏**: {profit:.2f} {currency}
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    send_wechat_notification(f"🛑 止损触发 A{order.level}", content)


def notify_startup(config: dict, current_price: Decimal):
    """通知程序启动"""
    symbol = config.get('symbol', '700.HK')
    currency = _get_currency_from_symbol(symbol)
    content = f"""> **交易对**: {symbol}
> **当前价格**: {current_price:.2f} {currency}
> **网格间距**: {float(config.get('grid_spacing', Decimal('0.01')))*100}%
> **止盈**: {float(config.get('exit_profit', Decimal('0.01')))*100}%
> **止损**: {float(config.get('stop_loss', Decimal('0.08')))*100}%
> **启动时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    send_wechat_notification("🚀 Autofish V1 LongPort 启动", content)


def _get_currency_from_symbol(symbol: str) -> str:
    """根据交易对获取货币类型"""
    if ".HK" in symbol.upper():
        return "HKD"
    elif ".US" in symbol.upper():
        return "USD"
    elif ".SH" in symbol.upper() or ".SZ" in symbol.upper():
        return "CNY"
    return "USD"


class LongPortLiveTrader:
    """LongPort 实盘交易器"""
    
    def __init__(self, config: dict, use_amplitude_config: bool = True):
        self.config = config
        self.use_amplitude_config = use_amplitude_config
        self.amplitude_config: Optional[AmplitudeConfig] = None
        self.custom_weights: Optional[Dict[int, Decimal]] = None
        
        if use_amplitude_config:
            symbol = config.get("symbol", "700.HK")
            self.amplitude_config = AmplitudeConfig.load_latest(symbol)
            if self.amplitude_config:
                decay_factor = Decimal(str(config.get("decay_factor", 0.5)))
                self.custom_weights = self.amplitude_config.get_weights(decay_factor)
                
                self.config["grid_spacing"] = self.amplitude_config.get_grid_spacing()
                self.config["exit_profit"] = self.amplitude_config.get_exit_profit()
                self.config["stop_loss"] = self.amplitude_config.get_stop_loss()
                self.config["total_amount_quote"] = self.amplitude_config.get_total_amount_quote()
                self.config["max_entries"] = self.amplitude_config.get_max_entries()
                
                logger.info(f"[配置加载] 使用振幅分析配置: {symbol}")
                logger.info(f"  配置文件: {self.amplitude_config.config_path}")
                logger.info(f"  交易对: {self.config.get('symbol')}")
                logger.info(f"  总投入: {self.config['total_amount_quote']} {self._get_currency()}")
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
        
        self.quote_ctx: Optional[QuoteContext] = None
        self.trade_ctx: Optional[TradeContext] = None
        
        self.results = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "total_profit": Decimal("0"),
            "total_loss": Decimal("0"),
        }
        
        self.running = True
        self._check_price_task: Optional[asyncio.Task] = None
        
        logger.info(f"初始化 LongPort 实盘交易器")
    
    def _get_currency(self) -> str:
        """根据交易对获取货币类型"""
        return _get_currency_from_symbol(self.config.get("symbol", "700.HK"))
    
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
    
    def _get_quantity(self, stake_amount: Decimal, price: Decimal, symbol: str) -> int:
        """获取股票数量（股票交易需要整数股）"""
        quantity = stake_amount / price
        
        if ".HK" in symbol.upper():
            lot_size = 100
        elif ".US" in symbol.upper():
            lot_size = 1
        elif ".SH" in symbol.upper() or ".SZ" in symbol.upper():
            lot_size = 100
        else:
            lot_size = 1
        
        return int(quantity // lot_size) * lot_size
    
    async def _place_entry_order(self, order: Order):
        """下入场单"""
        symbol = self.config.get("symbol", "700.HK")
        
        quantity = self._get_quantity(order.stake_amount, order.entry_price, symbol)
        if quantity <= 0:
            logger.error(f"[下单] 数量无效: quantity={quantity}")
            return
        
        try:
            result = self.trade_ctx.submit_order(
                symbol=symbol,
                order_type=OrderType.LO,
                side=OrderSide.Buy,
                submitted_quantity=Decimal(str(quantity)),
                time_in_force=TimeInForceType.Day,
                submitted_price=order.entry_price,
                remark=f"Autofish A{order.level}"
            )
            
            order.order_id = result.order_id
            order.quantity = Decimal(str(quantity))
            
            weight_pct = self.calculator.get_weight_percentage(order.level)
            
            print(f"\n{'='*60}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 下单成功: A{order.level}")
            print(f"{'='*60}")
            print(f"  层级: A{order.level} / {self.config.get('max_entries', 4)}")
            print(f"  权重: {weight_pct:.2f}%")
            print(f"  入场价: {order.entry_price:.2f}")
            print(f"  数量: {quantity} 股")
            print(f"  金额: {order.stake_amount:.2f} {self._get_currency()}")
            print(f"  止盈价: {order.take_profit_price:.2f}")
            print(f"  止损价: {order.stop_loss_price:.2f}")
            print(f"  订单ID: {order.order_id}")
            print(f"{'='*60}\n")
            
            logger.info(f"入场单下单成功: A{order.level}, orderId={order.order_id}")
            
            notify_entry_order(order, self.config)
            self._save_state()
            
        except Exception as e:
            logger.error(f"[下单] 失败: {e}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 下单失败: {e}")
    
    async def _place_exit_orders(self, order: Order):
        """下止盈止损单（LongPort 不支持条件单，需要手动监控）"""
        logger.info(f"[止盈止损设置] A{order.level}: TP={order.take_profit_price:.2f}, SL={order.stop_loss_price:.2f}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📊 A{order.level} 止盈止损已设置: TP={order.take_profit_price:.2f}, SL={order.stop_loss_price:.2f}")
    
    async def _cancel_all_orders(self):
        """取消所有挂单"""
        symbol = self.config.get("symbol", "700.HK")
        
        for order in self.chain_state.orders:
            if order.state == "pending" and order.order_id:
                try:
                    self.trade_ctx.cancel_order(symbol, order.order_id)
                    logger.info(f"[取消订单] A{order.level} orderId={order.order_id}")
                except Exception as e:
                    logger.error(f"[取消订单] 失败: {e}")
    
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
                print(f"   A{order.level}: state={order.state}, order_id={order.order_id}")
            
            has_active_order = any(o.state in ["pending", "filled"] for o in self.chain_state.orders)
            if has_active_order:
                need_new_order = False
        else:
            self.chain_state = ChainState(base_price=current_price)
            notify_startup(self.config, current_price)
        
        return need_new_order
    
    async def _check_price_and_execute(self):
        """检查价格并执行止盈止损"""
        symbol = self.config.get("symbol", "700.HK")
        
        while self.running:
            try:
                quotes = self.quote_ctx.quote([symbol])
                if quotes:
                    quote = quotes[0]
                    current_price = Decimal(str(quote.last_done))
                    
                    filled_orders = self.chain_state.get_filled_orders()
                    
                    for order in filled_orders:
                        if order.state != "filled":
                            continue
                        
                        if current_price >= order.take_profit_price:
                            await self._execute_take_profit(order, current_price)
                            break
                        elif current_price <= order.stop_loss_price:
                            await self._execute_stop_loss(order, current_price)
                            break
                    
                    pending_order = self.chain_state.get_pending_order()
                    if pending_order:
                        if current_price <= pending_order.entry_price:
                            await self._execute_entry(pending_order, current_price)
                
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"[价格检查] 异常: {e}")
                await asyncio.sleep(10)
    
    async def _execute_entry(self, order: Order, current_price: Decimal):
        """执行入场"""
        order.set_state("filled", "价格触发入场")
        
        logger.info(f"[入场成交] A{order.level}: 价格={current_price:.2f}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ A{order.level} 成交: 价格={current_price:.2f}")
        
        notify_entry_filled(order, current_price, self.config)
        
        await self._place_exit_orders(order)
        
        next_level = order.level + 1
        max_level = self.config.get("max_entries", 4)
        if next_level <= max_level:
            new_order = self._create_order(next_level, order.entry_price)
            self.chain_state.orders.append(new_order)
            await self._place_entry_order(new_order)
    
    async def _execute_take_profit(self, order: Order, current_price: Decimal):
        """执行止盈"""
        symbol = self.config.get("symbol", "700.HK")
        
        try:
            result = self.trade_ctx.submit_order(
                symbol=symbol,
                order_type=OrderType.LO,
                side=OrderSide.Sell,
                submitted_quantity=order.quantity,
                time_in_force=TimeInForceType.Day,
                submitted_price=order.take_profit_price,
                remark=f"Autofish TP A{order.level}"
            )
            
            profit = calculate_profit(order, order.take_profit_price, Decimal("1"))
            order.profit = profit
            order.close_price = order.take_profit_price
            order.set_state("closed", "take_profit")
            
            self.results["win_trades"] += 1
            self.results["total_profit"] += profit
            self.results["total_trades"] += 1
            
            logger.info(f"[止盈] A{order.level}: 盈利={profit:.2f}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 A{order.level} 止盈: 盈利={profit:.2f} {self._get_currency()}")
            
            notify_take_profit(order, profit, self.config)
            
            self.chain_state.cancel_pending_orders()
            new_order = self._create_order(order.level, current_price)
            self.chain_state.orders.append(new_order)
            await self._place_entry_order(new_order)
            
            self._save_state()
            
        except Exception as e:
            logger.error(f"[止盈执行] 失败: {e}")
    
    async def _execute_stop_loss(self, order: Order, current_price: Decimal):
        """执行止损"""
        symbol = self.config.get("symbol", "700.HK")
        
        try:
            result = self.trade_ctx.submit_order(
                symbol=symbol,
                order_type=OrderType.LO,
                side=OrderSide.Sell,
                submitted_quantity=order.quantity,
                time_in_force=TimeInForceType.Day,
                submitted_price=order.stop_loss_price,
                remark=f"Autofish SL A{order.level}"
            )
            
            profit = calculate_profit(order, order.stop_loss_price, Decimal("1"))
            order.profit = profit
            order.close_price = order.stop_loss_price
            order.set_state("closed", "stop_loss")
            
            self.results["loss_trades"] += 1
            self.results["total_loss"] += abs(profit)
            self.results["total_trades"] += 1
            
            logger.info(f"[止损] A{order.level}: 亏损={profit:.2f}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 A{order.level} 止损: 亏损={profit:.2f} {self._get_currency()}")
            
            notify_stop_loss(order, profit, self.config)
            
            self.chain_state.cancel_pending_orders()
            new_order = self._create_order(order.level, current_price)
            self.chain_state.orders.append(new_order)
            await self._place_entry_order(new_order)
            
            self._save_state()
            
        except Exception as e:
            logger.error(f"[止损执行] 失败: {e}")
    
    async def run(self):
        """运行实盘交易"""
        symbol = self.config.get("symbol", "700.HK")
        
        logger.info("=" * 60)
        logger.info("Autofish V1 LongPort 实盘交易启动")
        logger.info("=" * 60)
        
        print("=" * 60)
        print("Autofish V1 LongPort 实盘交易")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {symbol}")
        print(f"  日志文件: {LOG_FILE}")
        print(f"  状态文件: {STATE_FILE}")
        
        try:
            config = Config.from_env()
            self.quote_ctx = QuoteContext(config)
            self.trade_ctx = TradeContext(config)
            
            print(f"\n📊 获取账户信息...")
            
            quotes = self.quote_ctx.quote([symbol])
            current_price = Decimal(str(quotes[0].last_done)) if quotes else Decimal("0")
            print(f"   当前价格: {current_price:.2f} {self._get_currency()}")
            
            balance = self.trade_ctx.account_balance()
            if balance:
                for item in balance:
                    if item.currency == self._get_currency():
                        print(f"   账户余额: {item.available_cash:.2f} {item.currency}")
            
            need_new_order = await self._restore_orders(current_price)
            
            if need_new_order:
                first_order = self._create_order(1, current_price)
                self.chain_state.orders.append(first_order)
                await self._place_entry_order(first_order)
            else:
                print(f"\n📋 已有订单，等待执行...")
            
            print(f"\n📡 开始监控价格...")
            print(f"   按 Ctrl+C 停止\n")
            
            self._check_price_task = asyncio.create_task(self._check_price_and_execute())
            
            while self.running:
                await asyncio.sleep(1)
            
        except KeyboardInterrupt:
            print("\n\n⏹️ 停止交易")
            self.running = False
            if self._check_price_task:
                self._check_price_task.cancel()
            await self._cancel_all_orders()
            self._save_state()
        except Exception as e:
            logger.error(f"[运行] 错误: {e}", exc_info=True)
            print(f"\n❌ 错误: {e}")
        finally:
            self.running = False


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Autofish V1 LongPort 实盘交易")
    parser.add_argument("--symbol", type=str, default="700.HK", help="交易对 (默认: 700.HK)")
    parser.add_argument("--stop-loss", type=float, default=0.08, help="止损比例 (默认: 0.08)")
    parser.add_argument("--total-amount", type=float, default=1200, help="总投入金额 (默认: 1200)")
    
    args = parser.parse_args()
    
    config = get_default_config()
    config["symbol"] = args.symbol
    config.update({
        "stop_loss": Decimal(str(args.stop_loss)),
        "total_amount_quote": Decimal(str(args.total_amount)),
    })
    
    trader = LongPortLiveTrader(config)
    await trader.run()


if __name__ == "__main__":
    asyncio.run(main())
