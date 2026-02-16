"""最近の取引履歴を確認"""
import sys
import os
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from funding_arb.hyperliquid_client import HyperliquidExecutionClient
from datetime import datetime, timedelta

print("Hyperliquid 取引履歴確認中...")
print("=" * 70)

hl_exec = HyperliquidExecutionClient(testnet=False)

try:
    # ユーザーの取引履歴を取得
    user_fills = hl_exec.info.user_fills(hl_exec.main_address)

    if not user_fills:
        print("取引履歴がありません")
    else:
        print(f"取得した取引数: {len(user_fills)}\n")

        # 最近1時間の取引のみ表示
        one_hour_ago = datetime.now() - timedelta(hours=1)

        recent_fills = []
        for fill in user_fills[:20]:  # 最新20件
            timestamp_ms = fill.get('time', 0)
            fill_time = datetime.fromtimestamp(timestamp_ms / 1000)

            if fill_time > one_hour_ago:
                recent_fills.append((fill_time, fill))

        if not recent_fills:
            print("過去1時間の取引はありません")
            print("\n最新5件の取引:")
            for fill in user_fills[:5]:
                timestamp_ms = fill.get('time', 0)
                fill_time = datetime.fromtimestamp(timestamp_ms / 1000)
                coin = fill.get('coin', 'N/A')
                side = fill.get('side', 'N/A')
                px = float(fill.get('px', 0))
                sz = float(fill.get('sz', 0))
                print(f"  {fill_time.strftime('%Y-%m-%d %H:%M:%S')} - {coin} {side} {sz:.4f} @ ${px:.6f}")
        else:
            print(f"過去1時間の取引: {len(recent_fills)}件\n")

            for fill_time, fill in sorted(recent_fills, key=lambda x: x[0], reverse=True):
                coin = fill.get('coin', 'N/A')
                side = fill.get('side', 'N/A')
                px = float(fill.get('px', 0))
                sz = float(fill.get('sz', 0))
                closed_pnl = float(fill.get('closedPnl', 0))

                print(f"{fill_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  銘柄: {coin}")
                print(f"  サイド: {side}")
                print(f"  サイズ: {sz:.4f}")
                print(f"  価格: ${px:.6f}")
                if closed_pnl != 0:
                    print(f"  実現損益: ${closed_pnl:.4f}")
                print()

except Exception as e:
    print(f"エラー: {e}")
    import traceback
    traceback.print_exc()
