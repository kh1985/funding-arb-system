from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from .loris_client import LorisAPIClient, LorisFundingRate
from .types import FundingSnapshot
from .universe import DynamicUniverseProvider, SymbolScore

logger = logging.getLogger(__name__)


class MarketDataService(ABC):
    @abstractmethod
    def get_funding_snapshots(
        self,
        exchanges: Iterable[str],
        symbols: Iterable[str],
    ) -> List[FundingSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def get_orderbook_tops(
        self,
        exchange: str,
        symbols: Iterable[str],
    ) -> Dict[str, Dict[str, float]]:
        raise NotImplementedError

    def get_top_symbols_by_criteria(
        self,
        universe_size: int,
        min_fr_diff: Optional[float] = None,
    ) -> List[str]:
        """OIランキング・FR差に基づく上位N銘柄を返す。

        デフォルト実装では空リストを返す。
        Loris統合サービスではDynamicUniverseProviderを使って動的に選定する。

        Parameters
        ----------
        universe_size : int
            選定する銘柄数の上限。
        min_fr_diff : Optional[float]
            最小funding rate差。None でデフォルト閾値を使用。

        Returns
        -------
        List[str]
            選定された銘柄シンボルのリスト。
        """
        return []


class CCXTAdapter(ABC):
    @abstractmethod
    def fetch_funding_rate(self, symbol: str) -> Dict:
        raise NotImplementedError

    @abstractmethod
    def fetch_open_interest(self, symbol: str) -> Dict:
        raise NotImplementedError

    @abstractmethod
    def fetch_order_book(self, symbol: str, limit: int = 5) -> Dict:
        raise NotImplementedError


class CCXTMarketDataService(MarketDataService):
    """Collect market snapshots via injected exchange adapters."""

    def __init__(
        self,
        adapters: Dict[str, CCXTAdapter],
        canonical_sign_map: Optional[Dict[str, bool]] = None,
    ):
        self.adapters = adapters
        self.canonical_sign_map = canonical_sign_map or {}

    def normalize_funding_rate(self, exchange: str, funding_rate: float) -> float:
        is_canonical = self.canonical_sign_map.get(exchange, True)
        return funding_rate if is_canonical else -funding_rate

    def get_funding_snapshots(
        self,
        exchanges: Iterable[str],
        symbols: Iterable[str],
    ) -> List[FundingSnapshot]:
        snapshots: List[FundingSnapshot] = []
        now = datetime.utcnow()
        for exchange in exchanges:
            adapter = self.adapters.get(exchange)
            if adapter is None:
                continue
            for symbol in symbols:
                fr = adapter.fetch_funding_rate(symbol)
                oi = adapter.fetch_open_interest(symbol)
                ob = adapter.fetch_order_book(symbol, limit=5)

                raw_funding = float(fr.get("fundingRate", 0.0))
                funding_rate = self.normalize_funding_rate(exchange, raw_funding)
                mark = float(fr.get("markPrice", 0.0) or 0.0)
                oi_value = float(oi.get("openInterestValue", 0.0) or 0.0)

                bids = ob.get("bids", [])
                asks = ob.get("asks", [])
                bid = float(bids[0][0]) if bids else None
                ask = float(asks[0][0]) if asks else None

                snapshots.append(
                    FundingSnapshot(
                        exchange=exchange,
                        symbol=symbol,
                        timestamp=fr.get("timestamp") or now,
                        funding_rate=funding_rate,
                        next_funding_time=fr.get("nextFundingTime"),
                        oi=oi_value,
                        mark_price=mark,
                        bid=bid,
                        ask=ask,
                    )
                )
        return snapshots

    def get_orderbook_tops(
        self,
        exchange: str,
        symbols: Iterable[str],
    ) -> Dict[str, Dict[str, float]]:
        adapter = self.adapters[exchange]
        out: Dict[str, Dict[str, float]] = {}
        for symbol in symbols:
            ob = adapter.fetch_order_book(symbol, limit=5)
            bids = ob.get("bids", [])
            asks = ob.get("asks", [])
            out[symbol] = {
                "bid": float(bids[0][0]) if bids else 0.0,
                "ask": float(asks[0][0]) if asks else 0.0,
            }
        return out


# ---------------------------------------------------------------------------
# 取引所名マッピング: Loris表記 → funding_arb表記
# ---------------------------------------------------------------------------

# Loris API の取引所名（小文字）を funding_arb 内部で使う正規表記に変換する。
# マッピングに無い取引所名はそのまま使用される。
LORIS_EXCHANGE_MAP: Dict[str, str] = {
    "binance": "binance",
    "bybit": "bybit",
    "okx": "okx",
    "gate": "gate",
    "bitget": "bitget",
    "dydx": "dydx",
    "hyperliquid": "hyperliquid",
    "vertex": "vertex",
    "aevo": "aevo",
    "drift": "drift",
    "mango": "mango",
    "rabbitx": "rabbitx",
    "bluefin": "bluefin",
    "extended": "extended",
    "lighter": "lighter",
    "vest": "vest",
    "paradex": "paradex",
}

# Loris のシンボル（例: "BTC"）を CCXT 形式（例: "BTC/USDT:USDT"）に変換する。
# 逆方向マッピング（CCXT → Loris）も保持する。
LORIS_SYMBOL_MAP: Dict[str, str] = {
    "BTC": "BTC/USDT:USDT",
    "ETH": "ETH/USDT:USDT",
    "SOL": "SOL/USDT:USDT",
    "XRP": "XRP/USDT:USDT",
    "DOGE": "DOGE/USDT:USDT",
    "ADA": "ADA/USDT:USDT",
    "AVAX": "AVAX/USDT:USDT",
    "LINK": "LINK/USDT:USDT",
    "DOT": "DOT/USDT:USDT",
    "MATIC": "MATIC/USDT:USDT",
    "ARB": "ARB/USDT:USDT",
    "OP": "OP/USDT:USDT",
    "SUI": "SUI/USDT:USDT",
    "APT": "APT/USDT:USDT",
    "NEAR": "NEAR/USDT:USDT",
    "FIL": "FIL/USDT:USDT",
    "ATOM": "ATOM/USDT:USDT",
    "UNI": "UNI/USDT:USDT",
    "LTC": "LTC/USDT:USDT",
    "BCH": "BCH/USDT:USDT",
    "INJ": "INJ/USDT:USDT",
    "TIA": "TIA/USDT:USDT",
    "SEI": "SEI/USDT:USDT",
    "PEPE": "PEPE/USDT:USDT",
    "WIF": "WIF/USDT:USDT",
}


def _loris_to_internal_exchange(loris_name: str) -> str:
    """Loris取引所名を内部表記に変換する。"""
    return LORIS_EXCHANGE_MAP.get(loris_name, loris_name)


def _loris_to_ccxt_symbol(loris_symbol: str) -> str:
    """LorisシンボルをCCXT形式に変換する。"""
    return LORIS_SYMBOL_MAP.get(loris_symbol, f"{loris_symbol}/USDT:USDT")


def _ccxt_to_loris_symbol(ccxt_symbol: str) -> str:
    """CCXTシンボルをLoris形式に変換する。"""
    # "BTC/USDT:USDT" → "BTC"
    base = ccxt_symbol.split("/")[0]
    return base


# ---------------------------------------------------------------------------
# LorisMarketDataService
# ---------------------------------------------------------------------------

class LorisMarketDataService(MarketDataService):
    """Loris API からファンディングレートを取得する MarketDataService。

    Loris API は funding rate のみ提供する。OI・板情報は含まれないため、
    OI はデフォルト値を使用し、bid/ask は None となる。
    OI や板情報が必要な場合は HybridMarketDataService を使用する。

    Parameters
    ----------
    loris_client : LorisAPIClient
        Loris API クライアント。
    exchange_filter : Optional[List[str]]
        使用する取引所のリスト（Loris表記）。None で全取引所。
    default_oi : float
        OI のデフォルト値（USD）。Loris にはOIデータがないため使用。
    """

    def __init__(
        self,
        loris_client: LorisAPIClient,
        exchange_filter: Optional[List[str]] = None,
        default_oi: float = 5_000_000.0,
        config: Optional["FundingArbConfig"] = None,
    ) -> None:
        self._loris = loris_client
        self._exchange_filter = (
            frozenset(exchange_filter) if exchange_filter else None
        )
        self._default_oi = default_oi
        self._universe_provider: Optional[DynamicUniverseProvider] = None
        if config is not None:
            from .config import FundingArbConfig as _Cfg  # noqa: F811
            self._universe_provider = DynamicUniverseProvider(
                config,
                loris_client,
                target_exchanges=exchange_filter,
            )

    def get_top_symbols_by_criteria(
        self,
        universe_size: int,
        min_fr_diff: Optional[float] = None,
    ) -> List[str]:
        """Loris APIからFR差に基づく上位N銘柄を動的に選定する。

        DynamicUniverseProvider を使用してファンディングレート差の大きい
        銘柄を優先的に選定する。結果はCCXT形式のシンボルに変換して返す。

        Parameters
        ----------
        universe_size : int
            選定する銘柄数の上限。
        min_fr_diff : Optional[float]
            最小funding rate差フィルタ。

        Returns
        -------
        List[str]
            選定された銘柄シンボルのリスト（CCXT形式）。
        """
        if self._universe_provider is None:
            logger.warning(
                "DynamicUniverseProvider未初期化。config引数なしで構築された場合、"
                "get_top_symbols_by_criteriaは空リストを返します。"
            )
            return []

        snapshot = self._universe_provider.select_universe()
        # universe_size で切り詰め（DynamicUniverseProvider のconfig.universe_sizeと
        # 異なるサイズが指定された場合に対応）
        loris_symbols = snapshot.symbols[:universe_size]

        # FR差でさらにフィルタ
        # ただし、同一取引所内ペアリングモードの場合はスキップ
        # （別銘柄間のペアはSignalServiceで生成されるため）
        if min_fr_diff is not None and not self._universe_provider._config.allow_single_exchange_pairs:
            qualified = set()
            for ex_a, ex_b, diff in snapshot.pair_candidates:
                if diff >= min_fr_diff:
                    # "exchange:SYMBOL" → SYMBOL
                    sym = ex_a.split(":", 1)[1]
                    qualified.add(sym)
            loris_symbols = [s for s in loris_symbols if s in qualified]

        # LorisシンボルをCCXT形式に変換
        return [_loris_to_ccxt_symbol(s) for s in loris_symbols]

    def get_funding_snapshots(
        self,
        exchanges: Iterable[str],
        symbols: Iterable[str],
    ) -> List[FundingSnapshot]:
        """Loris API からファンディングレートを取得し FundingSnapshot に変換する。

        Parameters
        ----------
        exchanges : Iterable[str]
            対象取引所名のリスト（funding_arb 内部表記）。
        symbols : Iterable[str]
            対象シンボル（CCXT形式、例: "BTC/USDT:USDT"）。

        Returns
        -------
        List[FundingSnapshot]
            取得したスナップショットのリスト。
        """
        exchange_set = set(exchanges)
        symbol_list = list(symbols)
        # CCXTシンボルをLorisシンボルに変換
        loris_symbols = [_ccxt_to_loris_symbol(s) for s in symbol_list]

        response = self._loris.fetch()
        now = datetime.utcnow()

        # 対象exchangeの逆引きマップ: 内部名 → Loris名
        internal_to_loris: Dict[str, str] = {}
        for loris_name, internal_name in LORIS_EXCHANGE_MAP.items():
            if internal_name in exchange_set:
                internal_to_loris[internal_name] = loris_name

        snapshots: List[FundingSnapshot] = []
        for fr in response.funding_rates:
            internal_exchange = _loris_to_internal_exchange(fr.exchange)

            # 取引所フィルタ
            if internal_exchange not in exchange_set:
                continue

            # exchange_filter（Loris表記）
            if self._exchange_filter and fr.exchange not in self._exchange_filter:
                continue

            # シンボルフィルタ
            if fr.symbol not in loris_symbols:
                continue

            ccxt_symbol = _loris_to_ccxt_symbol(fr.symbol)

            snapshots.append(
                FundingSnapshot(
                    exchange=internal_exchange,
                    symbol=ccxt_symbol,
                    timestamp=now,
                    funding_rate=fr.rate,
                    next_funding_time=None,
                    oi=self._default_oi,
                    mark_price=0.0,
                    bid=None,
                    ask=None,
                )
            )

        logger.info(
            "Loris: %d スナップショット取得（対象: %d取引所, %dシンボル）",
            len(snapshots),
            len(exchange_set),
            len(symbol_list),
        )
        return snapshots

    def get_orderbook_tops(
        self,
        exchange: str,
        symbols: Iterable[str],
    ) -> Dict[str, Dict[str, float]]:
        """Loris API は板情報を提供しないため空の辞書を返す。"""
        logger.warning(
            "LorisMarketDataService は板情報を提供しません。"
            "HybridMarketDataService の使用を検討してください。"
        )
        return {}


# ---------------------------------------------------------------------------
# HybridMarketDataService
# ---------------------------------------------------------------------------

class HybridMarketDataService(MarketDataService):
    """Loris（funding rate）と CCXT（OI・板情報）を組み合わせたハイブリッドサービス。

    Loris API から高速に全取引所の funding rate を一括取得しつつ、
    OI と板情報は CCXT アダプタから補完する。

    Parameters
    ----------
    loris_client : LorisAPIClient
        Loris API クライアント。
    ccxt_adapters : Dict[str, CCXTAdapter]
        CCXT アダプタのマップ（取引所名 → アダプタ）。
    canonical_sign_map : Optional[Dict[str, bool]]
        取引所ごとの funding rate 符号正規化フラグ。
        Loris は既に正規化済みのためデフォルト True。
    """

    def __init__(
        self,
        loris_client: LorisAPIClient,
        ccxt_adapters: Dict[str, CCXTAdapter],
        canonical_sign_map: Optional[Dict[str, bool]] = None,
        config: Optional["FundingArbConfig"] = None,
    ) -> None:
        self._loris = loris_client
        self._ccxt_adapters = ccxt_adapters
        self._canonical_sign_map = canonical_sign_map or {}
        self._universe_provider: Optional[DynamicUniverseProvider] = None
        if config is not None:
            target_exchanges = list(ccxt_adapters.keys()) if ccxt_adapters else None
            self._universe_provider = DynamicUniverseProvider(
                config,
                loris_client,
                target_exchanges=target_exchanges,
            )

    def get_top_symbols_by_criteria(
        self,
        universe_size: int,
        min_fr_diff: Optional[float] = None,
    ) -> List[str]:
        """Loris APIからFR差に基づく上位N銘柄を動的に選定する。

        OIランキング上位N銘柄の選定、funding rate差の大きいペアの
        優先選定、universe_size設定に基づくフィルタリングを行う。

        Parameters
        ----------
        universe_size : int
            選定する銘柄数の上限。
        min_fr_diff : Optional[float]
            最小funding rate差フィルタ。

        Returns
        -------
        List[str]
            選定された銘柄シンボルのリスト（CCXT形式）。
        """
        if self._universe_provider is None:
            logger.warning(
                "DynamicUniverseProvider未初期化。config引数なしで構築された場合、"
                "get_top_symbols_by_criteriaは空リストを返します。"
            )
            return []

        snapshot = self._universe_provider.select_universe()
        loris_symbols = snapshot.symbols[:universe_size]

        # FR差でさらにフィルタ
        # ただし、同一取引所内ペアリングモードの場合はスキップ
        if min_fr_diff is not None and not self._universe_provider._config.allow_single_exchange_pairs:
            qualified = set()
            for ex_a, ex_b, diff in snapshot.pair_candidates:
                if diff >= min_fr_diff:
                    sym = ex_a.split(":", 1)[1]
                    qualified.add(sym)
            loris_symbols = [s for s in loris_symbols if s in qualified]

        return [_loris_to_ccxt_symbol(s) for s in loris_symbols]

    def get_funding_snapshots(
        self,
        exchanges: Iterable[str],
        symbols: Iterable[str],
    ) -> List[FundingSnapshot]:
        """Loris から funding rate、CCXT から OI・板情報を取得して統合する。

        Parameters
        ----------
        exchanges : Iterable[str]
            対象取引所名のリスト（funding_arb 内部表記）。
        symbols : Iterable[str]
            対象シンボル（CCXT形式）。

        Returns
        -------
        List[FundingSnapshot]
            統合済みスナップショットのリスト。
        """
        exchange_set = set(exchanges)
        symbol_list = list(symbols)
        loris_symbols = [_ccxt_to_loris_symbol(s) for s in symbol_list]

        # Loris から funding rate を一括取得
        response = self._loris.fetch()
        now = datetime.utcnow()

        # Loris のレートを (exchange, symbol) でインデックス化
        rate_index: Dict[tuple, LorisFundingRate] = {}
        for fr in response.funding_rates:
            internal_ex = _loris_to_internal_exchange(fr.exchange)
            if internal_ex in exchange_set and fr.symbol in loris_symbols:
                ccxt_sym = _loris_to_ccxt_symbol(fr.symbol)
                rate_index[(internal_ex, ccxt_sym)] = fr

        # Hyperliquid adapterがあれば価格を一括取得
        for exchange in exchange_set:
            adapter = self._ccxt_adapters.get(exchange)
            if adapter and hasattr(adapter, 'refresh_prices'):
                adapter.refresh_prices()

        snapshots: List[FundingSnapshot] = []
        for exchange in exchange_set:
            adapter = self._ccxt_adapters.get(exchange)
            for symbol in symbol_list:
                loris_rate = rate_index.get((exchange, symbol))
                if loris_rate is None:
                    continue

                funding_rate = loris_rate.rate

                # CCXT から OI と板情報を補完
                oi_value = 0.0
                mark_price = 0.0
                bid: Optional[float] = None
                ask: Optional[float] = None

                if adapter is not None:
                    try:
                        oi = adapter.fetch_open_interest(symbol)
                        oi_value = float(oi.get("openInterestValue", 0.0) or 0.0)
                    except Exception:
                        logger.warning(
                            "CCXT OI取得失敗: %s %s", exchange, symbol,
                            exc_info=True,
                        )

                    try:
                        ob = adapter.fetch_order_book(symbol, limit=5)
                        bids = ob.get("bids", [])
                        asks = ob.get("asks", [])
                        bid = float(bids[0][0]) if bids else None
                        ask = float(asks[0][0]) if asks else None
                        if bid and ask:
                            mark_price = (bid + ask) / 2
                    except Exception:
                        logger.warning(
                            "CCXT 板情報取得失敗: %s %s", exchange, symbol,
                            exc_info=True,
                        )

                snapshots.append(
                    FundingSnapshot(
                        exchange=exchange,
                        symbol=symbol,
                        timestamp=now,
                        funding_rate=funding_rate,
                        next_funding_time=None,
                        oi=oi_value,
                        mark_price=mark_price,
                        bid=bid,
                        ask=ask,
                    )
                )

        logger.info(
            "Hybrid: %d スナップショット取得（Loris FR + CCXT OI/板情報）",
            len(snapshots),
        )
        return snapshots

    def get_orderbook_tops(
        self,
        exchange: str,
        symbols: Iterable[str],
    ) -> Dict[str, Dict[str, float]]:
        """CCXT アダプタから板情報を取得する。"""
        adapter = self._ccxt_adapters.get(exchange)
        if adapter is None:
            logger.warning("CCXT アダプタが見つかりません: %s", exchange)
            return {}

        out: Dict[str, Dict[str, float]] = {}
        for symbol in symbols:
            try:
                ob = adapter.fetch_order_book(symbol, limit=5)
                bids = ob.get("bids", [])
                asks = ob.get("asks", [])
                out[symbol] = {
                    "bid": float(bids[0][0]) if bids else 0.0,
                    "ask": float(asks[0][0]) if asks else 0.0,
                }
            except Exception:
                logger.warning(
                    "板情報取得失敗: %s %s", exchange, symbol,
                    exc_info=True,
                )
                out[symbol] = {"bid": 0.0, "ask": 0.0}
        return out
