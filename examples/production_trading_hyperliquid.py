"""本番環境 Hyperliquid 少額取引

⚠️ 警告: このスクリプトは実際のお金を使います
- 初期資金: $1,000（少額でテスト）
- 1ペアあたり: $100-200
- 最大ポジション数: 2
"""

import sys
import os

# hyperliquid-botのsrcパスを追加
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")

import time
from datetime import datetime
from funding_arb import (
    FundingArbConfig,
    FundingArbOrchestrator,
    LorisAPIClient,
    HybridMarketDataService,
    SignalService,
    RiskService,
    ExecutionService,
)
from funding_arb.config import ExchangeConfig
from funding_arb.types import PortfolioState
from funding_arb.hyperliquid_client import HyperliquidMarketDataAdapter, HyperliquidExecutionClient


class ProductionTradingSimulator:
    """本番環境取引システム"""

    def __init__(self, initial_capital=50):
        print("\n" + "="*70)
        print("⚠️  本番環境 Hyperliquid 少額取引")
        print("="*70)
        print(f"初期資金: ${initial_capital:,.0f}")
        print(f"1ペアあたり最大: $20")
        print(f"最大同時ポジション: 1ペア")
        print("="*70)

        # 確認プロンプト
        confirm = input("\n本当に実行しますか？ (yes/no): ")
        if confirm.lower() != "yes":
            print("キャンセルしました")
            sys.exit(0)

        self.initial_capital = initial_capital
        self.loris_client = LorisAPIClient()

        # Hyperliquid 本番環境
        print("\n[初期化] Hyperliquid MarketDataAdapter初期化中...", flush=True)
        try:
            self.hl_adapter = HyperliquidMarketDataAdapter(testnet=False)
            print("[初期化] MarketDataAdapter完了", flush=True)
        except Exception as e:
            print(f"[エラー] MarketDataAdapter初期化失敗: {e}", flush=True)
            raise

        print("[初期化] Hyperliquid ExecutionClient初期化中...", flush=True)
        try:
            self.hl_exec = HyperliquidExecutionClient(testnet=False)
            print("[初期化] ExecutionClient完了", flush=True)
        except Exception as e:
            print(f"[エラー] ExecutionClient初期化失敗: {e}", flush=True)
            raise

        # 設定（$50用・超保守的）
        self.config = FundingArbConfig(
            exchanges=[
                ExchangeConfig("hyperliquid"),
            ],
            symbols=[],
            universe_size=10,  # 10銘柄に制限
            fr_diff_min=0.003,  # 0.3%以上のFR差を要求（厳しめ）
            min_persistence_windows=3,  # 3サイクル継続を要求
            min_pair_score=0.50,  # スコア0.5以上
            expected_edge_min_bps=2.0,  # 2bps以上のエッジ
            max_new_positions_per_cycle=1,  # 1サイクル1ペアまで
            max_notional_per_pair_usd=20,  # 1ペア$20まで
            max_total_notional_usd=50,  # 合計$50まで
            allow_single_exchange_pairs=True,
        )

        # HybridMarketDataService
        market_data = HybridMarketDataService(
            loris_client=self.loris_client,
            ccxt_adapters={"hyperliquid": self.hl_adapter},
            config=self.config,
        )

        signals = SignalService(self.config)
        risk = RiskService(self.config)
        execution = ExecutionService(self.hl_exec)

        self.orch = FundingArbOrchestrator(
            self.config, market_data, signals, risk, execution
        )

        self.start_time = datetime.utcnow()
        self.cycle_count = 0

        print("[初期化完了] 取引準備完了", flush=True)

    def get_current_portfolio(self):
        """現在のポートフォリオ状態を取得"""
        # 簡易版：初期資金ベース
        # 実際には、Hyperliquid APIから実際のポジションとエクイティを取得すべき
        return PortfolioState(
            equity=self.initial_capital,
            peak_equity=self.initial_capital,
            gross_notional_usd=0.0,
            net_delta_usd=0.0,
            exchange_notionals={},
        )

    def run_cycle(self):
        """1サイクル実行"""
        self.cycle_count += 1

        print(f"\n{'='*70}")
        print(f"サイクル #{self.cycle_count} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")

        # ポートフォリオ状態
        portfolio = self.get_current_portfolio()

        # サイクル実行
        market_features = {}
        result = self.orch.run_cycle(portfolio, market_features)

        print(f"\n結果:")
        print(f"  候補ペア: {result.candidates}")
        print(f"  エントリー意図: {result.intents}")
        print(f"  実行済み: {result.executed}")
        print(f"  ブロック: {result.blocked}")

        if result.executed > 0:
            print(f"\n⚠️  {result.executed}件の注文を実行しました")

    def run_continuous(self, max_cycles=None, interval_minutes=10):
        """連続実行"""
        print(f"\n連続実行モード:")
        print(f"  サイクル間隔: {interval_minutes}分")
        print(f"  最大サイクル数: {max_cycles if max_cycles else '無制限'}")
        print(f"  Ctrl+C で停止")
        print()

        cycle = 0
        try:
            while True:
                self.run_cycle()
                cycle += 1

                if max_cycles and cycle >= max_cycles:
                    print(f"\n最大サイクル数 {max_cycles} に到達しました")
                    break

                print(f"\n次のサイクルまで {interval_minutes} 分待機中...")
                time.sleep(interval_minutes * 60)

        except KeyboardInterrupt:
            print("\n\n[中断] ユーザーによって停止されました")
        finally:
            self.print_final_summary()

    def print_final_summary(self):
        """最終サマリー"""
        duration = datetime.utcnow() - self.start_time

        print(f"\n{'='*70}")
        print("最終結果")
        print(f"{'='*70}")
        print(f"実行時間: {duration}")
        print(f"サイクル数: {self.cycle_count}")
        print(f"{'='*70}")


if __name__ == "__main__":
    print("\n⚠️⚠️⚠️  警告  ⚠️⚠️⚠️")
    print("このスクリプトは本番環境で実際の取引を行います")
    print("テスト環境ではありません")
    print("\n前提条件:")
    print("1. .envファイルに本番環境の秘密鍵が設定されている")
    print("2. HL_TESTNET=false になっている")
    print("3. Hyperliquid本番アカウントに資金がある")
    print()

    simulator = ProductionTradingSimulator(initial_capital=50)

    # 最初は5サイクル（50分）だけ実行
    simulator.run_continuous(max_cycles=5, interval_minutes=10)
