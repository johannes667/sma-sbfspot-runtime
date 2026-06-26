#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${CONFIG_DIR:-/config}"
DATA_DIR="${DATA_DIR:-/data}"
CFG="${SBFSPOT_CFG:-$CONFIG_DIR/SBFspot.cfg}"
INTERVAL="${INTERVAL:-300}"
WEB_PORT="${WEB_PORT:-8088}"

mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$DATA_DIR/logs"

echo "Using config: $CFG"
echo "Using data dir: $DATA_DIR"

if [ ! -f "$CFG" ]; then
  echo "ERROR: $CFG not found."
  echo "Please create SBFspot.cfg in your Unraid appdata config folder."
  echo "Example path: /mnt/user/appdata/sma-sbfspot/SBFspot.cfg"
  sleep 3600
  exit 1
fi

echo "Config found."

# Web UI im Hintergrund starten
if command -v python3 >/dev/null 2>&1 && [ -f /app/main.py ]; then
  echo "Starting Web UI on port ${WEB_PORT}..."
  python3 /app/main.py &
else
  echo "WARNING: /app/main.py not found. Web UI will not start."
fi

# SBFspot zyklisch starten
while true; do
  echo "Starting SBFspot run: $(date)"

  if command -v SBFspot >/dev/null 2>&1; then
    cd /usr/local/bin
    ./SBFspot -cfg"$CFG" -v -finq || true
    python3 /app/update_state.py || true
  else
    echo "ERROR: SBFspot not found."
  fi

  echo "Sleeping ${INTERVAL}s..."
  sleep "$INTERVAL"
done