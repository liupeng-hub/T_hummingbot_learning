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
from decimal import Decimal
from typing import List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import aiohttp


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
    tp_order_id: Optional[int] = None  # 止盈订单ID
    sl_order_id: Optional[int] = None  # 止损订单ID
    close_price: Optional[Decimal] = None
    close_reason: Optional[str] = None
    profit: Optional[Decimal] = None


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

    def _sign(self, params: dict) -> str:
        """生成签名"""
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
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
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)
        
        async with self.session.request(method, url, params=params, headers=headers) as resp:
            data = await resp.json()
            if resp.status != 200:
                print(f"❌ API 错误: {data}")
            return data

    async def get_listen_key(self) -> str:
        """获取用户数据流 listenKey"""
        data = await self._request("POST", "/fapi/v1/listenKey")
        return data.get("listenKey")

    async def keepalive_listen_key(self):
        """保持 listenKey 有效"""
        await self._request("PUT", "/fapi/v1/listenKey")

    async def get_account_balance(self) -> dict:
        """获取账户余额"""
        return await self._request("GET", "/fapi/v2/balance", signed=True)

    async def get_current_price(self, symbol: str) -> Decimal:
        """获取当前价格"""
        data = await self._request("GET", "/fapi/v1/ticker/price", {"symbol": symbol})
        return Decimal(data["price"])

    async def place_order(self, symbol: str, side: str, order_type: str, 
                          quantity: Decimal, price: Decimal = None) -> dict:
        """下单"""
        # BTCUSDT 的精度规则
        # 价格精度: 0.1 (tick size)
        # 数量精度: 0.001
        
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        
        # 数量精度处理
        quantity = (quantity / Decimal("0.001")).quantize(Decimal("1")) * Decimal("0.001")
        params["quantity"] = f"{quantity:.3f}"
        
        if price:
            # 价格精度处理 (tick size = 0.1)
            price = (price / Decimal("0.1")).quantize(Decimal("1")) * Decimal("0.1")
            params["price"] = f"{price:.1f}"
        
        if order_type == "LIMIT":
            params["timeInForce"] = "GTC"
        
        return await self._request("POST", "/fapi/v1/order", params, signed=True)

    async def cancel_order(self, symbol: str, order_id: int) -> dict:
        """取消订单"""
        params = {
            "symbol": symbol,
            "orderId": order_id,
        }
        return await self._request("DELETE", "/fapi/v1/order", params, signed=True)

    async def cancel_algo_order(self, symbol: str, algo_id: int) -> dict:
        """取消 Algo 条件单"""
        params = {
            "symbol": symbol,
            "algoId": algo_id,
        }
        return await self._request("DELETE", "/fapi/v1/algoOrder", params, signed=True)

    async def get_open_orders(self, symbol: str) -> list:
        """获取当前挂单"""
        params = {"symbol": symbol}
        return await self._request("GET", "/fapi/v1/openOrders", params, signed=True)

    def _create_order(self, level: int, base_price: Decimal):
        """创建订单"""
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.03"))
        total_amount = self.config.get("total_amount_quote", Decimal("10000"))
        
        entry_price = base_price * (Decimal("1") - grid_spacing)
        take_profit_price = entry_price * (Decimal("1") + exit_profit)
        stop_loss_price = entry_price * (Decimal("1") - stop_loss)
        stake_amount = self.calculator.get_stake_amount(level, total_amount)
        quantity = stake_amount / entry_price
        
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
        return order

    async def _place_entry_order(self, order: Order):
        """下入场单（带止盈止损条件单）"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        # 1. 下限价买入单
        result = await self.place_order(
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            quantity=order.quantity,
            price=order.entry_price
        )
        
        if "orderId" in result:
            order.order_id = result["orderId"]
            
            # 打印详细订单信息
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
            
            # 2. 下止盈条件单 (TAKE_PROFIT_MARKET)
            # 注意：需要在入场单成交后才能下止盈止损单
            # 因为条件单需要已有仓位
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏳ 止盈止损单将在入场成交后下单...")
            
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 下单失败: {result}")

    async def _place_exit_orders(self, order: Order):
        """下止盈止损条件单（入场成交后调用）- 使用 Algo Order API"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        # 下止损条件单 (STOP_MARKET) - 使用 Algo Order API
        # 注意：Algo Order API 需要指定 algoType=CONDITIONAL，使用 triggerPrice 而不是 stopPrice
        sl_params = {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_MARKET",
            "algoType": "CONDITIONAL",
            "quantity": f"{order.quantity:.3f}",
            "triggerPrice": f"{order.stop_loss_price:.1f}",
        }
        sl_result = await self._request("POST", "/fapi/v1/algoOrder", sl_params, signed=True)
        if "algoId" in sl_result or "orderId" in sl_result:
            order.sl_order_id = sl_result.get("algoId") or sl_result.get("orderId")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 止损条件单已下: 触发价={order.stop_loss_price:.2f}, ID={order.sl_order_id}")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ 止损条件单失败: {sl_result}")
        
        # 下止盈条件单 (TAKE_PROFIT_MARKET) - 使用 Algo Order API
        tp_params = {
            "symbol": symbol,
            "side": "SELL",
            "type": "TAKE_PROFIT_MARKET",
            "algoType": "CONDITIONAL",
            "quantity": f"{order.quantity:.3f}",
            "triggerPrice": f"{order.take_profit_price:.1f}",
        }
        tp_result = await self._request("POST", "/fapi/v1/algoOrder", tp_params, signed=True)
        if "algoId" in tp_result or "orderId" in tp_result:
            order.tp_order_id = tp_result.get("algoId") or tp_result.get("orderId")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 止盈条件单已下: 触发价={order.take_profit_price:.2f}, ID={order.tp_order_id}")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ 止盈条件单失败: {tp_result}")

    async def _cancel_all_orders(self):
        """取消所有挂单"""
        symbol = self.config.get("symbol", "BTCUSDT")
        for order in self.chain_state.orders:
            if order.state == "pending" and order.order_id:
                try:
                    await self.cancel_order(symbol, order.order_id)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ 取消订单: A{order.level}")
                except Exception as e:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 取消失败: {e}")

    def _print_summary(self):
        print(f"\n📊 当前统计:")
        print(f"   总交易: {self.results['total_trades']}, 盈利: {self.results['win_trades']}, 亏损: {self.results['loss_trades']}")
        print(f"   总盈利: {float(self.results['total_profit']):.2f}, 总亏损: {float(self.results['total_loss']):.2f}")
        print(f"   净收益: {float(self.results['total_profit'] - self.results['total_loss']):.2f} USDT\n")

    async def on_order_update(self, data: dict):
        """处理订单更新"""
        event_type = data.get("e")
        
        # 处理 ALGO_UPDATE 事件 (条件单更新)
        if event_type == "ALGO_UPDATE":
            await self._handle_algo_update(data)
            return
        
        # 处理 ORDER_TRADE_UPDATE 事件 (普通订单更新)
        if event_type != "ORDER_TRADE_UPDATE":
            return
        
        order_data = data.get("o", {})
        order_status = order_data.get("X")
        order_id = order_data.get("i")
        symbol = order_data.get("s")
        order_type = order_data.get("o")
        
        # 查找对应的订单
        for order in self.chain_state.orders:
            # 入场单成交
            if order.order_id == order_id:
                if order_status == "FILLED":
                    order.state = "filled"
                    filled_price = Decimal(str(order_data.get("ap", order.entry_price)))
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ A{order.level} 成交: 价格={filled_price:.2f}")
                    
                    # 成交后下止盈止损条件单
                    await self._place_exit_orders(order)
                    
                    # 创建下一个入场订单
                    next_level = order.level + 1
                    max_level = self.config.get("max_entries", 4)
                    if next_level <= max_level:
                        new_order = self._create_order(next_level, order.entry_price)
                        await self._place_entry_order(new_order)
                    
                elif order_status == "CANCELED":
                    order.state = "cancelled"
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ A{order.level} 已取消")
                
                break

    async def _handle_algo_update(self, data: dict):
        """处理 Algo 条件单更新事件"""
        algo_data = data.get("A", {})
        algo_id = algo_data.get("i")  # algoId
        algo_status = algo_data.get("X")  # 状态
        symbol = algo_data.get("s")
        
        # 查找对应的订单
        for order in self.chain_state.orders:
            # 止盈单触发
            if order.tp_order_id == algo_id:
                if algo_status == "FILLED":
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 A{order.level} 止盈触发!")
                    self.results["total_trades"] += 1
                    self.results["win_trades"] += 1
                    profit = order.stake_amount * self.config.get("exit_profit", Decimal("0.01"))
                    self.results["total_profit"] += profit
                    print(f"   盈利: {float(profit):.2f} USDT")
                    # 取消止损单
                    if order.sl_order_id:
                        await self.cancel_algo_order(symbol, order.sl_order_id)
                    self._print_summary()
                break
            
            # 止损单触发
            elif order.sl_order_id == algo_id:
                if algo_status == "FILLED":
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 A{order.level} 止损触发!")
                    self.results["total_trades"] += 1
                    self.results["loss_trades"] += 1
                    loss = order.stake_amount * self.config.get("stop_loss", Decimal("0.08"))
                    self.results["total_loss"] += loss
                    print(f"   亏损: {float(loss):.2f} USDT")
                    # 取消止盈单
                    if order.tp_order_id:
                        await self.cancel_algo_order(symbol, order.tp_order_id)
                    # 取消所有待处理订单
                    self.chain_state.cancel_pending_orders()
                    self._print_summary()
                break

    async def run(self):
        """运行模拟器"""
        symbol = self.config.get("symbol", "BTCUSDT")
        
        print("=" * 60)
        print("Autofish V1 实时模拟测试（Binance API）")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {symbol}")
        print(f"  杠杆: {self.config.get('leverage', 10)}x")
        print(f"  网格间距: {float(self.config.get('grid_spacing', Decimal('0.01')))*100}%")
        print(f"  止盈: {float(self.config.get('exit_profit', Decimal('0.01')))*100}%")
        print(f"  止损: {float(self.config.get('stop_loss', Decimal('0.03')))*100}%")
        print(f"  测试网: {self.testnet}")
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            # 获取账户余额
            print(f"\n📊 获取账户信息...")
            balance = await self.get_account_balance()
            print(f"   账户余额: {balance}")
            
            # 获取当前价格
            current_price = await self.get_current_price(symbol)
            print(f"   当前价格: {current_price}")
            
            # 初始化链式状态
            self.chain_state = ChainState(base_price=current_price)
            first_order = self._create_order(1, current_price)
            
            # 获取 listenKey
            print(f"\n🔗 连接用户数据流...")
            self.listen_key = await self.get_listen_key()
            print(f"   listenKey: {self.listen_key[:20]}...")
            
            # 下第一个订单
            await self._place_entry_order(first_order)
            
            # 连接 WebSocket
            ws_uri = f"{self.ws_url}/{self.listen_key}"
            print(f"\n📡 连接 WebSocket...")
            
            try:
                async with session.ws_connect(ws_uri) as websocket:
                    print("✅ 连接成功！开始监听订单状态...\n")
                    
                    # 定期保持 listenKey 有效
                    async def keepalive():
                        while True:
                            await asyncio.sleep(1800)  # 每30分钟
                            await self.keepalive_listen_key()
                    
                    asyncio.create_task(keepalive())
                    
                    async for message in websocket:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(message.data)
                            await self.on_order_update(data)
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            print(f"WebSocket 错误: {websocket.exception()}")
                            break
                            
            except KeyboardInterrupt:
                print("\n\n⏹️ 停止模拟")
                await self._cancel_all_orders()
                self._print_summary()
            except Exception as e:
                print(f"\n❌ 错误: {e}")
                import traceback
                traceback.print_exc()
                self._print_summary()


