"""ペア特徴量の推定

カテゴリーベースのヒューリスティックにより、以下を推定：
- correlation: 価格変動の相関係数
- beta: ベータ値（銘柄Bの銘柄Aに対する価格変動比率）
- beta_stability: ベータの安定性
- atr_ratio_stability: ATR比率の安定性
- mean_reversion_score: 平均回帰スコア
"""

from typing import Dict, List, Optional, Tuple
from .types import PairFeatures


# 銘柄カテゴリー定義
SYMBOL_CATEGORIES = {
    "BTC": ["BTC", "WBTC"],
    "ETH": ["ETH", "WETH", "STETH", "RETH"],
    "SOL": ["SOL", "MSOL", "JSOL"],
    "LAYER1": ["AVAX", "FTM", "ATOM", "NEAR", "DOT", "ADA"],  # MATICを削除
    "LAYER2": ["ARB", "OP", "MATIC", "METIS"],  # MATICはLAYER2に統一
    "MAJOR_ALT": ["XRP", "LTC", "BCH", "LINK", "UNI"],  # 主要アルト追加
    "NEW_L1": ["SUI", "APT", "SEI", "TIA"],  # 新興L1追加
    "DEFI": ["AAVE", "MKR", "CRV", "SNX", "COMP"],
    "DEPIN_INFRA": ["FIL", "INJ", "AR", "HNT"],  # DePIN/インフラ追加
    "MEME": ["DOGE", "SHIB", "PEPE", "WIF", "BONK", "FLOKI"],
    "AI": ["FET", "AGIX", "RNDR", "TAO"],
    "GAMING": ["AXS", "SAND", "MANA", "IMX", "GALA"],
    "STABLE": ["USDT", "USDC", "DAI", "BUSD", "TUSD", "STBL"],
}

# 関連カテゴリー（中程度の相関が期待できる）
RELATED_CATEGORIES = {
    "BTC": ["LAYER1", "MAJOR_ALT"],
    "ETH": ["LAYER2", "DEFI"],
    "SOL": ["NEW_L1"],
    "LAYER1": ["BTC", "LAYER2", "NEW_L1"],
    "LAYER2": ["ETH", "LAYER1"],
    "MAJOR_ALT": ["BTC", "LAYER1"],
    "NEW_L1": ["SOL", "LAYER1"],
    "DEFI": ["ETH"],
    "DEPIN_INFRA": ["LAYER1"],
}

# ボラティリティ特性（高/中/低）
VOLATILITY_PROFILE = {
    "BTC": "low",
    "ETH": "low",
    "SOL": "medium",
    "LAYER1": "medium",
    "LAYER2": "medium",
    "MAJOR_ALT": "medium",
    "NEW_L1": "high",
    "DEFI": "medium",
    "DEPIN_INFRA": "medium",
    "MEME": "high",
    "AI": "high",
    "GAMING": "high",
    "STABLE": "very_low",
}


