from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from config import RiskConfig


@dataclass
class PositionSize:
    coin: str
    direction: str  # 'long' or 'short'
    size: float      # quantity in base units
    notional: float  # size * entry price


def compute_position_size(
    coin: str,
    entry_price: float,
    stop_loss: float,
    equity: float,
    open_positions_count: int,
    cfg: RiskConfig,
) -> PositionSize | None:
    """Compute position size based on risk config.

    - Risk per trade = risk_per_trade_pct * equity.
    - Risk per unit = |entry - stop|.
    - Size (base units) = (risk_amount / risk_per_unit).
    - Enforces max_positions.
    - Returns None if size would be <= 0 or if risk_per_unit is 0.
    """
    if open_positions_count >= cfg.max_positions:
        return None

    # Basic sanity
    if entry_price <= 0:
        return None

    # Risk per trade in quote currency (e.g. USD)
    risk_amount = cfg.risk_per_trade_pct * equity
    if risk_amount <= 0:
        return None

    risk_per_unit = abs(entry_price - stop_loss)
    if risk_per_unit <= 0:
        return None

    # Size in base units
    size = risk_amount / risk_per_unit
    if size <= 0:
        return None

    notional = size * entry_price

    # Direction string for logging / order side decision
    direction = "long" if entry_price > stop_loss else "short"

    return PositionSize(coin=coin, direction=direction, size=size, notional=notional)


def check_daily_loss_limits(
    equity_start_of_day: float,
    current_equity: float,
    per_coin_loss_pct: Dict[str, float],
    cfg: RiskConfig,
) -> bool:
    """Check if we are allowed to continue trading.

    Returns True if trading is allowed, False if we should stop for the day.
    """
    if equity_start_of_day <= 0:
        return True

    # Total equity drawdown
    dd = (equity_start_of_day - current_equity) / equity_start_of_day
    if dd >= cfg.daily_max_loss_pct:
        return False

    # Per-coin drawdown limits
    for coin, loss_pct in per_coin_loss_pct.items():
        if loss_pct >= cfg.per_coin_max_loss_pct:
            return False

    return True
