from datetime import datetime
from typing import Dict, Iterable, List, Tuple

from funding_arb.config import ExchangeConfig, FundingArbConfig
from funding_arb.execution import ExecutionService, ExchangeExecutionClient
from funding_arb.market_data import MarketDataService
from funding_arb.orchestrator import FundingArbOrchestrator
from funding_arb.risk import RiskService
from funding_arb.signals import SignalService
from funding_arb.types import FundingSnapshot, PairFeatures, PortfolioState


class FakeMarketData(MarketDataService):
    def __init__(self, snapshots: List[FundingSnapshot]):
        self.snapshots = snapshots

    def get_funding_snapshots(self, exchanges: Iterable[str], symbols: Iterable[str]) -> List[FundingSnapshot]:
        allowed_e = set(exchanges)
        allowed_s = set(symbols)
        return [s for s in self.snapshots if s.exchange in allowed_e and s.symbol in allowed_s]

    def get_orderbook_tops(self, exchange: str, symbols: Iterable[str]) -> Dict[str, Dict[str, float]]:
        return {symbol: {"bid": 100.0, "ask": 100.1} for symbol in symbols}


class FakeExecClient(ExchangeExecutionClient):
    def place_order(self, **kwargs):
        return {"id": kwargs["client_order_id"], "average": 100.0}


class TrackingExecutionService(ExecutionService):
    def __init__(self, client):
        super().__init__(client)
        self.rebalance_calls = 0

    def rebalance_open_positions(self):
        self.rebalance_calls += 1
        return []


def _snap(exchange: str, symbol: str, fr: float, oi: float) -> FundingSnapshot:
    return FundingSnapshot(
        exchange=exchange,
        symbol=symbol,
        timestamp=datetime.utcnow(),
        funding_rate=fr,
        next_funding_time=None,
        oi=oi,
        mark_price=100.0,
        bid=99.9,
        ask=100.1,
    )


def _orchestrator(snapshots: List[FundingSnapshot], cfg: FundingArbConfig) -> Tuple[FundingArbOrchestrator, TrackingExecutionService]:
    market = FakeMarketData(snapshots)
    signal = SignalService(cfg)
    risk = RiskService(cfg)
    exe = TrackingExecutionService(FakeExecClient())
    orch = FundingArbOrchestrator(cfg, market, signal, risk, exe)
    return orch, exe


def _default_cfg() -> FundingArbConfig:
    return FundingArbConfig(
        exchanges=[ExchangeConfig("binance"), ExchangeConfig("bybit")],
        symbols=["INIT/USDT:USDT", "FOLKS/USDT:USDT"],
        min_open_interest_usd=1_000_000,
        min_liquidity_score=0.5,
        fr_diff_min=0.002,
        min_persistence_windows=2,
        min_pair_score=0.2,
        expected_edge_min_bps=-10,
        delta_threshold_pct=10.0,
    )


def _features() -> Dict[Tuple[str, str], PairFeatures]:
    return {
        ("FOLKS/USDT:USDT", "INIT/USDT:USDT"): PairFeatures(
            correlation=0.8,
            beta=1.0,
            beta_stability=0.7,
            atr_ratio_stability=0.8,
            mean_reversion_score=0.7,
        )
    }


def test_scenario_fr_spike_without_persistence_no_entry():
    cfg = _default_cfg()
    snapshots = [_snap("binance", "INIT/USDT:USDT", -0.01, 5_000_000), _snap("bybit", "FOLKS/USDT:USDT", 0.01, 5_000_000)]
    orch, _ = _orchestrator(snapshots, cfg)

    p = PortfolioState(equity=10000, peak_equity=10000, gross_notional_usd=0, net_delta_usd=0)
    cycle = orch.run_cycle(p, _features())
    assert cycle.intents == 0
    assert cycle.executed == 0


def test_scenario_board_liquidity_bad_skip_entry():
    cfg = _default_cfg()
    snapshots = [_snap("binance", "INIT/USDT:USDT", -0.01, 100_000), _snap("bybit", "FOLKS/USDT:USDT", 0.01, 100_000)]
    orch, _ = _orchestrator(snapshots, cfg)

    p = PortfolioState(equity=10000, peak_equity=10000, gross_notional_usd=0, net_delta_usd=0)
    orch.run_cycle(p, _features())
    cycle2 = orch.run_cycle(p, _features())
    assert cycle2.candidates == 0
    assert cycle2.intents == 0


def test_scenario_dd_15_halts_new_entries():
    cfg = _default_cfg()
    snapshots = [_snap("binance", "INIT/USDT:USDT", -0.01, 5_000_000), _snap("bybit", "FOLKS/USDT:USDT", 0.01, 5_000_000)]
    orch, _ = _orchestrator(snapshots, cfg)

    p = PortfolioState(equity=8400, peak_equity=10000, gross_notional_usd=0, net_delta_usd=0)
    orch.run_cycle(p, _features())
    cycle2 = orch.run_cycle(p, _features())
    assert cycle2.intents == 0
    assert cycle2.executed == 0


def test_scenario_delta_drift_triggers_rebalance():
    cfg = _default_cfg()
    snapshots = [_snap("binance", "INIT/USDT:USDT", -0.01, 5_000_000), _snap("bybit", "FOLKS/USDT:USDT", 0.01, 5_000_000)]
    orch, exe = _orchestrator(snapshots, cfg)

    p = PortfolioState(equity=10000, peak_equity=10000, gross_notional_usd=1000, net_delta_usd=1500)
    orch.run_cycle(p, _features())
    assert exe.rebalance_calls == 1
