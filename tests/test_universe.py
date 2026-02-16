"""DynamicUniverseProvider のユニットテスト。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from funding_arb.config import FundingArbConfig
from funding_arb.loris_client import (
    LorisAPIClient,
    LorisExchange,
    LorisFundingRate,
    LorisResponse,
    LorisSymbol,
)
from funding_arb.universe import DynamicUniverseProvider, SymbolScore


def _make_response(
    rates: list[LorisFundingRate],
    symbols: list[str] | None = None,
) -> LorisResponse:
    """テスト用 LorisResponse を作成する。"""
    if symbols is None:
        symbols = sorted({fr.symbol for fr in rates})
    return LorisResponse(
        symbols=[LorisSymbol(name=s) for s in symbols],
        exchanges=[
            LorisExchange(name="binance", display="Binance", interval=8),
            LorisExchange(name="bybit", display="Bybit", interval=8),
            LorisExchange(name="okx", display="OKX", interval=8),
        ],
        funding_rates=rates,
    )


def _make_client(response: LorisResponse) -> LorisAPIClient:
    """fetch() がモックレスポンスを返すクライアントを作成する。"""
    client = MagicMock(spec=LorisAPIClient)
    client.fetch.return_value = response
    return client


class TestDynamicUniverseProvider:
    """DynamicUniverseProvider の基本テスト。"""

    def test_select_universe_basic(self):
        """基本的なユニバース選定が動作する。"""
        rates = [
            # BTC: binance +0.01%, bybit -0.02% → spread = 0.03%
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=10, rate=0.001),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-20, rate=-0.002),
            # ETH: binance +0.005%, bybit +0.001% → spread = 0.004%
            LorisFundingRate(exchange="binance", symbol="ETH", raw_value=5, rate=0.0005),
            LorisFundingRate(exchange="bybit", symbol="ETH", raw_value=1, rate=0.0001),
            # SOL: binance +0.03%, bybit -0.01% → spread = 0.04%
            LorisFundingRate(exchange="binance", symbol="SOL", raw_value=30, rate=0.003),
            LorisFundingRate(exchange="bybit", symbol="SOL", raw_value=-10, rate=-0.001),
        ]
        response = _make_response(rates)
        client = _make_client(response)
        config = FundingArbConfig(universe_size=2)

        provider = DynamicUniverseProvider(config, client)
        snapshot = provider.select_universe()

        # SOL (spread=0.004) > BTC (spread=0.003) の順で選定される
        assert len(snapshot.symbols) == 2
        assert "SOL" in snapshot.symbols
        assert "BTC" in snapshot.symbols
        # ETH はuniverse_size=2なので除外
        assert "ETH" not in snapshot.symbols

    def test_select_universe_respects_universe_size(self):
        """universe_size に基づいてフィルタリングされる。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=10, rate=0.001),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-20, rate=-0.002),
            LorisFundingRate(exchange="binance", symbol="ETH", raw_value=5, rate=0.0005),
            LorisFundingRate(exchange="bybit", symbol="ETH", raw_value=1, rate=0.0001),
            LorisFundingRate(exchange="binance", symbol="SOL", raw_value=30, rate=0.003),
            LorisFundingRate(exchange="bybit", symbol="SOL", raw_value=-10, rate=-0.001),
        ]
        response = _make_response(rates)
        client = _make_client(response)
        config = FundingArbConfig(universe_size=25)  # 全銘柄より大きいsize

        provider = DynamicUniverseProvider(config, client)
        snapshot = provider.select_universe()

        # 全銘柄が含まれる
        assert len(snapshot.symbols) == 3

    def test_single_exchange_symbol_excluded(self):
        """1取引所でしか取引できない銘柄は除外される。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=10, rate=0.001),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-20, rate=-0.002),
            # DOGE は binance のみ
            LorisFundingRate(exchange="binance", symbol="DOGE", raw_value=50, rate=0.005),
        ]
        response = _make_response(rates)
        client = _make_client(response)
        config = FundingArbConfig(universe_size=10)

        provider = DynamicUniverseProvider(config, client)
        snapshot = provider.select_universe()

        assert "BTC" in snapshot.symbols
        assert "DOGE" not in snapshot.symbols

    def test_target_exchanges_filter(self):
        """target_exchanges で取引所をフィルタリングできる。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=10, rate=0.001),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-20, rate=-0.002),
            LorisFundingRate(exchange="okx", symbol="BTC", raw_value=15, rate=0.0015),
        ]
        response = _make_response(rates)
        client = _make_client(response)
        config = FundingArbConfig(universe_size=10)

        # binance と bybit のみ対象
        provider = DynamicUniverseProvider(
            config, client, target_exchanges=["binance", "bybit"]
        )
        snapshot = provider.select_universe()

        assert "BTC" in snapshot.symbols
        # ペア候補に okx が含まれないこと
        for ex_a, ex_b, _ in snapshot.pair_candidates:
            assert "okx" not in ex_a
            assert "okx" not in ex_b

    def test_pair_candidates_sorted_by_fr_diff(self):
        """ペア候補はFR差降順でソートされる。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=10, rate=0.001),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-20, rate=-0.002),
            LorisFundingRate(exchange="okx", symbol="BTC", raw_value=5, rate=0.0005),
        ]
        response = _make_response(rates)
        client = _make_client(response)
        config = FundingArbConfig(universe_size=10)

        provider = DynamicUniverseProvider(config, client)
        snapshot = provider.select_universe()

        # FR差降順
        diffs = [diff for _, _, diff in snapshot.pair_candidates]
        assert diffs == sorted(diffs, reverse=True)

    def test_get_symbols_for_cycle(self):
        """get_symbols_for_cycle が銘柄リストを返す。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=10, rate=0.001),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-20, rate=-0.002),
        ]
        response = _make_response(rates)
        client = _make_client(response)
        config = FundingArbConfig(universe_size=10)

        provider = DynamicUniverseProvider(config, client)
        symbols = provider.get_symbols_for_cycle()

        assert symbols == ["BTC"]

    def test_get_exchange_symbol_pairs(self):
        """get_exchange_symbol_pairs がFR差フィルタ付きでペアを返す。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=10, rate=0.001),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-20, rate=-0.002),
            LorisFundingRate(exchange="binance", symbol="ETH", raw_value=1, rate=0.0001),
            LorisFundingRate(exchange="bybit", symbol="ETH", raw_value=2, rate=0.0002),
        ]
        response = _make_response(rates)
        client = _make_client(response)
        config = FundingArbConfig(universe_size=10, fr_diff_min=0.002)

        provider = DynamicUniverseProvider(config, client)
        pairs = provider.get_exchange_symbol_pairs()

        # BTC: |0.001 - (-0.002)| = 0.003 >= 0.002 → 含まれる
        # ETH: |0.0001 - 0.0002| = 0.0001 < 0.002 → 含まれない
        assert len(pairs) == 1
        ea, sym, eb = pairs[0]
        assert sym == "BTC"

    def test_empty_rates(self):
        """レートが空の場合でもエラーにならない。"""
        response = _make_response([], symbols=[])
        client = _make_client(response)
        config = FundingArbConfig(universe_size=10)

        provider = DynamicUniverseProvider(config, client)
        snapshot = provider.select_universe()

        assert snapshot.symbols == []
        assert snapshot.scores == {}
        assert snapshot.pair_candidates == []

    def test_force_refresh_passed_to_client(self):
        """force_refresh がクライアントに渡される。"""
        response = _make_response([])
        client = _make_client(response)
        config = FundingArbConfig(universe_size=10)

        provider = DynamicUniverseProvider(config, client)
        provider.select_universe(force_refresh=True)

        client.fetch.assert_called_once_with(force=True)

    def test_scores_contain_correct_values(self):
        """スコアリングが正しい値を含む。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=10, rate=0.001),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-20, rate=-0.002),
            LorisFundingRate(exchange="okx", symbol="BTC", raw_value=5, rate=0.0005),
        ]
        response = _make_response(rates)
        client = _make_client(response)
        config = FundingArbConfig(universe_size=10)

        provider = DynamicUniverseProvider(config, client)
        snapshot = provider.select_universe()

        score = snapshot.scores["BTC"]
        assert score.exchange_count == 3
        # max spread = |0.001 - (-0.002)| = 0.003
        assert abs(score.max_fr_spread - 0.003) < 1e-9
        # avg_abs = (0.001 + 0.002 + 0.0005) / 3
        expected_avg = (0.001 + 0.002 + 0.0005) / 3
        assert abs(score.avg_abs_rate - expected_avg) < 1e-9
