# Neurabot Heartbeat

On heartbeat, quickly check Neurabot's health and trading status.

## Checklist

1. **Service health**
   - Command:
     - `systemctl is-active neurabot.service`
   - If result is `active` → OK.
   - If not `active` (e.g., `failed` or `inactive`):
     - Report that Neurabot is not running.
     - Suggest: `sudo systemctl restart neurabot.service`.

2. **Recent logs**
   - Command:
     - `journalctl -u neurabot.service -n 40 --no-pager`
   - Scan for:
     - `ORDER` or `ORDER_ERROR` lines → trading attempts.
     - `Traceback` or obvious Python errors.
     - Repeated "Scheduled restart job" messages (crash loop).
   - Summarize:
     - Are there recent orders?
     - Are there repeated errors or restarts?

3. **Positions & equity**
   - Use Neurabot's exchange wrapper (or hyperbot context) to fetch:
     - Current equity / withdrawable.
     - Open positions count and any large/unusual ones.
   - Note if:
     - No positions for a long time (possible no-signal or data issue).
     - Positions look stuck (e.g., small equity, many small positions).

4. **Data health (optional deeper check)**
   - If Neurabot is running but no trades for a long time:
     - Check whether candles are being fetched:
       - Look for debug lines like `Coin X candles=...` in Neurabot logs.
     - Check if signals are being generated:
       - Look for `Signals generated: [...]` logs.

## Response Format

- If **nothing needs attention**:
  - Reply: `HEARTBEAT_OK`
- If **something needs attention** (service down, crash loop, no trades, etc.):
  - Briefly report:
    - Service status.
    - Any recent errors or restart loops.
    - Whether Neurabot seems to be trading (recent ORDER logs) or idle.
  - Do **not** silently restart or patch; report the situation and suggest the next safe step.

## Notes

- Heartbeat is for **lightweight monitoring**, not deep surgery.
- Use it to alert Aditya if Neurabot is down, crash-looping, or clearly not trading when it should be.
- For big fixes (strategy changes, new data sources, major code edits), follow the guidance in `NEURABOT_SKILL.md` and coordinate explicitly.
