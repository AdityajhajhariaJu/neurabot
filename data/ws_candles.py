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
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List

import websockets


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

    async def _ensure_history(self, coin: str) -> CandleHistory:
        if coin not in self._histories:
            self._histories[coin] = CandleHistory(
                candles=deque(maxlen=self.max_candles),
                bucket_ms=self.bucket_ms,
            )
        return self._histories[coin]

    async def _handle_msg(self, msg: Dict[str, Any]) -> None:
        """Handle a single WS message.

        Expects trade messages with `channel == "trades"` and `data` as a list
        of trade objects as described in the module docstring.
        """
        channel = msg.get("channel")

        # Ignore subscription acks or unrelated channels
        if channel == "subscriptionResponse":
            return
        if channel != "trades":
            return

        data = msg.get("data") or []
        if not isinstance(data, list):
            return

        async with self._lock:
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
                except Exception:
                    # Ignore malformed trades
                    continue

    async def _ws_loop(self, coins: List[str]) -> None:
        """Background WS loop that subscribes to trades and updates candles.

        Always handles reconnects with a short backoff when the connection drops
        or on any exception.
        """
        while self._running:
            try:
                async with websockets.connect(HYPERLIQUID_WS_URL) as ws:
                    # Subscribe to trades for each requested coin
                    for c in coins:
                        sub_msg = {
                            "method": "subscribe",
                            "subscription": {"type": "trades", "coin": c},
                        }
                        await ws.send(json.dumps(sub_msg))

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        await self._handle_msg(msg)
            except Exception:
                # On any error, wait a bit and reconnect
                await asyncio.sleep(5)

    async def start(self, coins: List[str]) -> None:
        if self._running:
            return
        self._running = True
        # Fire-and-forget WS loop; it will maintain candles in the background
        asyncio.create_task(self._ws_loop(coins=coins))

    async def stop(self) -> None:
        self._running = False

    async def get_candles(self, coin: str, limit: int) -> List[Dict[str, Any]]:
        async with self._lock:
            hist = self._histories.get(coin)
            if not hist:
                return []
            return hist.get_last(limit)
