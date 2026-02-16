# Funding Rate Arbitrage System

Hyperliquid向けのFunding Rate裁定取引システム。デルタニュートラル戦略により、市場の方向性リスクを抑えながらFunding Rateの差分から収益を得ます。

## 概要

このシステムは、同一取引所内でFunding Rateが異なる銘柄ペアを見つけ、以下の戦略を実行します：

- **プラスFRの銘柄**: ショート（Funding Rateを受け取る）
- **マイナスFRの銘柄**: ロング（Funding Rateを支払わない）
- **収益**: 2銘柄のFR差分 × ポジションサイズが8時間ごとに入る

### 例
- 銘柄A: FR +0.50% (ショート) → +0.50%受け取り
- 銘柄B: FR -0.20% (ロング) → +0.20%受け取り
- **合計収益**: 0.70% / 8時間

## 前提条件

### 環境
- Python 3.10以上
- Hyperliquidアカウント（本番環境）
- 最低資金: $50（推奨: $100以上）

### 依存関係
```bash
pip install -r requirements.txt
```

主な依存パッケージ：
- `hyperliquid-python-sdk`
- `ccxt`
- `python-dotenv`
- `requests`

## セットアップ

### 1. 環境変数の設定

`.env`ファイルを作成（または`hyperliquid-bot`プロジェクトの`.env`を使用）：

```bash
# Hyperliquid本番環境
HL_PRIVATE_KEY=your_agent_wallet_private_key
HL_MAIN_ADDRESS=your_main_wallet_address
HL_TESTNET=false
```

### 2. パスの設定

`examples/production_continuous.py`の7行目を確認：
```python
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")
```

### 3. 初期資金の入金

Hyperliquidアカウントに最低$50を入金してください。

## 使い方

### 本番環境での連続実行

```bash
python examples/production_continuous.py
```

または、バックグラウンドで実行：
```bash
nohup python -u examples/production_continuous.py > /tmp/production_continuous.log 2>&1 &
```

ログ確認：
```bash
tail -f /tmp/production_continuous.log
```

停止方法：
```bash
# プロセスIDを確認
ps aux | grep production_continuous.py

# 停止
kill <プロセスID>
```

### 現在のポジション確認

```bash
python check_positions.py
```

### 取引履歴確認

```bash
python check_trade_history.py
```

## 設定パラメータ

`examples/production_continuous.py`の主要設定：

```python
config = FundingArbConfig(
    universe_size=10,                    # 監視する銘柄数
    fr_diff_min=0.001,                   # 最小FR差分 (0.1%)
    min_persistence_windows=1,           # 継続サイクル数（1=即エントリー）
    min_pair_score=0.30,                 # 最小ペアスコア
    expected_edge_min_bps=1.0,           # 最小期待エッジ (1bps)
    max_new_positions_per_cycle=1,       # サイクルあたりの最大新規ポジション数
    max_notional_per_pair_usd=40,        # ペアあたりの最大想定元本
    max_total_notional_usd=50,           # 合計最大想定元本
    allow_single_exchange_pairs=True,    # 同一取引所ペアを許可
)
```

### サイジングロジック

`funding_arb/signals.py:168-169`:
```python
notional_a = max(10.0, min(max_notional_per_pair_usd, capital_usd * 0.40))
notional_b = notional_a * max(0.1, beta)
```

- 資金の40%、または`max_notional_per_pair_usd`の小さい方
- 最低$10を保証（Hyperliquidの最小注文金額）

## 動作の仕組み

### サイクルフロー（10分間隔）

1. **銘柄選定**: Loris APIから動的に銘柄を選定
2. **候補ペア構築**: FR差分が大きいペアを検出
3. **リスク評価**: ポートフォリオ状態を確認
4. **エントリー選定**: フィルター条件を満たすペアを選択
5. **注文実行**: 2レッグの成行注文を送信
6. **10分待機**: 次のサイクルまで待機

### Funding Rate決済

- **頻度**: 8時間ごと
- **決済時刻（UTC）**: 00:00, 08:00, 16:00
- **日本時間**: 09:00, 17:00, 01:00（翌日）

## 注意事項

### ⚠️ リスク

1. **市場リスク**: 完全なデルタニュートラルは困難（ベータリスク）
2. **流動性リスク**: 流動性の低い銘柄で大きなスリッページが発生する可能性
3. **資金調達リスク**: FR差分が縮小または逆転する可能性
4. **技術リスク**: システム障害、API障害、ネットワーク遅延

### 💡 ベストプラクティス

1. **少額から開始**: 最初は$50-100で動作を確認
2. **ログ監視**: 定期的にログとポジションを確認
3. **FR確認**: Hyperliquid UIでFunding Rateを定期的に確認
4. **手動クローズ準備**: 緊急時に手動でポジションをクローズできるようにする

### 🔧 トラブルシューティング

#### 注文が実行されない

- ログで「Order must have minimum value of $10」エラーを確認
- `max_notional_per_pair_usd`を増やす
- `signals.py`のサイジングロジックを確認

#### ポジションが開かれない

- 取引履歴を確認: `python check_trade_history.py`
- デバッグモードで実行: `python debug_execution.py`

#### FR差分が見つからない

- `fr_diff_min`を下げる（例: 0.001 → 0.0005）
- `min_pair_score`を下げる（例: 0.30 → 0.20）

## ファイル構成

```
funding-arb-system/
├── funding_arb/              # コアロジック
│   ├── orchestrator.py       # メインオーケストレーター
│   ├── signals.py            # シグナル生成とサイジング
│   ├── execution.py          # 注文実行
│   ├── market_data.py        # 市場データ取得
│   ├── hyperliquid_client.py # Hyperliquidクライアント
│   └── ...
├── examples/
│   ├── production_continuous.py  # 本番連続実行
│   └── production_simple.py      # 本番単発実行
├── check_positions.py        # ポジション確認
├── check_trade_history.py    # 取引履歴確認
└── debug_execution.py        # デバッグ実行

## 開発

### テスト実行

```bash
pytest tests/
```

### デバッグモード

詳細ログを出力：
```bash
python debug_execution.py
```

## ライセンス

このプロジェクトは個人使用を目的としています。

## 免責事項

このシステムは教育・研究目的で提供されています。実際の取引による損失について、開発者は一切の責任を負いません。自己責任でご利用ください。
