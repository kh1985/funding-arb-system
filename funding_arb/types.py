from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class RiskStatus(str, Enum):
    NORMAL = "NORMAL"
    REDUCE = "REDUCE"
    HALT_NEW = "HALT_NEW"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class FundingSnapshot:
    exchange: str
    symbol: str
    timestamp: datetime
    funding_rate: float
    next_funding_time: Optional[datetime]
    oi: float
    mark_price: float
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass
class PairFeatures:
    correlation: float
    beta: float
    beta_stability: float
    atr_ratio_stability: float
    mean_reversion_score: float


@dataclass
class PairCandidate:
    pair_id: str
    symbol_a: str
    exchange_a: str
    symbol_b: str
    exchange_b: str
    fr_diff: float
    persistence: int
    liquidity_score: float
    pair_score: float
    beta: float
    expected_edge_bps: float
    reason_codes: List[str] = field(default_factory=list)


@dataclass
class TradeLeg:
    exchange: str
    symbol: str
    side: OrderSide
    qty: float
    order_type: OrderType = OrderType.MARKET
    reduce_only: bool = False


@dataclass
class TradeIntent:
    pair_id: str
    leg_a: TradeLeg
    leg_b: TradeLeg
    leverage: float
    reason_codes: List[str] = field(default_factory=list)


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str]
    exchange: str
    symbol: str
    side: OrderSide
    qty: float
    avg_price: Optional[float] = None
    error: Optional[str] = None


@dataclass
class ExecutionResult:
    success: bool
    pair_id: str
    leg_results: List[OrderResult]
    error: Optional[str] = None
    recovery_action: Optional[str] = None


@dataclass
class FlattenResult:
    success: bool
    closed_pairs: List[str]
    failures: Dict[str, str]


@dataclass
class OpenPairPosition:
    pair_id: str
    leg_a: TradeLeg
    leg_b: TradeLeg
    opened_at: datetime


@dataclass
class PortfolioState:
    equity: float
    peak_equity: float
    gross_notional_usd: float
    net_delta_usd: float
    exchange_notionals: Dict[str, float] = field(default_factory=dict)


@dataclass
class RiskState:
    equity: float
    dd_pct: float
    gross_leverage: float
    net_delta: float
    status: RiskStatus
