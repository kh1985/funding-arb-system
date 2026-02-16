"""Loris Funding API クライアント。

https://api.loris.tools/funding からファンディングレートを取得し、
正規化されたデータを返す。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# 1時間周期（interval=1）の取引所。レートをさらに8で割って8h相当に正規化する。
HOURLY_EXCHANGES = frozenset({"extended", "hyperliquid", "lighter", "vest"})

LORIS_FUNDING_URL = "https://api.loris.tools/funding"

# レスポンスのファンディングレート値を実際のレートに変換する除数。
# 例: 25 → 25 / 10_000 = 0.0025 (0.25%)
RATE_DIVISOR = 10_000

# 1時間周期取引所を8時間相当に正規化する除数。
HOURLY_TO_8H_DIVISOR = 8


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LorisSymbol:
    """APIが返すシンボル情報。"""
    name: str


@dataclass(frozen=True)
class LorisExchange:
    """APIが返す取引所情報。"""
    name: str
    display: str
    interval: int


@dataclass(frozen=True)
class LorisFundingRate:
    """正規化済みファンディングレート。"""
    exchange: str
    symbol: str
    raw_value: float
    rate: float  # 正規化済み（8h相当）


@dataclass
class LorisResponse:
    """Loris Funding API のパース済みレスポンス全体。"""
    symbols: List[LorisSymbol]
    exchanges: List[LorisExchange]
    funding_rates: List[LorisFundingRate]
    fetched_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# クライアント
# ---------------------------------------------------------------------------

class LorisAPIClient:
    """Loris Funding API クライアント。

    60秒キャッシュ付きでファンディングレートを取得する。

    Parameters
    ----------
    url : str
        APIエンドポイント。デフォルトは公式URL。
    timeout : float
        HTTPリクエストのタイムアウト秒数。
    max_retries : int
        リクエスト失敗時の最大リトライ回数。
    retry_delay : float
        リトライ間の待機秒数。
    cache_ttl : float
        キャッシュの有効秒数。
    session : Optional[requests.Session]
        テスト用にセッションを差し替え可能。
    """

    def __init__(
        self,
        url: str = LORIS_FUNDING_URL,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        cache_ttl: float = 60.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._cache_ttl = cache_ttl
        self._session = session or requests.Session()
        self._cache: Optional[LorisResponse] = None

    # ------------------------------------------------------------------
    # パブリックAPI
    # ------------------------------------------------------------------

    def fetch(self, force: bool = False) -> LorisResponse:
        """ファンディングレートを取得して返す。

        Parameters
        ----------
        force : bool
            True の場合、キャッシュを無視して再取得する。

        Returns
        -------
        LorisResponse
            正規化済みのレスポンスデータ。

        Raises
        ------
        LorisAPIError
            全てのリトライが失敗した場合。
        """
        if not force and self._cache is not None:
            elapsed = time.time() - self._cache.fetched_at
            if elapsed < self._cache_ttl:
                logger.debug("キャッシュヒット (%.1f秒前)", elapsed)
                return self._cache

        raw = self._request_with_retry()
        response = self._parse(raw)
        self._cache = response
        return response

    def get_rate(
        self,
        exchange: str,
        symbol: str,
        force: bool = False,
    ) -> Optional[LorisFundingRate]:
        """特定の取引所・シンボルのレートを取得する。

        Parameters
        ----------
        exchange : str
            取引所名（小文字）。
        symbol : str
            シンボル名（大文字）。
        force : bool
            キャッシュを無視するか。

        Returns
        -------
        Optional[LorisFundingRate]
            見つかった場合はレート、なければ None。
        """
        resp = self.fetch(force=force)
        for fr in resp.funding_rates:
            if fr.exchange == exchange and fr.symbol == symbol:
                return fr
        return None

    def get_rates_by_symbols(
        self,
        symbols: List[str],
        force: bool = False,
    ) -> List[LorisFundingRate]:
        """指定シンボル群に関する全取引所のレートを返す。

        Parameters
        ----------
        symbols : List[str]
            フィルタするシンボル名のリスト（大文字）。
        force : bool
            キャッシュを無視するか。

        Returns
        -------
        List[LorisFundingRate]
            マッチしたレートのリスト。
        """
        symbol_set = frozenset(symbols)
        resp = self.fetch(force=force)
        return [fr for fr in resp.funding_rates if fr.symbol in symbol_set]

    def invalidate_cache(self) -> None:
        """キャッシュを明示的にクリアする。"""
        self._cache = None

    # ------------------------------------------------------------------
    # 内部メソッド
    # ------------------------------------------------------------------

    def _request_with_retry(self) -> Dict[str, Any]:
        """リトライ付きHTTPリクエスト。"""
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._session.get(self._url, timeout=self._timeout)
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                logger.warning(
                    "Loris API リクエスト失敗 (試行 %d/%d): %s",
                    attempt,
                    self._max_retries,
                    exc,
                )
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay)

        raise LorisAPIError(
            f"全{self._max_retries}回のリトライが失敗しました"
        ) from last_exc

    def _parse(self, raw: Dict[str, Any]) -> LorisResponse:
        """生JSONレスポンスを LorisResponse にパースする。"""
        # シンボル
        raw_symbols = raw.get("symbols", [])
        symbols = [LorisSymbol(name=s) for s in raw_symbols]

        # 取引所
        raw_exchange_names = raw.get("exchanges", {}).get("exchange_names", [])
        exchange_map: Dict[str, LorisExchange] = {}
        exchanges: List[LorisExchange] = []
        for ex in raw_exchange_names:
            le = LorisExchange(
                name=ex.get("name", ""),
                display=ex.get("display", ""),
                interval=int(ex.get("interval", 8)),
            )
            exchanges.append(le)
            exchange_map[le.name] = le

        # ファンディングレート
        raw_rates = raw.get("funding_rates", {})
        funding_rates: List[LorisFundingRate] = []
        for ex_name, symbol_rates in raw_rates.items():
            if not isinstance(symbol_rates, dict):
                continue
            is_hourly = ex_name in HOURLY_EXCHANGES
            for sym, raw_value in symbol_rates.items():
                try:
                    val = float(raw_value)
                except (TypeError, ValueError):
                    continue
                rate = val / RATE_DIVISOR
                if is_hourly:
                    rate = rate / HOURLY_TO_8H_DIVISOR
                funding_rates.append(
                    LorisFundingRate(
                        exchange=ex_name,
                        symbol=sym,
                        raw_value=val,
                        rate=rate,
                    )
                )

        return LorisResponse(
            symbols=symbols,
            exchanges=exchanges,
            funding_rates=funding_rates,
        )


# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------

class LorisAPIError(Exception):
    """Loris API に関するエラー。"""
