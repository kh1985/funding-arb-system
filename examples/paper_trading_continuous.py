"""連続ペーパートレーディング - 放置可能

Ctrl+C で停止するまで実行し続けます。
リアルタイムでfunding rateを監視し、自動的にペアを選定・実行します。
"""

import time
import signal
import sys
from paper_trading import PaperTradingSimulator


class ContinuousPaperTrading:
    """連続実行用のラッパー"""

    def __init__(self, initial_capital=100_000, cycle_interval_minutes=10):
        self.simulator = PaperTradingSimulator(initial_capital)
        self.cycle_interval = cycle_interval_minutes * 60  # 秒に変換
        self.running = True

        # Ctrl+C のハンドラ設定
        signal.signal(signal.SIGINT, self.handle_interrupt)

    def handle_interrupt(self, signum, frame):
        """Ctrl+C が押されたときの処理"""
        print("\n\n🛑 停止シグナルを受信しました...")
        self.running = False

    def run(self):
        """連続実行"""
        print("\n" + "=" * 70)
        print("連続ペーパートレーディング")
        print("=" * 70)
        print(f"初期資金: ${self.simulator.initial_capital:,.0f}")
        print(f"サイクル間隔: {self.cycle_interval // 60}分")
        print(f"取引所: {[e.name for e in self.simulator.config.exchanges]}")
        print("\n💡 Ctrl+C で停止できます")
        print("=" * 70)

        try:
            while self.running:
                # 1サイクル実行
                self.simulator.run_cycle()

                if self.running:
                    # 次のサイクルまで待機
                    print(f"\n⏰ 次のサイクルまで {self.cycle_interval // 60}分待機...")
                    print(f"   (Ctrl+C で停止できます)")

                    # 1秒ごとにチェックして中断可能に
                    for i in range(self.cycle_interval):
                        if not self.running:
                            break
                        time.sleep(1)

                        # 30秒ごとに待機中のメッセージ
                        if (i + 1) % 30 == 0:
                            remaining = (self.cycle_interval - i - 1) // 60
                            print(f"   残り約{remaining}分...")

        except KeyboardInterrupt:
            print("\n\n🛑 KeyboardInterrupt を検出")
            self.running = False

        finally:
            # 最終結果を表示
            print("\n\n" + "=" * 70)
            print("停止処理中...")
            print("=" * 70)
            self.simulator.print_final_summary()


def main():
    """メイン実行"""
    print("\n選択してください:")
    print("1. デモモード（10サイクルで終了）")
    print("2. 連続モード（Ctrl+Cで停止するまで実行）")
    print()

    try:
        choice = input("番号を入力 [1-2]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\nキャンセルされました。")
        return

    if choice == "1":
        # デモモード
        print("\n🎮 デモモード開始")
        simulator = PaperTradingSimulator(initial_capital=100_000)
        simulator.run_continuous(cycles=10, interval_minutes=10)

    elif choice == "2":
        # 連続モード
        print("\n🔄 連続モード開始")
        continuous = ContinuousPaperTrading(
            initial_capital=100_000,
            cycle_interval_minutes=10
        )
        continuous.run()

    else:
        print("❌ 無効な選択です。")


if __name__ == "__main__":
    main()
