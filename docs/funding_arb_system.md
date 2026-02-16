# Funding Arb Delta-Neutral System

## Overview

This module implements a dedicated funding arbitrage project under `funding_arb/`.

- Strategy: opposite-sign funding pairs + persistence gating
- Positioning: beta-neutral pair sizing
- Risk: drawdown-based state machine (`NORMAL -> REDUCE -> HALT_NEW`)
- Execution: idempotent pair orders + partial-fill fail-safe flatten
- Runtime: single-instance cycle orchestrator with threshold-triggered rebalance
- **NEW**: Loris API integration for real-time funding rates from 24+ exchanges
- **NEW**: Dynamic universe selection based on funding rate differentials

## Package Layout

- `funding_arb/types.py`: domain models (`FundingSnapshot`, `PairCandidate`, `TradeIntent`, `RiskState`)
- `funding_arb/config.py`: strategy and risk parameters
- `funding_arb/loris_client.py`: **NEW** - Loris API client with 60s cache and normalization
- `funding_arb/universe.py`: **NEW** - Dynamic symbol selection based on FR spreads
- `funding_arb/market_data.py`: market data service interface, CCXT adapter, and Loris integration
- `funding_arb/signals.py`: pair detection, quality scoring, and entry intent construction
- `funding_arb/risk.py`: risk evaluation and pre-trade checks
- `funding_arb/execution.py`: execution service with retries and emergency handling
- `funding_arb/orchestrator.py`: end-to-end cycle coordinator (supports dynamic universe)
- `funding_arb/backtest.py`: cycle-based backtest harness
- `funding_arb/monitoring.py`: webhook alerts

## Risk Model

- `max_drawdown_stop_pct`: 15% -> `HALT_NEW`
- `reduce_mode_drawdown_pct`: 10% -> `REDUCE`
- `normal_leverage_cap`: 2x
- `max_leverage`: up to 5x (policy-controlled)

## Quick Start Examples

### Example 1: Loris + Dynamic Universe

```python
from funding_arb import (
    FundingArbConfig,
    LorisAPIClient,
    LorisMarketDataService,
    DynamicUniverseProvider,
    FundingArbOrchestrator,
    SignalService,
    RiskService,
    ExecutionService,
)

# Setup
config = FundingArbConfig(
    symbols=[],  # Empty = dynamic mode
    universe_size=25,
    exchanges=[
        ExchangeConfig("binance"),
        ExchangeConfig("bybit"),
    ],
)

loris_client = LorisAPIClient()
market_data = LorisMarketDataService(loris_client, config=config)
signals = SignalService(config)
risk = RiskService(config)
execution = ExecutionService(exec_client)

orch = FundingArbOrchestrator(config, market_data, signals, risk, execution)

# Run cycle (symbols selected dynamically)
result = orch.run_cycle(portfolio_state, market_features)
```

### Example 2: Hybrid Mode (Loris FR + CCXT OI/Book)

```python
from funding_arb import HybridMarketDataService

# CCXT adapters for OI and order book
ccxt_adapters = {
    "binance": BinanceCCXTAdapter(),
    "bybit": BybitCCXTAdapter(),
}

market_data = HybridMarketDataService(
    loris_client=LorisAPIClient(),
    ccxt_adapters=ccxt_adapters,
)

# Use with orchestrator (best of both worlds)
orch = FundingArbOrchestrator(config, market_data, signals, risk, execution)
```

### Example 3: Static Symbol List (従来通り)

```python
config = FundingArbConfig(
    symbols=["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"],
    exchanges=[ExchangeConfig("binance"), ExchangeConfig("bybit")],
)

# Works with any MarketDataService
market_data = LorisMarketDataService(loris_client)
orch = FundingArbOrchestrator(config, market_data, signals, risk, execution)
```

## Loris API Integration

### LorisAPIClient (`funding_arb/loris_client.py`)

Fetches real-time funding rates from 24+ exchanges via `https://api.loris.tools/funding`.

**Features**:
- 60-second response cache
- Automatic normalization: rates divided by 10,000 (e.g., 25 → 0.0025 = 0.25%)
- Hourly-interval exchanges (Extended, Hyperliquid, Lighter, Vest) further divided by 8
- 3-retry logic with exponential backoff
- Convenience methods: `get_rate(exchange, symbol)`, `get_rates_by_symbols(symbols)`

**Important**: Loris API は本番取引には推奨されません（データ整合性・可用性保証なし）

### Dynamic Universe Selection (`funding_arb/universe.py`)

**DynamicUniverseProvider** automatically selects top symbols based on:
- Maximum funding rate spread across exchanges
- Exchange coverage count
- Average absolute funding rate

**Usage**:
```python
from funding_arb import LorisAPIClient, DynamicUniverseProvider, FundingArbConfig

config = FundingArbConfig(universe_size=25, fr_diff_min=0.002)
loris_client = LorisAPIClient()
universe = DynamicUniverseProvider(config, loris_client)

# Get top symbols dynamically
symbols = universe.get_symbols_for_cycle()
```

### MarketDataService Modes

**1. LorisMarketDataService** - Loris単独モード
- Funding rates from Loris API
- Default OI value (5M USD)
- No bid/ask data
- Fast and lightweight

**2. HybridMarketDataService** - Loris + CCXT統合
- Funding rates from Loris (fast)
- OI and order book from CCXT (accurate)
- Graceful fallback on CCXT errors
- Recommended for production

**3. CCXTMarketDataService** - CCXT単独モード（既存）
- All data from CCXT
- Slower but fully self-contained

### Orchestrator Integration

The orchestrator automatically uses dynamic universe selection when `config.symbols` is empty:

```python
# Static mode (従来通り)
config = FundingArbConfig(
    symbols=["BTC/USDT:USDT", "ETH/USDT:USDT"],
    exchanges=[...]
)

# Dynamic mode (新機能)
config = FundingArbConfig(
    symbols=[],  # Empty = use dynamic selection
    universe_size=25,
    exchanges=[...]
)
```

## Tests

- `tests/test_funding_arb_signal.py`
- `tests/test_funding_arb_risk.py`
- `tests/test_funding_arb_execution.py`
- `tests/test_funding_arb_scenarios.py`
- `tests/test_loris_integration.py` - **NEW** - Loris API and market data integration tests
- `tests/test_universe.py` - **NEW** - Dynamic universe selection tests

Run all tests:

```bash
pytest tests/ -v
```

**Test Coverage**: 63 tests (全テストパス)
