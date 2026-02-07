from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List

import requests

from ..config import NewsConfig


@dataclass
class CoinNewsState:
    last_block_ts: float = 0.0  # unix timestamp when we last saw bad news


@dataclass
class NewsFilter:
    cfg: NewsConfig
    # Global and per-coin block state (very simple for now)
    global_state: CoinNewsState = field(default_factory=CoinNewsState)
    per_coin_state: Dict[str, CoinNewsState] = field(default_factory=dict)

    def _fetch_all_feeds(self) -> List[str]:
        """Fetch RSS feeds and return a list of headlines (strings).

        This is intentionally simple: we only care about headlines for now.
        """
        headlines: List[str] = []
        for url in self.cfg.rss_feeds:
            try:
                resp = requests.get(url, timeout=5)
                if resp.status_code != 200:
                    continue
                text = resp.text.lower()
                # Extremely naive parsing: split on <title> tags
                # and take small chunks. For a production bot you would
                # use a proper RSS parser.
                parts = text.split("<title>")
                for part in parts[1:]:
                    title = part.split("</title>")[0].strip()
                    if title:
                        headlines.append(title)
            except Exception:
                continue
        return headlines

    def _update_state_from_headlines(self, headlines: List[str]) -> None:
        now = time.time()
        for title in headlines:
            for kw in self.cfg.block_keywords:
                if kw.lower() in title.lower():
                    # For now, treat all as global risk-off events.
                    self.global_state.last_block_ts = now
                    break

    def refresh(self) -> None:
        """Fetch feeds and update internal state.

        Should be called periodically (e.g. every few minutes).
        """
        headlines = self._fetch_all_feeds()
        if headlines:
            self._update_state_from_headlines(headlines)

    def is_blocked(self, coin: str) -> bool:
        """Return True if trading should be blocked due to recent bad news."""
        now = time.time()
        cooloff = self.cfg.cool_off_minutes * 60

        # Global block
        if self.global_state.last_block_ts and now - self.global_state.last_block_ts < cooloff:
            return True

        # Per-coin block (not implemented yet, placeholder for future)
        state = self.per_coin_state.get(coin)
        if state and now - state.last_block_ts < cooloff:
            return True

        return False
