"""
CoinGecko price service for fetching USD prices of tokens.
Uses contract addresses for precise lookups (BSC), with symbol fallback for unsupported chains.
Includes a simple in-memory cache to avoid rate limiting.
"""

import time
import logging
import requests
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# CoinGecko platform IDs for chains we support
CHAIN_TO_PLATFORM = {
    "BSC": "binance-smart-chain",
    "HyperEVM": "hyperliquid",  # May not be supported yet; will fall back to symbol
}

# Fallback: symbol -> CoinGecko coin ID (used when contract address lookup fails)
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
    """Fetches and caches USD prices from CoinGecko, preferring contract address lookup."""

    def __init__(self):
        self._cache: dict = {}  # {cache_key: (price_usd, timestamp)}

    def _get_cached(self, key: str) -> Optional[float]:
        """Return cached price if still fresh, else None."""
        if key in self._cache:
            price, ts = self._cache[key]
            if time.time() - ts < CACHE_TTL_SECONDS:
                return price
        return None

    def _set_cache(self, key: str, price: float):
        self._cache[key] = (price, time.time())

    def get_token_prices(
        self,
        chain: str,
        tokens: List[dict],
    ) -> Dict[str, Optional[float]]:
        """
        Get USD prices for tokens on a specific chain.

        Args:
            chain: Chain name (e.g. "BSC", "HyperEVM")
            tokens: List of dicts with 'symbol' and 'address' keys

        Returns:
            {symbol: price_usd} dict
        """
        result = {}
        tokens_needing_lookup = []

        # Step 0: Check stablecoins and cache
        for token in tokens:
            sym = token["symbol"].upper()
            addr = token["address"].lower()

            if sym in STABLECOIN_SYMBOLS:
                result[sym] = 1.0
                continue

            cached = self._get_cached(f"addr:{addr}")
            if cached is not None:
                result[sym] = cached
                continue

            cached = self._get_cached(f"sym:{sym}")
            if cached is not None:
                result[sym] = cached
                continue

            tokens_needing_lookup.append(token)

        if not tokens_needing_lookup:
            return result

        # Step 1: Try contract address lookup
        platform = CHAIN_TO_PLATFORM.get(chain)
        if platform:
            addresses = [t["address"].lower() for t in tokens_needing_lookup]
            addr_to_sym = {t["address"].lower(): t["symbol"].upper() for t in tokens_needing_lookup}

            try:
                resp = requests.get(
                    f"{COINGECKO_BASE_URL}/simple/token_price/{platform}",
                    params={
                        "contract_addresses": ",".join(addresses),
                        "vs_currencies": "usd",
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()

                still_missing = []
                for token in tokens_needing_lookup:
                    addr = token["address"].lower()
                    sym = token["symbol"].upper()
                    price = data.get(addr, {}).get("usd")
                    if price is not None:
                        self._set_cache(f"addr:{addr}", price)
                        result[sym] = price
                        logger.debug(f"Price via contract: {sym} ({addr}) = ${price}")
                    else:
                        still_missing.append(token)

                tokens_needing_lookup = still_missing

            except Exception as e:
                logger.warning(f"Contract address price lookup failed for {chain}: {e}")
                # Fall through to symbol-based lookup

        # Step 2: Fallback to symbol-based lookup for remaining tokens
        if tokens_needing_lookup:
            ids_to_fetch = []
            sym_to_id = {}

            for token in tokens_needing_lookup:
                sym = token["symbol"].upper()
                cg_id = SYMBOL_TO_COINGECKO_ID.get(sym)
                if cg_id is None and sym in STABLECOIN_SYMBOLS:
                    result[sym] = 1.0
                    continue
                if cg_id is None:
                    logger.warning(f"No CoinGecko mapping for {sym}, price unavailable")
                    result[sym] = None
                    continue

                ids_to_fetch.append(cg_id)
                sym_to_id[sym] = cg_id

            if ids_to_fetch:
                try:
                    resp = requests.get(
                        f"{COINGECKO_BASE_URL}/simple/price",
                        params={"ids": ",".join(set(ids_to_fetch)), "vs_currencies": "usd"},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    for sym, cg_id in sym_to_id.items():
                        price = data.get(cg_id, {}).get("usd")
                        if price is not None:
                            self._set_cache(f"sym:{sym}", price)
                            logger.debug(f"Price via symbol fallback: {sym} = ${price}")
                        result[sym] = price
                except Exception as e:
                    logger.error(f"Symbol-based price lookup failed: {e}")
                    for sym in sym_to_id:
                        # Try stale cache
                        stale = self._cache.get(f"sym:{sym}")
                        result[sym] = stale[0] if stale else None

        return result


# Singleton instance
price_service = PriceService()
