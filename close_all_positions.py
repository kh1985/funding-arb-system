"""全ポジションをクローズ"""
import sys
import os
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from funding_arb.hyperliquid_client import HyperliquidExecutionClient

print("全ポジションをクローズします...")
print("=" * 70)

hl_exec = HyperliquidExecutionClient(testnet=False)

try:
    # 現在のポジション取得
    user_state = hl_exec.info.user_state(hl_exec.main_address)

    if not user_state or 'assetPositions' not in user_state:
        print("ポジション情報を取得できませんでした")
        sys.exit(1)

    positions = user_state['assetPositions']

    if not positions or len(positions) == 0:
        print("クローズするポジションはありません")
        sys.exit(0)

    print(f"クローズ対象: {len(positions)}ポジション\n")

    # 各ポジションをクローズ
    for i, pos in enumerate(positions, 1):
        position = pos['position']
        coin = position['coin']
        szi = float(position['szi'])

        if szi == 0:
            print(f"[{i}/{len(positions)}] {coin}: サイズ0、スキップ")
            continue

        side = "LONG" if szi > 0 else "SHORT"
        print(f"[{i}/{len(positions)}] {coin} {side}をクローズ中...", end=" ")

        try:
            result = hl_exec.exchange.market_close(coin=coin)

            if result.get("status") == "ok":
                print("✅ 成功")
            else:
                print(f"❌ 失敗: {result}")

        except Exception as e:
            print(f"❌ エラー: {e}")

    print("\n" + "=" * 70)
    print("全ポジションのクローズ処理が完了しました")
    print("=" * 70)

except Exception as e:
    print(f"エラー: {e}")
    import traceback
    traceback.print_exc()
