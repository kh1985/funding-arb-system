"""1取引所内での Funding Arbitrage 戦略

戦略の本質:
- 同一取引所内で異なる銘柄のFRが反対符号の場合にペア構築
- 例: Bitget内で BTC(FR+0.03%) と ETH(FR-0.02%) をペアリング
- 取引所数は関係なし。1取引所でも複数銘柄があれば成立

Bitget単独で十分に運用可能。
"""

from funding_arb import ExchangeConfig, FundingArbConfig, LorisAPIClient, LorisMarketDataService


def create_single_exchange_config(exchange_name: str = "bitget") -> FundingArbConfig:
    """1取引所のみでの運用設定

    Parameters
    ----------
    exchange_name : str
        "bitget" または "hyperliquid"
    """
    return FundingArbConfig(
        # 1取引所のみ
        exchanges=[
            ExchangeConfig(exchange_name, canonical_funding_sign=True)
        ],

        # 動的銘柄選定
        symbols=[],
        universe_size=25,  # 25銘柄を監視

        # エントリー条件
        fr_diff_min=0.002,  # 最小FR差 0.2%
        min_persistence_windows=3,
        min_pair_score=0.50,
        expected_edge_min_bps=3.0,

        # リスク管理
        max_leverage=3.0,
        normal_leverage_cap=2.0,
        max_drawdown_stop_pct=15.0,
        reduce_mode_drawdown_pct=10.0,

        # ポジションサイズ（1取引所なので集中リスクに注意）
        max_notional_per_pair_usd=8_000,
        max_notional_per_exchange_usd=40_000,  # 1取引所のみなので実質全体上限
        max_total_notional_usd=40_000,
        max_new_positions_per_cycle=3,  # 複数ペア同時運用可能

        # その他
        rebalance_interval_minutes=10,
        delta_threshold_pct=10.0,
        min_open_interest_usd=1_000_000,
        min_liquidity_score=0.30,
    )


def setup_single_exchange_system(exchange_name: str = "bitget"):
    """1取引所システムのセットアップ

    Returns
    -------
    tuple
        (config, market_data)
    """
    config = create_single_exchange_config(exchange_name)

    loris_client = LorisAPIClient(cache_ttl=60.0)

    market_data = LorisMarketDataService(
        loris_client=loris_client,
        config=config,
        exchange_filter=[exchange_name],  # 1取引所のみ
    )

    return config, market_data


# ============================================================================
# 実行例
# ============================================================================

if __name__ == "__main__":
    # Bitget単独で運用
    config, market_data = setup_single_exchange_system("bitget")

    print("=== Bitget単独 Funding Arbitrage 設定 ===")
    print(f"取引所: {[e.name for e in config.exchanges]}")
    print(f"監視銘柄数: {config.universe_size}")
    print(f"最小FR差: {config.fr_diff_min * 100:.2f}%")
    print(f"最大ペア数/サイクル: {config.max_new_positions_per_cycle}")
    print()

    # 動的銘柄選定のテスト
    print("動的銘柄選定を実行中...")
    symbols = market_data.get_top_symbols_by_criteria(
        universe_size=config.universe_size,
        min_fr_diff=config.fr_diff_min,
    )

    print(f"選定された銘柄数: {len(symbols)}")
    if len(symbols) >= 10:
        print(f"上位10銘柄: {symbols[:10]}")
    elif symbols:
        print(f"全銘柄: {symbols}")

    # Loris APIから実際のFRを取得して反対符号ペアを確認
    print("\n=== Bitget内の反対符号ペア例 ===")
    loris_client = LorisAPIClient()
    response = loris_client.fetch()

    bitget_rates = [fr for fr in response.funding_rates if fr.exchange == "bitget"]

    positive_fr = [fr for fr in bitget_rates if fr.rate > 0][:5]
    negative_fr = [fr for fr in bitget_rates if fr.rate < 0][:5]

    print(f"\nプラスFR銘柄（上位5）:")
    for fr in positive_fr:
        print(f"  {fr.symbol}: +{fr.rate * 100:.3f}%")

    print(f"\nマイナスFR銘柄（上位5）:")
    for fr in negative_fr:
        print(f"  {fr.symbol}: {fr.rate * 100:.3f}%")

    if positive_fr and negative_fr:
        print(f"\n例: {positive_fr[0].symbol}(short) + {negative_fr[0].symbol}(long)")
        print(f"  → 合計収益: {(abs(positive_fr[0].rate) + abs(negative_fr[0].rate)) * 100:.3f}%")
