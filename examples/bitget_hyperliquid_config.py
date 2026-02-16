"""Bitget + Hyperliquid funding arbitrage 設定例

重要事項:
- Hyperliquidは1時間周期のfunding rate（LorisAPIClientが自動で8h相当に正規化済み）
- Loris APIは両取引所をサポート
- 動的銘柄選定により最適なペアを自動選択
"""

from funding_arb import (
    ExchangeConfig,
    FundingArbConfig,
    HybridMarketDataService,
    LorisAPIClient,
    LorisMarketDataService,
)

# ============================================================================
# 設定1: Loris単独モード（軽量・高速）
# ============================================================================

def create_loris_only_config() -> FundingArbConfig:
    """Loris API のみを使用する設定（OI・板情報なし）"""
    return FundingArbConfig(
        # 取引所設定
        exchanges=[
            ExchangeConfig("bitget", canonical_funding_sign=True),
            ExchangeConfig("hyperliquid", canonical_funding_sign=True),
        ],

        # 動的銘柄選定（空リスト = Loris APIから自動選定）
        symbols=[],
        universe_size=20,  # 上位20銘柄を選定

        # リバランス設定
        rebalance_interval_minutes=10,

        # リスク管理
        max_leverage=3.0,
        normal_leverage_cap=2.0,
        max_drawdown_stop_pct=15.0,
        reduce_mode_drawdown_pct=10.0,

        # エントリー条件
        fr_diff_min=0.003,  # 最小FR差 0.3%
        min_persistence_windows=3,  # 3サイクル持続
        min_pair_score=0.50,
        expected_edge_min_bps=5.0,  # 最小期待エッジ 5bps

        # ポジションサイズ
        max_notional_per_pair_usd=10_000,
        max_notional_per_exchange_usd=30_000,
        max_total_notional_usd=50_000,
        max_new_positions_per_cycle=2,

        # その他
        min_open_interest_usd=1_000_000,
        min_liquidity_score=0.30,
        delta_threshold_pct=10.0,
        beta_drift_threshold_pct=15.0,
        max_holding_windows=36,
        funding_event_guard_minutes=5,
    )


def setup_loris_market_data(config: FundingArbConfig) -> LorisMarketDataService:
    """Loris単独モードのMarketDataService作成"""
    loris_client = LorisAPIClient(
        cache_ttl=60.0,  # 60秒キャッシュ
        max_retries=3,
        retry_delay=1.0,
    )

    return LorisMarketDataService(
        loris_client=loris_client,
        config=config,
        exchange_filter=["bitget", "hyperliquid"],  # 対象取引所のみ
        default_oi=2_000_000.0,  # デフォルトOI値
    )


# ============================================================================
# 設定2: Hybridモード（推奨）
# ============================================================================

def create_hybrid_config() -> FundingArbConfig:
    """Loris + CCXT ハイブリッドモード設定"""
    # 基本設定はLoris単独と同じ
    config = create_loris_only_config()

    # OIと板情報が必要な場合、流動性スコアの閾値を上げる
    config.min_liquidity_score = 0.40
    config.min_open_interest_usd = 2_000_000

    return config


def setup_hybrid_market_data(
    config: FundingArbConfig,
    ccxt_adapters: dict,  # {"bitget": adapter, "hyperliquid": adapter}
) -> HybridMarketDataService:
    """Hybridモード（Loris FR + CCXT OI/板）のMarketDataService作成

    Parameters
    ----------
    config : FundingArbConfig
        設定
    ccxt_adapters : dict
        CCXTアダプタの辞書
        例: {"bitget": BinanceCCXTAdapter(), "hyperliquid": HyperliquidCCXTAdapter()}
    """
    loris_client = LorisAPIClient(cache_ttl=60.0)

    return HybridMarketDataService(
        loris_client=loris_client,
        ccxt_adapters=ccxt_adapters,
        canonical_sign_map=config.exchange_sign_map,
    )


# ============================================================================
# 設定3: 静的シンボルリスト（動的選定を使わない場合）
# ============================================================================

def create_static_symbols_config() -> FundingArbConfig:
    """特定の銘柄のみを監視する静的設定"""
    config = create_loris_only_config()

    # 動的選定の代わりに固定シンボルリストを使用
    config.symbols = [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "ARB/USDT:USDT",
        "OP/USDT:USDT",
    ]

    return config


# ============================================================================
# 使用例
# ============================================================================

if __name__ == "__main__":
    # 例1: Loris単独モード（最もシンプル）
    config = create_loris_only_config()
    market_data = setup_loris_market_data(config)

    print("Loris単独モード設定完了")
    print(f"- 取引所: {[e.name for e in config.exchanges]}")
    print(f"- 動的選定: universe_size={config.universe_size}")
    print(f"- 最小FR差: {config.fr_diff_min * 100:.2f}%")
    print(f"- 最大ポジション数/サイクル: {config.max_new_positions_per_cycle}")

    # 動的銘柄選定のテスト
    symbols = market_data.get_top_symbols_by_criteria(
        universe_size=config.universe_size,
        min_fr_diff=config.fr_diff_min,
    )
    print(f"\n選定された銘柄数: {len(symbols)}")
    if symbols:
        print(f"上位5銘柄: {symbols[:5]}")
