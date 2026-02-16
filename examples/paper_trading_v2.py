"""改良版ペーパートレーディング - PnL計算付き

修正点:
- 毎サイクルfunding収益を計算
- 価格変動によるPnL計算
- より詳細なポートフォリオ追跡
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
from funding_arb.types import PortfolioState
from funding_arb.execution import ExchangeExecutionClient


class ImprovedPaperTradingClient(ExchangeExecutionClient):
    """改良版ペーパートレーディングクライアント"""

    def __init__(self, loris_client):
        self.loris_client = loris_client
        self.orders = []
        self.positions = {}  # {(exchange, symbol): {"qty": float, "entry_price": float}}
        self.realized_pnl = 0.0
        self.total_funding_collected = 0.0
        self.cycle_count = 0

    def place_order(self, exchange, symbol, side, qty, order_type, reduce_only, client_order_id):
        """仮想注文を実行"""
        # 現在価格を取得（簡易版：固定100.0）
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

        # ポジション更新
        key = (exchange, symbol)
        if key not in self.positions:
            self.positions[key] = {"qty": 0.0, "entry_price": avg_price, "notional": 0.0}

        pos = self.positions[key]
        old_qty = pos["qty"]

        if side == "buy":
            new_qty = old_qty + qty
            # 加重平均エントリー価格
            if new_qty != 0:
                pos["entry_price"] = (
                    (old_qty * pos["entry_price"] + qty * avg_price) / new_qty
                )
            pos["qty"] = new_qty
        else:  # sell
            new_qty = old_qty - qty
            # 決済の場合、実現損益を計算
            if old_qty > 0 and new_qty < old_qty:  # long を決済
                closed_qty = min(qty, old_qty)
                self.realized_pnl += closed_qty * (avg_price - pos["entry_price"])
            pos["qty"] = new_qty

        # notionalを更新
        pos["notional"] = abs(pos["qty"]) * avg_price

        # ポジションがゼロなら削除
        if abs(pos["qty"]) < 1e-6:
            del self.positions[key]

        print(f"  [PAPER] {exchange} {symbol} {side} {qty:.2f} @ ${avg_price:.2f}")
        return order

    def calculate_funding_pnl(self):
        """funding rate収益を計算（毎サイクル）"""
        response = self.loris_client.fetch()
        rate_map = {}

        for fr in response.funding_rates:
            # CCXTシンボルをLorisシンボルに変換
            loris_symbol = fr.symbol
            rate_map[(fr.exchange, loris_symbol)] = fr.rate

        funding_pnl = 0.0

        for (exchange, symbol), pos in self.positions.items():
            # シンボルを正規化
            loris_symbol = symbol.split("/")[0] if "/" in symbol else symbol

            rate = rate_map.get((exchange, loris_symbol), 0.0)
            if rate == 0.0:
                continue

            qty = pos["qty"]
            notional = pos.get("notional", abs(qty) * 100)

            # funding rate は8時間あたり
            # 1サイクル（10分）あたりの収益: rate * notional * (10/480)
            # ここでは簡易的に rate * notional / 48 とする
            cycle_rate = rate / 48.0  # 8時間 = 48 * 10分

            if qty > 0:  # long
                # rate > 0 なら支払い、rate < 0 なら受取
                payment = -cycle_rate * notional
            else:  # short
                # rate > 0 なら受取、rate < 0 なら支払い
                payment = cycle_rate * notional

            funding_pnl += payment

        self.total_funding_collected += funding_pnl
        return funding_pnl

    def calculate_unrealized_pnl(self):
        """未実現損益を計算"""
        unrealized = 0.0
        # 現在価格は簡易的に100.0固定（本来はLorisまたはCCXTから取得）
        current_price = 100.0

        for (exchange, symbol), pos in self.positions.items():
            qty = pos["qty"]
            entry_price = pos["entry_price"]

            if qty > 0:  # long
                unrealized += qty * (current_price - entry_price)
            else:  # short
                unrealized += abs(qty) * (entry_price - current_price)

        return unrealized

    def get_total_pnl(self):
        """総PnL = 実現 + 未実現 + funding"""
        unrealized = self.calculate_unrealized_pnl()
        return self.realized_pnl + unrealized + self.total_funding_collected

    def get_portfolio_summary(self):
        """ポートフォリオサマリー"""
        return {
            "positions": len(self.positions),
            "total_orders": len(self.orders),
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.calculate_unrealized_pnl(),
            "funding_collected": self.total_funding_collected,
            "total_pnl": self.get_total_pnl(),
        }


class ImprovedPaperTradingSimulator:
    """改良版シミュレータ"""

    def __init__(self, initial_capital=100_000):
        self.initial_capital = initial_capital
        self.loris_client = LorisAPIClient()
        self.paper_client = ImprovedPaperTradingClient(self.loris_client)

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
        self.paper_client.cycle_count = self.cycle_count

        print(f"\n{'='*70}")
        print(f"サイクル #{self.cycle_count} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")

        # Funding収益を計算（毎サイクル）
        funding_pnl = self.paper_client.calculate_funding_pnl()

        # ポートフォリオ状態
        summary = self.paper_client.get_portfolio_summary()
        current_equity = self.initial_capital + summary["total_pnl"]

        portfolio = PortfolioState(
            equity=current_equity,
            peak_equity=max(self.initial_capital, current_equity),
            gross_notional_usd=sum(p.get("notional", 0) for p in self.paper_client.positions.values()),
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

        if funding_pnl != 0:
            print(f"\n💰 今サイクルのFunding収益: ${funding_pnl:.2f}")

        # 詳細サマリー
        summary = self.paper_client.get_portfolio_summary()
        print(f"\nポートフォリオ:")
        print(f"  エクイティ: ${current_equity:,.2f}")
        print(f"  オープンポジション: {summary['positions']}")
        print(f"  累計注文: {summary['total_orders']}")
        print(f"  実現損益: ${summary['realized_pnl']:.2f}")
        print(f"  未実現損益: ${summary['unrealized_pnl']:.2f}")
        print(f"  累計Funding: ${summary['funding_collected']:.2f}")
        print(f"  総PnL: ${summary['total_pnl']:.2f} ({summary['total_pnl']/self.initial_capital*100:+.2f}%)")

    def run_continuous(self, cycles=10):
        """連続実行"""
        print(f"\n{'='*70}")
        print("改良版ペーパートレーディング（PnL計算付き）")
        print(f"{'='*70}")
        print(f"初期資金: ${self.initial_capital:,.0f}")
        print(f"実行サイクル数: {cycles}")
        print(f"取引所: {[e.name for e in self.config.exchanges]}")
        print(f"{'='*70}")

        for i in range(cycles):
            self.run_cycle()

        # 最終結果
        self.print_final_summary()

    def print_final_summary(self):
        """最終サマリー"""
        summary = self.paper_client.get_portfolio_summary()
        final_equity = self.initial_capital + summary["total_pnl"]
        duration = datetime.utcnow() - self.start_time

        print(f"\n{'='*70}")
        print("最終結果")
        print(f"{'='*70}")
        print(f"実行時間: {duration}")
        print(f"サイクル数: {self.cycle_count}")
        print(f"初期資金: ${self.initial_capital:,.2f}")
        print(f"最終エクイティ: ${final_equity:,.2f}")
        print(f"\n損益内訳:")
        print(f"  実現損益: ${summary['realized_pnl']:.2f}")
        print(f"  未実現損益: ${summary['unrealized_pnl']:.2f}")
        print(f"  Funding収益: ${summary['funding_collected']:.2f}")
        print(f"  総PnL: ${summary['total_pnl']:.2f} ({summary['total_pnl']/self.initial_capital*100:+.2f}%)")
        print(f"\n総注文数: {summary['total_orders']}")
        print(f"{'='*70}")


if __name__ == "__main__":
    simulator = ImprovedPaperTradingSimulator(initial_capital=100_000)
    simulator.run_continuous(cycles=20)
