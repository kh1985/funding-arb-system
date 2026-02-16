from datetime import datetime

from funding_arb.config import FundingArbConfig
from funding_arb.market_data import CCXTMarketDataService
from funding_arb.signals import SignalService, SizingContext
from funding_arb.types import FundingSnapshot, PairFeatures, RiskState, RiskStatus


def _snapshot(exchange: str, symbol: str, fr: float, oi: float, price: float = 100.0) -> FundingSnapshot:
    return FundingSnapshot(
        exchange=exchange,
        symbol=symbol,
        timestamp=datetime.utcnow(),
        funding_rate=fr,
        next_funding_time=None,
        oi=oi,
        mark_price=price,
    )


def test_funding_sign_normalization():
    service = CCXTMarketDataService(adapters={}, canonical_sign_map={"binance": True, "x": False})
    assert service.normalize_funding_rate("binance", 0.01) == 0.01
    assert service.normalize_funding_rate("x", 0.01) == -0.01


def test_build_candidates_requires_opposite_sign_and_persistence():
    cfg = FundingArbConfig(
        min_open_interest_usd=1_000,
        min_liquidity_score=0.2,
        min_persistence_windows=2,
        fr_diff_min=0.001,
        min_pair_score=0.0,
        expected_edge_min_bps=-999,
    )
    svc = SignalService(cfg)

    a = _snapshot("binance", "INIT/USDT:USDT", -0.004, oi=2_000_000, price=1.0)
    b = _snapshot("bybit", "FOLKS/USDT:USDT", 0.006, oi=2_000_000, price=1.0)
    feats = {("FOLKS/USDT:USDT", "INIT/USDT:USDT"): PairFeatures(0.8, 1.1, 0.8, 0.7, 0.7)}

    c1 = svc.build_pair_candidates([a, b], feats)
    assert len(c1) == 1
    assert c1[0].persistence == 1

    c2 = svc.build_pair_candidates([a, b], feats)
    assert len(c2) == 1
    assert c2[0].persistence == 2


def test_select_entries_halt_new_returns_empty():
    cfg = FundingArbConfig(
        min_persistence_windows=1,
        fr_diff_min=0.0001,
        min_pair_score=0.0,
        expected_edge_min_bps=-999,
    )
    svc = SignalService(cfg)

    a = _snapshot("binance", "INIT/USDT:USDT", -0.003, oi=4_000_000, price=1.0)
    b = _snapshot("bybit", "FOLKS/USDT:USDT", 0.004, oi=4_000_000, price=2.0)
    feats = {("FOLKS/USDT:USDT", "INIT/USDT:USDT"): PairFeatures(0.9, 1.0, 0.9, 0.9, 0.9)}

    candidates = svc.build_pair_candidates([a, b], feats)
    snapshots_by_id = {candidates[0].pair_id: (a, b)}
    risk_state = RiskState(equity=10000, dd_pct=20, gross_leverage=0.0, net_delta=0.0, status=RiskStatus.HALT_NEW)
    intents = svc.select_entries(candidates, snapshots_by_id, risk_state, SizingContext(capital_usd=10000))
    assert intents == []
