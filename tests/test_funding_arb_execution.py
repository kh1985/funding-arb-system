from typing import Dict

from funding_arb.execution import ExecutionService, ExchangeExecutionClient
from funding_arb.types import OrderSide, TradeIntent, TradeLeg


class FakeClient(ExchangeExecutionClient):
    def __init__(self):
        self.calls = []
        self.fail_on: Dict[str, int] = {}

    def place_order(
        self,
        exchange: str,
        symbol: str,
        side: str,
        qty: float,
        order_type: str,
        reduce_only: bool,
        client_order_id: str,
    ) -> Dict:
        self.calls.append((exchange, symbol, side, qty, reduce_only, client_order_id))
        key = f"{exchange}:{symbol}:{side}:{'R' if reduce_only else 'N'}"
        remaining = self.fail_on.get(key, 0)
        if remaining > 0:
            self.fail_on[key] = remaining - 1
            raise RuntimeError("temporary failure")
        return {"id": client_order_id, "average": 100.0}


def _intent(pair_id: str = "pair-1") -> TradeIntent:
    return TradeIntent(
        pair_id=pair_id,
        leg_a=TradeLeg(exchange="binance", symbol="INIT/USDT:USDT", side=OrderSide.BUY, qty=1.0),
        leg_b=TradeLeg(exchange="bybit", symbol="FOLKS/USDT:USDT", side=OrderSide.SELL, qty=1.0),
        leverage=2.0,
        reason_codes=[],
    )


def test_duplicate_intent_blocked():
    client = FakeClient()
    svc = ExecutionService(client)

    first = svc.execute_pair(_intent("pair-dup"))
    second = svc.execute_pair(_intent("pair-dup"))

    assert first.success
    assert not second.success
    assert second.error == "DUPLICATE_INTENT"


def test_leg_b_failure_triggers_flatten_a():
    client = FakeClient()
    client.fail_on["bybit:FOLKS/USDT:USDT:sell:N"] = 3
    svc = ExecutionService(client, max_retries=1)

    result = svc.execute_pair(_intent("pair-fail"))

    assert not result.success
    assert result.error == "LEG_B_FAILED"
    assert result.recovery_action in {"LEG_A_FLATTENED", "LEG_A_FLATTEN_FAILED"}
