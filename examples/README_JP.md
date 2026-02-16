# 日本ユーザー向け Funding Arbitrage 設定ガイド

## 🇯🇵 日本からアクセス可能な取引所

日本の居住者がアクセス可能な主要取引所：
- **Bitget**: 8時間周期のfunding rate
- **Hyperliquid**: 1時間周期のfunding rate（システムが自動で8h相当に正規化）

## 📋 セットアップ手順

### 1. 基本設定の作成

```python
from funding_arb import ExchangeConfig, FundingArbConfig

config = FundingArbConfig(
    # 日本からアクセス可能な取引所のみ
    exchanges=[
        ExchangeConfig("bitget"),
        ExchangeConfig("hyperliquid"),
    ],

    # 動的銘柄選定（空 = Loris APIから自動選定）
    symbols=[],
    universe_size=15,  # 2取引所なので控えめに

    # エントリー条件（2取引所のみなので条件を緩和）
    fr_diff_min=0.0025,  # 0.25% - やや低めに設定
    min_persistence_windows=2,  # 2サイクル - 短めに
    min_pair_score=0.45,  # スコア閾値を下げる

    # リスク管理
    max_leverage=2.0,  # 2取引所のみなので控えめに
    max_notional_per_pair_usd=5_000,
    max_total_notional_usd=30_000,
    max_new_positions_per_cycle=1,  # 慎重に1ペアずつ
)
```

### 2. Loris APIの使用

```python
from funding_arb import LorisAPIClient, LorisMarketDataService

# Lorisクライアント作成
loris_client = LorisAPIClient()

# MarketDataService作成（bitget + hyperliquidのみ）
market_data = LorisMarketDataService(
    loris_client=loris_client,
    config=config,
    exchange_filter=["bitget", "hyperliquid"],
)
```

### 3. オーケストレータの実行

```python
from funding_arb import (
    FundingArbOrchestrator,
    SignalService,
    RiskService,
    ExecutionService,
)

signals = SignalService(config)
risk = RiskService(config)
execution = ExecutionService(exec_client)

orch = FundingArbOrchestrator(config, market_data, signals, risk, execution)

# サイクル実行
result = orch.run_cycle(portfolio_state, market_features)
print(f"候補: {result.candidates}, 実行: {result.executed}")
```

## 🎯 2取引所戦略のポイント

### 1. 銘柄選定の調整

2取引所のみなので、銘柄選定基準を調整：

```python
config.universe_size = 10  # 少なめに
config.min_pair_score = 0.40  # スコア閾値を下げる
config.min_persistence_windows = 2  # 永続性を短く
```

### 2. 両取引所でサポートされている主要銘柄

一般的に両方でサポートされている銘柄：
- BTC/USDT
- ETH/USDT
- SOL/USDT
- ARB/USDT
- OP/USDT
- AVAX/USDT
- LINK/USDT

**実際の対応状況は各取引所で確認してください**

### 3. Hyperliquid 1時間周期の特性

Hyperliquidは1時間ごとにfunding発生：
- 年間8,760回の収益機会（通常取引所の8倍）
- システムが自動で ÷8 して8時間相当に正規化
- 比較時に公平な比較が可能

### 4. リスク管理の重要性

2取引所のみ = 分散が限定的：
- レバレッジは控えめに（2倍推奨）
- ポジションサイズを小さく
- 1サイクル1ペアずつ慎重に

## 🚀 実行例

### 例1: 動的銘柄選定

```python
# bitget_hyperliquid_config.py を使用
from examples.bitget_hyperliquid_config import (
    create_loris_only_config,
    setup_loris_market_data,
)

config = create_loris_only_config()
market_data = setup_loris_market_data(config)

# 動的に銘柄を選定
symbols = market_data.get_top_symbols_by_criteria(
    universe_size=10,
    min_fr_diff=0.0025,
)

print(f"選定された銘柄: {symbols}")
```

### 例2: 特定銘柄のみ監視

```python
config = FundingArbConfig(
    exchanges=[
        ExchangeConfig("bitget"),
        ExchangeConfig("hyperliquid"),
    ],
    symbols=[
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
    ],
    # ... その他の設定
)
```

## ⚠️ 注意事項

### 1. 取引所のAPI制限
- 各取引所のAPI制限を確認
- レート制限を守る
- 本番環境ではテストから開始

### 2. 流動性の確認
- 両取引所で十分な流動性があるか確認
- 小さいポジションサイズから開始
- スリッページを考慮

### 3. 規制の確認
- 日本の法規制を遵守
- 各取引所の利用規約を確認
- 税務処理の準備

### 4. Loris APIの制限
- 本番取引利用は非推奨（公式ドキュメント記載）
- 60秒ごとの更新
- データ保証なし

## 📊 パフォーマンスモニタリング

```python
# サイクル結果のログ
print(f"""
サイクル結果:
- タイムスタンプ: {result.timestamp}
- 候補ペア数: {result.candidates}
- エントリー意図: {result.intents}
- 実行済み: {result.executed}
- ブロック済み: {result.blocked}
- リバランス: {result.rebalanced}
""")
```

## 🔗 関連ファイル

- `bitget_hyperliquid_config.py`: 設定例とヘルパー関数
- `../docs/funding_arb_system.md`: システム全体のドキュメント
- `../tests/test_loris_integration.py`: 統合テスト

## 💡 トラブルシューティング

### Q1: 候補ペアが見つからない
- `fr_diff_min` を下げる（0.002など）
- `min_persistence_windows` を短く（2など）
- `min_pair_score` を下げる（0.40など）

### Q2: 両取引所で銘柄がマッチしない
- 動的選定ではなく、静的リストを使用
- 両取引所で確実にサポートされている銘柄を指定

### Q3: Hyperliquidのレートがおかしい
- 1時間周期なので値が大きく見える可能性
- LorisAPIClientが自動で÷8しているか確認
- `LorisFundingRate.rate` が正規化済みの値

## 📞 サポート

問題が発生した場合：
1. テストファイルを実行: `pytest tests/test_loris_integration.py -v`
2. ログを確認
3. 設定パラメータの調整
