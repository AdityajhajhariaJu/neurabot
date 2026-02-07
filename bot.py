from __future__ import annotations

import asyncio
import time
from typing import Dict, List

from dotenv import load_dotenv

# Use absolute imports so we match the tested config/exchange modules
from config import load_config
from exchange import NeurabotExchange, get_ws_store
from strategy.ema_breakout import generate_signals_for_universe
from risk.position_sizing import compute_position_size, check_daily_loss_limits
from news.filter import NewsFilter


TOP_N_COINS = 20
CANDLE_LIMIT = 100  # number of candles to fetch per coin (enough for EMA + range)


async def main_loop() -> None:
    """Main Neurabot loop.

    Always load .env.local explicitly so config sees NEURABOT_* / HL_* vars.
    """
    load_dotenv(".env.local")
    cfg = load_config()

    exch = NeurabotExchange.from_config(cfg.exchange)
    news_filter = NewsFilter(cfg.news)

    # ── Historical backfill: seed candles before starting WS ──
    from data.http_candles import fetch_candles
    ws_store = get_ws_store()

    universe = exch.get_top_n_universe(TOP_N_COINS)
    coins = [asset["name"] for asset in universe]
    print("[Neurabot] Backfilling 15m candles for coins:", coins)

    for coin in coins:
        try:
            hist = fetch_candles(
                cfg.exchange.base_url,
                coin,
                interval=cfg.ema.timeframe,
                limit=CANDLE_LIMIT,
            )
            print(f"[Neurabot] Backfill {coin}: fetched {len(hist)} candles")
            # Seed historical candles into the store
            await ws_store.seed_candles(coin, hist)
        except Exception as e:
            print(f"[Neurabot] Backfill error for {coin}: {e}")

    # ── Fetch real starting equity ──
    print("[Neurabot] Fetching initial equity from Hyperliquid...")
    try:
        equity_start_of_day, _ = exch.get_equity_and_withdrawable()
        print(f"[Neurabot] Real equity at start: {equity_start_of_day}")
    except Exception as e:
        print(f"[Neurabot] WARNING: Could not fetch equity ({e}), defaulting to 96.0")
        equity_start_of_day = 96.0

    per_coin_loss_pct: Dict[str, float] = {}

    # Start websocket candle store (15m candles) for top N coins
    ws_store = get_ws_store()
    universe = exch.get_top_n_universe(TOP_N_COINS)
    coins = [asset["name"] for asset in universe]
    print("[Neurabot] Starting WS candle store for coins:", coins)
    await ws_store.start(coins=coins)

    # Give WS some time to connect and start receiving data
    print("[Neurabot] Waiting 10s for initial candle data...")
    await asyncio.sleep(10)

    print(f"[Neurabot] Started main loop. Equity start of day: {equity_start_of_day}")

    while True:
        loop_start = time.time()

        # Refresh news state
        try:
            news_filter.refresh()
        except Exception as e:
            print(f"[Neurabot] News refresh error (non-fatal): {e}")

        # ── Fetch real equity ──
        try:
            equity, withdrawable = exch.get_equity_and_withdrawable()
        except Exception as e:
            print(f"[Neurabot] Equity fetch failed ({e}), using last known: {equity_start_of_day}")
            equity = equity_start_of_day
            withdrawable = equity_start_of_day

        print(f"[Neurabot] Loop start: equity={equity}, withdrawable={withdrawable}")

        # Check daily loss limits before doing anything else
        if not check_daily_loss_limits(equity_start_of_day, equity, per_coin_loss_pct, cfg.risk):
            print("[Neurabot] Daily loss limit hit. Sleeping 60s.")
            await asyncio.sleep(60)
            continue

        # Get top N coins from universe
        universe = exch.get_top_n_universe(TOP_N_COINS)
        mids = exch.get_mids()
        print(f"[Neurabot] Universe size: {len(universe)}, mids: {len(mids)}")

        # ── Fetch real open positions ──
        try:
            open_positions = exch.get_open_positions()
            open_positions_count = len(open_positions)
        except Exception as e:
            print(f"[Neurabot] Open positions fetch failed ({e}), assuming 0")
            open_positions = []
            open_positions_count = 0

        print(f"[Neurabot] Open positions: {open_positions_count}")

        closes_by_coin: Dict[str, List[float]] = {}

        for asset in universe:
            coin = asset["name"]
            if coin not in mids:
                continue
            try:
                candles = await exch.get_candles_async(coin, cfg.ema.timeframe, CANDLE_LIMIT)
            except NotImplementedError as e:
                print(f"[Neurabot] No candles for coin: {coin} ({e})")
                continue
            except Exception as e:
                print(f"[Neurabot] Error fetching candles for {coin}: {e}")
                continue

            if not candles:
                continue

            closes = [float(c["c"]) for c in candles]
            if len(closes) >= cfg.ema.slow_period:
                # Only log coins with enough data for signals
                print(f"[Neurabot] Coin {coin} candles={len(candles)}")

            if not closes:
                continue
            closes_by_coin[coin] = closes

        if not closes_by_coin:
            print("[Neurabot] No closes_by_coin; sleeping 10s.")
            await asyncio.sleep(10)
            continue

        # Generate EMA + breakout signals
        signals = generate_signals_for_universe(closes_by_coin, cfg.ema, cfg.breakout)
        if signals:
            print(f"[Neurabot] Signals generated: {list(signals.keys())}")

        for coin, sig in signals.items():
            # Skip if news filter blocks trading
            if news_filter.is_blocked(coin):
                print(f"[Neurabot] Coin blocked by news: {coin}")
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
                print(f"[Neurabot] Position size invalid for {coin}")
                continue

            # Place order (LIVE)
            is_buy = sig.direction.name == "LONG"
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
                    f"[Neurabot] ORDER {coin} side={'BUY' if is_buy else 'SELL'} "
                    f"size={pos_size.size} entry={sig.entry_price:.4f} "
                    f"sl={sig.stop_loss:.4f} tp={sig.take_profit:.4f} res={res}"
                )
            except Exception as e:
                print(f"[Neurabot] ORDER_ERROR {coin}: {e}")

        # Basic pacing
        elapsed = time.time() - loop_start
        sleep_s = max(5.0 - elapsed, 1.0)
        print(f"[Neurabot] Loop completed in {elapsed:.2f}s, sleeping {sleep_s:.2f}s")
        await asyncio.sleep(sleep_s)


def main() -> None:
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("[Neurabot] Shutting down gracefully...")
    except Exception as e:
        print(f"[Neurabot] Fatal error: {e}")
        raise


if __name__ == "__main__":
    main()
