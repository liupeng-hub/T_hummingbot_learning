import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
import json


class MockWebSocket:
    """模拟 WebSocket 连接"""
    
    def __init__(self):
        self.messages: asyncio.Queue = asyncio.Queue()
        self.connected: bool = False
        self.closed: bool = False
        self.subscriptions: list = []
    
    async def connect(self, url: str = None) -> None:
        """模拟连接"""
        self.connected = True
        self.closed = False
    
    async def send(self, message: str) -> None:
        """模拟发送消息"""
        if not self.connected:
            raise Exception("WebSocket not connected")
        
        try:
            data = json.loads(message)
            if data.get("method") == "SUBSCRIBE":
                self.subscriptions.extend(data.get("params", []))
        except:
            pass
    
    async def recv(self) -> str:
        """模拟接收消息"""
        if not self.connected:
            raise Exception("WebSocket not connected")
        
        message = await self.messages.get()
        return json.dumps(message)
    
    async def put_message(self, event_type: str, data: Dict[str, Any]) -> None:
        """放入模拟消息"""
        message = {
            "e": event_type,
            "E": int(datetime.now().timestamp() * 1000),
            **data
        }
        await self.messages.put(message)
    
    async def put_raw_message(self, message: Dict[str, Any]) -> None:
        """放入原始消息"""
        await self.messages.put(message)
    
    async def close(self) -> None:
        """模拟关闭连接"""
        self.connected = False
        self.closed = True
    
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self.connected and not self.closed
    
    async def simulate_disconnect(self) -> None:
        """模拟断开连接"""
        self.connected = False
    
    async def simulate_reconnect(self) -> None:
        """模拟重连"""
        self.connected = True
        self.closed = False


class MockWebSocketManager:
    """模拟 WebSocket 管理器"""
    
    def __init__(self):
        self.ws: Optional[MockWebSocket] = None
        self.listen_key: str = "mock_listen_key_12345"
        self.keepalive_task: Optional[asyncio.Task] = None
        self.running: bool = False
    
    async def start(self) -> MockWebSocket:
        """启动 WebSocket"""
        self.ws = MockWebSocket()
        await self.ws.connect()
        self.running = True
        return self.ws
    
    async def stop(self) -> None:
        """停止 WebSocket"""
        self.running = False
        if self.ws:
            await self.ws.close()
        if self.keepalive_task:
            self.keepalive_task.cancel()
    
    async def put_order_update(self, order_data: Dict[str, Any]) -> None:
        """放入订单更新消息"""
        if self.ws:
            await self.ws.put_message("ORDER_TRADE_UPDATE", {"o": order_data})
    
    async def put_algo_update(self, algo_data: Dict[str, Any]) -> None:
        """放入 ALGO 更新消息"""
        if self.ws:
            await self.ws.put_message("ALGO_UPDATE", {"o": algo_data})
    
    async def put_listen_key_expired(self) -> None:
        """放入 listen key 过期消息"""
        if self.ws:
            await self.ws.put_raw_message({"e": "listenKeyExpired"})
