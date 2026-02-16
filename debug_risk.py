"""リスクチェックのデバッグ"""
import sys
import os
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
logging.basicConfig(level=logging.INFO)

from datetime import datetime
from funding_arb import (
    FundingArbConfig,
    FundingArbOrchestrator,
    LorisAPIClient,
    HybridMarketDataService,
    SignalService,
    RiskService,
    ExecutionService,
)
from funding_arb.config import ExchangeConfig
from funding_arb.types import PortfolioState
from funding_arb.hyperliquid_client import HyperliquidMarketDataAdapter, HyperliquidExecutionClient

loris_client = LorisAPIClient()
hl_adapter = HyperliquidMarketDataAdapter(testnet=False)
hl_exec = HyperliquidExecutionClient(testnet=False)

config = FundingArbConfig(
    exchanges=[ExchangeConfig("hyperliquid")],
    symbols=[],
    universe_size=10,
    fr_diff_min=0.001,
    min_persistence_windows=1,
    min_pair_score=0.30,
    expected_edge_min_bps=1.0,
    max_new_positions_per_cycle=1,
    max_notional_per_pair_usd=30,
    max_total_notional_usd=30,
    allow_single_exchange_pairs=True,
)

print(f"Config:")
print(f"  max_notional_per_pair_usd: {config.max_notional_per_pair_usd}")
print(f"  max_total_notional_usd: {config.max_total_notional_usd}")
print(f"  max_leverage: {config.max_leverage}")
print()

market_data = HybridMarketDataService(
    loris_client=loris_client,
    ccxt_adapters={"hyperliquid": hl_adapter},
    config=config,
)

signals = SignalService(config)
risk = RiskService(config)
execution = ExecutionService(hl_exec)

orch = FundingArbOrchestrator(config, market_data, signals, risk, execution)

portfolio = PortfolioState(
    equity=49.51,
    peak_equity=50.0,
    gross_notional_usd=0.0,
    net_delta_usd=0.0,
    exchange_notionals={},
)

print(f"Portfolio:")
print(f"  equity: ${portfolio.equity}")
print(f"  gross_notional_usd: ${portfolio.gross_notional_usd}")
print()

print("実行中...")
result = orch.run_cycle(portfolio, {})

print(f"\n結果:")
print(f"  候補ペア: {result.candidates}")
print(f"  エントリー意図: {result.intents}")
print(f"  実行済み: {result.executed}")
print(f"  ブロック: {result.blocked}")
