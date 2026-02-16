"""ペーパートレーディング（仮想資金でのシミュレーション）

実際のお金を使わずに、リアルタイムデータで戦略をテストできます。

機能:
- リアルタイムのfunding rateデータ
- 仮想的なポジション管理
- 仮想的なPnL計算
- 実際の注文は出さない
"""

import time
from datetime import datetime, timedelta
from funding_arb import (
    FundingArbConfig,
    FundingArbOrchestrator,
    LorisAPIClient,
    LorisMarketDataService,
    SignalService,
    RiskService,
    ExecutionService,
)
from funding_arb.config import ExchangeConfig
from funding_arb.types import PortfolioState, OrderSide
from funding_arb.execution import ExchangeExecutionClient


class PaperTradingClient(ExchangeExecutionClient):
    """ペーパートレーディング用のクライアント"""

    def __init__(self):
        self.orders = []
        self.positions = {}  # {(exchange, symbol): qty}
        self.pnl = 0.0
        self.funding_collected = 0.0

    def place_order(self, exchange, symbol, side, qty, order_type, reduce_only, client_order_id):
        """仮想注文を記録"""
        # 仮想的な約定価格（実際にはLorisからmark_priceを取得すべき）
        avg_price = 100.0

        order = {
            "id": client_order_id,
            "exchange": exchange,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": avg_price,
            "timestamp": datetime.utcnow(),
            "average": avg_price,
        }
        self.orders.append(order)

        # ポジションを更新
        key = (exchange, symbol)
        current = self.positions.get(key, 0.0)

        if side == "buy":
            self.positions[key] = current + qty
        else:
            self.positions[key] = current - qty

        print(f"  [PAPER] {exchange} {symbol} {side} {qty:.4f} @ ${avg_price:.2f}")
        return order

    def simulate_funding_payment(self, loris_client):
        """仮想的なfunding rate収益を計算"""
        response = loris_client.fetch()
        rate_map = {(fr.exchange, fr.symbol): fr.rate for fr in response.funding_rates}

        funding_pnl = 0.0
        for (exchange, symbol), qty in self.positions.items():
            # シンボルを正規化（CCXT形式 → Loris形式）
            loris_symbol = symbol.split("/")[0]
            rate = rate_map.get((exchange, loris_symbol), 0.0)

            # qty > 0 = long, qty < 0 = short
            # rate > 0 = long pays short (shortが受取)
            # rate < 0 = short pays long (longが受取)
            if qty > 0:  # long
                payment = -rate * abs(qty) * 100  # 仮のnotional
            else:  # short
                payment = rate * abs(qty) * 100

            funding_pnl += payment

        self.funding_collected += funding_pnl
        return funding_pnl

    def get_portfolio_summary(self):
        """ポートフォリオサマリー"""
        return {
            "positions": len([q for q in self.positions.values() if q != 0]),
            "total_orders": len(self.orders),
            "funding_collected": self.funding_collected,
            "pnl": self.pnl + self.funding_collected,
        }


class PaperTradingSimulator:
    """ペーパートレーディングシミュレータ"""

    def __init__(self, initial_capital=100_000):
        self.initial_capital = initial_capital
        self.paper_client = PaperTradingClient()
        self.loris_client = LorisAPIClient()

        # 設定
        self.config = FundingArbConfig(
            exchanges=[
                ExchangeConfig("bitget"),
                ExchangeConfig("hyperliquid"),
            ],
            symbols=[],
            universe_size=20,
            fr_diff_min=0.002,
            min_persistence_windows=2,
            min_pair_score=0.40,
            expected_edge_min_bps=1.0,
            max_new_positions_per_cycle=2,
            max_notional_per_pair_usd=5_000,
            max_total_notional_usd=30_000,
        )

        # サービス
        market_data = LorisMarketDataService(self.loris_client, config=self.config)
        signals = SignalService(self.config)
        risk = RiskService(self.config)
        execution = ExecutionService(self.paper_client)

        self.orch = FundingArbOrchestrator(
            self.config, market_data, signals, risk, execution
        )

        self.start_time = datetime.utcnow()
        self.cycle_count = 0

    def run_cycle(self):
        """1サイクル実行"""
        self.cycle_count += 1
        print(f"\n{'='*70}")
        print(f"サイクル #{self.cycle_count} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")

        # ポートフォリオ状態
        summary = self.paper_client.get_portfolio_summary()
        current_equity = self.initial_capital + summary["pnl"]

        portfolio = PortfolioState(
            equity=current_equity,
            peak_equity=max(self.initial_capital, current_equity),
            gross_notional_usd=0.0,
            net_delta_usd=0.0,
            exchange_notionals={},
        )

        # サイクル実行
        market_features = {}
        result = self.orch.run_cycle(portfolio, market_features)

        print(f"\n結果:")
        print(f"  候補ペア: {result.candidates}")
        print(f"  エントリー意図: {result.intents}")
        print(f"  実行済み: {result.executed}")
        print(f"  ブロック: {result.blocked}")

        # Funding収益をシミュレート（8時間ごとと仮定）
        if self.cycle_count % 48 == 0:  # 10分サイクルなら48サイクル = 8時間
            funding_pnl = self.paper_client.simulate_funding_payment(self.loris_client)
            print(f"\n💰 Funding収益: ${funding_pnl:.2f}")

        # サマリー
        summary = self.paper_client.get_portfolio_summary()
        print(f"\nポートフォリオ:")
        print(f"  エクイティ: ${current_equity:,.2f}")
        print(f"  オープンポジション: {summary['positions']}")
        print(f"  累計注文: {summary['total_orders']}")
        print(f"  累計Funding収益: ${summary['funding_collected']:.2f}")
        print(f"  総PnL: ${summary['pnl']:.2f} ({summary['pnl']/self.initial_capital*100:+.2f}%)")

    def run_continuous(self, cycles=10, interval_minutes=10):
        """連続実行"""
        print(f"\n{'='*70}")
        print("ペーパートレーディング シミュレーション")
        print(f"{'='*70}")
        print(f"初期資金: ${self.initial_capital:,.0f}")
        print(f"実行サイクル数: {cycles}")
        print(f"サイクル間隔: {interval_minutes}分")
        print(f"取引所: {[e.name for e in self.config.exchanges]}")
        print(f"{'='*70}")

        for i in range(cycles):
            self.run_cycle()

            if i < cycles - 1:
                print(f"\n⏳ 次のサイクルまで待機中...")
                # 実際の運用では time.sleep(interval_minutes * 60)
                # デモでは待機なし

        # 最終結果
        self.print_final_summary()

    def print_final_summary(self):
        """最終サマリー"""
        summary = self.paper_client.get_portfolio_summary()
        final_equity = self.initial_capital + summary["pnl"]
        duration = datetime.utcnow() - self.start_time

        print(f"\n{'='*70}")
        print("最終結果")
        print(f"{'='*70}")
        print(f"実行時間: {duration}")
        print(f"サイクル数: {self.cycle_count}")
        print(f"初期資金: ${self.initial_capital:,.2f}")
        print(f"最終エクイティ: ${final_equity:,.2f}")
        print(f"総PnL: ${summary['pnl']:.2f} ({summary['pnl']/self.initial_capital*100:+.2f}%)")
        print(f"累計Funding収益: ${summary['funding_collected']:.2f}")
        print(f"総注文数: {summary['total_orders']}")
        print(f"{'='*70}")


if __name__ == "__main__":
    # ペーパートレーディングを実行
    simulator = PaperTradingSimulator(initial_capital=100_000)

    # 10サイクル実行
    simulator.run_continuous(cycles=10, interval_minutes=10)
