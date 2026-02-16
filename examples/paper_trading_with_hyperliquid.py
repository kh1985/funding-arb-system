"""Hyperliquid API統合版ペーパートレーディング

既存のhyperliquid-botのAPI設定を使用して、
実際のmark_priceでペーパートレーディングを実行します。
"""

import sys
import os

# hyperliquid-botのsrcパスを追加
sys.path.insert(0, "/Users/kenjihachiya/Desktop/work/development/hyperliquid-bot/src")

import time
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
from funding_arb.hyperliquid_client import HyperliquidMarketDataAdapter
from funding_arb.execution import ExchangeExecutionClient


class PaperTradingClient(ExchangeExecutionClient):
    """ペーパートレーディング用クライアント（実際の価格を使用）"""

    def __init__(self, hl_adapter):
        self.hl_adapter = hl_adapter
        self.orders = []
        self.positions = {}
        self.realized_pnl = 0.0
        self.total_funding_collected = 0.0
        self.loris_client = LorisAPIClient()

    def place_order(self, exchange, symbol, side, qty, order_type, reduce_only, client_order_id):
        """仮想注文を実行（実際の価格を使用）"""
        # Hyperliquidから実際の価格を取得
        avg_price = self._get_real_price(symbol)

        if avg_price == 0:
            print(f"  [WARNING] {symbol} の価格が取得できません")
            avg_price = 1.0

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
            if new_qty != 0:
                pos["entry_price"] = (
                    (old_qty * pos["entry_price"] + qty * avg_price) / new_qty
                )
            pos["qty"] = new_qty
        else:
            new_qty = old_qty - qty
            if old_qty > 0 and new_qty < old_qty:
                closed_qty = min(qty, old_qty)
                self.realized_pnl += closed_qty * (avg_price - pos["entry_price"])
            pos["qty"] = new_qty

        pos["notional"] = abs(pos["qty"]) * avg_price

        if abs(pos["qty"]) < 1e-6:
            del self.positions[key]
        else:
            # 価格が小さい場合は8桁表示
            price_fmt = f"${avg_price:.8f}" if avg_price < 0.01 else f"${avg_price:.2f}"
            print(f"  [PAPER] {exchange} {symbol} {side} {qty:.4f} @ {price_fmt} (notional: ${pos['notional']:.2f})")

        return order

    def _get_real_price(self, symbol):
        """Hyperliquidから実際の価格を取得（キャッシュ使用）"""
        try:
            return self.hl_adapter.get_mark_price(symbol)
        except:
            return 0.0

    def calculate_funding_pnl(self):
        """funding rate収益を計算"""
        if not self.positions:
            return 0.0

        response = self.loris_client.fetch()
        rate_map = {}

        for fr in response.funding_rates:
            rate_map[(fr.exchange, fr.symbol)] = fr.rate

        funding_pnl = 0.0

        for (exchange, symbol), pos in self.positions.items():
            loris_symbol = symbol.split("/")[0] if "/" in symbol else symbol
            rate = rate_map.get((exchange, loris_symbol), 0.0)

            if rate == 0.0:
                continue

            qty = pos["qty"]
            notional = pos.get("notional", 0.0)

            # 1サイクル10分 = 1/48 of 8時間
            cycle_rate = rate / 48.0

            if qty > 0:  # long
                payment = -cycle_rate * notional
            else:  # short
                payment = cycle_rate * notional

            funding_pnl += payment

        self.total_funding_collected += funding_pnl
        return funding_pnl

    def get_total_pnl(self):
        """総PnL"""
        return self.realized_pnl + self.total_funding_collected

    def get_portfolio_summary(self):
        """ポートフォリオサマリー"""
        total_notional = sum(p.get("notional", 0) for p in self.positions.values())
        return {
            "positions": len(self.positions),
            "total_orders": len(self.orders),
            "total_notional": total_notional,
            "realized_pnl": self.realized_pnl,
            "funding_collected": self.total_funding_collected,
            "total_pnl": self.get_total_pnl(),
        }


class HyperliquidPaperTradingSimulator:
    """Hyperliquid API統合シミュレータ"""

    def __init__(self, initial_capital=100_000):
        self.initial_capital = initial_capital
        self.loris_client = LorisAPIClient()

        # Hyperliquid Market Data Adapter
        self.hl_adapter = HyperliquidMarketDataAdapter(testnet=True)

        # ペーパートレーディングクライアント
        self.paper_client = PaperTradingClient(self.hl_adapter)

        # 設定
        self.config = FundingArbConfig(
            exchanges=[
                ExchangeConfig("hyperliquid"),  # Hyperliquidのみ
            ],
            symbols=[],
            universe_size=15,
            fr_diff_min=0.002,
            min_persistence_windows=2,
            min_pair_score=0.40,
            expected_edge_min_bps=1.0,
            max_new_positions_per_cycle=2,
            max_notional_per_pair_usd=5_000,
            max_total_notional_usd=30_000,
            allow_single_exchange_pairs=True,  # Hyperliquid内ペアリングを許可
        )

        # HybridMarketDataService（Loris FR + Hyperliquid価格）
        market_data = HybridMarketDataService(
            loris_client=self.loris_client,
            ccxt_adapters={"hyperliquid": self.hl_adapter},
            config=self.config,
        )

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

        # Funding収益計算
        funding_pnl = self.paper_client.calculate_funding_pnl()

        # ポートフォリオ状態
        summary = self.paper_client.get_portfolio_summary()
        current_equity = self.initial_capital + summary["total_pnl"]

        portfolio = PortfolioState(
            equity=current_equity,
            peak_equity=max(self.initial_capital, current_equity),
            gross_notional_usd=summary["total_notional"],
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

        # サマリー
        print(f"\nポートフォリオ:")
        print(f"  エクイティ: ${current_equity:,.2f} ({(current_equity-self.initial_capital)/self.initial_capital*100:+.3f}%)")
        print(f"  オープンポジション: {summary['positions']}")
        print(f"  総Notional: ${summary['total_notional']:,.2f}")
        print(f"  累計注文: {summary['total_orders']}")
        print(f"  累計Funding: ${summary['funding_collected']:.2f}")
        print(f"  総PnL: ${summary['total_pnl']:.2f}")

    def run_continuous(self, cycles=10):
        """連続実行"""
        print(f"\n{'='*70}")
        print("Hyperliquid API統合ペーパートレーディング")
        print(f"{'='*70}")
        print(f"初期資金: ${self.initial_capital:,.0f}")
        print(f"実行サイクル数: {cycles}")
        print(f"取引所: Hyperliquid (Testnet)")
        print(f"{'='*70}")

        for i in range(cycles):
            self.run_cycle()

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
        print(f"  Funding収益: ${summary['funding_collected']:.2f}")
        print(f"  実現損益: ${summary['realized_pnl']:.2f}")
        print(f"  総PnL: ${summary['total_pnl']:.2f} ({summary['total_pnl']/self.initial_capital*100:+.3f}%)")
        print(f"\n総注文数: {summary['total_orders']}")
        print(f"最終ポジション数: {summary['positions']}")
        print(f"{'='*70}")


if __name__ == "__main__":
    print("⚠️  注意: hyperliquid-python-sdkと.envファイルの設定が必要です")
    print("⚠️  実際の注文は出ません（ペーパートレーディング）\n")

    simulator = HyperliquidPaperTradingSimulator(initial_capital=100_000)
    simulator.run_continuous(cycles=10)
