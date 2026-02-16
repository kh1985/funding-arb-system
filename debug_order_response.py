"""注文レスポンスを詳しく確認"""
import sys
import os
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from funding_arb.hyperliquid_client import HyperliquidExecutionClient

hl_exec = HyperliquidExecutionClient(testnet=False)

print("簡単な成行注文テスト")
print("=" * 70)

# 小さなサイズでテスト（STBL）
ticker = "STBL"
is_buy = False  # Sell
size = 1.0  # 最小サイズ

print(f"注文: {ticker} {'BUY' if is_buy else 'SELL'} {size}")

try:
    result = hl_exec.exchange.market_open(
        name=ticker,
        is_buy=is_buy,
        sz=size,
    )

    print("\nレスポンス:")
    print(json.dumps(result, indent=2))

    if result.get("status") == "ok":
        print("\n✅ 注文成功")

        # 約定したか確認
        user_fills = hl_exec.info.user_fills(hl_exec.main_address)
        if user_fills:
            latest = user_fills[0]
            print(f"\n最新の約定:")
            print(f"  銘柄: {latest.get('coin')}")
            print(f"  サイド: {latest.get('side')}")
            print(f"  サイズ: {latest.get('sz')}")
            print(f"  価格: {latest.get('px')}")
    else:
        print(f"\n❌ 注文失敗: {result}")

except Exception as e:
    print(f"\nエラー: {e}")
    import traceback
    traceback.print_exc()
