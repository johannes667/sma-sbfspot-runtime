#!/usr/bin/env bash
set -euo pipefail
CONFIG_DIR="${CONFIG_DIR:-/config}"
DATA_DIR="${DATA_DIR:-/data}"
CFG="${SBFSPOT_CFG:-$CONFIG_DIR/SBFspot.cfg}"
INTERVAL="${INTERVAL:-300}"
mkdir -p "$CONFIG_DIR" "$DATA_DIR"
if [[ ! -f "$CFG" ]]; then
  cp /config/SBFspot.cfg "$CFG"
  echo "Created default config at $CFG. Please edit it and restart."
fi
cd /
python3 /app/main.py &
WEB_PID=$!
trap 'kill $WEB_PID 2>/dev/null || true' EXIT
while true; do
  python3 /app/collector.py || true
  sleep "$INTERVAL"
done
