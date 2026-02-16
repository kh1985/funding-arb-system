"""現在のHyperliquidポジションを確認"""
import sys
import os
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from funding_arb.hyperliquid_client import HyperliquidExecutionClient

print("Hyperliquid ポジション確認中...")
print("=" * 70)

hl_exec = HyperliquidExecutionClient(testnet=False)

try:
    # ユーザー状態を取得
    user_state = hl_exec.info.user_state(hl_exec.main_address)

    if not user_state or 'assetPositions' not in user_state:
        print("ポジション情報を取得できませんでした")
        sys.exit(1)

    positions = user_state['assetPositions']

    if not positions or len(positions) == 0:
        print("現在ポジションはありません")
    else:
        print(f"現在のポジション数: {len(positions)}\n")

        for pos in positions:
            position = pos['position']
            coin = position['coin']
            szi = float(position['szi'])
            entry_px = float(position['entryPx']) if 'entryPx' in position else 0
            unrealized_pnl = float(position['unrealizedPnl']) if 'unrealizedPnl' in position else 0

            side = "LONG" if szi > 0 else "SHORT"
            notional = abs(szi * entry_px)

            print(f"銘柄: {coin}")
            print(f"  サイド: {side}")
            print(f"  サイズ: {abs(szi):.4f}")
            print(f"  エントリー価格: ${entry_px:.6f}")
            print(f"  想定元本: ${notional:.2f}")
            print(f"  未実現損益: ${unrealized_pnl:.2f}")
            print()

    # アカウント情報も表示
    if 'marginSummary' in user_state:
        margin = user_state['marginSummary']
        account_value = float(margin['accountValue'])
        total_margin_used = float(margin['totalMarginUsed']) if 'totalMarginUsed' in margin else 0

        print("=" * 70)
        print("アカウント情報:")
        print(f"  口座残高: ${account_value:.2f}")
        print(f"  使用証拠金: ${total_margin_used:.2f}")
        print("=" * 70)

except Exception as e:
    print(f"エラー: {e}")
    import traceback
    traceback.print_exc()
