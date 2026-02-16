from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ExchangeConfig:
    name: str
    # True if exchange already uses canonical sign:
    # positive funding means long pays short.
    canonical_funding_sign: bool = True


@dataclass
class FundingArbConfig:
    universe_size: int = 25
    rebalance_interval_minutes: int = 10
    delta_threshold_pct: float = 10.0
    beta_drift_threshold_pct: float = 15.0
    max_leverage: float = 5.0
    normal_leverage_cap: float = 2.0
    fr_diff_min: float = 0.0025
    min_persistence_windows: int = 3
    min_pair_score: float = 0.55
    min_open_interest_usd: float = 2_000_000
    min_liquidity_score: float = 0.30
    max_new_positions_per_cycle: int = 3
    max_notional_per_pair_usd: float = 25_000
    max_notional_per_exchange_usd: float = 75_000
    max_total_notional_usd: float = 150_000
    max_drawdown_stop_pct: float = 15.0
    reduce_mode_drawdown_pct: float = 10.0
    max_holding_windows: int = 36
    expected_edge_min_bps: float = 1.0
    funding_event_guard_minutes: int = 5
    allow_single_exchange_pairs: bool = False  # 同一取引所内ペアリングを許可

    exchanges: List[ExchangeConfig] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)

    @property
    def exchange_sign_map(self) -> Dict[str, bool]:
        return {e.name: e.canonical_funding_sign for e in self.exchanges}
