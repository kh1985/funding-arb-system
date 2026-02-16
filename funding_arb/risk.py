from __future__ import annotations

from dataclasses import dataclass

from .config import FundingArbConfig
from .types import PortfolioState, RiskState, RiskStatus, TradeIntent


@dataclass
class RiskCheckResult:
    allowed: bool
    reason: str = ""


class RiskService:
    def __init__(self, config: FundingArbConfig):
        self.config = config

    def evaluate(self, portfolio_state: PortfolioState) -> RiskState:
        if portfolio_state.peak_equity <= 0:
            dd_pct = 0.0
        else:
            dd_pct = max(
                0.0,
                (portfolio_state.peak_equity - portfolio_state.equity)
                / portfolio_state.peak_equity
                * 100,
            )

        gross_leverage = (
            portfolio_state.gross_notional_usd / portfolio_state.equity
            if portfolio_state.equity > 0
            else 0.0
        )
        net_delta = (
            portfolio_state.net_delta_usd / portfolio_state.equity
            if portfolio_state.equity > 0
            else 0.0
        )

        if dd_pct >= self.config.max_drawdown_stop_pct:
            status = RiskStatus.HALT_NEW
        elif dd_pct >= self.config.reduce_mode_drawdown_pct:
            status = RiskStatus.REDUCE
        else:
            status = RiskStatus.NORMAL

        return RiskState(
            equity=portfolio_state.equity,
            dd_pct=dd_pct,
            gross_leverage=gross_leverage,
            net_delta=net_delta,
            status=status,
        )

    def enforce_pretrade(
        self,
        intent: TradeIntent,
        risk_state: RiskState,
        portfolio_state: PortfolioState,
        mark_a: float,
        mark_b: float,
    ) -> RiskCheckResult:
        if risk_state.status == RiskStatus.HALT_NEW:
            return RiskCheckResult(False, "HALT_NEW_ACTIVE")

        projected_pair_notional = intent.leg_a.qty * mark_a + intent.leg_b.qty * mark_b
        projected_total = portfolio_state.gross_notional_usd + projected_pair_notional

        if projected_total > self.config.max_total_notional_usd:
            return RiskCheckResult(False, "TOTAL_NOTIONAL_LIMIT")

        for leg, mark in ((intent.leg_a, mark_a), (intent.leg_b, mark_b)):
            ex_total = portfolio_state.exchange_notionals.get(leg.exchange, 0.0) + leg.qty * mark
            if ex_total > self.config.max_notional_per_exchange_usd:
                return RiskCheckResult(False, f"EXCHANGE_LIMIT:{leg.exchange}")

        cap = self.config.normal_leverage_cap if risk_state.status == RiskStatus.REDUCE else self.config.max_leverage
        projected_lev = projected_total / portfolio_state.equity if portfolio_state.equity > 0 else 0.0
        if projected_lev > cap:
            return RiskCheckResult(False, "LEVERAGE_LIMIT")

        return RiskCheckResult(True, "")
