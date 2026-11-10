import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.core.data_type.common import OrderType, TradeType


class _Log:
    def __init__(self):
        self.warning = None
        self.log_msg = None

    def network(self, log_msg, app_warning_msg=None, *args, **kwargs):
        self.log_msg = log_msg
        self.warning = app_warning_msg


def _connector():
    class _Stub(ExchangePyBase):
        pass

    _Stub.__abstractmethods__ = frozenset()
    _Stub.name_cap = property(lambda self: "Okx_perpetual")
    connector = _Stub.__new__(_Stub)
    connector._log = _Log()
    connector.logger = lambda: connector._log
    connector.failed = {}

    def remember(**kwargs):
        connector.failed = kwargs

    connector._update_order_after_failure = remember
    return connector


def _secret_error():
    return RuntimeError(
        'code 50102 apiKey=SECRETKEY signature=SIGVALUE '
        'body={"instId":"SOL-USDT","px":"1"}'
    )


def test_submit_warning_shows_code_and_hides_secrets():
    connector = _connector()
    connector._on_order_failure(
        order_id="sell-9",
        trading_pair="SOL-USDT",
        amount=Decimal("0.1"),
        trade_type=TradeType.SELL,
        order_type=OrderType.MARKET,
        price=Decimal("86"),
        exception=_secret_error(),
    )
    warning = connector._log.warning
    assert "sell-9" in warning
    assert "SELL" in warning
    assert "50102" in warning
    assert "SECRETKEY" not in warning
    assert "SIGVALUE" not in warning
    assert "instId" not in warning
    assert connector.failed["order_id"] == "sell-9"
    assert connector.failed["exception"].__class__ is RuntimeError


def test_cancel_warning_shows_id_and_hides_secrets():
    connector = _connector()
    order = SimpleNamespace(is_done=False, trading_pair="SOL-USDT", client_order_id="sell-1")
    connector._order_tracker = SimpleNamespace(active_orders={"sell-1": order})
    connector._execute_cancel = lambda *args, **kwargs: None

    class _Boom:
        async def __aenter__(self):
            raise _secret_error()

        async def __aexit__(self, *args):
            return False

    with patch("hummingbot.connector.exchange_py_base.timeout", return_value=_Boom()):
        asyncio.run(connector.cancel_all(1))
    warning = connector._log.warning
    assert "sell-1" in warning
    assert "50102" in warning
    assert "SECRETKEY" not in warning
    assert "SIGVALUE" not in warning
    assert "instId" not in warning
    assert "Check API key" not in warning
