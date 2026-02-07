#!/bin/bash
# Neurabot status helper
# Usage: ./neurabot_status.sh

set -euo pipefail

echo "=== Neurabot Service Status ==="
systemctl is-active neurabot.service || echo "neurabot.service is NOT active"
systemctl --no-pager --full status neurabot.service | sed -n '1,12p' || true

echo
echo "=== Recent Neurabot Logs (last 40 lines) ==="
sudo journalctl -u neurabot.service -n 40 --no-pager || echo "no logs"

echo
echo "=== Disk Usage ==="
df -h | sed -n '1,5p'

# Optional: show open positions/equity using Neurabot's exchange wrapper
if [ -d /mnt/botdisk/neurabot ]; then
  cd /mnt/botdisk
  if [ -d neurabot/.venv ]; then
    source neurabot/.venv/bin/activate
    python3 - << 'PY'
from neurabot.config import load_config
from neurabot.exchange import NeurabotExchange

try:
    cfg = load_config()
    exch = NeurabotExchange.from_config(cfg.exchange)
    equity, withdrawable = exch.get_equity_and_withdrawable()
    positions = exch.get_open_positions()
    print("\n=== Neurabot Account State ===")
    print("Equity:", equity)
    print("Withdrawable:", withdrawable)
    print("Open positions:")
    if not positions:
        print("  (none)")
    else:
        for p in positions:
            print("  ", p)
except Exception as e:
    print("\n[Neurabot] Error fetching account state:", e)
PY
  fi
fi
