"""シンプルな本番環境テスト（1サイクルのみ）"""

import sys
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")

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
print("本番環境 1サイクルテスト", flush=True)
print("=" * 70, flush=True)

# 初期化
print("\n[1/5] LorisAPIClient初期化...", flush=True)
loris_client = LorisAPIClient()

print("[2/5] HyperliquidMarketDataAdapter初期化...", flush=True)
hl_adapter = HyperliquidMarketDataAdapter(testnet=False)

print("[3/5] HyperliquidExecutionClient初期化...", flush=True)
hl_exec = HyperliquidExecutionClient(testnet=False)

print("[4/5] 設定とサービス初期化...", flush=True)
config = FundingArbConfig(
    exchanges=[ExchangeConfig("hyperliquid")],
    symbols=[],
    universe_size=10,
    fr_diff_min=0.003,
    min_persistence_windows=3,
    min_pair_score=0.50,
    expected_edge_min_bps=2.0,
    max_new_positions_per_cycle=1,
    max_notional_per_pair_usd=20,
    max_total_notional_usd=50,
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

print("[5/5] 初期化完了", flush=True)

# 1サイクル実行
print("\n" + "=" * 70, flush=True)
print(f"サイクル実行中 - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
print("=" * 70, flush=True)

portfolio = PortfolioState(
    equity=50.0,
    peak_equity=50.0,
    gross_notional_usd=0.0,
    net_delta_usd=0.0,
    exchange_notionals={},
)

result = orch.run_cycle(portfolio, {})

print("\n結果:", flush=True)
print(f"  候補ペア: {result.candidates}", flush=True)
print(f"  エントリー意図: {result.intents}", flush=True)
print(f"  実行済み: {result.executed}", flush=True)
print(f"  ブロック: {result.blocked}", flush=True)

print("\n" + "=" * 70, flush=True)
print("テスト完了！", flush=True)
print("=" * 70, flush=True)
