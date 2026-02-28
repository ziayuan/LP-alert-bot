"""
CoinGecko price service for fetching USD prices of tokens.
Uses symbol-to-CoinGecko-ID mapping with batched API calls and caching.
"""

import time
import logging
import requests
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# Symbol -> CoinGecko coin ID mapping
# Wrapped/synthetic tokens are mapped to their underlying asset (1:1 peg)
SYMBOL_TO_COINGECKO_ID = {
    # BTC variants (all pegged 1:1 to BTC)
    "BTC": "bitcoin",
    "BTCB": "bitcoin",
    "WBTC": "bitcoin",
    "UBTC": "bitcoin",
    "SBTC": "bitcoin",
    "STBTC": "bitcoin",
    "TBTC": "bitcoin",
    "RENBTC": "bitcoin",
    "CBBTC": "bitcoin",
    # BNB variants
    "BNB": "binancecoin",
    "WBNB": "binancecoin",
    "SBNB": "binancecoin",
    # ETH variants
    "ETH": "ethereum",
    "WETH": "ethereum",
    "STETH": "ethereum",
    "WSTETH": "ethereum",
    "CBETH": "ethereum",
    "RETH": "ethereum",
    # Stablecoins (handled separately but also here for symbol fallback)
    "USDT": "tether",
    "USDC": "usd-coin",
    "BUSD": "binance-usd",
    # HyperEVM tokens
    "HYPE": "hyperliquid",
    "WHYPE": "hyperliquid",
    "LHYPE": "hyperliquid",
    "USDXL": None,  # Stablecoin, pegged to $1
    # SOL
    "SOL": "solana",
    "WSOL": "solana",
}

# Symbols pegged to $1 (stablecoins)
STABLECOIN_SYMBOLS = {"USDT", "USDC", "BUSD", "DAI", "USDXL", "USDbC", "USDE", "USDX"}

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
CACHE_TTL_SECONDS = 60  # Cache prices for 60 seconds


class PriceService:
    """Fetches and caches USD prices from CoinGecko via batched symbol lookup."""

    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # {symbol: (price_usd, timestamp)}

    def _get_cached(self, sym: str) -> Optional[float]:
        """Return cached price if still fresh, else None."""
        if sym in self._cache:
            price, ts = self._cache[sym]
            if time.time() - ts < CACHE_TTL_SECONDS:
                return price
        return None

    def _set_cache(self, sym: str, price: float):
        self._cache[sym] = (price, time.time())

    def get_prices(self, symbols: List[str]) -> Dict[str, Optional[float]]:
        """
        Get USD prices for a list of token symbols in a SINGLE API call.

        Args:
            symbols: List of token symbols (e.g. ["BTCB", "WBNB", "WHYPE", "UBTC"])

        Returns:
            {SYMBOL: price_usd_or_None} dict
        """
        result = {}
        ids_to_fetch = {}  # {coingecko_id: [symbols_using_it]}

        # Step 1: Check stablecoins and cache first
        for raw_sym in symbols:
            sym = raw_sym.upper()

            if sym in STABLECOIN_SYMBOLS:
                result[sym] = 1.0
                continue

            cached = self._get_cached(sym)
            if cached is not None:
                result[sym] = cached
                continue

            # Look up CoinGecko ID
            cg_id = SYMBOL_TO_COINGECKO_ID.get(sym)
            if cg_id is None:
                logger.warning(f"No CoinGecko mapping for symbol '{sym}', price unavailable")
                result[sym] = None
                continue

            # Group by CoinGecko ID (multiple symbols may map to same ID)
            if cg_id not in ids_to_fetch:
                ids_to_fetch[cg_id] = []
            ids_to_fetch[cg_id].append(sym)

        # Step 2: Single batched API call for all remaining tokens
        if ids_to_fetch:
            try:
                ids_param = ",".join(ids_to_fetch.keys())
                logger.info(f"CoinGecko batch request: ids={ids_param}")

                resp = requests.get(
                    f"{COINGECKO_BASE_URL}/simple/price",
                    params={"ids": ids_param, "vs_currencies": "usd"},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()

                for cg_id, syms in ids_to_fetch.items():
                    price = data.get(cg_id, {}).get("usd")
                    for sym in syms:
                        if price is not None:
                            self._set_cache(sym, price)
                            logger.info(f"Price: {sym} = ${price:,.2f}")
                        else:
                            logger.warning(f"No price returned for {sym} (cg_id={cg_id})")
                        result[sym] = price

            except Exception as e:
                logger.error(f"CoinGecko API request failed: {e}")
                # Fall back to stale cache for any remaining symbols
                for cg_id, syms in ids_to_fetch.items():
                    for sym in syms:
                        stale = self._cache.get(sym)
                        result[sym] = stale[0] if stale else None

        return result


# Singleton instance
price_service = PriceService()
