from __future__ import annotations

import time
from typing import Any, Dict, List

from hyperliquid.info import Info


def fetch_candles(
    base_url: str,
    coin: str,
    interval: str = "15m",
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Fetch historical candles for a coin from Hyperliquid via Info.candles_snapshot.

    Returns list of dicts with keys: t, o, h, l, c (aligned with WsCandleStore format).
    """
    info = Info(base_url, skip_ws=True)

    # End time = now, start time = now - limit * interval
    now_ms = int(time.time() * 1000)
    interval_ms = 15 * 60 * 1000 if interval == "15m" else 60 * 1000
    start_ms = now_ms - limit * interval_ms

    raw = info.candles_snapshot(name=coin, interval=interval, startTime=start_ms, endTime=now_ms)
    candles: List[Dict[str, Any]] = []

    for c in raw:
        try:
            candles.append(
                {
                    "t": int(c["t"]),
                    "o": float(c["o"]),
                    "h": float(c["h"]),
                    "l": float(c["l"]),
                    "c": float(c["c"]),
                }
            )
        except Exception:
            continue

    # Sort by time just in case
    candles.sort(key=lambda x: x["t"])
    return candles
