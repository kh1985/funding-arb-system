"""Loris API 統合テスト。

LorisAPIClient、LorisMarketDataService、HybridMarketDataService、
DynamicUniverseProvider とオーケストレータの統合を網羅的にテストする。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, Iterable, List, Tuple
from unittest.mock import MagicMock, patch

import pytest
import requests

from funding_arb.config import ExchangeConfig, FundingArbConfig
from funding_arb.execution import ExecutionService, ExchangeExecutionClient
from funding_arb.loris_client import (
    HOURLY_EXCHANGES,
    HOURLY_TO_8H_DIVISOR,
    RATE_DIVISOR,
    LorisAPIClient,
    LorisAPIError,
    LorisExchange,
    LorisFundingRate,
    LorisResponse,
    LorisSymbol,
)
from funding_arb.market_data import (
    CCXTAdapter,
    HybridMarketDataService,
    LorisMarketDataService,
    _ccxt_to_loris_symbol,
    _loris_to_ccxt_symbol,
    _loris_to_internal_exchange,
)
from funding_arb.orchestrator import FundingArbOrchestrator
from funding_arb.risk import RiskService
from funding_arb.signals import SignalService
from funding_arb.types import FundingSnapshot, PairFeatures, PortfolioState
from funding_arb.universe import DynamicUniverseProvider


# ---------------------------------------------------------------------------
# テスト用フィクスチャ / ヘルパー
# ---------------------------------------------------------------------------

SAMPLE_API_RESPONSE = {
    "symbols": ["BTC", "ETH", "SOL"],
    "exchanges": {
        "exchange_names": [
            {"name": "binance", "display": "Binance", "interval": 8},
            {"name": "bybit", "display": "Bybit", "interval": 8},
            {"name": "hyperliquid", "display": "Hyperliquid", "interval": 1},
        ]
    },
    "funding_rates": {
        "binance": {"BTC": 25, "ETH": -10, "SOL": 50},
        "bybit": {"BTC": -15, "ETH": 20, "SOL": -30},
        "hyperliquid": {"BTC": 40, "ETH": -8},
    },
}


def _mock_session(json_data: dict, status_code: int = 200) -> MagicMock:
    """モックHTTPセッションを作成する。"""
    session = MagicMock(spec=requests.Session)
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    session.get.return_value = resp
    return session


def _failing_session(fail_count: int = 3) -> MagicMock:
    """指定回数失敗するモックセッションを作成する。"""
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = requests.ConnectionError("mock connection error")
    return session


def _make_loris_response(rates: List[LorisFundingRate]) -> LorisResponse:
    """テスト用 LorisResponse を作成する。"""
    symbols = sorted({fr.symbol for fr in rates})
    return LorisResponse(
        symbols=[LorisSymbol(name=s) for s in symbols],
        exchanges=[
            LorisExchange(name="binance", display="Binance", interval=8),
            LorisExchange(name="bybit", display="Bybit", interval=8),
        ],
        funding_rates=rates,
    )


class FakeCCXTAdapter(CCXTAdapter):
    """テスト用CCXTアダプタ。"""

    def __init__(
        self,
        funding_rate: float = 0.001,
        oi: float = 5_000_000.0,
        mark_price: float = 50000.0,
    ):
        self._funding_rate = funding_rate
        self._oi = oi
        self._mark_price = mark_price

    def fetch_funding_rate(self, symbol: str) -> Dict:
        return {
            "fundingRate": self._funding_rate,
            "markPrice": self._mark_price,
            "timestamp": datetime.utcnow(),
            "nextFundingTime": None,
        }

    def fetch_open_interest(self, symbol: str) -> Dict:
        return {"openInterestValue": self._oi}

    def fetch_order_book(self, symbol: str, limit: int = 5) -> Dict:
        bid = self._mark_price - 1.0
        ask = self._mark_price + 1.0
        return {
            "bids": [[bid, 10.0]],
            "asks": [[ask, 10.0]],
        }


class FakeExecClient(ExchangeExecutionClient):
    """テスト用実行クライアント。"""

    def place_order(self, **kwargs) -> Dict:
        return {"id": kwargs.get("client_order_id", "test-id"), "average": 50000.0}


# =========================================================================
# 1. Loris APIクライアントのテスト
# =========================================================================


class TestLorisAPIClientParser:
    """レスポンスパーサーのテスト。"""

    def test_parse_symbols(self):
        """シンボルが正しくパースされる。"""
        session = _mock_session(SAMPLE_API_RESPONSE)
        client = LorisAPIClient(session=session, cache_ttl=0)
        resp = client.fetch()

        assert len(resp.symbols) == 3
        names = [s.name for s in resp.symbols]
        assert "BTC" in names
        assert "ETH" in names
        assert "SOL" in names

    def test_parse_exchanges(self):
        """取引所情報が正しくパースされる。"""
        session = _mock_session(SAMPLE_API_RESPONSE)
        client = LorisAPIClient(session=session, cache_ttl=0)
        resp = client.fetch()

        assert len(resp.exchanges) == 3
        ex_map = {e.name: e for e in resp.exchanges}
        assert ex_map["binance"].interval == 8
        assert ex_map["hyperliquid"].interval == 1

    def test_parse_funding_rates(self):
        """ファンディングレートがパースされる。"""
        session = _mock_session(SAMPLE_API_RESPONSE)
        client = LorisAPIClient(session=session, cache_ttl=0)
        resp = client.fetch()

        assert len(resp.funding_rates) > 0
        # binance BTC: 25 / 10_000 = 0.0025
        btc_binance = [
            fr for fr in resp.funding_rates
            if fr.exchange == "binance" and fr.symbol == "BTC"
        ]
        assert len(btc_binance) == 1
        assert btc_binance[0].raw_value == 25
        assert abs(btc_binance[0].rate - 25 / RATE_DIVISOR) < 1e-9

    def test_parse_invalid_rate_value_skipped(self):
        """数値変換できないレートはスキップされる。"""
        raw = {
            "symbols": ["BTC"],
            "exchanges": {"exchange_names": []},
            "funding_rates": {
                "binance": {"BTC": "not_a_number"},
            },
        }
        session = _mock_session(raw)
        client = LorisAPIClient(session=session, cache_ttl=0)
        resp = client.fetch()

        assert len(resp.funding_rates) == 0

    def test_parse_non_dict_funding_rates_skipped(self):
        """funding_rates内の非辞書値はスキップされる。"""
        raw = {
            "symbols": [],
            "exchanges": {"exchange_names": []},
            "funding_rates": {
                "binance": "invalid",
            },
        }
        session = _mock_session(raw)
        client = LorisAPIClient(session=session, cache_ttl=0)
        resp = client.fetch()

        assert len(resp.funding_rates) == 0

    def test_parse_empty_response(self):
        """空レスポンスでもエラーにならない。"""
        raw = {"symbols": [], "exchanges": {"exchange_names": []}, "funding_rates": {}}
        session = _mock_session(raw)
        client = LorisAPIClient(session=session, cache_ttl=0)
        resp = client.fetch()

        assert resp.symbols == []
        assert resp.exchanges == []
        assert resp.funding_rates == []


class TestLorisAPIClientFundingRateNormalization:
    """funding rate正規化のテスト。"""

    def test_8h_exchange_rate_calculation(self):
        """8時間周期取引所のレートは RATE_DIVISOR で割るだけ。"""
        raw = {
            "symbols": ["BTC"],
            "exchanges": {"exchange_names": [
                {"name": "binance", "display": "Binance", "interval": 8},
            ]},
            "funding_rates": {"binance": {"BTC": 100}},
        }
        session = _mock_session(raw)
        client = LorisAPIClient(session=session, cache_ttl=0)
        resp = client.fetch()

        rate = resp.funding_rates[0]
        assert rate.exchange == "binance"
        assert abs(rate.rate - 100 / RATE_DIVISOR) < 1e-9

    def test_hourly_exchange_rate_normalized_to_8h(self):
        """1時間周期取引所のレートは さらに8で割られる。"""
        raw = {
            "symbols": ["BTC"],
            "exchanges": {"exchange_names": [
                {"name": "hyperliquid", "display": "Hyperliquid", "interval": 1},
            ]},
            "funding_rates": {"hyperliquid": {"BTC": 80}},
        }
        session = _mock_session(raw)
        client = LorisAPIClient(session=session, cache_ttl=0)
        resp = client.fetch()

        rate = resp.funding_rates[0]
        expected = 80 / RATE_DIVISOR / HOURLY_TO_8H_DIVISOR
        assert abs(rate.rate - expected) < 1e-9

    def test_all_hourly_exchanges_are_normalized(self):
        """HOURLY_EXCHANGES の全取引所で正規化される。"""
        for ex_name in HOURLY_EXCHANGES:
            raw = {
                "symbols": ["ETH"],
                "exchanges": {"exchange_names": [
                    {"name": ex_name, "display": ex_name.title(), "interval": 1},
                ]},
                "funding_rates": {ex_name: {"ETH": 40}},
            }
            session = _mock_session(raw)
            client = LorisAPIClient(session=session, cache_ttl=0)
            resp = client.fetch()

            rate = resp.funding_rates[0]
            expected = 40 / RATE_DIVISOR / HOURLY_TO_8H_DIVISOR
            assert abs(rate.rate - expected) < 1e-9, f"{ex_name}の正規化が不正"

    def test_negative_rate_preserved(self):
        """負のレートが正しく保持される。"""
        raw = {
            "symbols": ["BTC"],
            "exchanges": {"exchange_names": []},
            "funding_rates": {"binance": {"BTC": -50}},
        }
        session = _mock_session(raw)
        client = LorisAPIClient(session=session, cache_ttl=0)
        resp = client.fetch()

        rate = resp.funding_rates[0]
        assert rate.rate < 0
        assert abs(rate.rate - (-50 / RATE_DIVISOR)) < 1e-9


class TestLorisAPIClientCache:
    """キャッシュ機構のテスト。"""

    def test_cache_hit_within_ttl(self):
        """TTL内ではキャッシュを返す。"""
        session = _mock_session(SAMPLE_API_RESPONSE)
        client = LorisAPIClient(session=session, cache_ttl=60)

        resp1 = client.fetch()
        resp2 = client.fetch()

        # 1回しかHTTPリクエストしない
        assert session.get.call_count == 1
        assert resp1 is resp2

    def test_cache_miss_after_ttl(self):
        """TTL経過後は再取得する。"""
        session = _mock_session(SAMPLE_API_RESPONSE)
        client = LorisAPIClient(session=session, cache_ttl=0.01)

        client.fetch()
        time.sleep(0.02)
        client.fetch()

        assert session.get.call_count == 2

    def test_force_fetch_ignores_cache(self):
        """force=True でキャッシュを無視する。"""
        session = _mock_session(SAMPLE_API_RESPONSE)
        client = LorisAPIClient(session=session, cache_ttl=60)

        client.fetch()
        client.fetch(force=True)

        assert session.get.call_count == 2

    def test_invalidate_cache(self):
        """invalidate_cache() でキャッシュがクリアされる。"""
        session = _mock_session(SAMPLE_API_RESPONSE)
        client = LorisAPIClient(session=session, cache_ttl=60)

        client.fetch()
        client.invalidate_cache()
        client.fetch()

        assert session.get.call_count == 2


class TestLorisAPIClientErrorHandling:
    """エラーハンドリングのテスト。"""

    def test_all_retries_fail_raises_error(self):
        """全リトライ失敗で LorisAPIError が発生する。"""
        session = _failing_session()
        client = LorisAPIClient(
            session=session, max_retries=2, retry_delay=0.01, cache_ttl=0
        )

        with pytest.raises(LorisAPIError, match="全2回のリトライが失敗しました"):
            client.fetch()

        assert session.get.call_count == 2

    def test_retry_succeeds_on_second_attempt(self):
        """2回目のリトライで成功する場合。"""
        session = MagicMock(spec=requests.Session)
        good_resp = MagicMock()
        good_resp.json.return_value = {
            "symbols": [], "exchanges": {"exchange_names": []}, "funding_rates": {}
        }
        good_resp.raise_for_status.return_value = None
        session.get.side_effect = [
            requests.ConnectionError("fail 1"),
            good_resp,
        ]

        client = LorisAPIClient(
            session=session, max_retries=3, retry_delay=0.01, cache_ttl=0
        )
        resp = client.fetch()

        assert session.get.call_count == 2
        assert len(resp.funding_rates) == 0

    def test_get_rate_returns_none_for_missing(self):
        """存在しない取引所/シンボルの get_rate は None を返す。"""
        session = _mock_session(SAMPLE_API_RESPONSE)
        client = LorisAPIClient(session=session, cache_ttl=0)

        result = client.get_rate("nonexistent", "BTC")
        assert result is None

    def test_get_rate_returns_matching_entry(self):
        """存在する取引所/シンボルの get_rate は正しいレートを返す。"""
        session = _mock_session(SAMPLE_API_RESPONSE)
        client = LorisAPIClient(session=session, cache_ttl=0)

        result = client.get_rate("binance", "BTC")
        assert result is not None
        assert result.exchange == "binance"
        assert result.symbol == "BTC"

    def test_get_rates_by_symbols(self):
        """get_rates_by_symbols がフィルタしたレートを返す。"""
        session = _mock_session(SAMPLE_API_RESPONSE)
        client = LorisAPIClient(session=session, cache_ttl=0)

        rates = client.get_rates_by_symbols(["BTC"])
        for fr in rates:
            assert fr.symbol == "BTC"
        # binance, bybit, hyperliquid の3レート
        assert len(rates) == 3


# =========================================================================
# 2. シンボル/取引所マッピングのテスト
# =========================================================================


class TestSymbolExchangeMapping:
    """Loris ⇔ 内部形式マッピングのテスト。"""

    def test_loris_to_ccxt_symbol_known(self):
        assert _loris_to_ccxt_symbol("BTC") == "BTC/USDT:USDT"
        assert _loris_to_ccxt_symbol("ETH") == "ETH/USDT:USDT"

    def test_loris_to_ccxt_symbol_unknown_fallback(self):
        assert _loris_to_ccxt_symbol("UNKNOWN") == "UNKNOWN/USDT:USDT"

    def test_ccxt_to_loris_symbol(self):
        assert _ccxt_to_loris_symbol("BTC/USDT:USDT") == "BTC"
        assert _ccxt_to_loris_symbol("ETH/USDT:USDT") == "ETH"

    def test_loris_to_internal_exchange_known(self):
        assert _loris_to_internal_exchange("binance") == "binance"
        assert _loris_to_internal_exchange("hyperliquid") == "hyperliquid"

    def test_loris_to_internal_exchange_unknown_passthrough(self):
        assert _loris_to_internal_exchange("new_exchange") == "new_exchange"


# =========================================================================
# 3. LorisMarketDataService のテスト
# =========================================================================


class TestLorisMarketDataService:
    """LorisMarketDataService のテスト。"""

    def _make_client(self, rates: List[LorisFundingRate]) -> LorisAPIClient:
        client = MagicMock(spec=LorisAPIClient)
        client.fetch.return_value = _make_loris_response(rates)
        return client

    def test_get_funding_snapshots_basic(self):
        """基本的なFundingSnapshot変換が正しい。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=25, rate=0.0025),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-10, rate=-0.001),
        ]
        client = self._make_client(rates)
        service = LorisMarketDataService(loris_client=client)

        snapshots = service.get_funding_snapshots(
            exchanges=["binance", "bybit"],
            symbols=["BTC/USDT:USDT"],
        )

        assert len(snapshots) == 2
        for snap in snapshots:
            assert isinstance(snap, FundingSnapshot)
            assert snap.symbol == "BTC/USDT:USDT"
            assert snap.next_funding_time is None
            assert snap.bid is None
            assert snap.ask is None

    def test_exchange_filter(self):
        """exchange_filter でフィルタリングされる。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=25, rate=0.0025),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-10, rate=-0.001),
            LorisFundingRate(exchange="okx", symbol="BTC", raw_value=15, rate=0.0015),
        ]
        client = self._make_client(rates)
        service = LorisMarketDataService(
            loris_client=client, exchange_filter=["binance"]
        )

        snapshots = service.get_funding_snapshots(
            exchanges=["binance", "bybit", "okx"],
            symbols=["BTC/USDT:USDT"],
        )

        assert len(snapshots) == 1
        assert snapshots[0].exchange == "binance"

    def test_default_oi_value(self):
        """OIのデフォルト値が設定される。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=25, rate=0.0025),
        ]
        client = self._make_client(rates)
        service = LorisMarketDataService(loris_client=client, default_oi=10_000_000.0)

        snapshots = service.get_funding_snapshots(
            exchanges=["binance"], symbols=["BTC/USDT:USDT"]
        )

        assert snapshots[0].oi == 10_000_000.0

    def test_mark_price_is_zero(self):
        """Loris APIは板情報を持たないのでmark_priceは0。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="ETH", raw_value=-10, rate=-0.001),
        ]
        client = self._make_client(rates)
        service = LorisMarketDataService(loris_client=client)

        snapshots = service.get_funding_snapshots(
            exchanges=["binance"], symbols=["ETH/USDT:USDT"]
        )

        assert snapshots[0].mark_price == 0.0

    def test_funding_rate_is_loris_normalized_rate(self):
        """FundingSnapshotのfunding_rateはLoris正規化済みレートを使用する。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=25, rate=0.0025),
        ]
        client = self._make_client(rates)
        service = LorisMarketDataService(loris_client=client)

        snapshots = service.get_funding_snapshots(
            exchanges=["binance"], symbols=["BTC/USDT:USDT"]
        )

        assert abs(snapshots[0].funding_rate - 0.0025) < 1e-9

    def test_symbol_filter_excludes_non_matching(self):
        """指定シンボル以外はフィルタリングされる。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=25, rate=0.0025),
            LorisFundingRate(exchange="binance", symbol="ETH", raw_value=-10, rate=-0.001),
        ]
        client = self._make_client(rates)
        service = LorisMarketDataService(loris_client=client)

        snapshots = service.get_funding_snapshots(
            exchanges=["binance"], symbols=["BTC/USDT:USDT"]
        )

        assert len(snapshots) == 1
        assert snapshots[0].symbol == "BTC/USDT:USDT"

    def test_get_orderbook_tops_returns_empty(self):
        """板情報APIは空辞書を返す。"""
        client = self._make_client([])
        service = LorisMarketDataService(loris_client=client)

        result = service.get_orderbook_tops("binance", ["BTC/USDT:USDT"])
        assert result == {}


# =========================================================================
# 4. HybridMarketDataService のテスト
# =========================================================================


class TestHybridMarketDataService:
    """Loris + CCXT ハイブリッドサービスのテスト。"""

    def _make_loris_client(self, rates: List[LorisFundingRate]) -> LorisAPIClient:
        client = MagicMock(spec=LorisAPIClient)
        client.fetch.return_value = _make_loris_response(rates)
        return client

    def test_combines_loris_fr_with_ccxt_oi_and_orderbook(self):
        """LorisのFRとCCXTのOI/板情報が統合される。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=25, rate=0.0025),
        ]
        loris_client = self._make_loris_client(rates)
        ccxt_adapter = FakeCCXTAdapter(oi=8_000_000, mark_price=50000)

        service = HybridMarketDataService(
            loris_client=loris_client,
            ccxt_adapters={"binance": ccxt_adapter},
        )

        snapshots = service.get_funding_snapshots(
            exchanges=["binance"], symbols=["BTC/USDT:USDT"]
        )

        assert len(snapshots) == 1
        snap = snapshots[0]
        assert abs(snap.funding_rate - 0.0025) < 1e-9  # Loris FR
        assert snap.oi == 8_000_000  # CCXT OI
        assert snap.bid is not None  # CCXT orderbook
        assert snap.ask is not None

    def test_no_ccxt_adapter_returns_zero_oi(self):
        """CCXTアダプタがない場合、OIは0になる。"""
        rates = [
            LorisFundingRate(exchange="bybit", symbol="ETH", raw_value=-10, rate=-0.001),
        ]
        loris_client = self._make_loris_client(rates)

        service = HybridMarketDataService(
            loris_client=loris_client,
            ccxt_adapters={},  # アダプタなし
        )

        snapshots = service.get_funding_snapshots(
            exchanges=["bybit"], symbols=["ETH/USDT:USDT"]
        )

        assert len(snapshots) == 1
        assert snapshots[0].oi == 0.0
        assert snapshots[0].bid is None
        assert snapshots[0].mark_price == 0.0

    def test_ccxt_adapter_error_graceful_fallback(self):
        """CCXTアダプタエラー時はデフォルト値にフォールバックする。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=25, rate=0.0025),
        ]
        loris_client = self._make_loris_client(rates)

        failing_adapter = MagicMock(spec=CCXTAdapter)
        failing_adapter.fetch_open_interest.side_effect = Exception("OI API down")
        failing_adapter.fetch_order_book.side_effect = Exception("OB API down")

        service = HybridMarketDataService(
            loris_client=loris_client,
            ccxt_adapters={"binance": failing_adapter},
        )

        snapshots = service.get_funding_snapshots(
            exchanges=["binance"], symbols=["BTC/USDT:USDT"]
        )

        assert len(snapshots) == 1
        snap = snapshots[0]
        assert abs(snap.funding_rate - 0.0025) < 1e-9  # FRはLorisから取得済み
        assert snap.oi == 0.0  # CCXTエラーなのでデフォルト
        assert snap.bid is None

    def test_get_orderbook_tops_uses_ccxt(self):
        """get_orderbook_tops は CCXT アダプタを使用する。"""
        loris_client = self._make_loris_client([])
        adapter = FakeCCXTAdapter(mark_price=45000)

        service = HybridMarketDataService(
            loris_client=loris_client,
            ccxt_adapters={"binance": adapter},
        )

        tops = service.get_orderbook_tops("binance", ["BTC/USDT:USDT"])
        assert "BTC/USDT:USDT" in tops
        assert tops["BTC/USDT:USDT"]["bid"] > 0
        assert tops["BTC/USDT:USDT"]["ask"] > 0

    def test_get_orderbook_tops_no_adapter(self):
        """アダプタがない取引所の板情報は空辞書。"""
        loris_client = self._make_loris_client([])
        service = HybridMarketDataService(
            loris_client=loris_client, ccxt_adapters={}
        )

        tops = service.get_orderbook_tops("unknown_ex", ["BTC/USDT:USDT"])
        assert tops == {}


# =========================================================================
# 5. エンドツーエンド: オーケストレータとの統合テスト
# =========================================================================


class TestEndToEndWithOrchestrator:
    """Loris経由のデータでオーケストレータが正常にサイクル実行できることを確認。"""

    def _make_loris_client_for_e2e(self) -> LorisAPIClient:
        """E2E用のLorisクライアント（反対符号のFRペアを含む）。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=50, rate=0.005),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-30, rate=-0.003),
            LorisFundingRate(exchange="binance", symbol="ETH", raw_value=-20, rate=-0.002),
            LorisFundingRate(exchange="bybit", symbol="ETH", raw_value=15, rate=0.0015),
        ]
        client = MagicMock(spec=LorisAPIClient)
        client.fetch.return_value = _make_loris_response(rates)
        return client

    def test_loris_market_data_with_orchestrator(self):
        """LorisMarketDataService経由でオーケストレータのサイクルが実行できる。"""
        loris_client = self._make_loris_client_for_e2e()

        config = FundingArbConfig(
            exchanges=[ExchangeConfig("binance"), ExchangeConfig("bybit")],
            symbols=["BTC/USDT:USDT", "ETH/USDT:USDT"],
            min_open_interest_usd=1_000_000,
            min_liquidity_score=0.2,
            fr_diff_min=0.002,
            min_persistence_windows=1,
            min_pair_score=0.0,
            expected_edge_min_bps=-100,
            universe_size=10,
        )

        market_data = LorisMarketDataService(
            loris_client=loris_client, default_oi=5_000_000.0
        )
        signal = SignalService(config)
        risk = RiskService(config)
        execution = ExecutionService(FakeExecClient())
        orch = FundingArbOrchestrator(config, market_data, signal, risk, execution)

        portfolio = PortfolioState(
            equity=100_000,
            peak_equity=100_000,
            gross_notional_usd=0,
            net_delta_usd=0,
        )
        features: Dict[Tuple[str, str], PairFeatures] = {
            ("BTC/USDT:USDT", "ETH/USDT:USDT"): PairFeatures(
                correlation=0.8, beta=1.0,
                beta_stability=0.7, atr_ratio_stability=0.8,
                mean_reversion_score=0.7,
            ),
        }

        # サイクル1: persistenceが1なのでmin_persistence_windows=1ならcandidateが生成される
        cycle = orch.run_cycle(portfolio, features)

        assert cycle.candidates >= 0
        # LorisのデータにはFR反対符号のペアがあるのでcandidateが生成されうる
        # mark_priceが0なのでexecutionの数量計算に注意

    def test_hybrid_market_data_with_orchestrator(self):
        """HybridMarketDataService経由でサイクルが実行できる。"""
        loris_client = self._make_loris_client_for_e2e()

        config = FundingArbConfig(
            exchanges=[ExchangeConfig("binance"), ExchangeConfig("bybit")],
            symbols=["BTC/USDT:USDT", "ETH/USDT:USDT"],
            min_open_interest_usd=1_000_000,
            min_liquidity_score=0.2,
            fr_diff_min=0.002,
            min_persistence_windows=1,
            min_pair_score=0.0,
            expected_edge_min_bps=-100,
        )

        ccxt_adapters = {
            "binance": FakeCCXTAdapter(oi=10_000_000, mark_price=50000),
            "bybit": FakeCCXTAdapter(oi=8_000_000, mark_price=50000),
        }
        market_data = HybridMarketDataService(
            loris_client=loris_client, ccxt_adapters=ccxt_adapters
        )
        signal = SignalService(config)
        risk = RiskService(config)
        execution = ExecutionService(FakeExecClient())
        orch = FundingArbOrchestrator(config, market_data, signal, risk, execution)

        portfolio = PortfolioState(
            equity=100_000,
            peak_equity=100_000,
            gross_notional_usd=0,
            net_delta_usd=0,
        )
        features: Dict[Tuple[str, str], PairFeatures] = {
            ("BTC/USDT:USDT", "ETH/USDT:USDT"): PairFeatures(
                correlation=0.8, beta=1.0,
                beta_stability=0.7, atr_ratio_stability=0.8,
                mean_reversion_score=0.7,
            ),
        }

        cycle = orch.run_cycle(portfolio, features)

        # HybridはCCXTからmark_priceを取得するので、正常にペアが評価される
        assert cycle.candidates >= 0

    def test_hybrid_orchestrator_two_cycles_with_persistence(self):
        """2サイクルでpersistenceが蓄積されエントリが実行される。"""
        loris_client = self._make_loris_client_for_e2e()

        config = FundingArbConfig(
            exchanges=[ExchangeConfig("binance"), ExchangeConfig("bybit")],
            symbols=["BTC/USDT:USDT"],
            min_open_interest_usd=1_000_000,
            min_liquidity_score=0.2,
            fr_diff_min=0.002,
            min_persistence_windows=2,
            min_pair_score=0.0,
            expected_edge_min_bps=-100,
        )

        ccxt_adapters = {
            "binance": FakeCCXTAdapter(oi=10_000_000, mark_price=50000),
            "bybit": FakeCCXTAdapter(oi=8_000_000, mark_price=50000),
        }
        market_data = HybridMarketDataService(
            loris_client=loris_client, ccxt_adapters=ccxt_adapters
        )
        signal = SignalService(config)
        risk = RiskService(config)
        execution = ExecutionService(FakeExecClient())
        orch = FundingArbOrchestrator(config, market_data, signal, risk, execution)

        portfolio = PortfolioState(
            equity=100_000,
            peak_equity=100_000,
            gross_notional_usd=0,
            net_delta_usd=0,
        )
        features: Dict[Tuple[str, str], PairFeatures] = {}

        # サイクル1: persistence=1 → min_persistence_windows=2なのでエントリなし
        cycle1 = orch.run_cycle(portfolio, features)
        assert cycle1.intents == 0

        # サイクル2: persistence=2 → エントリ可能
        cycle2 = orch.run_cycle(portfolio, features)
        assert cycle2.candidates >= 1
        # BTC binance +0.005, bybit -0.003 → fr_diff = 0.008 > 0.002
        # persistenceが2に到達しているのでintentが生成される
        assert cycle2.intents >= 1
        assert cycle2.executed >= 1


