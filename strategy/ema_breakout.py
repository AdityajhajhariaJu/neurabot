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


def _ema(prices: List[float], period: int) -> float:
    if not prices:
        return 0.0
    k = 2.0 / (period + 1)
    ema_val = prices[0]
    for px in prices[1:]:
        ema_val = (px * k) + (ema_val * (1 - k))
    return ema_val


def compute_emas(closes: List[float], cfg: EmaConfig) -> Tuple[float, float]:
    """Compute EMA_fast and EMA_slow from a list of closing prices.

    Assumes `closes` are ordered oldest -> newest.
    """
    if len(closes) < cfg.slow_period:
        return 0.0, 0.0
    ema_fast = _ema(closes[-cfg.fast_period :], cfg.fast_period)
    ema_slow = _ema(closes[-cfg.slow_period :], cfg.slow_period)
    return ema_fast, ema_slow


def _range_high_low(closes: List[float], lookback: int) -> Tuple[float, float]:
    window = closes[-lookback:] if len(closes) >= lookback else closes
    if not window:
        return 0.0, 0.0
    return max(window), min(window)


def _buffer_for_coin(coin: str, price: float, cfg: BreakoutConfig) -> Tuple[float, float]:
    """Return (min_buffer, max_buffer) in absolute price units for a coin.

    BTC/ETH: use btc_eth_* buffers, else alt_* buffers.
    """
    is_btc_or_eth = coin.upper() in {"BTC", "ETH"}
    if is_btc_or_eth:
        return price * cfg.btc_eth_buffer_min, price * cfg.btc_eth_buffer_max
    return price * cfg.alt_buffer_min, price * cfg.alt_buffer_max


def generate_signal_for_coin(
    coin: str,
    closes: List[float],
    cfg_ema: EmaConfig,
    cfg_breakout: BreakoutConfig,
    atr: Optional[float] = None,
) -> Optional[Signal]:
    """Generate EMA+breakout signal for a single coin.

    - Uses EMA(20/50) on 15m (from cfg_ema) to determine direction bias.
    - Uses 24-candle range + buffer from cfg_breakout.
    - Returns a Signal with entry/stop/take-profit, or None if no trade.
    """
    if len(closes) < max(cfg_ema.slow_period, cfg_ema.lookback_candles):
        return None

    ema_fast, ema_slow = compute_emas(closes, cfg_ema)
    if ema_fast == 0.0 and ema_slow == 0.0:
        return None

    # Direction bias from EMA
    if ema_fast > ema_slow:
        bias = Direction.LONG
    elif ema_fast < ema_slow:
        bias = Direction.SHORT
    else:
        return None  # flat / chop, skip

    range_high, range_low = _range_high_low(closes, cfg_ema.lookback_candles)
    last_price = closes[-1]

    # Compute buffer in absolute price units
    min_buf, max_buf = _buffer_for_coin(coin, last_price, cfg_breakout)

    # We can use the mid of the buffer range for now
    buf = (min_buf + max_buf) / 2.0

    # Basic ATR proxy if none provided: average abs change over last N candles
    if atr is None:
        diffs = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
        atr = sum(diffs[-cfg_ema.lookback_candles :]) / max(1, min(len(diffs), cfg_ema.lookback_candles))

    # Entry / SL / TP based on direction and breakout
    reason = ""
    if bias is Direction.LONG:
        breakout_level = range_high + buf
        if last_price > breakout_level:
            entry = last_price
            # Stop below range low by 0.5 * ATR
            stop = range_low - 0.5 * atr
            # Take profit at 2R from entry
            risk_per_unit = entry - stop
            tp = entry + 2.0 * risk_per_unit
            reason = "EMA20>50 + breakout above range"
            return Signal(coin, Direction.LONG, entry, stop, tp, reason)
    elif bias is Direction.SHORT:
        breakout_level = range_low - buf
        if last_price < breakout_level:
            entry = last_price
            # Stop above range high by 0.5 * ATR
            stop = range_high + 0.5 * atr
            risk_per_unit = stop - entry
            tp = entry - 2.0 * risk_per_unit
            reason = "EMA20<50 + breakout below range"
            return Signal(coin, Direction.SHORT, entry, stop, tp, reason)

    return None


def generate_signals_for_universe(
    closes_by_coin: Dict[str, List[float]],
    cfg_ema: EmaConfig,
    cfg_breakout: BreakoutConfig,
) -> Dict[str, Signal]:
    """Generate signals for multiple coins.

    `closes_by_coin` maps coin symbol -> list of closes (oldest -> newest).
    Returns a dict of coin -> Signal for coins with valid trade setups.
    """
    signals: Dict[str, Signal] = {}
    for coin, closes in closes_by_coin.items():
        sig = generate_signal_for_coin(coin, closes, cfg_ema, cfg_breakout)
        if sig is not None:
            signals[coin] = sig
    return signals
