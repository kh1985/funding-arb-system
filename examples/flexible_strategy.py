"""柔軟なペアリング戦略

このシステムは以下の全パターンを自動評価:
1. 同一取引所・異なる銘柄（例: Bitget BTC + Bitget ETH）
2. 異なる取引所・同一銘柄（例: Bitget BTC + Hyperliquid BTC）← クラシック
3. 異なる取引所・異なる銘柄（例: Bitget BTC + Hyperliquid SOL）← クロス

唯一の除外条件:
- 同一銘柄 AND 同一取引所
- FRが同符号

最適なペアをスコアリングで自動選定。
"""

from funding_arb import FundingArbConfig, LorisAPIClient, LorisMarketDataService
from funding_arb.config import ExchangeConfig


def create_flexible_config() -> FundingArbConfig:
    """最も柔軟な設定 - あらゆるペアパターンを評価"""
    return FundingArbConfig(
        # 利用可能な全取引所を登録
        exchanges=[
            ExchangeConfig("bitget", canonical_funding_sign=True),
            ExchangeConfig("hyperliquid", canonical_funding_sign=True),
        ],

        # 動的銘柄選定 - 両取引所から最適な銘柄を選ぶ
        symbols=[],
        universe_size=30,  # 2取引所なので多めに

        # エントリー条件
        fr_diff_min=0.002,  # 0.2%
        min_persistence_windows=3,
        min_pair_score=0.50,  # ペアスコアで質を担保
        expected_edge_min_bps=3.0,

        # リスク管理
        max_leverage=3.0,
        normal_leverage_cap=2.0,
        max_drawdown_stop_pct=15.0,
        reduce_mode_drawdown_pct=10.0,

        # ポジションサイズ
        max_notional_per_pair_usd=10_000,
        max_notional_per_exchange_usd=40_000,  # 各取引所40K
        max_total_notional_usd=80_000,  # 全体80K
        max_new_positions_per_cycle=3,

        # その他
        rebalance_interval_minutes=10,
        delta_threshold_pct=10.0,
        beta_drift_threshold_pct=15.0,
        min_open_interest_usd=1_000_000,
        min_liquidity_score=0.30,
    )


def analyze_pair_patterns():
    """実際のLorisデータから可能なペアパターンを分析"""
    loris_client = LorisAPIClient()
    response = loris_client.fetch()

    bitget_rates = [fr for fr in response.funding_rates if fr.exchange == "bitget"]
    hyper_rates = [fr for fr in response.funding_rates if fr.exchange == "hyperliquid"]

    print("=== ペアパターン分析 ===\n")

    # パターン1: 同一取引所・異なる銘柄
    print("【パターン1】同一取引所・異なる銘柄")
    bitget_pos = [fr for fr in bitget_rates if fr.rate > 0][:3]
    bitget_neg = [fr for fr in bitget_rates if fr.rate < 0][:3]

    if bitget_pos and bitget_neg:
        for pos, neg in zip(bitget_pos, bitget_neg):
            spread = abs(pos.rate) + abs(neg.rate)
            print(f"  Bitget {pos.symbol}(short) + Bitget {neg.symbol}(long)")
            print(f"    → FR差: {spread * 100:.3f}%")

    # パターン2: 異なる取引所・同一銘柄
    print("\n【パターン2】異なる取引所・同一銘柄（クラシック）")
    bitget_symbols = {fr.symbol: fr for fr in bitget_rates}
    hyper_symbols = {fr.symbol: fr for fr in hyper_rates}

    common_symbols = set(bitget_symbols.keys()) & set(hyper_symbols.keys())
    classic_pairs = []

    for symbol in common_symbols:
        bg_rate = bitget_symbols[symbol].rate
        hl_rate = hyper_symbols[symbol].rate

        # 反対符号のみ
        if bg_rate * hl_rate < 0:
            spread = abs(bg_rate - hl_rate)
            classic_pairs.append((symbol, bg_rate, hl_rate, spread))

    # FR差でソート
    classic_pairs.sort(key=lambda x: x[3], reverse=True)

    for symbol, bg_rate, hl_rate, spread in classic_pairs[:3]:
        bg_side = "short" if bg_rate > 0 else "long"
        hl_side = "long" if bg_rate > 0 else "short"
        print(f"  {symbol}: Bitget {bg_side}({bg_rate*100:+.3f}%) + Hyperliquid {hl_side}({hl_rate*100:+.3f}%)")
        print(f"    → FR差: {spread * 100:.3f}%")

    # パターン3: 異なる取引所・異なる銘柄
    print("\n【パターン3】異なる取引所・異なる銘柄（クロス戦略）")
    cross_pairs = []

    for bg_fr in bitget_rates[:10]:
        for hl_fr in hyper_rates[:10]:
            if bg_fr.symbol == hl_fr.symbol:
                continue
            if bg_fr.rate * hl_fr.rate >= 0:
                continue

            spread = abs(bg_fr.rate) + abs(hl_fr.rate)
            cross_pairs.append((bg_fr.symbol, hl_fr.symbol, bg_fr.rate, hl_fr.rate, spread))

    cross_pairs.sort(key=lambda x: x[4], reverse=True)

    for bg_sym, hl_sym, bg_rate, hl_rate, spread in cross_pairs[:3]:
        bg_side = "short" if bg_rate > 0 else "long"
        hl_side = "long" if bg_rate > 0 else "short"
        print(f"  Bitget {bg_sym} {bg_side}({bg_rate*100:+.3f}%) + Hyperliquid {hl_sym} {hl_side}({hl_rate*100:+.3f}%)")
        print(f"    → FR差: {spread * 100:.3f}%")

    print(f"\n総ペア候補数の推定:")
    print(f"  Bitget銘柄数: {len(bitget_rates)}")
    print(f"  Hyperliquid銘柄数: {len(hyper_rates)}")
    print(f"  理論上の組み合わせ数: {len(bitget_rates) * len(hyper_rates) + len(bitget_rates) * (len(bitget_rates)-1) // 2 + len(hyper_rates) * (len(hyper_rates)-1) // 2}")


