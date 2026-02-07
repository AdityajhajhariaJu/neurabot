from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional

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
        """Initialize Hyperliquid Exchange + Info from config.

        If cfg.wallet_address is missing, fall back to NEURABOT_WALLET_ADDRESS
        from the environment so account_address is always set.
        """
        ex = Exchange(
            cfg.private_key,
            cfg.base_url,
            account_address=cfg.wallet_address or None,
        )

        # Fallback: ensure account_address is set from env if config left it blank
        if not getattr(ex, "account_address", None):
            import os

            env_addr = os.getenv("NEURABOT_WALLET_ADDRESS")
            if env_addr:
                ex.account_address = env_addr

        info = Info(cfg.base_url, skip_ws=True)
        return cls(exchange=ex, info=info, base_url=cfg.base_url.rstrip("/"))

    # --- Account / state ---

    def get_user_state(self) -> Dict[str, Any]:
        """Fetch user state via SDK, with debug logging on non-JSON errors.

        If Hyperliquid returns a non-JSON body (e.g. plain text or HTML),
        log the raw response once so we can see what it is complaining about.
        """
        try:
            print(
                "[Neurabot][DEBUG] get_user_state using:",
                "base_url=", self.base_url,
                "account_address=", self.exchange.account_address,
            )
            return self.info.user_state(self.exchange.account_address)
        except Exception as e:
            # Best-effort debug: print the raw response if available
            raw = None
            try:
                resp = getattr(e, "response", None)
                if resp is not None:
                    raw = resp.text
            except Exception:
                raw = None

            print("[Neurabot][DEBUG] user_state error:", repr(e))
            if raw is not None:
                print("[Neurabot][DEBUG] user_state raw response:")
                # Trim to avoid huge logs
                print(raw[:2000])

            # Re-raise so the bot exits visibly during debugging
            raise

    def get_equity_and_withdrawable(self) -> Tuple[float, float]:
        """Fetch equity/withdrawable using a fresh Info instance.

        This mirrors the working path in test_user_state.py and avoids any
        subtle issues with wrapper state.
        """
        info = Info(self.base_url, skip_ws=True)
        state = info.user_state(address=self.exchange.account_address)
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

    def get_universe(self) -> List[Dict[str, Any]]:
        """Fetch universe via Hyperliquid SDK Info helper."""
        meta, _ = self.info.meta_and_asset_ctxs()
        return meta.get("universe", [])


    def get_top_n_universe(self, n: int) -> List[Dict[str, Any]]:
        universe = self.get_universe()
        return universe[: min(len(universe), n)]

    def get_mids(self) -> Dict[str, float]:
        """Fetch mid prices via Hyperliquid SDK Info helper."""
        mids = self.info.all_mids()
        return {k: float(v) for k, v in mids.items()}


    # --- Candles (async method to be called with await) ---

    async def get_candles_async(
        self, coin: str, timeframe: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Async method to get candles from WS store."""
        global _WS_STORE
        if timeframe != "15m":
            raise NotImplementedError("Only 15m timeframe supported in WS candle store for now")
        if _WS_STORE is None:
            raise NotImplementedError("WsCandleStore not started; cannot provide candles")
        return await _WS_STORE.get_candles(coin, limit)

    def get_candles(
        self, coin: str, timeframe: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Sync wrapper for get_candles - deprecated, use get_candles_async instead."""
        # This is a backward compatibility wrapper
        # Try to use the current event loop if it exists
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, this shouldn't be called
            raise RuntimeError("get_candles called from async context - use get_candles_async instead")
        except RuntimeError:
            # No running loop, create a new one
            return asyncio.run(self.get_candles_async(coin, timeframe, limit))

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