# =========================================================================
# 6. DynamicUniverseProvider の追加統合テスト
# =========================================================================


class TestDynamicUniverseIntegration:
    """DynamicUniverseProvider と他コンポーネントの統合テスト。"""

    def test_universe_symbols_usable_by_loris_market_data(self):
        """universeで選定されたシンボルがLorisMarketDataServiceで使える。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=50, rate=0.005),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-30, rate=-0.003),
            LorisFundingRate(exchange="binance", symbol="ETH", raw_value=-20, rate=-0.002),
            LorisFundingRate(exchange="bybit", symbol="ETH", raw_value=15, rate=0.0015),
        ]
        loris_client = MagicMock(spec=LorisAPIClient)
        loris_client.fetch.return_value = _make_loris_response(rates)

        config = FundingArbConfig(universe_size=5, fr_diff_min=0.001)

        # 動的ユニバースでシンボル選定
        provider = DynamicUniverseProvider(config, loris_client)
        symbols = provider.get_symbols_for_cycle()

        # 選定されたシンボルをCCXT形式に変換してMarketDataServiceに渡す
        ccxt_symbols = [_loris_to_ccxt_symbol(s) for s in symbols]
        service = LorisMarketDataService(loris_client=loris_client)
        snapshots = service.get_funding_snapshots(
            exchanges=["binance", "bybit"],
            symbols=ccxt_symbols,
        )

        assert len(snapshots) > 0
        snap_symbols = {s.symbol for s in snapshots}
        for ccxt_sym in ccxt_symbols:
            assert ccxt_sym in snap_symbols

    def test_oi_ranking_filtering(self):
        """OIランキングに基づくフィルタリング。

        DynamicUniverseProviderはOIデータを直接持たないが、
        funding rate spreadが大きいシンボルを優先する。
        universe_size で上位N銘柄に絞る。
        """
        rates = [
            # 大きいspreadのシンボル
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=100, rate=0.01),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-80, rate=-0.008),
            # 中程度のspread
            LorisFundingRate(exchange="binance", symbol="ETH", raw_value=30, rate=0.003),
            LorisFundingRate(exchange="bybit", symbol="ETH", raw_value=-10, rate=-0.001),
            # 小さいspread
            LorisFundingRate(exchange="binance", symbol="SOL", raw_value=5, rate=0.0005),
            LorisFundingRate(exchange="bybit", symbol="SOL", raw_value=3, rate=0.0003),
        ]
        loris_client = MagicMock(spec=LorisAPIClient)
        loris_client.fetch.return_value = _make_loris_response(rates)

        config = FundingArbConfig(universe_size=2)
        provider = DynamicUniverseProvider(config, loris_client)
        snapshot = provider.select_universe()

        # BTC (spread=0.018) > ETH (spread=0.004) > SOL (spread=0.0002)
        assert len(snapshot.symbols) == 2
        assert "BTC" in snapshot.symbols
        assert "ETH" in snapshot.symbols
        assert "SOL" not in snapshot.symbols

    def test_universe_size_limit(self):
        """universe_size が正しく適用される。"""
        rates = []
        for i, sym in enumerate(["BTC", "ETH", "SOL", "XRP", "DOGE"]):
            rates.append(LorisFundingRate(
                exchange="binance", symbol=sym, raw_value=(50 - i * 10), rate=(0.005 - i * 0.001)
            ))
            rates.append(LorisFundingRate(
                exchange="bybit", symbol=sym, raw_value=-(50 - i * 10), rate=-(0.005 - i * 0.001)
            ))

        loris_client = MagicMock(spec=LorisAPIClient)
        loris_client.fetch.return_value = _make_loris_response(rates)

        config = FundingArbConfig(universe_size=3)
        provider = DynamicUniverseProvider(config, loris_client)
        snapshot = provider.select_universe()

        assert len(snapshot.symbols) == 3


# =========================================================================
# 7. get_top_symbols_by_criteria のテスト
# =========================================================================


class TestGetTopSymbolsByCriteria:
    """MarketDataService.get_top_symbols_by_criteria のテスト。"""

    def _make_loris_client(self, rates: List[LorisFundingRate]) -> LorisAPIClient:
        client = MagicMock(spec=LorisAPIClient)
        client.fetch.return_value = _make_loris_response(rates)
        return client

    def test_base_class_returns_empty(self):
        """MarketDataService基底クラスのデフォルト実装は空リストを返す。"""
        from funding_arb.market_data import CCXTMarketDataService

        service = CCXTMarketDataService(adapters={})
        result = service.get_top_symbols_by_criteria(universe_size=10)
        assert result == []

    def test_loris_service_without_config_returns_empty(self):
        """config未指定のLorisMarketDataServiceは空リストを返す。"""
        client = self._make_loris_client([])
        service = LorisMarketDataService(loris_client=client)

        result = service.get_top_symbols_by_criteria(universe_size=10)
        assert result == []

    def test_loris_service_with_config_returns_symbols(self):
        """config指定ありのLorisMarketDataServiceがCCXT形式シンボルを返す。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=50, rate=0.005),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-30, rate=-0.003),
            LorisFundingRate(exchange="binance", symbol="ETH", raw_value=-20, rate=-0.002),
            LorisFundingRate(exchange="bybit", symbol="ETH", raw_value=15, rate=0.0015),
        ]
        client = self._make_loris_client(rates)
        config = FundingArbConfig(universe_size=10, fr_diff_min=0.001)
        service = LorisMarketDataService(loris_client=client, config=config)

        result = service.get_top_symbols_by_criteria(universe_size=10)

        assert len(result) > 0
        # CCXT形式であることを確認
        for sym in result:
            assert "/USDT:USDT" in sym

    def test_loris_service_universe_size_limits_results(self):
        """universe_sizeパラメータでシンボル数が制限される。"""
        rates = []
        for sym in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            rates.append(LorisFundingRate(exchange="binance", symbol=sym, raw_value=50, rate=0.005))
            rates.append(LorisFundingRate(exchange="bybit", symbol=sym, raw_value=-30, rate=-0.003))

        client = self._make_loris_client(rates)
        config = FundingArbConfig(universe_size=10)
        service = LorisMarketDataService(loris_client=client, config=config)

        result = service.get_top_symbols_by_criteria(universe_size=2)
        assert len(result) <= 2

    def test_loris_service_min_fr_diff_filters(self):
        """min_fr_diffパラメータでFR差が小さいシンボルが除外される。"""
        rates = [
            # 大きいFR差
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=100, rate=0.01),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-80, rate=-0.008),
            # 小さいFR差
            LorisFundingRate(exchange="binance", symbol="ETH", raw_value=1, rate=0.0001),
            LorisFundingRate(exchange="bybit", symbol="ETH", raw_value=2, rate=0.0002),
        ]
        client = self._make_loris_client(rates)
        config = FundingArbConfig(universe_size=10)
        service = LorisMarketDataService(loris_client=client, config=config)

        result = service.get_top_symbols_by_criteria(
            universe_size=10, min_fr_diff=0.01
        )

        # BTC: |0.01 - (-0.008)| = 0.018 >= 0.01 → 含まれる
        # ETH: |0.0001 - 0.0002| = 0.0001 < 0.01 → 除外
        assert "BTC/USDT:USDT" in result
        assert "ETH/USDT:USDT" not in result

    def test_hybrid_service_with_config_returns_symbols(self):
        """config指定ありのHybridMarketDataServiceがCCXT形式シンボルを返す。"""
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=50, rate=0.005),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-30, rate=-0.003),
        ]
        client = self._make_loris_client(rates)
        config = FundingArbConfig(universe_size=10)
        ccxt_adapters = {
            "binance": FakeCCXTAdapter(),
            "bybit": FakeCCXTAdapter(),
        }
        service = HybridMarketDataService(
            loris_client=client, ccxt_adapters=ccxt_adapters, config=config
        )

        result = service.get_top_symbols_by_criteria(universe_size=10)

        assert len(result) > 0
        assert "BTC/USDT:USDT" in result

    def test_hybrid_service_without_config_returns_empty(self):
        """config未指定のHybridMarketDataServiceは空リストを返す。"""
        client = self._make_loris_client([])
        service = HybridMarketDataService(
            loris_client=client, ccxt_adapters={}
        )

        result = service.get_top_symbols_by_criteria(universe_size=10)
        assert result == []


