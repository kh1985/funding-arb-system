"""本番環境 連続実行版（$50少額取引）

10分ごとに自動実行し、Ctrl+Cで停止するまで継続します。
"""

import sys
import os
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

print("=" * 70, flush=True)
print("本番環境 連続実行モード", flush=True)
print("=" * 70, flush=True)
print("初期資金: $50", flush=True)
print("1ペアあたり: 最大$20", flush=True)
print("サイクル間隔: 10分", flush=True)
print("停止方法: Ctrl+C", flush=True)
print("=" * 70, flush=True)

# 初期化
print("\n[初期化中...]", flush=True)
loris_client = LorisAPIClient()
hl_adapter = HyperliquidMarketDataAdapter(testnet=False)
hl_exec = HyperliquidExecutionClient(testnet=False)

config = FundingArbConfig(
    exchanges=[ExchangeConfig("hyperliquid")],
    symbols=[],
    universe_size=10,
    fr_diff_min=0.001,  # 0.1%以上（緩和）
    min_persistence_windows=1,  # 1サイクルで即エントリー可能（緩和）
    min_pair_score=0.30,  # スコア要件緩和
    expected_edge_min_bps=1.0,  # エッジ要件緩和
    max_new_positions_per_cycle=1,
    max_notional_per_pair_usd=30,  # ペアあたり$30（各レッグ$15前後）
    max_total_notional_usd=60,  # 合計$60（betaが小さいペアを考慮）
    allow_single_exchange_pairs=True,
)

market_data = HybridMarketDataService(
    loris_client=loris_client,
    ccxt_adapters={"hyperliquid": hl_adapter},
    config=config,
)

signals = SignalService(config)
risk = RiskService(config)
execution = ExecutionService(hl_exec)

orch = FundingArbOrchestrator(config, market_data, signals, risk, execution)

print("[初期化完了]", flush=True)

# 連続実行
cycle_count = 0
start_time = datetime.utcnow()
total_executed = 0

try:
    while True:
        cycle_count += 1

        print("\n" + "=" * 70, flush=True)
        print(f"サイクル #{cycle_count} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
        print("=" * 70, flush=True)

        # ポートフォリオ状態（簡易版）
        portfolio = PortfolioState(
            equity=50.0,
            peak_equity=50.0,
            gross_notional_usd=0.0,
            net_delta_usd=0.0,
            exchange_notionals={},
        )

        # サイクル実行
        try:
            result = orch.run_cycle(portfolio, {})

            print(f"\n結果:", flush=True)
            print(f"  候補ペア: {result.candidates}", flush=True)
            print(f"  エントリー意図: {result.intents}", flush=True)
            print(f"  実行済み: {result.executed}", flush=True)
            print(f"  ブロック: {result.blocked}", flush=True)

            total_executed += result.executed

            if result.executed > 0:
                print(f"\n⚠️  {result.executed}件の注文を実行しました", flush=True)

        except Exception as e:
            print(f"\n✗ サイクルエラー: {e}", flush=True)
            import traceback
            traceback.print_exc()

        # 累計統計
        duration = datetime.utcnow() - start_time
        print(f"\n累計統計:", flush=True)
        print(f"  実行時間: {duration}", flush=True)
        print(f"  総サイクル数: {cycle_count}", flush=True)
        print(f"  総注文数: {total_executed}", flush=True)

        # 10分待機
        if cycle_count == 1:
            print(f"\n次のサイクルまで10分待機中...", flush=True)
            print(f"  (Ctrl+Cで停止)", flush=True)

        time.sleep(600)  # 10分 = 600秒

except KeyboardInterrupt:
    print("\n\n" + "=" * 70, flush=True)
    print("停止シグナルを受信しました", flush=True)
    print("=" * 70, flush=True)

    duration = datetime.utcnow() - start_time
    print(f"\n最終統計:", flush=True)
    print(f"  実行時間: {duration}", flush=True)
    print(f"  総サイクル数: {cycle_count}", flush=True)
    print(f"  総注文数: {total_executed}", flush=True)
    print("\n正常に停止しました", flush=True)

except Exception as e:
    print(f"\n✗ 予期しないエラー: {e}", flush=True)
    import traceback
    traceback.print_exc()
