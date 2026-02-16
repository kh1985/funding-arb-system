from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Set

from .types import (
    ExecutionResult,
    FlattenResult,
    OpenPairPosition,
    OrderResult,
    TradeIntent,
    TradeLeg,
)


class ExchangeExecutionClient(ABC):
    @abstractmethod
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
        raise NotImplementedError


class ExecutionService:
    def __init__(
        self,
        client: ExchangeExecutionClient,
        max_retries: int = 2,
    ):
        self.client = client
        self.max_retries = max_retries
        self._executed_ids: Set[str] = set()
        self._open_positions: Dict[str, OpenPairPosition] = {}

    @property
    def open_positions(self) -> Dict[str, OpenPairPosition]:
        return dict(self._open_positions)

    def _place_leg(self, leg: TradeLeg, client_order_id: str) -> OrderResult:
        last_err: Optional[str] = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self.client.place_order(
                    exchange=leg.exchange,
                    symbol=leg.symbol,
                    side=leg.side.value,
                    qty=leg.qty,
                    order_type=leg.order_type.value,
                    reduce_only=leg.reduce_only,
                    client_order_id=f"{client_order_id}-{attempt}",
                )
                return OrderResult(
                    success=True,
                    order_id=str(raw.get("id")),
                    exchange=leg.exchange,
                    symbol=leg.symbol,
                    side=leg.side,
                    qty=leg.qty,
                    avg_price=float(raw.get("average", 0.0) or 0.0),
                )
            except Exception as exc:  # pragma: no cover - exercised by tests with fake client
                last_err = str(exc)
        return OrderResult(
            success=False,
            order_id=None,
            exchange=leg.exchange,
            symbol=leg.symbol,
            side=leg.side,
            qty=leg.qty,
            error=last_err or "UNKNOWN_ERROR",
        )

    @staticmethod
    def _opposite(leg: TradeLeg) -> TradeLeg:
        side = "buy" if leg.side.value == "sell" else "sell"
        return TradeLeg(
            exchange=leg.exchange,
            symbol=leg.symbol,
            side=leg.side.__class__(side),
            qty=leg.qty,
            order_type=leg.order_type,
            reduce_only=True,
        )

    def execute_pair(self, intent: TradeIntent) -> ExecutionResult:
        if intent.pair_id in self._executed_ids:
            return ExecutionResult(
                success=False,
                pair_id=intent.pair_id,
                leg_results=[],
                error="DUPLICATE_INTENT",
            )

        self._executed_ids.add(intent.pair_id)
        leg_a = self._place_leg(intent.leg_a, f"{intent.pair_id}-a")
        if not leg_a.success:
            return ExecutionResult(
                success=False,
                pair_id=intent.pair_id,
                leg_results=[leg_a],
                error="LEG_A_FAILED",
            )

        leg_b = self._place_leg(intent.leg_b, f"{intent.pair_id}-b")
        if not leg_b.success:
            # Fail-safe: force-close leg A to avoid directional exposure.
            close_a = self._place_leg(self._opposite(intent.leg_a), f"{intent.pair_id}-flatten-a")
            recovery = "LEG_A_FLATTENED" if close_a.success else "LEG_A_FLATTEN_FAILED"
            return ExecutionResult(
                success=False,
                pair_id=intent.pair_id,
                leg_results=[leg_a, leg_b, close_a],
                error="LEG_B_FAILED",
                recovery_action=recovery,
            )

        self._open_positions[intent.pair_id] = OpenPairPosition(
            pair_id=intent.pair_id,
            leg_a=intent.leg_a,
            leg_b=intent.leg_b,
            opened_at=datetime.utcnow(),
        )

        return ExecutionResult(
            success=True,
            pair_id=intent.pair_id,
            leg_results=[leg_a, leg_b],
        )

    def rebalance_open_positions(self) -> List[ExecutionResult]:
        # Caller computes target sizes and feeds explicit intents in this MVP.
        return []

    def emergency_flatten(self, scope: str = "all") -> FlattenResult:
        failures: Dict[str, str] = {}
        closed: List[str] = []

        pair_ids = list(self._open_positions.keys())
        for pair_id in pair_ids:
            pos = self._open_positions[pair_id]
            leg_a = self._place_leg(self._opposite(pos.leg_a), f"{pair_id}-emergency-a")
            leg_b = self._place_leg(self._opposite(pos.leg_b), f"{pair_id}-emergency-b")
            if leg_a.success and leg_b.success:
                closed.append(pair_id)
                del self._open_positions[pair_id]
            else:
                failures[pair_id] = "EMERGENCY_FLATTEN_FAILED"

        return FlattenResult(success=len(failures) == 0, closed_pairs=closed, failures=failures)
