"""システムの動作確認デモ

実装済み:
✅ Loris APIクライアント
✅ 動的銘柄選定
✅ ペア候補生成
✅ リスク評価
✅ シグナル生成

必要なもの:
❌ 実際の取引所APIクライアント（ExecutionClient）
❌ market_features（相関・ベータデータ）
"""

from datetime import datetime
from funding_arb import (
    FundingArbConfig,
    FundingArbOrchestrator,
    LorisAPIClient,
    LorisMarketDataService,
    SignalService,
    RiskService,
    ExecutionService,
)
from funding_arb.types import PortfolioState
from funding_arb.config import ExchangeConfig
from funding_arb.execution import ExchangeExecutionClient


# ============================================================================
# モック実装（実際の取引はしない）
# ============================================================================

class MockExecutionClient(ExchangeExecutionClient):
    """モックの取引所クライアント（実際には注文しない）"""

    def place_order(self, exchange, symbol, side, qty, order_type, reduce_only, client_order_id):
        print(f"  [MOCK] 注文: {exchange} {symbol} {side} {qty:.4f}")
        return {
            "id": client_order_id,
            "average": 100.0,
            "filled": qty,
        }


# ============================================================================
# システムのセットアップ
# ============================================================================

def setup_demo_system():
    """デモシステムのセットアップ"""
    print("=== システムセットアップ ===\n")

    # 設定
    config = FundingArbConfig(
        exchanges=[
            ExchangeConfig("bitget"),
            ExchangeConfig("hyperliquid"),
        ],
        symbols=[],  # 動的選定
        universe_size=20,
        fr_diff_min=0.001,  # デモなので低めに
        min_persistence_windows=1,  # デモなので緩く
        min_pair_score=0.0,  # デモなので無効化
        expected_edge_min_bps=-100,  # デモなので無効化
        max_new_positions_per_cycle=3,
    )
    print(f"✅ 設定完了: {len(config.exchanges)}取引所, universe_size={config.universe_size}")

    # MarketDataService
    loris_client = LorisAPIClient()
    market_data = LorisMarketDataService(loris_client, config=config)
    print(f"✅ Loris APIクライアント準備完了")

    # SignalService
    signals = SignalService(config)
    print(f"✅ シグナルサービス準備完了")

    # RiskService
    risk = RiskService(config)
    print(f"✅ リスクサービス準備完了")

    # ExecutionService（モック）
    mock_client = MockExecutionClient()
    execution = ExecutionService(mock_client)
    print(f"✅ 実行サービス準備完了（モックモード）")

    # Orchestrator
    orch = FundingArbOrchestrator(config, market_data, signals, risk, execution)
    print(f"✅ オーケストレータ準備完了\n")

    return orch, config


# ============================================================================
# 実行
# ============================================================================

def run_demo():
    """デモ実行"""
    print("=" * 70)
    print("Funding Arbitrage System - 動作確認デモ")
    print("=" * 70)
    print()

    # セットアップ
    orch, config = setup_demo_system()

    # ポートフォリオ状態（初期状態）
    portfolio = PortfolioState(
        equity=100_000.0,  # 10万ドル
        peak_equity=100_000.0,
        gross_notional_usd=0.0,
        net_delta_usd=0.0,
        exchange_notionals={},
    )

    # market_features（空でもOK、ペアスコアはデフォルト値を使用）
    market_features = {}

    print("=== サイクル実行 ===\n")
    print(f"初期エクイティ: ${portfolio.equity:,.0f}")
    print(f"ネットデルタ: ${portfolio.net_delta_usd:,.2f}")
    print()

    try:
        # サイクル実行
        print("サイクル開始...\n")
        result = orch.run_cycle(portfolio, market_features)

        print("\n=== サイクル結果 ===\n")
        print(f"タイムスタンプ: {result.timestamp}")
        print(f"候補ペア数: {result.candidates}")
        print(f"エントリー意図: {result.intents}")
        print(f"実行済み: {result.executed}")
        print(f"ブロック済み: {result.blocked}")
        print(f"リバランス: {result.rebalanced}")

        # オープンポジション
        open_pos = orch.execution.open_positions
        print(f"\nオープンポジション数: {len(open_pos)}")
        for pair_id, pos in open_pos.items():
            print(f"  {pair_id}")
            print(f"    Leg A: {pos.leg_a.exchange} {pos.leg_a.symbol} {pos.leg_a.side.value} {pos.leg_a.qty:.4f}")
            print(f"    Leg B: {pos.leg_b.exchange} {pos.leg_b.symbol} {pos.leg_b.side.value} {pos.leg_b.qty:.4f}")

        print("\n" + "=" * 70)
        print("✅ デモ実行完了")
        print("=" * 70)

        # 次のステップ
        print("\n【次のステップ】")
        print("1. 実際の取引所APIクライアントを実装")
        print("   - BitgetのAPI連携")
        print("   - HyperliquidのAPI連携")
        print("2. market_features（相関・ベータ）の計算")
        print("   - 過去価格データの取得")
        print("   - ローリング相関の計算")
        print("3. 本番環境での小規模テスト")
        print("   - 最小ポジションサイズから開始")
        print("   - ログとモニタリングの確認")

    except Exception as e:
        print(f"\n❌ エラー発生: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_demo()
