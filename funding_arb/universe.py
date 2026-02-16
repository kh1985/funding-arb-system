"""動的銘柄選定（ユニバース管理）モジュール。

Loris APIから取得したファンディングレート情報をもとに、
取引対象銘柄を動的に選定する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Set, Tuple

from .config import FundingArbConfig
from .loris_client import LorisAPIClient, LorisFundingRate, LorisResponse

logger = logging.getLogger(__name__)


@dataclass
class SymbolScore:
    """銘柄ごとのスコアリング結果。"""
    symbol: str
    max_fr_spread: float  # 取引所間のfunding rate最大差（絶対値）
    exchange_count: int   # この銘柄を扱う取引所数
    avg_abs_rate: float   # 平均絶対funding rate


@dataclass
class UniverseSnapshot:
    """動的ユニバースの選定結果。"""
    symbols: List[str]
    scores: Dict[str, SymbolScore]
    pair_candidates: List[Tuple[str, str, float]]  # (exchange_a, exchange_b, fr_diff)


class DynamicUniverseProvider:
    """Loris APIを使った動的銘柄選定。

    OIランキング上位N銘柄の選定、funding rate差の大きいペア候補の抽出、
    config.universe_sizeに基づくフィルタリングを行う。

    Parameters
    ----------
    config : FundingArbConfig
        アービトラージ設定。universe_size を使用。
    loris_client : LorisAPIClient
        Loris APIクライアント。
    target_exchanges : Optional[List[str]]
        対象とする取引所名のリスト。None の場合は全取引所を対象。
    """

    def __init__(
        self,
        config: FundingArbConfig,
        loris_client: LorisAPIClient,
        target_exchanges: Optional[List[str]] = None,
    ) -> None:
        self._config = config
        self._loris = loris_client
        self._target_exchanges: Optional[Set[str]] = (
            set(target_exchanges) if target_exchanges else None
        )

    def select_universe(self, force_refresh: bool = False) -> UniverseSnapshot:
        """動的ユニバースを選定する。

        1. Loris APIからfunding rateを取得
        2. 取引所間のfunding rate差でシンボルをスコアリング
        3. 上位 universe_size 銘柄を選定

        Parameters
        ----------
        force_refresh : bool
            キャッシュを無視して再取得するか。

        Returns
        -------
        UniverseSnapshot
            選定結果。
        """
        response = self._loris.fetch(force=force_refresh)
        rates = self._filter_rates(response)

        # シンボルごとに取引所別レートをグループ化
        rates_by_symbol = self._group_by_symbol(rates)

        # スコアリング
        scores = self._score_symbols(rates_by_symbol)

        # universe_size でフィルタリング
        # 同一取引所モードでは正と負をバランスよく選定
        if self._config.allow_single_exchange_pairs:
            # FR値で分類（正/負）して、それぞれから選定
            response = self._loris.fetch()
            rates_map = {}
            for fr in response.funding_rates:
                if self._target_exchanges and fr.exchange not in self._target_exchanges:
                    continue
                rates_map[fr.symbol] = fr.rate

            # 正と負に分類
            positive_scores = []
            negative_scores = []
            for score in scores.values():
                rate = rates_map.get(score.symbol, 0)
                if rate >= 0:
                    positive_scores.append(score)
                else:
                    negative_scores.append(score)

            # 正：大きい順、負：小さい順（絶対値が大きい順）
            positive_scores.sort(key=lambda s: rates_map.get(s.symbol, 0), reverse=True)
            negative_scores.sort(key=lambda s: rates_map.get(s.symbol, 0))

            # 半々で選定（正の方が少なければ全部、残りは負から）
            half = self._config.universe_size // 2
            selected = positive_scores[:half] + negative_scores[:self._config.universe_size - len(positive_scores[:half])]
            selected_symbols = [s.symbol for s in selected]
        else:
            sorted_scores = sorted(
                scores.values(),
                key=lambda s: (s.max_fr_spread, s.exchange_count),
                reverse=True,
            )
            selected = sorted_scores[: self._config.universe_size]
            selected_symbols = [s.symbol for s in selected]

        # 選定銘柄のペア候補を抽出
        selected_set = set(selected_symbols)
        pair_candidates = self._extract_pair_candidates(rates_by_symbol, selected_set)

        logger.info(
            "ユニバース選定完了: %d銘柄 (全%d銘柄からフィルタ)",
            len(selected_symbols),
            len(scores),
        )

        return UniverseSnapshot(
            symbols=selected_symbols,
            scores={s.symbol: s for s in selected},
            pair_candidates=pair_candidates,
        )

    def _filter_rates(self, response: LorisResponse) -> List[LorisFundingRate]:
        """対象取引所のレートのみ抽出する。"""
        if self._target_exchanges is None:
            return response.funding_rates
        return [
            fr for fr in response.funding_rates
            if fr.exchange in self._target_exchanges
        ]

    @staticmethod
    def _group_by_symbol(
        rates: List[LorisFundingRate],
    ) -> Dict[str, List[LorisFundingRate]]:
        """シンボルごとにレートをグループ化する。"""
        grouped: Dict[str, List[LorisFundingRate]] = {}
        for fr in rates:
            grouped.setdefault(fr.symbol, []).append(fr)
        return grouped

    def _score_symbols(
        self,
        rates_by_symbol: Dict[str, List[LorisFundingRate]],
    ) -> Dict[str, SymbolScore]:
        """各シンボルのスコアを計算する。

        スコア基準:
        - max_fr_spread: 取引所間のfunding rate最大差（アービトラージ機会の大きさ）
        - exchange_count: 取引所カバレッジ（多いほど流動性が高い傾向）
        - avg_abs_rate: 平均絶対レート（funding収益の指標）
        """
        scores: Dict[str, SymbolScore] = {}
        # 同一取引所内ペアリングを許可する場合は1、クロス取引所の場合は2
        min_exchanges = 1 if self._config.allow_single_exchange_pairs else 2

        for symbol, rates in rates_by_symbol.items():
            if len(rates) < min_exchanges:
                continue

            # 取引所間のfunding rate最大差を計算
            max_spread = 0.0
            for a, b in combinations(rates, 2):
                spread = abs(a.rate - b.rate)
                if spread > max_spread:
                    max_spread = spread

            avg_abs = sum(abs(fr.rate) for fr in rates) / len(rates)

            scores[symbol] = SymbolScore(
                symbol=symbol,
                max_fr_spread=max_spread,
                exchange_count=len(rates),
                avg_abs_rate=avg_abs,
            )

        return scores

    @staticmethod
    def _extract_pair_candidates(
        rates_by_symbol: Dict[str, List[LorisFundingRate]],
        selected_symbols: Set[str],
    ) -> List[Tuple[str, str, float]]:
        """選定銘柄から、取引所ペア候補（FR差が大きい）を抽出する。

        同じシンボルの異なる取引所間でfunding rateの差が大きいペアを返す。
        符号が異なるペアを優先する（long/shortアービトラージ機会）。

        Returns
        -------
        List[Tuple[str, str, float]]
            (exchange_a:symbol, exchange_b:symbol, fr_diff) のリスト。
            fr_diff降順でソート済み。
        """
        candidates: List[Tuple[str, str, float]] = []

        for symbol, rates in rates_by_symbol.items():
            if symbol not in selected_symbols:
                continue
            for a, b in combinations(rates, 2):
                fr_diff = abs(a.rate - b.rate)
                candidates.append(
                    (f"{a.exchange}:{a.symbol}", f"{b.exchange}:{b.symbol}", fr_diff)
                )

        # FR差降順でソート
        candidates.sort(key=lambda x: x[2], reverse=True)
        return candidates

    def get_symbols_for_cycle(self, force_refresh: bool = False) -> List[str]:
        """オーケストレータ向けの簡易メソッド。

        選定されたシンボルリストのみを返す。
        既存の config.symbols の代替として使用する。

        Parameters
        ----------
        force_refresh : bool
            キャッシュを無視して再取得するか。

        Returns
        -------
        List[str]
            選定された銘柄シンボルのリスト。
        """
        snapshot = self.select_universe(force_refresh=force_refresh)
        return snapshot.symbols

    def get_exchange_symbol_pairs(
        self,
        force_refresh: bool = False,
        min_fr_diff: Optional[float] = None,
    ) -> List[Tuple[str, str, str]]:
        """取引所-シンボルペアのリストを返す。

        Parameters
        ----------
        force_refresh : bool
            キャッシュを無視するか。
        min_fr_diff : Optional[float]
            最小FR差フィルタ。None の場合は config.fr_diff_min を使用。

        Returns
        -------
        List[Tuple[str, str, str]]
            (exchange, symbol, exchange) のトリプレット。
        """
        threshold = min_fr_diff if min_fr_diff is not None else self._config.fr_diff_min
        snapshot = self.select_universe(force_refresh=force_refresh)
        result: List[Tuple[str, str, str]] = []
        for ex_a, ex_b, diff in snapshot.pair_candidates:
            if diff >= threshold:
                # "exchange:symbol" 形式をパース
                ea, sa = ex_a.split(":", 1)
                eb, _sb = ex_b.split(":", 1)
                result.append((ea, sa, eb))
        return result
