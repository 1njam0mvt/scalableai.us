import logging
import time
from typing import Any, Dict, List, Optional

import requests

from app.utils.retry import with_retry
from config import FMP_API_KEY

logger = logging.getLogger("SCALABLE")

FMP_BASE = "https://financialmodelingprep.com/stable"
_REQUEST_TIMEOUT = 8

# Major indices shown in the market summary row.
INDEX_SYMBOLS = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq"),
    ("^DJI", "Dow Jones"),
]

CARDS_PER_COLUMN = 10
CACHE_TTL_SECONDS = 300  # 5 minutes — protects the free-tier daily quota from repeated page loads


class FinanceService:
    """Thin wrapper around Financial Modeling Prep's free-tier endpoints.

    Every method degrades gracefully: if FMP_API_KEY is missing, or a request
    fails, methods return empty lists/None rather than raising, so the
    dashboard can render a partial or honest empty state instead of crashing.
    """

    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # key -> (expires_at, value)

        if not FMP_API_KEY:
            logger.warning("[FINANCE] FMP_API_KEY not set. Finance dashboard will be unavailable.")

    # ---- low-level HTTP helpers ----

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[Any]:
        if not FMP_API_KEY:
            return None

        params = dict(params or {})
        params["apikey"] = FMP_API_KEY
        url = f"{FMP_BASE}/{path}"

        try:
            def _do():
                resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
                resp.raise_for_status()
                return resp.json()

            return with_retry(_do, max_retries=2, initial_delay=0.6)

        except Exception as e:
            logger.warning("[FINANCE] Request failed for %s: %s", path, e)
            return None

    def _cached(self, key: str, fetch_fn):
        now = time.time()
        cached = self._cache.get(key)

        if cached and cached[0] > now:
            return cached[1]

        value = fetch_fn()
        self._cache[key] = (now + CACHE_TTL_SECONDS, value)
        return value

    # ---- public API ----

    def get_indices(self) -> List[Dict[str, Any]]:
        def _fetch():
            symbols = ",".join(sym for sym, _ in INDEX_SYMBOLS)
            data = self._get("quote", {"symbol": symbols})

            if not data or not isinstance(data, list):
                return []

            by_symbol = {row.get("symbol"): row for row in data}
            out = []

            for sym, label in INDEX_SYMBOLS:
                row = by_symbol.get(sym)

                if not row:
                    continue

                out.append({
                    "symbol": sym,
                    "name": label,
                    "price": row.get("price"),
                    "change": row.get("change"),
                    "changesPercentage": row.get("changesPercentage"),
                })
            return out

        return self._cached("indices", _fetch) or []

    def _get_movers(self, endpoint: str, cache_key: str) -> List[Dict[str, Any]]:
        def _fetch():
            data = self._get(endpoint)

            if not data or not isinstance(data, list):
                return []

            out = []

            for row in data[:CARDS_PER_COLUMN]:
                out.append({
                    "symbol": row.get("symbol", ""),
                    "name": row.get("name", row.get("symbol", "")),
                    "price": row.get("price"),
                    "change": row.get("change"),
                    "changesPercentage": row.get("changesPercentage"),
                })
            return out

        return self._cached(cache_key, _fetch) or []

    def get_gainers(self) -> List[Dict[str, Any]]:
        return self._get_movers("biggest-gainers", "gainers")

    def get_losers(self) -> List[Dict[str, Any]]:
        return self._get_movers("biggest-losers", "losers")

    def get_most_active(self) -> List[Dict[str, Any]]:
        return self._get_movers("most-actives", "actives")

    def get_mini_chart(self, symbol: str, days: int = 30) -> List[float]:
        """Return up to `days` closing prices (oldest first) for a symbol's sparkline."""

        def _fetch():
            data = self._get("historical-price-eod/light", {"symbol": symbol})

            if not data or not isinstance(data, list):
                return []

            # FMP returns newest-first; take the most recent `days` and reverse to oldest-first.
            recent = data[:days]
            closes = [row.get("price") for row in recent if isinstance(row.get("price"), (int, float))]
            closes.reverse()
            return closes

        return self._cached(f"chart:{symbol}", _fetch) or []

    def get_dashboard(self) -> Dict[str, Any]:
        """Assemble the full dashboard payload: indices (with charts) + three mover columns (with charts)."""

        indices = self.get_indices()
        gainers = self.get_gainers()
        losers = self.get_losers()
        actives = self.get_most_active()

        for idx in indices:
            idx["chart"] = self.get_mini_chart(idx["symbol"])

        for group in (gainers, losers, actives):
            for stock in group:
                if stock.get("symbol"):
                    stock["chart"] = self.get_mini_chart(stock["symbol"])

        return {
            "indices": indices,
            "gainers": gainers,
            "losers": losers,
            "actives": actives,
            "available": bool(FMP_API_KEY),
        }