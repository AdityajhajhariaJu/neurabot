from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List


@dataclass
class ExchangeConfig:
    base_url: str
    private_key: str
    wallet_address: str


@dataclass
class EmaConfig:
    timeframe: str  # '15m'
    fast_period: int  # 20
    slow_period: int  # 50
    lookback_candles: int  # 24


@dataclass
class BreakoutConfig:
    btc_eth_buffer_min: float  # 0.001 = 0.1%
    btc_eth_buffer_max: float  # 0.002 = 0.2%
    alt_buffer_min: float      # 0.002 = 0.2%
    alt_buffer_max: float      # 0.004 = 0.4%


@dataclass
class RiskConfig:
    max_leverage: float        # 15x
    max_positions: int         # 8
    risk_per_trade_pct: float  # e.g. 0.01 = 1% of equity
    daily_max_loss_pct: float  # e.g. 0.05 = 5% of equity per day
    per_coin_max_loss_pct: float  # e.g. 0.03 = 3% per coin per day


@dataclass
class NewsConfig:
    rss_feeds: List[str]
    block_keywords: List[str]   # headlines that block trading or reduce size
    cool_off_minutes: int


@dataclass
class NeurabotConfig:
    exchange: ExchangeConfig
    ema: EmaConfig
    breakout: BreakoutConfig
    risk: RiskConfig
    news: NewsConfig


def env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def env_float(key: str, default: float) -> float:
    v = os.environ.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def load_config() -> NeurabotConfig:
    # Exchange config (from your existing .env)
    exchange = ExchangeConfig(
        base_url=env_str("HL_BASE_URL", "https://api.hyperliquid.xyz"),
        private_key=env_str("HL_PRIVATE_KEY", ""),
        wallet_address=env_str("HL_WALLET_ADDRESS", ""),
    )

    # EMA config (your choices)
    ema = EmaConfig(
        timeframe="15m",
        fast_period=20,
        slow_period=50,
        lookback_candles=24,
    )

    # Breakout buffers (your choices)
    breakout = BreakoutConfig(
        btc_eth_buffer_min=0.001,  # 0.1%
        btc_eth_buffer_max=0.002,  # 0.2%
        alt_buffer_min=0.002,      # 0.2%
        alt_buffer_max=0.004,      # 0.4%,
    )

    # Risk config (reasonable starting values – can tune later)
    risk = RiskConfig(
        max_leverage=env_float("NEURABOT_MAX_LEVERAGE", 15.0),
        max_positions=env_int("NEURABOT_MAX_POSITIONS", 8),
        risk_per_trade_pct=env_float("NEURABOT_RISK_PER_TRADE_PCT", 0.01),  # 1%
        daily_max_loss_pct=env_float("NEURABOT_DAILY_MAX_LOSS_PCT", 0.05),   # 5%
        per_coin_max_loss_pct=env_float("NEURABOT_PER_COIN_MAX_LOSS_PCT", 0.03),  # 3%
    )

    # News config – simple defaults for now
    news = NewsConfig(
        rss_feeds=[
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "https://cointelegraph.com/rss",
            "https://decrypt.co/feed",
        ],
        block_keywords=[
            "hack",
            "exploit",
            "rug pull",
            "insolvency",
            "bankruptcy",
            "regulation ban",
        ],
        cool_off_minutes=env_int("NEURABOT_NEWS_COOLOFF_MIN", 30),
    )

    return NeurabotConfig(
        exchange=exchange,
        ema=ema,
        breakout=breakout,
        risk=risk,
        news=news,
    )
