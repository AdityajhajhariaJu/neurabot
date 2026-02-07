from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional

import json
import requests

from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from .config import ExchangeConfig
from .data.ws_candles import WsCandleStore


# Global websocket candle store (15m candles by default)
_WS_STORE: Optional[WsCandleStore] = None


@dataclass
class NeurabotExchange:
    exchange: Exchange
    info: Info
    base_url: str

    @classmethod
    def from_config(cls, cfg: ExchangeConfig) -> "NeurabotExchange":
        """Initialize Hyperliquid Exchange + Info from config."""
        ex = Exchange(
            cfg.private_key,
            cfg.base_url,
            account_address=cfg.wallet_address,
        )
        info = Info(cfg.base_url, skip_ws=True)
        return cls(exchange=ex, info=info, base_url=cfg.base_url.rstrip("/"))

    # --- Account / state ---

    def get_user_state(self) -> Dict[str, Any]:
        payload = {"type": "clearinghouseState", "user": self.exchange.account_address}
        r = requests.post(
            f"{self.base_url}/info",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()

    def get_equity_and_withdrawable(self) -> Tuple[float, float]:
        state = self.get_user_state()
        margin_summary = state.get("marginSummary", {}) or {}
        equity = float(margin_summary.get("accountValue", 0.0))
        withdrawable = float(state.get("withdrawable", 0.0))
        return equity, withdrawable

    def get_open_positions(self) -> List[Dict[str, Any]]:
        state = self.get_user_state()
        positions: List[Dict[str, Any]] = []
        for ap in state.get("assetPositions", []):
            p = ap.get("position") or {}
            if not p:
                continue
            if float(p.get("szi", "0") or 0) != 0:
                positions.append(p)
        return positions

    # --- Market data ---

    def _info(self, payload: Dict[str, Any]) -> Any:
        """Low-level /info call via HTTP (mirrors old HyperliquidHTTP helper)."""
        r = requests.post(
            f"{self.base_url}/info",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()

    def get_universe(self) -> List[Dict[str, Any]]:
        meta, _ = self._info({"type": "metaAndAssetCtxs"})
        return meta.get("universe", [])

    def get_top_n_universe(self, n: int) -> List[Dict[str, Any]]:
        universe = self.get_universe()
        return universe[: min(len(universe), n)]

    def get_mids(self) -> Dict[str, float]:
        mids = self._info({"type": "allMids"})
        return {k: float(v) for k, v in mids.items()}

    # NOTE: get_candles is now wired to the global websocket candle store.
    # The store must be started elsewhere (e.g., in bot.py) before this will
    # return meaningful data.
    def get_candles(
        self, coin: str, timeframe: str, limit: int
    ) -> List[Dict[str, Any]]:
        global _WS_STORE
        if timeframe != "15m":
            raise NotImplementedError("Only 15m timeframe supported in WS candle store for now")
        if _WS_STORE is None:
            raise NotImplementedError("WsCandleStore not started; cannot provide candles")
        # Delegate to the websocket candle store
        loop = asyncio.get_event_loop() if asyncio.get_event_loop().is_running() else asyncio.new_event_loop()
        return loop.run_until_complete(_WS_STORE.get_candles(coin, limit))

    # --- Orders ---

    def place_order(
        self,
        coin: str,
        is_buy: bool,
        size: float,
        limit_px: float,
        tif: str = "Ioc",
        reduce_only: bool = False,
    ) -> Dict[str, Any]:
        """Place a limit order with TIF and reduce_only flag."""
        order_type = {"limit": {"tif": tif}}
        res = self.exchange.order(
            name=coin,
            is_buy=is_buy,
            sz=size,
            limit_px=limit_px,
            order_type=order_type,
            reduce_only=reduce_only,
        )
        return res


def get_ws_store() -> WsCandleStore:
    """Return the global websocket candle store (create if needed)."""
    global _WS_STORE
    if _WS_STORE is None:
        _WS_STORE = WsCandleStore()
    return _WS_STORE