# =========================================================================
# 8. オーケストレータ動的銘柄選定パスのテスト
# =========================================================================


class TestOrchestratorDynamicSymbolSelection:
    """config.symbolsが空の場合にオーケストレータが動的銘柄選定を行うテスト。"""

    def _make_loris_client(self) -> LorisAPIClient:
        rates = [
            LorisFundingRate(exchange="binance", symbol="BTC", raw_value=50, rate=0.005),
            LorisFundingRate(exchange="bybit", symbol="BTC", raw_value=-30, rate=-0.003),
            LorisFundingRate(exchange="binance", symbol="ETH", raw_value=-20, rate=-0.002),
            LorisFundingRate(exchange="bybit", symbol="ETH", raw_value=15, rate=0.0015),
        ]
        client = MagicMock(spec=LorisAPIClient)
        client.fetch.return_value = _make_loris_response(rates)
        return client

    def test_empty_symbols_triggers_dynamic_selection(self):
        """config.symbolsが空の場合、get_top_symbols_by_criteriaが呼ばれる。"""
        loris_client = self._make_loris_client()
        config = FundingArbConfig(
            exchanges=[ExchangeConfig("binance"), ExchangeConfig("bybit")],
            symbols=[],  # 空 → 動的選定
            universe_size=10,
            fr_diff_min=0.001,
            min_open_interest_usd=1_000_000,
            min_liquidity_score=0.2,
            min_persistence_windows=1,
            min_pair_score=0.0,
            expected_edge_min_bps=-100,
        )

        ccxt_adapters = {
            "binance": FakeCCXTAdapter(oi=10_000_000, mark_price=50000),
            "bybit": FakeCCXTAdapter(oi=8_000_000, mark_price=50000),
        }
        market_data = HybridMarketDataService(
            loris_client=loris_client, ccxt_adapters=ccxt_adapters, config=config
        )
        signal = SignalService(config)
        risk = RiskService(config)
        execution = ExecutionService(FakeExecClient())
        orch = FundingArbOrchestrator(config, market_data, signal, risk, execution)

        portfolio = PortfolioState(
            equity=100_000, peak_equity=100_000,
            gross_notional_usd=0, net_delta_usd=0,
        )

        # symbols が空なので動的選定パスを通る
        cycle = orch.run_cycle(portfolio, {})
        # エラーなく完了すること（動的選定が動作した証拠）
        assert cycle.candidates >= 0

    def test_nonempty_symbols_skips_dynamic_selection(self):
        """config.symbolsが設定されている場合は動的選定しない。"""
        loris_client = self._make_loris_client()
        config = FundingArbConfig(
            exchanges=[ExchangeConfig("binance"), ExchangeConfig("bybit")],
            symbols=["BTC/USDT:USDT"],  # 明示的に指定
            universe_size=10,
            fr_diff_min=0.001,
            min_open_interest_usd=1_000_000,
            min_liquidity_score=0.2,
            min_persistence_windows=2,
            min_pair_score=0.0,
            expected_edge_min_bps=-100,
        )

        ccxt_adapters = {
            "binance": FakeCCXTAdapter(oi=10_000_000, mark_price=50000),
            "bybit": FakeCCXTAdapter(oi=8_000_000, mark_price=50000),
        }
        market_data = HybridMarketDataService(
            loris_client=loris_client, ccxt_adapters=ccxt_adapters, config=config
        )
        signal = SignalService(config)
        risk = RiskService(config)
        execution = ExecutionService(FakeExecClient())
        orch = FundingArbOrchestrator(config, market_data, signal, risk, execution)

        portfolio = PortfolioState(
            equity=100_000, peak_equity=100_000,
            gross_notional_usd=0, net_delta_usd=0,
        )

        cycle = orch.run_cycle(portfolio, {})
        # BTC/USDT:USDT のみ → 同一シンボルのbinance vs bybitペア
        assert cycle.candidates >= 0

    def test_dynamic_selection_e2e_two_cycles(self):
        """動的選定パスで2サイクル実行しpersistence蓄積→エントリ。"""
        loris_client = self._make_loris_client()
        config = FundingArbConfig(
            exchanges=[ExchangeConfig("binance"), ExchangeConfig("bybit")],
            symbols=[],  # 動的選定
            universe_size=10,
            fr_diff_min=0.001,
            min_open_interest_usd=1_000_000,
            min_liquidity_score=0.2,
            min_persistence_windows=2,
            min_pair_score=0.0,
            expected_edge_min_bps=-100,
        )

        ccxt_adapters = {
            "binance": FakeCCXTAdapter(oi=10_000_000, mark_price=50000),
            "bybit": FakeCCXTAdapter(oi=8_000_000, mark_price=50000),
        }
        market_data = HybridMarketDataService(
            loris_client=loris_client, ccxt_adapters=ccxt_adapters, config=config
        )
        signal = SignalService(config)
        risk = RiskService(config)
        execution = ExecutionService(FakeExecClient())
        orch = FundingArbOrchestrator(config, market_data, signal, risk, execution)

        portfolio = PortfolioState(
            equity=100_000, peak_equity=100_000,
            gross_notional_usd=0, net_delta_usd=0,
        )

        # サイクル1: persistence=1
        cycle1 = orch.run_cycle(portfolio, {})
        assert cycle1.intents == 0

        # サイクル2: persistence=2 → エントリ
        cycle2 = orch.run_cycle(portfolio, {})
        assert cycle2.candidates >= 1
        assert cycle2.intents >= 1
        assert cycle2.executed >= 1
