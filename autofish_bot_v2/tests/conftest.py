import pytest
import asyncio
from decimal import Decimal
from datetime import datetime
from typing import Dict, Any
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.mocks.binance_client import MockBinanceClient
from tests.mocks.websocket import MockWebSocket
from tests.mocks.market_data import MockMarketData


@pytest.fixture
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_client():
    return MockBinanceClient()


@pytest.fixture
def mock_ws():
    return MockWebSocket()


@pytest.fixture
def mock_market_data():
    return MockMarketData()


@pytest.fixture
def config():
    return {
        "symbol": "BTCUSDT",
        "leverage": 10,
        "total_amount_quote": Decimal("5000"),
        "grid_spacing": Decimal("0.01"),
        "exit_profit": Decimal("0.01"),
        "stop_loss": Decimal("0.08"),
        "decay_factor": 0.5,
        "max_entries": 4,
        "weights": [Decimal("0.0831"), Decimal("0.2996"), Decimal("0.3167"), Decimal("0.1365"),
                    Decimal("0.1005"), Decimal("0.0281"), Decimal("0.027"), Decimal("0.0066"), Decimal("0.0018")],
        "api_key": "test_api_key",
        "api_secret": "test_api_secret"
    }


@pytest.fixture
def entry_price():
    return Decimal("67000.00")


@pytest.fixture
def take_profit_price(entry_price, config):
    return entry_price * (Decimal("1") + config["exit_profit"])


@pytest.fixture
def stop_loss_price(entry_price, config):
    return entry_price * (Decimal("1") - config["stop_loss"])
