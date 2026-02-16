from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .config import FundingArbConfig
from .types import (
    FundingSnapshot,
    OrderSide,
    PairCandidate,
    PairFeatures,
    RiskState,
    RiskStatus,
    TradeIntent,
    TradeLeg,
)


@dataclass
class SizingContext:
    capital_usd: float


class SignalService:
    def __init__(self, config: FundingArbConfig):
        self.config = config
        self._persistence_windows: Dict[str, int] = {}

    @staticmethod
    def _key(a: FundingSnapshot, b: FundingSnapshot) -> str:
        left = f"{a.exchange}:{a.symbol}"
        right = f"{b.exchange}:{b.symbol}"
        return "|".join(sorted([left, right]))

    @staticmethod
    def _funding_receiver_side(funding_rate: float) -> OrderSide:
        # Canonical sign: FR > 0 => long pays short, so short receives.
        return OrderSide.SELL if funding_rate > 0 else OrderSide.BUY

    def _liquidity_score(self, a: FundingSnapshot, b: FundingSnapshot) -> float:
        oi_floor = self.config.min_open_interest_usd
        score_a = min(1.0, a.oi / oi_floor) if oi_floor > 0 else 1.0
        score_b = min(1.0, b.oi / oi_floor) if oi_floor > 0 else 1.0
        return min(score_a, score_b)

    def _pair_score(self, features: PairFeatures, liquidity_score: float) -> float:
        corr = max(0.0, min(1.0, features.correlation))
        beta_stability = max(0.0, min(1.0, features.beta_stability))
        atr_stability = max(0.0, min(1.0, features.atr_ratio_stability))
        mr_score = max(0.0, min(1.0, features.mean_reversion_score))
        score = (
            0.30 * corr
            + 0.25 * beta_stability
            + 0.20 * liquidity_score
            + 0.15 * atr_stability
            + 0.10 * mr_score
        )
        return round(score, 6)

    @staticmethod
    def _feature_key(a: FundingSnapshot, b: FundingSnapshot) -> Tuple[str, str]:
        pair = sorted([a.symbol, b.symbol])
        return pair[0], pair[1]

    def build_pair_candidates(
        self,
        snapshots: List[FundingSnapshot],
        market_features: Dict[Tuple[str, str], PairFeatures],
    ) -> List[PairCandidate]:
        candidates: List[PairCandidate] = []
        n = len(snapshots)
        for i in range(n):
            for j in range(i + 1, n):
                a = snapshots[i]
                b = snapshots[j]
                if a.symbol == b.symbol and a.exchange == b.exchange:
                    continue
                if a.funding_rate == 0 or b.funding_rate == 0:
                    continue
                if a.funding_rate * b.funding_rate >= 0:
                    continue

                key = self._key(a, b)
                self._persistence_windows[key] = self._persistence_windows.get(key, 0) + 1
                persistence = self._persistence_windows[key]

                liq = self._liquidity_score(a, b)
                if liq < self.config.min_liquidity_score:
                    continue

                feature_key = self._feature_key(a, b)
                feats = market_features.get(
                    feature_key,
                    PairFeatures(
                        correlation=0.5,
                        beta=1.0,
                        beta_stability=0.5,
                        atr_ratio_stability=0.5,
                        mean_reversion_score=0.5,
                    ),
                )
                pair_score = self._pair_score(feats, liq)
                fr_diff = abs(a.funding_rate - b.funding_rate)

                # Estimate edge in bps after coarse taker cost model.
                # funding_rate is assumed fraction per funding window.
                taker_cost_bps = 8.0
                expected_edge_bps = fr_diff * 10_000 - taker_cost_bps

                candidates.append(
                    PairCandidate(
                        pair_id=key,
                        symbol_a=a.symbol,
                        exchange_a=a.exchange,
                        symbol_b=b.symbol,
                        exchange_b=b.exchange,
                        fr_diff=fr_diff,
                        persistence=persistence,
                        liquidity_score=liq,
                        pair_score=pair_score,
                        beta=feats.beta,
                        expected_edge_bps=expected_edge_bps,
                        reason_codes=[
                            "FR_OPPOSITE_SIGN",
                            f"PERSIST_{persistence}",
                            f"SCORE_{pair_score:.3f}",
                        ],
                    )
                )

        valid_pair_ids = {c.pair_id for c in candidates}
        # Reset missing keys to avoid stale carry-over when sign flips away.
        stale = [k for k in self._persistence_windows if k not in valid_pair_ids]
        for k in stale:
            self._persistence_windows[k] = 0

        return candidates

    def select_entries(
        self,
        candidates: List[PairCandidate],
        snapshots_by_id: Dict[str, Tuple[FundingSnapshot, FundingSnapshot]],
        risk_state: RiskState,
        sizing: SizingContext,
    ) -> List[TradeIntent]:
        if risk_state.status == RiskStatus.HALT_NEW:
            return []

        leverage_cap = (
            self.config.normal_leverage_cap
            if risk_state.status == RiskStatus.REDUCE
            else self.config.max_leverage
        )

        filtered = [
            c
            for c in candidates
            if c.fr_diff >= self.config.fr_diff_min
            and c.persistence >= self.config.min_persistence_windows
            and c.pair_score >= self.config.min_pair_score
            and c.expected_edge_bps >= self.config.expected_edge_min_bps
        ]
        filtered.sort(key=lambda c: (c.expected_edge_bps, c.pair_score), reverse=True)

        intents: List[TradeIntent] = []
        for c in filtered[: self.config.max_new_positions_per_cycle]:
            s_a, s_b = snapshots_by_id[c.pair_id]
            # デルタニュートラルを実現するためのサイジング
            # ペア全体の基準想定元本（少額資金でも取引できるよう調整）
            base_notional = min(self.config.max_notional_per_pair_usd, max(20.0, sizing.capital_usd * 0.40))

            # betaをクランプ（極端な値を制限）
            beta_clamped = max(0.1, min(10.0, c.beta))

            # Hyperliquid最小注文額（余裕を持って$12に設定）
            MIN_ORDER_VALUE = 12.0

            # leg_aを基準として、leg_bをbetaで調整してデルタニュートラルを実現
            # beta = 1.0 の場合: notional_a ≈ notional_b
            # beta = 0.5 の場合: notional_b = 2 × notional_a （Bの変動が小さい→大きく）
            # beta = 2.0 の場合: notional_b = 0.5 × notional_a （Bの変動が大きい→小さく）
            notional_a = base_notional * 0.5  # 基準の半分から開始
            notional_b = notional_a / beta_clamped  # betaで調整

            # 数量計算
            qty_a = notional_a / max(s_a.mark_price, 1e-9)
            qty_b = notional_b / max(s_b.mark_price, 1e-9)

            # 実際の注文額を計算
            actual_value_a = qty_a * s_a.mark_price
            actual_value_b = qty_b * s_b.mark_price

            # どちらか一方でも$10未満の場合、betaの関係を保ちながらスケールアップ
            min_value = min(actual_value_a, actual_value_b)
            if min_value < MIN_ORDER_VALUE:
                # スケールファクターを計算（余裕を持って10%増し）
                scale_factor = (MIN_ORDER_VALUE * 1.1) / min_value
                qty_a *= scale_factor
                qty_b *= scale_factor

            # 最終的な想定元本を計算してログ出力
            final_value_a = qty_a * s_a.mark_price
            final_value_b = qty_b * s_b.mark_price
            total_notional = final_value_a + final_value_b
            print(f"[SIZING] {s_a.symbol}/{s_b.symbol}: leg_a=${final_value_a:.2f}, leg_b=${final_value_b:.2f}, total=${total_notional:.2f}, max={self.config.max_total_notional_usd}", flush=True)

            leg_a = TradeLeg(
                exchange=s_a.exchange,
                symbol=s_a.symbol,
                side=self._funding_receiver_side(s_a.funding_rate),
                qty=qty_a,
            )
            leg_b = TradeLeg(
                exchange=s_b.exchange,
                symbol=s_b.symbol,
                side=self._funding_receiver_side(s_b.funding_rate),
                qty=qty_b,
            )
            intents.append(
                TradeIntent(
                    pair_id=c.pair_id,
                    leg_a=leg_a,
                    leg_b=leg_b,
                    leverage=leverage_cap,
                    reason_codes=c.reason_codes + [f"EDGE_{c.expected_edge_bps:.1f}bps"],
                )
            )
        return intents
