from __future__ import annotations

"""Hyperliquid websocket candle builder for Neurabot.

This module defines the structures and API needed to build 15m candles from
Hyperliquid's websocket trade stream.

**Note:** This is based on the reference you provided. It assumes the
Hyperliquid WS 'trades' channel uses messages of the form:

Subscription payload per coin:

    {"method": "subscribe", "subscription": {"type": "trades", "coin": "BTC"}}

Ack response:

    {"channel": "subscriptionResponse", "data": ...}

Trade messages:

    {
      "channel": "trades",
      "data": [
        {
          "coin": "BTC",
          "side": "B" | "S",   # buy/sell
          "px": "47862.0",      # price as string
          "sz": "0.001",        # size as string
          "time": 1707535600000, # epoch millis
          "tid": "...",         # trade id
          "users": ["buyer", "seller"]
        },
        ...
      ]
    }

If Hyperliquid changes this schema, _handle_msg will need updates.
"""

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional

try:
    import websockets
except ImportError:
    print("[WS_CANDLES] WARNING: websockets library not installed. Install with: pip install websockets")
    websockets = None

# Hyperliquid WS endpoint (trades)
HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws"


@dataclass
class Candle:
    t: int  # open time in ms since epoch
    o: float
    h: float
    l: float
    c: float

    def to_dict(self) -> Dict[str, Any]:
        return {"t": self.t, "o": self.o, "h": self.h, "l": self.l, "c": self.c}


@dataclass
class CandleHistory:
    """Rolling candle history per coin and timeframe."""

    candles: Deque[Candle]
    bucket_ms: int

    def add_trade(self, ts_ms: int, price: float) -> None:
        """Add a trade tick to the appropriate candle bucket."""
        bucket_start = ts_ms - (ts_ms % self.bucket_ms)

        if not self.candles or self.candles[-1].t != bucket_start:
            # Start a new candle
            c = Candle(t=bucket_start, o=price, h=price, l=price, c=price)
            self.candles.append(c)
        else:
            c = self.candles[-1]
            c.h = max(c.h, price)
            c.l = min(c.l, price)
            c.c = price

    def get_last(self, limit: int) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in list(self.candles)[-limit:]]


class WsCandleStore:
    """Maintains candle histories for multiple coins from Hyperliquid WS trades."""

    def __init__(self, bucket_ms: int = 15 * 60 * 1000, max_candles: int = 200):
        self.bucket_ms = bucket_ms
        self.max_candles = max_candles
        self._histories: Dict[str, CandleHistory] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._ws_task: Optional[asyncio.Task] = None
        self._subscribed_coins: List[str] = []

    async def _ensure_history(self, coin: str) -> CandleHistory:
        if coin not in self._histories:
            self._histories[coin] = CandleHistory(
                candles=deque(maxlen=self.max_candles),
                bucket_ms=self.bucket_ms,
            )
        return self._histories[coin]

    async def _handle_msg(self, msg: Dict[str, Any]) -> None:
        """Handle a single WS message."""
        channel = msg.get("channel")

        # Ignore subscription acks or unrelated channels
        if channel == "subscriptionResponse":
            print("[WS_CANDLES] Subscription confirmed:", msg.get("data", {}).get("method"))
            return
        if channel != "trades":
            return

        data = msg.get("data") or []
        if not isinstance(data, list):
            return

        async with self._lock:
            trades_processed = 0
            for trade in data:
                try:
                    coin = trade.get("coin")
                    px_str = trade.get("px")
                    ts = trade.get("time")
                    if not coin or px_str is None or ts is None:
                        continue
                    price = float(px_str)
                    ts_ms = int(ts)
                    hist = await self._ensure_history(coin)
                    hist.add_trade(ts_ms, price)
                    trades_processed += 1
                except Exception as e:
                    print(f"[WS_CANDLES] Error processing trade: {e}")
                    continue
            if trades_processed > 0:
                print(f"[WS_CANDLES] Processed {trades_processed} trades")

    async def _ws_loop(self, coins: List[str]) -> None:
        """Background WS loop that subscribes to trades and updates candles.

        Handles reconnects with exponential backoff when the connection drops
        or on any exception.
        """
        if websockets is None:
            print("[WS_CANDLES] ERROR: websockets library not available")
            return

        reconnect_count = 0
        while self._running:
            try:
                print(f"[WS_CANDLES] Connecting to {HYPERLIQUID_WS_URL}...")
                async with websockets.connect(HYPERLIQUID_WS_URL) as ws:
                    print(f"[WS_CANDLES] Connected! Subscribing to {len(coins)} coins...")
                    # Subscribe to trades for each requested coin
                    for c in coins:
                        sub_msg = {
                            "method": "subscribe",
                            "subscription": {"type": "trades", "coin": c},
                        }
                        await ws.send(json.dumps(sub_msg))
                        print(f"[WS_CANDLES] Subscribed to {c}")

                    reconnect_count = 0  # reset on successful connection
                    print("[WS_CANDLES] All subscriptions sent, listening for trades...")

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            print("[WS_CANDLES] Invalid JSON received")
                            continue
                        await self._handle_msg(msg)
            except Exception as e:
                reconnect_count += 1
                backoff = min(5 * reconnect_count, 60)  # Max 60s backoff
                print(f"[WS_CANDLES] Error (reconnect #{reconnect_count}): {e}")
                print(f"[WS_CANDLES] Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)

    async def start(self, coins: List[str]) -> None:
        if self._running:
            print("[WS_CANDLES] Already running")
            return
        self._running = True
        self._subscribed_coins = coins
        # Fire-and-forget WS loop; it will maintain candles in the background
        self._ws_task = asyncio.create_task(self._ws_loop(coins=coins))
        print(f"[WS_CANDLES] Started background task for {len(coins)} coins")

    async def stop(self) -> None:
        print("[WS_CANDLES] Stopping...")
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        print("[WS_CANDLES] Stopped")

    async def get_candles(self, coin: str, limit: int) -> List[Dict[str, Any]]:
        async with self._lock:
            hist = self._histories.get(coin)
            if not hist:
                return []
            return hist.get_last(limit)

    async def get_candle_counts(self) -> Dict[str, int]:
        """Get number of candles available for each coin (for debugging)."""
        async with self._lock:
            return {coin: len(hist.candles) for coin, hist in self._histories.items()}
