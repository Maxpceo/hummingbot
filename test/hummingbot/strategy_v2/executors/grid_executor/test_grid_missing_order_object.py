from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridLevel, GridLevelStates
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.models.executors import TrackedOrder


def _level(level_id: str, amount: str = "11") -> GridLevel:
    return GridLevel(
        id=level_id,
        price=Decimal("90"),
        amount_quote=Decimal(amount),
        take_profit=Decimal("0.01"),
        side=TradeType.BUY,
        open_order_type=OrderType.LIMIT,
        take_profit_order_type=OrderType.LIMIT,
    )


def _executor(levels) -> GridExecutor:
    executor = object.__new__(GridExecutor)
    executor.grid_levels = levels
    executor.levels_by_state = {state: [] for state in GridLevelStates}
    executor._filled_orders = []
    executor._close_order = None
    executor._open_fee_in_base = False
    executor.mid_price = Decimal("90")
    executor.config = SimpleNamespace(
        side=TradeType.BUY,
        connector_name="okx_perpetual_demo",
        trading_pair="SOL-USDT",
    )
    executor.stop = MagicMock()
    executor._strategy = MagicMock()
    return executor


def _filled(amount: str, price: str = "90"):
    return SimpleNamespace(
        amount=Decimal(amount),
        price=Decimal(price),
        is_filled=True,
        completely_filled_event=SimpleNamespace(is_set=lambda: True),
        quote_asset="USDT",
        base_asset="SOL",
        cumulative_fee_paid=lambda token=None: Decimal("0"),
        to_json=lambda: {"client_order_id": "filled", "amount": amount},
    )


def _cancel_ids(executor: GridExecutor):
    found = []
    for level in executor.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]:
        if level.active_open_order:
            found.append(level.active_open_order.order_id)
    for level in executor.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]:
        if level.active_close_order:
            found.append(level.active_close_order.order_id)
    return found


def test_completed_level_without_open_object_is_not_reset():
    level = _level("L0")
    level.active_close_order = TrackedOrder(order_id="sell-1")
    level.active_close_order.order = _filled("1")
    executor = _executor([level])

    executor.update_grid_levels()

    assert level.active_close_order.order_id == "sell-1"
    assert executor._filled_orders == []
    assert level.id == "L0"
    executor.stop.assert_not_called()


def test_unfilled_close_without_open_does_not_zero_liquidity():
    level = _level("L0", "11.5")
    level.active_close_order = TrackedOrder(order_id="sell-1")
    executor = _executor([level])

    executor.update_grid_levels()
    executor.update_position_metrics()

    assert executor.position_size_base == Decimal("0")
    assert executor.close_liquidity_placed == Decimal("11.5")
    assert _cancel_ids(executor) == ["sell-1"]
    executor.stop.assert_not_called()


def test_neighbor_size_is_not_mixed_with_missing_open():
    empty = _level("L0", "11.5")
    empty.active_close_order = TrackedOrder(order_id="sell-1")
    neighbor = _level("L1", "8")
    neighbor.active_open_order = TrackedOrder(order_id="buy-2")
    neighbor.active_open_order.order = _filled("2", "90")
    executor = _executor([empty, neighbor])

    executor.update_grid_levels()
    executor.update_position_metrics()

    assert executor.position_size_base == Decimal("2")
    assert executor.close_liquidity_placed == Decimal("11.5")
    assert "sell-1" in _cancel_ids(executor)
    executor.stop.assert_not_called()


def test_seated_id_without_order_stays_visible_for_cancel():
    level = _level("L0")
    level.active_open_order = TrackedOrder(order_id="buy-1")
    executor = _executor([level])

    executor.update_grid_levels()

    assert executor.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED] == [level]
    assert level.active_open_order.order_id == "buy-1"
    assert _cancel_ids(executor) == ["buy-1"]


def test_seated_id_without_order_and_unfilled_close_does_not_throw():
    level = _level("L0", "11.5")
    level.active_open_order = TrackedOrder(order_id="buy-1")
    level.active_close_order = TrackedOrder(order_id="sell-1")
    executor = _executor([level])

    executor.update_grid_levels()
    executor.update_position_metrics()

    assert executor.position_size_base == Decimal("0")
    assert executor.close_liquidity_placed == Decimal("11.5")
    assert _cancel_ids(executor) == ["sell-1"]
    executor.stop.assert_not_called()


def test_both_filled_objects_still_reset_the_level():
    level = _level("L0")
    level.active_open_order = TrackedOrder(order_id="buy-1")
    level.active_open_order.order = _filled("1", "90")
    level.active_close_order = TrackedOrder(order_id="sell-1")
    level.active_close_order.order = _filled("1", "91")
    executor = _executor([level])

    executor.update_grid_levels()

    assert level.active_open_order is None
    assert level.active_close_order is None
    assert len(executor._filled_orders) == 2
    assert executor.levels_by_state[GridLevelStates.NOT_ACTIVE] == [level]