def load_api_keys() -> tuple:
    """从 .env 文件加载 API Key"""
    import os
    
    env_path = "/Users/liupeng/Documents/trae_projects/mybot/binance_bot/.env"
    
    api_key = None
    api_secret = None
    
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith("BINANCE_TESTNET_API_KEY="):
                    api_key = line.split("=")[1].strip("'\"")
                elif line.startswith("BINANCE_TESTNET_SECRET_KEY="):
                    api_secret = line.split("=")[1].strip("'\"")
    
    return api_key, api_secret


async def main():
    # 加载 API Key
    api_key, api_secret = load_api_keys()
    
    if not api_key or not api_secret:
        print("❌ 未找到 API Key，请检查 .env 文件")
        return
    
    config = {
        "symbol": "BTCUSDT",
        "grid_spacing": Decimal("0.01"),   # 网格间距 1%
        "exit_profit": Decimal("0.01"),    # 止盈 1%
        "stop_loss": Decimal("0.08"),      # 止损 8%
        "decay_factor": Decimal("0.5"),
        "total_amount_quote": Decimal("1200"),  # 总金额 1200 USDT (确保每层 >= 100)
        "leverage": Decimal("10"),
        "max_entries": 4,
    }
    
    simulator = BinanceAPISimulator(config, api_key, api_secret, testnet=True)
    await simulator.run()


if __name__ == '__main__':
    asyncio.run(main())
