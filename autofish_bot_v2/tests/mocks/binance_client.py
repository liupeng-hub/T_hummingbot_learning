from decimal import Decimal
from datetime import datetime
from typing import Dict, Any, Optional, List
import asyncio


class MockBinanceClient:
    """模拟 Binance API 客户端"""
    
    def __init__(self):
        self.orders: Dict[int, Dict[str, Any]] = {}
        self.algo_orders: Dict[int, Dict[str, Any]] = {}
        self.next_order_id = 10000000000
        self.next_algo_id = 20000000000
        self.listen_key = "mock_listen_key_12345"
        self.position = Decimal("0")
        self.balance = Decimal("10000")
    
    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal,
        **kwargs
    ) -> Dict[str, Any]:
        """模拟下单"""
        order_id = self.next_order_id
        self.next_order_id += 1
        
        order = {
            "orderId": order_id,
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "origQty": str(quantity),
            "price": str(price),
            "status": "NEW",
            "executedQty": "0",
            "avgPrice": "0",
            "createdTime": int(datetime.now().timestamp() * 1000),
            "updateTime": int(datetime.now().timestamp() * 1000)
        }
        self.orders[order_id] = order
        return order
    
    async def place_tp_sl_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        trigger_price: Decimal,
        price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """模拟下止盈止损单"""
        algo_id = self.next_algo_id
        self.next_algo_id += 1
        
        algo = {
            "algoId": algo_id,
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "origQty": str(quantity),
            "triggerPrice": str(trigger_price),
            "price": str(price) if price else "0",
            "stopPrice": str(stop_price) if stop_price else str(trigger_price),
            "status": "NEW",
            "createdTime": int(datetime.now().timestamp() * 1000),
            "updateTime": int(datetime.now().timestamp() * 1000)
        }
        self.algo_orders[algo_id] = algo
        return algo
    
    async def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """模拟取消订单"""
        if order_id not in self.orders:
            raise Exception(f"Binance API Error [-2011]: Unknown order sent.")
        
        self.orders[order_id]["status"] = "CANCELED"
        self.orders[order_id]["updateTime"] = int(datetime.now().timestamp() * 1000)
        return {"orderId": order_id, "status": "CANCELED"}
    
    async def cancel_algo_order(self, symbol: str, algo_id: int) -> Dict[str, Any]:
        """模拟取消 ALGO 订单"""
        if algo_id not in self.algo_orders:
            raise Exception(f"Binance API Error [-2011]: Unknown algo order sent.")
        
        self.algo_orders[algo_id]["status"] = "CANCELED"
        self.algo_orders[algo_id]["updateTime"] = int(datetime.now().timestamp() * 1000)
        return {"algoId": algo_id, "status": "CANCELED"}
    
    async def get_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """模拟获取订单"""
        if order_id not in self.orders:
            raise Exception(f"Binance API Error [-2011]: Unknown order sent.")
        return self.orders[order_id]
    
    async def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """模拟获取未完成订单"""
        return [o for o in self.orders.values() if o["status"] == "NEW"]
    
    async def get_listen_key(self) -> str:
        """模拟获取 listen key"""
        return self.listen_key
    
    async def keepalive_listen_key(self) -> None:
        """模拟续期 listen key"""
        pass
    
    async def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """模拟设置杠杆"""
        return {"symbol": symbol, "leverage": leverage}
    
    async def get_position(self, symbol: str) -> Dict[str, Any]:
        """模拟获取持仓"""
        return {
            "symbol": symbol,
            "positionAmt": str(self.position),
            "entryPrice": "0",
            "unRealizedProfit": "0"
        }
    
    async def get_balance(self) -> Dict[str, Any]:
        """模拟获取余额"""
        return {"balance": str(self.balance)}
    
    async def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[List]:
        """模拟获取 K 线数据"""
        base_price = Decimal("67000")
        klines = []
        for i in range(limit):
            high = base_price * (Decimal("1") + Decimal("0.01") * Decimal(str(i % 10)))
            low = base_price * (Decimal("1") - Decimal("0.01") * Decimal(str(i % 10)))
            klines.append([
                int(datetime.now().timestamp() * 1000) - i * 60000,
                str(low),
                str(high),
                str(high),
                str(low),
                "100",
                int(datetime.now().timestamp() * 1000) - i * 60000 + 60000,
                "1000000",
                100,
                "50",
                "500000"
            ])
        return klines
    
    def simulate_order_filled(self, order_id: int, filled_price: Decimal) -> Optional[Dict[str, Any]]:
        """模拟订单成交"""
        if order_id not in self.orders:
            return None
        
        order = self.orders[order_id]
        order["status"] = "FILLED"
        order["avgPrice"] = str(filled_price)
        order["executedQty"] = order["origQty"]
        order["updateTime"] = int(datetime.now().timestamp() * 1000)
        return order
    
    def simulate_algo_triggered(self, algo_id: int, filled_price: Optional[Decimal] = None) -> Optional[Dict[str, Any]]:
        """模拟 ALGO 订单触发"""
        if algo_id not in self.algo_orders:
            return None
        
        algo = self.algo_orders[algo_id]
        algo["status"] = "FINISHED"
        if filled_price:
            algo["avgPrice"] = str(filled_price)
        else:
            algo["avgPrice"] = algo["triggerPrice"]
        algo["executedQty"] = algo["origQty"]
        algo["updateTime"] = int(datetime.now().timestamp() * 1000)
        return algo
    
    def get_order_ws_message(self, order_id: int, status: str = None) -> Dict[str, Any]:
        """生成订单 WebSocket 消息"""
        if order_id not in self.orders:
            return None
        
        order = self.orders[order_id]
        return {
            "e": "ORDER_TRADE_UPDATE",
            "E": int(datetime.now().timestamp() * 1000),
            "o": {
                "s": order["symbol"],
                "c": str(order_id),
                "S": order["side"],
                "o": order["type"],
                "f": "GTC",
                "q": order["origQty"],
                "p": order["price"],
                "ap": order.get("avgPrice", "0"),
                "X": status or order["status"],
                "i": order_id,
                "l": order.get("executedQty", "0"),
                "z": order.get("executedQty", "0"),
                "T": int(datetime.now().timestamp() * 1000)
            }
        }
    
    def get_algo_ws_message(self, algo_id: int, status: str = None) -> Dict[str, Any]:
        """生成 ALGO WebSocket 消息"""
        if algo_id not in self.algo_orders:
            return None
        
        algo = self.algo_orders[algo_id]
        return {
            "e": "ALGO_UPDATE",
            "E": int(datetime.now().timestamp() * 1000),
            "o": {
                "s": algo["symbol"],
                "c": str(algo_id),
                "S": algo["side"],
                "o": algo["type"],
                "f": "GTC",
                "q": algo["origQty"],
                "p": algo.get("price", "0"),
                "ap": algo.get("avgPrice", algo["triggerPrice"]),
                "X": status or algo["status"],
                "i": algo_id,
                "l": algo.get("executedQty", "0"),
                "z": algo.get("executedQty", "0"),
                "T": int(datetime.now().timestamp() * 1000)
            }
        }
