from funding_arb.config import FundingArbConfig
from funding_arb.risk import RiskService
from funding_arb.types import OrderSide, PortfolioState, RiskStatus, TradeIntent, TradeLeg


def _intent(exchange_a: str = "binance", exchange_b: str = "bybit") -> TradeIntent:
    return TradeIntent(
        pair_id="pair-1",
        leg_a=TradeLeg(exchange=exchange_a, symbol="INIT/USDT:USDT", side=OrderSide.BUY, qty=10),
        leg_b=TradeLeg(exchange=exchange_b, symbol="FOLKS/USDT:USDT", side=OrderSide.SELL, qty=10),
        leverage=2.0,
        reason_codes=[],
    )


def test_risk_state_transitions():
    cfg = FundingArbConfig(max_drawdown_stop_pct=15, reduce_mode_drawdown_pct=10)
    svc = RiskService(cfg)

    normal = PortfolioState(equity=10000, peak_equity=10000, gross_notional_usd=0, net_delta_usd=0)
    reduce = PortfolioState(equity=8900, peak_equity=10000, gross_notional_usd=0, net_delta_usd=0)
    halt = PortfolioState(equity=8400, peak_equity=10000, gross_notional_usd=0, net_delta_usd=0)

    assert svc.evaluate(normal).status == RiskStatus.NORMAL
    assert svc.evaluate(reduce).status == RiskStatus.REDUCE
    assert svc.evaluate(halt).status == RiskStatus.HALT_NEW


def test_enforce_pretrade_leverage_and_exchange_limit():
    cfg = FundingArbConfig(
        max_total_notional_usd=1000,
        max_notional_per_exchange_usd=600,
        max_leverage=2,
        normal_leverage_cap=1.5,
    )
    svc = RiskService(cfg)
    p = PortfolioState(
        equity=500,
        peak_equity=500,
        gross_notional_usd=400,
        net_delta_usd=0,
        exchange_notionals={"binance": 500, "bybit": 100},
    )
    risk_state = svc.evaluate(p)
    intent = _intent()

    # mark prices => projected pair notional = 1000 + existing -> violates total and exchange limits
    res = svc.enforce_pretrade(intent, risk_state, p, mark_a=50, mark_b=50)
    assert not res.allowed
    assert res.reason in {"TOTAL_NOTIONAL_LIMIT", "EXCHANGE_LIMIT:binance", "LEVERAGE_LIMIT"}
