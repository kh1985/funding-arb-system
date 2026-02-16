#!/bin/bash

# 連続ペーパートレーディング実行スクリプト

cd "$(dirname "$0")"

echo "======================================"
echo "連続ペーパートレーディング"
echo "======================================"
echo ""
echo "このモードでは、Ctrl+C で停止するまで"
echo "10分ごとにサイクルを実行し続けます。"
echo ""
echo "実際のお金は使いません。"
echo "リアルタイムのfunding rateデータで"
echo "シミュレーションします。"
echo ""

PYTHONPATH=. python examples/paper_trading_continuous.py
