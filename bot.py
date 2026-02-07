from __future__ import annotations

import asyncio
import time
from typing import Dict, List

from dotenv import load_dotenv

from .config import load_config
from .exchange import NeurabotExchange, get_ws_store
from .strategy.ema_breakout import generate_signals_for_universe
from .risk.position_sizing import compute_position_size, check_daily_loss_limits
from .news.filter import NewsFilter


TOP_N_COINS = 20
CANDLE_LIMIT = 100  # number of candles to fetch per coin (enough for EMA + range)


async def main_loop() -> None:
    load_dotenv()
    cfg = load_config()

    exch = NeurabotExchange.from_config(cfg.exchange)
    news_filter = NewsFilter(cfg.news)

    # Start websocket candle store (15m candles) for top N coins
    ws_store = get_ws_store()
    universe = exch.get_top_n_universe(TOP_N_COINS)
    coins = [asset["name"] for asset in universe]
    print("[Neurabot] Starting WS candle store for coins:", coins)
    await ws_store.start(coins=coins)

    # For daily loss checks
    equity_start_of_day, _ = exch.get_equity_and_withdrawable()
    per_coin_loss_pct: Dict[str, float] = {}

    print("[Neurabot] Started main loop. Equity start of day:", equity_start_of_day)

    while True:
        loop_start = time.time()

        # Refresh news state (could be less frequent in practice)
        news_filter.refresh()

        equity, withdrawable = exch.get_equity_and_withdrawable()
        print("[Neurabot] Loop start: equity=", equity, "withdrawable=", withdrawable)

        # Check daily loss limits before doing anything else
        if not check_daily_loss_limits(equity_start_of_day, equity, per_coin_loss_pct, cfg.risk):
            print("[Neurabot] Daily loss limit hit. Sleeping 60s.")
            await asyncio.sleep(60)
            continue

        # Get top N coins from universe (may change over time)
        universe = exch.get_top_n_universe(TOP_N_COINS)
        mids = exch.get_mids()
        print("[Neurabot] Universe size:", len(universe), "mids:", len(mids))

        closes_by_coin: Dict[str, List[float]] = {}

        for asset in universe:
            coin = asset["name"]
            if coin not in mids:
                continue
            try:
                candles = exch.get_candles(coin, cfg.ema.timeframe, CANDLE_LIMIT)
            except NotImplementedError as e:
                print("[Neurabot] No candles for coin:", coin, e)
                continue
            except Exception as e:
                print("[Neurabot] Error fetching candles for", coin, e)
                continue

            closes = [float(c["c"]) for c in candles]
            print("[Neurabot] Coin", coin, "candles=", len(candles), "closes=", len(closes))
            if not closes:
                continue
            closes_by_coin[coin] = closes

        if not closes_by_coin:
            print("[Neurabot] No closes_by_coin; sleeping 10s.")
            await asyncio.sleep(10)
            continue

        # Generate EMA + breakout signals
        signals = generate_signals_for_universe(closes_by_coin, cfg.ema, cfg.breakout)
        print("[Neurabot] Signals generated:", list(signals.keys()))

        # Get current open positions count
        open_positions = exch.get_open_positions()
        open_positions_count = len(open_positions)
        print("[Neurabot] Open positions:", open_positions_count)

        for coin, sig in signals.items():
            # Skip if news filter blocks trading
            if news_filter.is_blocked(coin):
                print("[Neurabot] Coin blocked by news:", coin)
                continue

            # Compute position size based on risk
            pos_size = compute_position_size(
                coin=coin,
                entry_price=sig.entry_price,
                stop_loss=sig.stop_loss,
                equity=equity,
                open_positions_count=open_positions_count,
                cfg=cfg.risk,
            )
            if pos_size is None or pos_size.size <= 0:
                print("[Neurabot] Position size invalid for", coin)
                continue

            # Place order live (no dry-run here)
            is_buy = sig.direction.name == "LONG"

            # Simple limit price around entry (tiny slippage allowance)
            limit_px = sig.entry_price * (1.001 if is_buy else 0.999)

            try:
                res = exch.place_order(
                    coin=coin,
                    is_buy=is_buy,
                    size=pos_size.size,
                    limit_px=limit_px,
                    tif="Ioc",
                    reduce_only=False,
                )
                print(
                    "[Neurabot] ORDER",
                    coin,
                    "side=",
                    "BUY" if is_buy else "SELL",
                    "size=",
                    pos_size.size,
                    "res=",
                    res,
                )
            except Exception as e:
                print("[Neurabot] ORDER_ERROR", coin, e)

        # Basic pacing
        elapsed = time.time() - loop_start
        sleep_s = max(5.0 - elapsed, 1.0)
        await asyncio.sleep(sleep_s)


def main() -> None:
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()
