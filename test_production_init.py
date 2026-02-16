"""本番環境初期化テスト"""

import sys
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")

print("=" * 70)
print("本番環境初期化テスト開始")
print("=" * 70)

try:
    print("\n[1/3] HyperliquidMarketDataAdapter初期化中...")
    from funding_arb.hyperliquid_client import HyperliquidMarketDataAdapter
    hl_adapter = HyperliquidMarketDataAdapter(testnet=False)
    print("[1/3] ✓ MarketDataAdapter初期化成功")

    print("\n[2/3] 価格取得テスト中...")
    hl_adapter.refresh_prices()
    print(f"[2/3] ✓ 価格取得成功: {len(hl_adapter._price_cache)}銘柄")

    print("\n[3/3] HyperliquidExecutionClient初期化中...")
    from funding_arb.hyperliquid_client import HyperliquidExecutionClient
    hl_exec = HyperliquidExecutionClient(testnet=False)
    print("[3/3] ✓ ExecutionClient初期化成功（遅延ロード）")

    print("\n" + "=" * 70)
    print("✓ 全ての初期化テストが成功しました")
    print("=" * 70)

except Exception as e:
    print(f"\n✗ エラー発生: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