class PairFeaturesEstimator:
    """ペア特徴量の推定エンジン"""

    def __init__(self):
        # 逆引き辞書を構築
        self._symbol_to_category: Dict[str, str] = {}
        for category, symbols in SYMBOL_CATEGORIES.items():
            for symbol in symbols:
                self._symbol_to_category[symbol.upper()] = category

    def _normalize_symbol(self, symbol: str) -> str:
        """シンボルを正規化（例: BTC/USDT:USDT → BTC）"""
        # スラッシュ、コロン、ハイフンで分割して最初の部分を取得
        normalized = symbol.split("/")[0].split(":")[0].split("-")[0].upper()
        return normalized

    def _get_category(self, symbol: str) -> Optional[str]:
        """銘柄のカテゴリーを取得"""
        normalized = self._normalize_symbol(symbol)
        return self._symbol_to_category.get(normalized)

    def _estimate_correlation(self, symbol_a: str, symbol_b: str) -> float:
        """相関係数を推定

        Returns:
            0.0-1.0の相関係数
        """
        cat_a = self._get_category(symbol_a)
        cat_b = self._get_category(symbol_b)

        # 同一カテゴリー: 高相関
        if cat_a == cat_b and cat_a is not None:
            return 0.85

        # 関連カテゴリー: 中相関
        if cat_a and cat_b:
            if cat_b in RELATED_CATEGORIES.get(cat_a, []):
                return 0.60
            if cat_a in RELATED_CATEGORIES.get(cat_b, []):
                return 0.60

        # ステーブルコインは他と相関が極めて低い
        if cat_a == "STABLE" or cat_b == "STABLE":
            return 0.05

        # その他: 低相関（デフォルト）
        return 0.35

    def _estimate_beta(self, symbol_a: str, symbol_b: str, correlation: float) -> float:
        """ベータ値を推定

        beta = (σ_b / σ_a) * ρ
        ここでは簡易的にボラティリティプロファイルから推定

        Returns:
            ベータ値（通常0.5-2.0程度）
        """
        cat_a = self._get_category(symbol_a)
        cat_b = self._get_category(symbol_b)

        vol_a = VOLATILITY_PROFILE.get(cat_a, "medium")
        vol_b = VOLATILITY_PROFILE.get(cat_b, "medium")

        # ボラティリティの比率を推定
        vol_ratios = {
            "very_low": 0.2,
            "low": 0.5,
            "medium": 1.0,
            "high": 2.0,
        }

        sigma_a = vol_ratios.get(vol_a, 1.0)
        sigma_b = vol_ratios.get(vol_b, 1.0)

        # beta = (σ_b / σ_a) * ρ
        beta = (sigma_b / sigma_a) * correlation

        # 現実的な範囲に制限
        return max(0.1, min(3.0, beta))

    def _estimate_beta_stability(self, symbol_a: str, symbol_b: str, correlation: float) -> float:
        """ベータ安定性を推定

        Returns:
            0.0-1.0のスコア（1.0が最も安定）
        """
        cat_a = self._get_category(symbol_a)
        cat_b = self._get_category(symbol_b)

        # 同じカテゴリー: 高安定性
        if cat_a == cat_b and cat_a is not None:
            return 0.80

        # 関連カテゴリー: 中安定性
        if cat_a and cat_b:
            if cat_b in RELATED_CATEGORIES.get(cat_a, []) or cat_a in RELATED_CATEGORIES.get(cat_b, []):
                return 0.60

        # ステーブルコイン関連: 不安定
        if cat_a == "STABLE" or cat_b == "STABLE":
            return 0.20

        # その他: 相関に基づいて推定
        return max(0.3, correlation * 0.8)

    def _estimate_atr_ratio_stability(
        self, symbol_a: str, symbol_b: str, correlation: float
    ) -> float:
        """ATR比率安定性を推定

        Returns:
            0.0-1.0のスコア（1.0が最も安定）
        """
        cat_a = self._get_category(symbol_a)
        cat_b = self._get_category(symbol_b)

        vol_a = VOLATILITY_PROFILE.get(cat_a, "medium")
        vol_b = VOLATILITY_PROFILE.get(cat_b, "medium")

        # 同じボラティリティプロファイル: 高安定性
        if vol_a == vol_b:
            return 0.85

        # 隣接するボラティリティレベル: 中安定性
        vol_order = ["very_low", "low", "medium", "high"]
        try:
            idx_a = vol_order.index(vol_a)
            idx_b = vol_order.index(vol_b)
            diff = abs(idx_a - idx_b)

            if diff == 1:
                return 0.60
            elif diff == 2:
                return 0.40
            else:
                return 0.20
        except ValueError:
            return 0.50

    def _estimate_mean_reversion_score(
        self, symbol_a: str, symbol_b: str, correlation: float
    ) -> float:
        """平均回帰スコアを推定

        高相関ペアほど、価格差が平均に戻りやすい

        Returns:
            0.0-1.0のスコア（1.0が最も強い平均回帰）
        """
        cat_a = self._get_category(symbol_a)
        cat_b = self._get_category(symbol_b)

        # 同じカテゴリー: 強い平均回帰
        if cat_a == cat_b and cat_a is not None:
            # ボラティリティが低いほど平均回帰が強い
            vol = VOLATILITY_PROFILE.get(cat_a, "medium")
            if vol == "very_low":
                return 0.90
            elif vol == "low":
                return 0.75
            elif vol == "medium":
                return 0.65
            else:
                return 0.50

        # 相関ベース
        if correlation > 0.7:
            return 0.70
        elif correlation > 0.5:
            return 0.55
        else:
            return max(0.30, correlation * 0.8)

    def estimate_features(self, symbol_a: str, symbol_b: str) -> PairFeatures:
        """ペアの全特徴量を推定

        Args:
            symbol_a: 銘柄A（例: "BTC/USDT:USDT"）
            symbol_b: 銘柄B（例: "ETH/USDT:USDT"）

        Returns:
            推定されたPairFeatures
        """
        correlation = self._estimate_correlation(symbol_a, symbol_b)
        beta = self._estimate_beta(symbol_a, symbol_b, correlation)
        beta_stability = self._estimate_beta_stability(symbol_a, symbol_b, correlation)
        atr_ratio_stability = self._estimate_atr_ratio_stability(symbol_a, symbol_b, correlation)
        mean_reversion_score = self._estimate_mean_reversion_score(symbol_a, symbol_b, correlation)

        return PairFeatures(
            correlation=correlation,
            beta=beta,
            beta_stability=beta_stability,
            atr_ratio_stability=atr_ratio_stability,
            mean_reversion_score=mean_reversion_score,
        )


# グローバルインスタンス
_estimator = PairFeaturesEstimator()


def estimate_pair_features(symbol_a: str, symbol_b: str) -> PairFeatures:
    """ペア特徴量を推定（便利関数）

    Args:
        symbol_a: 銘柄A
        symbol_b: 銘柄B

    Returns:
        推定されたPairFeatures
    """
    return _estimator.estimate_features(symbol_a, symbol_b)
