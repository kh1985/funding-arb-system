"""DynamicUniverseProvider デバッグスクリプト"""

import sys
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")

from funding_arb import (
    FundingArbConfig,
    LorisAPIClient,
    HybridMarketDataService,
)
from funding_arb.config import ExchangeConfig
from funding_arb.hyperliquid_client import HyperliquidMarketDataAdapter

# 設定
config = FundingArbConfig(
    exchanges=[
        ExchangeConfig("hyperliquid"),
    ],
    symbols=[],
    universe_size=15,
    fr_diff_min=0.002,
    min_persistence_windows=2,
    min_pair_score=0.40,
    expected_edge_min_bps=1.0,
    max_new_positions_per_cycle=2,
    max_notional_per_pair_usd=5_000,
    max_total_notional_usd=30_000,
    allow_single_exchange_pairs=True,  # Hyperliquid内ペアリングを許可
)

# クライアント
loris_client = LorisAPIClient()
hl_adapter = HyperliquidMarketDataAdapter(testnet=True)

# HybridMarketDataService
market_data = HybridMarketDataService(
    loris_client=loris_client,
    ccxt_adapters={"hyperliquid": hl_adapter},
    config=config,
)

# 動的選定
symbols = market_data.get_top_symbols_by_criteria(
    universe_size=config.universe_size,
    min_fr_diff=config.fr_diff_min,
)

print(f"選定された銘柄数: {len(symbols)}")
print(f"銘柄: {symbols}")
print()

# 各銘柄のFRを確認
if symbols:
    print("=== 各銘柄のFR ===")
    for symbol in symbols:
        snapshots = market_data.fetch_funding_snapshots(symbols=[symbol])
        for snap in snapshots:
            if snap.exchange == "hyperliquid":
                print(f"  {symbol} ({snap.exchange}): {snap.funding_rate*100:.4f}%")
