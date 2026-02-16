from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .orchestrator import FundingArbOrchestrator
from .types import PairFeatures, PortfolioState


@dataclass
class BacktestCycleInput:
    portfolio_state: PortfolioState
    market_features: Dict[Tuple[str, str], PairFeatures]


@dataclass
class BacktestSummary:
    cycles: int
    total_candidates: int
    total_intents: int
    total_executed: int
    total_blocked: int
    execution_rate: float
    records: List[dict] = field(default_factory=list)


class FundingBacktester:
    def __init__(self, orchestrator: FundingArbOrchestrator):
        self.orchestrator = orchestrator

    def run(self, inputs: List[BacktestCycleInput]) -> BacktestSummary:
        total_candidates = 0
        total_intents = 0
        total_executed = 0
        total_blocked = 0
        records: List[dict] = []

        for cycle in inputs:
            out = self.orchestrator.run_cycle(
                portfolio_state=cycle.portfolio_state,
                market_features=cycle.market_features,
            )
            total_candidates += out.candidates
            total_intents += out.intents
            total_executed += out.executed
            total_blocked += out.blocked
            records.append(
                {
                    "timestamp": out.timestamp.isoformat(),
                    "candidates": out.candidates,
                    "intents": out.intents,
                    "executed": out.executed,
                    "blocked": out.blocked,
                    "rebalanced": out.rebalanced,
                }
            )

        rate = (total_executed / total_intents) if total_intents > 0 else 0.0
        return BacktestSummary(
            cycles=len(inputs),
            total_candidates=total_candidates,
            total_intents=total_intents,
            total_executed=total_executed,
            total_blocked=total_blocked,
            execution_rate=rate,
            records=records,
        )
