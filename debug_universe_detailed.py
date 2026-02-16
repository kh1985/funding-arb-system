"""DynamicUniverseProvider 詳細デバッグ"""

import sys
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")

from funding_arb import (
    FundingArbConfig,
    LorisAPIClient,
)
from funding_arb.config import ExchangeConfig
from funding_arb.universe import DynamicUniverseProvider

# 設定
config = FundingArbConfig(
    exchanges=[ExchangeConfig("hyperliquid")],
    symbols=[],
    universe_size=15,
    fr_diff_min=0.002,
    allow_single_exchange_pairs=True,
)

loris_client = LorisAPIClient()

# DynamicUniverseProviderを直接作成
universe = DynamicUniverseProvider(
    config=config,
    loris_client=loris_client,
    target_exchanges=["hyperliquid"],
)

print("=== DynamicUniverseProvider 初期化完了 ===")
print(f"target_exchanges: {universe._target_exchanges}")
print(f"allow_single_exchange_pairs: {config.allow_single_exchange_pairs}")
print()

# Loris APIからデータ取得
response = loris_client.fetch()
print(f"Loris API: 総FR数 {len(response.funding_rates)}")

# フィルタリング後
filtered = universe._filter_rates(response)
print(f"フィルタ後: {len(filtered)}個")
print()

# グループ化
grouped = universe._group_by_symbol(filtered)
print(f"グループ化後: {len(grouped)}銘柄")
print()

# スコアリング
scores = universe._score_symbols(grouped)
print(f"スコアリング後: {len(scores)}銘柄")
print()

if scores:
    print("=== 上位5銘柄のスコア ===")
    sorted_scores = sorted(scores.values(), key=lambda s: (s.max_fr_spread, s.exchange_count), reverse=True)
    for i, score in enumerate(sorted_scores[:5], 1):
        print(f"{i}. {score.symbol}: spread={score.max_fr_spread*100:.4f}%, exchanges={score.exchange_count}")
else:
    print("スコアが0個！")
    print()
    print("=== グループ化されたデータの例 ===")
    for symbol, rates in list(grouped.items())[:5]:
        print(f"{symbol}: {len(rates)}個の取引所")
        for rate in rates:
            print(f"  - {rate.exchange}: {rate.rate*100:.4f}%")
