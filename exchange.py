from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional

from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

# Use absolute imports when running as a script from /mnt/botdisk/neurabot
from config import ExchangeConfig
from data.ws_candles import WsCandleStore

# Global websocket candle store (15m candles by default)
_WS_STORE: Optional[WsCandleStore] = None


@dataclass
class NeurabotExchange:
    exchange: Exchange
    info: Info
    base_url: str
    wallet_address: str  # <-- always stored explicitly, never rely on SDK internals

    @classmethod
    def from_config(cls, cfg: ExchangeConfig) -> "NeurabotExchange":
        """Initialize Hyperliquid Exchange + Info from config."""
        if not cfg.wallet_address:
            raise ValueError(
                "wallet_address is empty! "
                "Set NEURABOT_WALLET_ADDRESS or HL_WALLET_ADDRESS in your .env.local"
            )

        ex = Exchange(
            cfg.private_key,
            cfg.base_url,
            account_address=cfg.wallet_address,
        )
        info = Info(cfg.base_url, skip_ws=True)
        print(f"[Neurabot][Exchange] Initialized with wallet={cfg.wallet_address}")
        return cls(
            exchange=ex,
            info=info,
            base_url=cfg.base_url.rstrip("/"),
            wallet_address=cfg.wallet_address,
        )

    # --- Account / state ---

    def get_user_state(self) -> Dict[str, Any]:
        """Fetch user state using our stored wallet_address (not SDK's internal attr)."""
        print(f"[Neurabot][DEBUG] get_user_state addr={self.wallet_address}")
        # Always create a fresh Info to avoid stale connection issues
        info = Info(self.base_url, skip_ws=True)
        return info.user_state(address=self.wallet_address)

    def get_equity_and_withdrawable(self) -> Tuple[float, float]:
        """Fetch equity/withdrawable from user state."""
        state = self.get_user_state()
        margin_summary = state.get("marginSummary", {}) or {}
        equity = float(margin_summary.get("accountValue", 0.0))
        withdrawable = float(state.get("withdrawable", 0.0))
        return equity, withdrawable

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Fetch open positions from user state."""
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
