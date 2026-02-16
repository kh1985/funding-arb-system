#!/bin/bash

# ペーパートレーディングを実行するスクリプト

cd "$(dirname "$0")"

echo "======================================"
echo "Funding Arbitrage ペーパートレーディング"
echo "======================================"
echo ""
echo "実際のお金は使いません。"
echo "リアルタイムのfunding rateデータでシミュレーションします。"
echo ""
echo "Ctrl+C で停止できます。"
echo ""

PYTHONPATH=. python examples/paper_trading.py