def show_system_behavior():
    """システムの実際の動作を説明"""
    print("\n=== システムの動作フロー ===\n")

    print("1. 【銘柄取得】")
    print("   Loris APIから全銘柄のFRを取得")
    print("   - Bitget: 全対応銘柄")
    print("   - Hyperliquid: 全対応銘柄")

    print("\n2. 【ペア候補生成】（signals.py:build_pair_candidates）")
    print("   全組み合わせを総当たりで評価:")
    print("   - 同一銘柄 AND 同一取引所 → 除外")
    print("   - 同符号のFR → 除外")
    print("   - それ以外 → 全て候補")

    print("\n3. 【スコアリング】")
    print("   各ペアを以下で評価:")
    print("   - 相関係数: 30%")
    print("   - ベータ安定性: 25%")
    print("   - 流動性: 20%")
    print("   - ATR安定性: 15%")
    print("   - 平均回帰: 10%")

    print("\n4. 【フィルタリング】")
    print("   - FR差 >= 0.2%")
    print("   - 永続性 >= 3サイクル")
    print("   - ペアスコア >= 0.50")
    print("   - 期待エッジ >= 3bps")

    print("\n5. 【選定】")
    print("   上位3ペアを選択（max_new_positions_per_cycle=3）")
    print("   - 同一取引所ペアが有利な場合 → それを選ぶ")
    print("   - クロス取引所ペアが有利な場合 → それを選ぶ")
    print("   - 完全に柔軟に最適化")

    print("\n6. 【実行】")
    print("   選定されたペアを執行")


if __name__ == "__main__":
    print("=" * 60)
    print("Funding Arbitrage - 柔軟なペアリング戦略")
    print("=" * 60)

    # 設定の表示
    config = create_flexible_config()
    print("\n【設定】")
    print(f"取引所: {[e.name for e in config.exchanges]}")
    print(f"監視銘柄数: {config.universe_size}")
    print(f"最小FR差: {config.fr_diff_min * 100:.2f}%")
    print(f"最大新規ペア/サイクル: {config.max_new_positions_per_cycle}")
    print(f"ペアスコア閾値: {config.min_pair_score}")

    print("\n" + "=" * 60)

    # 実際のデータで分析
    try:
        analyze_pair_patterns()
    except Exception as e:
        print(f"\nLoris API接続エラー: {e}")
        print("（インターネット接続を確認してください）")

    print("\n" + "=" * 60)

    # システム動作の説明
    show_system_behavior()

    print("\n" + "=" * 60)
    print("結論: システムは完全に柔軟。最適なペアを自動選定します。")
    print("=" * 60)
