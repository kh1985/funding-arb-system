"""Hyperliquid Funding Rate デバッグスクリプト"""

import sys
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")

from funding_arb import LorisAPIClient

# Loris APIからデータ取得
client = LorisAPIClient()
response = client.fetch()

# Hyperliquidのみ抽出
hl_rates = [fr for fr in response.funding_rates if fr.exchange == "hyperliquid"]

print(f"総Funding Rate数: {len(response.funding_rates)}")
print(f"Hyperliquid FR数: {len(hl_rates)}")
print()

# 正と負のFRを分類
positive = [fr for fr in hl_rates if fr.rate > 0]
negative = [fr for fr in hl_rates if fr.rate < 0]

print(f"正のFR（long払い）: {len(positive)}個")
print(f"負のFR（short払い）: {len(negative)}個")
print()

# サンプル表示
print("=== 正のFR（上位5件）===")
for fr in sorted(positive, key=lambda x: x.rate, reverse=True)[:5]:
    print(f"  {fr.symbol}: {fr.rate*100:.4f}%")

print()
print("=== 負のFR（下位5件）===")
for fr in sorted(negative, key=lambda x: x.rate)[:5]:
    print(f"  {fr.symbol}: {fr.rate*100:.4f}%")

print()
print(f"理論的ペア数: {len(positive)} × {len(negative)} = {len(positive) * len(negative)}")
