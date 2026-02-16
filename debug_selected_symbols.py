"""選定された銘柄とFRを確認"""

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
    exchanges=[ExchangeConfig("hyperliquid")],
    symbols=[],
    universe_size=15,
    fr_diff_min=0.002,
    allow_single_exchange_pairs=True,
)

loris_client = LorisAPIClient()
hl_adapter = HyperliquidMarketDataAdapter(testnet=True)

market_data = HybridMarketDataService(
    loris_client=loris_client,
    ccxt_adapters={"hyperliquid": hl_adapter},
    config=config,
)

# 選定された銘柄
symbols = market_data.get_top_symbols_by_criteria(
    universe_size=config.universe_size,
    min_fr_diff=config.fr_diff_min,
)

print(f"選定銘柄数: {len(symbols)}")
print(f"銘柄: {symbols}")
print()

# 各銘柄のFRを確認
response = loris_client.fetch()
hl_rates = {fr.symbol: fr.rate for fr in response.funding_rates if fr.exchange == "hyperliquid"}

print("=== 選定銘柄のFR ===")
for sym in symbols:
    base = sym.split("/")[0]
    rate = hl_rates.get(base, 0)
    print(f"{base}: {rate*100:.4f}%")

print()
print("=== YZY と FTT は選定されているか？===")
print(f"YZY: {'YZY/USDT:USDT' in symbols} (FR: {hl_rates.get('YZY', 0)*100:.4f}%)")
print(f"FTT: {'FTT/USDT:USDT' in symbols} (FR: {hl_rates.get('FTT', 0)*100:.4f}%)")
print()

# FR差が大きい順にトップ10
print("=== FR差が大きい組み合わせ（トップ10）===")
positive = [(sym, rate) for sym, rate in hl_rates.items() if rate > 0]
negative = [(sym, rate) for sym, rate in hl_rates.items() if rate < 0]

pairs = []
for pos_sym, pos_rate in positive:
    for neg_sym, neg_rate in negative:
        diff = abs(pos_rate - neg_rate)
        pairs.append((pos_sym, neg_sym, diff))

pairs.sort(key=lambda x: x[2], reverse=True)
for i, (sym1, sym2, diff) in enumerate(pairs[:10], 1):
    print(f"{i}. {sym1}(+{hl_rates[sym1]*100:.4f}%) - {sym2}({hl_rates[sym2]*100:.4f}%) = {diff*100:.4f}%")
