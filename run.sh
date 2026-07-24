#!/usr/bin/env bash
# Launch the ICC scanner. Loads credentials from a local .env file (not committed).
#
# Examples:
#   ./run.sh --oanda                    # one live scan on real spot data
#   ./run.sh --oanda --telegram         # ...+ Telegram alerts
#   ./run.sh --oanda --telegram --paper # ...+ auto paper-execute setups (demo)
#   ./run.sh --demo                     # offline synthetic test
#
# To run continuously: use cron (see below) — the weekly cap persists between runs.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a; . ./.env; set +a
else
  echo "No .env found. Copy .env.example -> .env and fill it in (or set env vars manually)."
fi

exec python3 scanner.py "$@"

# --- run every 15 minutes with cron (uncomment + edit path) ---
# crontab -e
# */15 * * * * cd /FULL/PATH/trading_bot && set -a && . ./.env && set +a && python3 scanner.py --oanda --telegram >> scan.log 2>&1
