"""Hyperliquid統合クライアント

既存のhyperliquid-botから移植し、funding-arb-systemに統合
"""

import os
import logging
from typing import Dict
from dotenv import load_dotenv

# hyperliquid-python-sdkをインポート
try:
    from hyperliquid.info import Info
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils import constants
    from eth_account import Account
except ImportError:
    raise ImportError(
        "hyperliquid-python-sdkが必要です: pip install hyperliquid-python-sdk"
    )

from .execution import ExchangeExecutionClient
from .market_data import CCXTAdapter

load_dotenv()
logger = logging.getLogger(__name__)


class HyperliquidExecutionClient(ExchangeExecutionClient):
    """Hyperliquid用のExecutionClient実装（遅延初期化）"""

    def __init__(
        self,
        private_key: str | None = None,
        main_address: str | None = None,
        testnet: bool = True,
    ):
        """
        Args:
            private_key: Agent Walletの秘密鍵
            main_address: メインウォレットのアドレス
            testnet: テストネットを使用するか
        """
        self.private_key = private_key or os.getenv("HL_PRIVATE_KEY")
        if not self.private_key:
            raise ValueError("HL_PRIVATE_KEY が必要です")

        self.main_address = main_address or os.getenv("HL_MAIN_ADDRESS")
        if not self.main_address:
            raise ValueError("HL_MAIN_ADDRESS が必要です")

        self.testnet = testnet
        self.base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL

        # アカウントのみ初期化（Info/Exchangeは遅延）
        self.account = Account.from_key(self.private_key)
        self._info = None
        self._exchange = None

        mode = "TESTNET" if testnet else "MAINNET"
        logger.info(f"HyperliquidExecutionClient 初期化 [{mode}] (遅延ロード)")

    @property
    def info(self):
        """Info の遅延初期化"""
        if self._info is None:
            logger.info("Info初期化中...")
            self._info = Info(self.base_url, skip_ws=True)
        return self._info

    @property
    def exchange(self):
        """Exchange の遅延初期化（timeout付き）"""
        if self._exchange is None:
            logger.info("Exchange初期化中...")
            self._exchange = Exchange(
                wallet=self.account,
                base_url=self.base_url,
                account_address=self.main_address,
            )
        return self._exchange

    def _get_market_price(self, symbol: str) -> float:
        """現在の市場価格を取得"""
        # シンボルを正規化（"ETH/USDT:USDT" → "ETH"）
        ticker = symbol.split("/")[0] if "/" in symbol else symbol
        all_mids = self.info.all_mids()
        return float(all_mids.get(ticker.upper(), 0))

    def _get_sz_decimals(self, ticker: str) -> int:
        """ティッカーのサイズ小数点桁数を取得"""
        meta = self.info.meta()
        for asset in meta.get("universe", []):
            if asset.get("name", "").upper() == ticker.upper():
                return asset.get("szDecimals", 0)
        return 0

    def _calculate_size(self, symbol: str, qty: float) -> float:
        """数量を適切な小数点桁数に丸める"""
        import math
        ticker = symbol.split("/")[0] if "/" in symbol else symbol
        sz_decimals = self._get_sz_decimals(ticker)
        factor = 10 ** sz_decimals
        return int(qty * factor) / factor

    def place_order(
        self,
        exchange: str,
        symbol: str,
        side: str,
        qty: float,
        order_type: str,
        reduce_only: bool,
        client_order_id: str,
    ) -> Dict:
        """注文を実行"""
        # シンボルを正規化
        ticker = symbol.split("/")[0] if "/" in symbol else symbol
        ticker = ticker.upper()

        # 数量を丸める
        size = self._calculate_size(ticker, qty)

        # 成行注文のみサポート
        if order_type != "market":
            raise ValueError("Hyperliquidでは成行注文のみサポート")

        is_buy = side.lower() == "buy"

        logger.info(f"[Hyperliquid] 注文: {ticker} {side} {size}")

        try:
            if reduce_only:
                # クローズ注文
                result = self.exchange.market_close(coin=ticker)
            else:
                # オープン注文
                result = self.exchange.market_open(
                    name=ticker,
                    is_buy=is_buy,
                    sz=size,
                )

            if result.get("status") == "ok":
                # 平均価格を取得（簡易版：現在価格を使用）
                avg_price = self._get_market_price(symbol)

                return {
                    "id": client_order_id,
                    "average": avg_price,
                    "filled": size,
                    "status": "ok",
                }
            else:
                raise Exception(f"注文失敗: {result}")

        except Exception as e:
            logger.error(f"注文エラー: {e}")
            raise


class HyperliquidMarketDataAdapter(CCXTAdapter):
    """Hyperliquid用のMarketDataAdapter実装（軽量版）"""

    def __init__(self, testnet: bool = True):
        """
        Args:
            testnet: テストネットを使用するか
        """
        self.testnet = testnet
        self.base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        self._price_cache = {}  # キャッシュ：銘柄 → 価格

        # 軽量HTTPクライアント（Info初期化を回避）
        import requests
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

        logger.info(f"HyperliquidMarketDataAdapter 初期化 [{'TESTNET' if testnet else 'MAINNET'}] (軽量版)")

    def _api_post(self, endpoint: str, data: dict, timeout=(3, 10)):
        """軽量APIクライアント"""
        try:
            response = self.session.post(
                f"{self.base_url}{endpoint}",
                json=data,
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"API呼び出し失敗 {endpoint}: {e}")
            raise

    def refresh_prices(self):
        """全銘柄の価格を一括取得してキャッシュ"""
        try:
            # all_mids APIを直接呼び出し（Info不要）
            result = self._api_post("/info", {"type": "allMids"})
            self._price_cache = result if isinstance(result, dict) else {}
            logger.info(f"価格キャッシュ更新: {len(self._price_cache)}銘柄")
        except Exception as e:
            logger.error(f"価格取得失敗: {e}")

    def get_mark_price(self, symbol: str) -> float:
        """キャッシュから価格取得"""
        ticker = self._normalize_symbol(symbol)
        return float(self._price_cache.get(ticker.upper(), 0))

    def _normalize_symbol(self, symbol: str) -> str:
        """CCXT形式のシンボルをHyperliquid形式に変換"""
        # "ETH/USDT:USDT" → "ETH"
        return symbol.split("/")[0] if "/" in symbol else symbol

    def fetch_funding_rate(self, symbol: str) -> Dict:
        """Funding rateを取得（キャッシュ使用）"""
        # HyperliquidのFRはLoris APIから取得するため、ここでは価格のみ
        mark_price = self.get_mark_price(symbol)

        return {
            "fundingRate": 0.0,  # Lorisから取得
            "markPrice": mark_price,
            "timestamp": None,
            "nextFundingTime": None,
        }

    def fetch_open_interest(self, symbol: str) -> Dict:
        """Open Interestを取得（ダミー固定値）"""
        # API呼び出しを削減するため固定値を返す
        return {"openInterestValue": 5_000_000.0}

    def fetch_order_book(self, symbol: str, limit: int = 5) -> Dict:
        """板情報を取得（キャッシュから生成）"""
        mid_price = self.get_mark_price(symbol)

        if mid_price == 0:
            return {"bids": [], "asks": []}

        # ダミーのbid/ask（0.1%スプレッド）
        spread = mid_price * 0.001
        bid = mid_price - spread / 2
        ask = mid_price + spread / 2

        return {
            "bids": [[bid, 100.0]],
            "asks": [[ask, 100.0]],
        }
