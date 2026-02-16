"""詳細ログ付き実行テスト"""
import sys
import os
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
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

# ログレベルをDEBUGに設定
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

print("=" * 70)
print("デバッグ実行テスト")
print("=" * 70)

# 初期化
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
    max_notional_per_pair_usd=20,
    max_total_notional_usd=50,
    allow_single_exchange_pairs=True,
)

market_data = HybridMarketDataService(
    loris_client=loris_client,
    ccxt_adapters={"hyperliquid": hl_adapter},
    config=config,
)

signals = SignalService(config)
risk = RiskService(config)
execution = ExecutionService(hl_exec)

orch = FundingArbOrchestrator(config, market_data, signals, risk, execution)

print("\n1サイクル実行中...")
print("=" * 70)

portfolio = PortfolioState(
    equity=50.0,
    peak_equity=50.0,
    gross_notional_usd=0.0,
    net_delta_usd=0.0,
    exchange_notionals={},
)

try:
    result = orch.run_cycle(portfolio, {})

    print("\n結果:")
    print(f"  候補ペア: {result.candidates}")
    print(f"  エントリー意図: {result.intents}")
    print(f"  実行済み: {result.executed}")
    print(f"  ブロック: {result.blocked}")

except Exception as e:
    print(f"\nエラー: {e}")
    import traceback
    traceback.print_exc()

print("\n=" * 70)
print("完了")
