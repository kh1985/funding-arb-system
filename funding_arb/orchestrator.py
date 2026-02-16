from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from .config import FundingArbConfig
from .execution import ExecutionService
from .market_data import MarketDataService
from .pair_features import estimate_pair_features
from .risk import RiskService
from .signals import SignalService, SizingContext
from .types import FundingSnapshot, PairFeatures, PortfolioState


@dataclass
class CycleResult:
    timestamp: datetime
    candidates: int
    intents: int
    executed: int
    blocked: int
    rebalanced: bool


class FundingArbOrchestrator:
    def __init__(
        self,
        config: FundingArbConfig,
        market_data: MarketDataService,
        signals: SignalService,
        risk: RiskService,
        execution: ExecutionService,
    ):
        self.config = config
        self.market_data = market_data
        self.signals = signals
        self.risk = risk
        self.execution = execution

    @staticmethod
    def _index_snapshots(
        snapshots: List[FundingSnapshot],
    ) -> Dict[str, Tuple[FundingSnapshot, FundingSnapshot]]:
        idx: Dict[str, Tuple[FundingSnapshot, FundingSnapshot]] = {}
        n = len(snapshots)
        for i in range(n):
            for j in range(i + 1, n):
                a = snapshots[i]
                b = snapshots[j]
                key = "|".join(sorted([f"{a.exchange}:{a.symbol}", f"{b.exchange}:{b.symbol}"]))
                idx[key] = (a, b)
        return idx

    def _estimate_market_features(
        self, snapshots: List[FundingSnapshot]
    ) -> Dict[Tuple[str, str], PairFeatures]:
        """全ペアの特徴量を推定"""
        features: Dict[Tuple[str, str], PairFeatures] = {}
        n = len(snapshots)
        for i in range(n):
            for j in range(i + 1, n):
                a = snapshots[i]
                b = snapshots[j]
                # キーの生成（signals.pyの_feature_keyと同じ形式）
                key = tuple(sorted([a.symbol, b.symbol]))
                features[key] = estimate_pair_features(a.symbol, b.symbol)
        return features

    def _should_rebalance(self, portfolio_state: PortfolioState) -> bool:
        if portfolio_state.equity <= 0:
            return False
        delta_pct = abs(portfolio_state.net_delta_usd) / portfolio_state.equity * 100
        return delta_pct >= self.config.delta_threshold_pct

    def run_cycle(
        self,
        portfolio_state: PortfolioState,
        market_features: Dict[Tuple[str, str], PairFeatures],
    ) -> CycleResult:
        # 動的銘柄選定: config.symbolsが空の場合、Loris APIから動的に選定
        symbols = self.config.symbols
        if not symbols:
            symbols = self.market_data.get_top_symbols_by_criteria(
                universe_size=self.config.universe_size,
                min_fr_diff=self.config.fr_diff_min,
            )

        snapshots = self.market_data.get_funding_snapshots(
            exchanges=[e.name for e in self.config.exchanges],
            symbols=symbols,
        )
        snap_idx = self._index_snapshots(snapshots)

        # market_featuresが空の場合、自動的に推定
        if not market_features:
            market_features = self._estimate_market_features(snapshots)

        candidates = self.signals.build_pair_candidates(snapshots, market_features)
        risk_state = self.risk.evaluate(portfolio_state)

        intents = self.signals.select_entries(
            candidates=candidates,
            snapshots_by_id=snap_idx,
            risk_state=risk_state,
            sizing=SizingContext(capital_usd=portfolio_state.equity),
        )

        executed = 0
        blocked = 0
        for intent in intents:
            a, b = snap_idx[intent.pair_id]
            check = self.risk.enforce_pretrade(
                intent,
                risk_state,
                portfolio_state,
                mark_a=a.mark_price,
                mark_b=b.mark_price,
            )
            if not check.allowed:
                blocked += 1
                print(f"[RISK BLOCK] {intent.pair_id}: {check.reason}", flush=True)
                continue

            res = self.execution.execute_pair(intent)
            if res.success:
                executed += 1

        rebalanced = False
        if self._should_rebalance(portfolio_state):
            self.execution.rebalance_open_positions()
            rebalanced = True

        return CycleResult(
            timestamp=datetime.utcnow(),
            candidates=len(candidates),
            intents=len(intents),
            executed=executed,
            blocked=blocked,
            rebalanced=rebalanced,
        )
