"""HMSTRの価格問題を調査"""

import sys
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")

from funding_arb import LorisAPIClient
from funding_arb.hyperliquid_client import HyperliquidMarketDataAdapter

# Loris APIでHMSTRのFRを確認
loris = LorisAPIClient()
response = loris.fetch()

hmstr_rates = [fr for fr in response.funding_rates if fr.symbol == "HMSTR" and fr.exchange == "hyperliquid"]
print("=== Loris API: HMSTR ===")
if hmstr_rates:
    for fr in hmstr_rates:
        print(f"Exchange: {fr.exchange}, Symbol: {fr.symbol}, Rate: {fr.rate*100:.4f}%")
else:
    print("HMSTR が見つかりません")
print()

# Hyperliquid APIでHMSTRの価格を確認
hl = HyperliquidMarketDataAdapter(testnet=True)
print("=== Hyperliquid API: all_mids() ===")
try:
    all_mids = hl.info.all_mids()
    print(f"総銘柄数: {len(all_mids)}")

    # HMSTRを検索
    hmstr_variants = ["HMSTR", "HAMSTER", "hmstr", "Hmstr"]
    for variant in hmstr_variants:
        if variant in all_mids:
            print(f"✓ {variant}: {all_mids[variant]}")
        else:
            print(f"✗ {variant}: 見つかりません")

    # "H"で始まる銘柄を確認
    print()
    print("=== 'H'で始まる銘柄 ===")
    h_symbols = {k: v for k, v in all_mids.items() if k.startswith('H') or k.startswith('h')}
    for sym, price in sorted(h_symbols.items()):
        print(f"{sym}: {price}")

except Exception as e:
    print(f"エラー: {e}")

print()
print("=== HyperliquidMarketDataAdapterのキャッシュ ===")
hl.refresh_prices()
print(f"キャッシュサイズ: {len(hl._price_cache)}")

# _normalize_symbolの動作確認
test_symbols = ["HMSTR/USDT:USDT", "HMSTR", "Hmstr/USDT:USDT"]
print()
print("=== シンボル正規化テスト ===")
for sym in test_symbols:
    normalized = hl._normalize_symbol(sym)
    price = hl.get_mark_price(sym)
    print(f"{sym} → {normalized} → ${price}")
