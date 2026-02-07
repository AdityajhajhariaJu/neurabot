from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from config import EmaConfig, BreakoutConfig


class Direction(Enum):
    FLAT = auto()
    LONG = auto()
    SHORT = auto()


@dataclass
class Signal:
    coin: str
    direction: Direction
    entry_price: float
    stop_loss: float
    take_profit: float
    reason: str


def _sma(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return 0.0
    return sum(prices[-period:]) / float(period)


def _std(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return 0.0
    window = prices[-period:]
    mean = sum(window) / float(period)
    var = sum((p - mean) ** 2 for p in window) / float(period)
    return math.sqrt(var)


def _atr_proxy(closes: List[float], lookback: int) -> float:
    if len(closes) < 2:
        return 0.0
    diffs = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    window = diffs[-lookback:] if len(diffs) >= lookback else diffs
    if not window:
        return 0.0
    return sum(window) / float(len(window))


def generate_signal_for_coin(
    coin: str,
    closes: List[float],
    cfg_ema: EmaConfig,
    cfg_breakout: BreakoutConfig,  # unused, kept for signature compatibility
    atr: Optional[float] = None,
) -> Optional[Signal]:
    """Generate a simple Bollinger mean-reversion signal for a single coin.

    - Uses SMA20 +/- 2*Std20 as bands on 15m closes.
    - Long when price closes below lower band (mean reversion up).
    - Short when price closes above upper band (mean reversion down).
    - Stop loss placed slightly outside the band; TP at the SMA (mean).

    Assumes `closes` ordered oldest -> newest.
    """

    # Require enough data for Bollinger bands
    period = 20
    if len(closes) < period:
        return None

    sma = _sma(closes, period)
    std = _std(closes, period)
    if sma == 0.0 or std == 0.0:
        return None

    # Slightly tighter bands to increase trade frequency
    upper = sma + 1.5 * std
    lower = sma - 1.5 * std
    last = closes[-1]

    # Volatility filter: skip completely dead coins
    atr_val = atr if atr is not None else _atr_proxy(closes, lookback=10)
    if atr_val <= 0:
        return None
    if last <= 0:
        return None
    # Require some recent volatility, but be fairly permissive
    if atr_val / last <= 0.0003:  # ~0.03% recent vol
        return None

    # LONG mean reversion: price below lower band
    if last < lower:
        entry = last
        # Stop a bit below lower band
        stop = lower - 0.5 * std
        # Take profit at the mean
        tp = sma
        reason = "Bollinger mean-reversion LONG (close < lower band)"
        return Signal(coin, Direction.LONG, entry, stop, tp, reason)

    # SHORT mean reversion: price above upper band
    if last > upper:
        entry = last
        stop = upper + 0.5 * std
        tp = sma
        reason = "Bollinger mean-reversion SHORT (close > upper band)"
        return Signal(coin, Direction.SHORT, entry, stop, tp, reason)

    return None


def generate_signals_for_universe(
    closes_by_coin: Dict[str, List[float]],
    cfg_ema: EmaConfig,
    cfg_breakout: BreakoutConfig,
) -> Dict[str, Signal]:
    """Generate Bollinger mean-reversion signals for multiple coins.

    `closes_by_coin` maps coin symbol -> list of closes (oldest -> newest).
    Returns a dict of coin -> Signal for coins with valid trade setups.
    """
    signals: Dict[str, Signal] = {}
    for coin, closes in closes_by_coin.items():
        sig = generate_signal_for_coin(coin, closes, cfg_ema, cfg_breakout)
        if sig is not None:
            signals[coin] = sig
    return signals
