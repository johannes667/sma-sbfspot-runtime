#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${CONFIG_DIR:-/config}"
DATA_DIR="${DATA_DIR:-/data}"
CFG="${SBFSPOT_CFG:-$CONFIG_DIR/SBFspot.cfg}"
INTERVAL="${INTERVAL:-300}"

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

while true; do
  echo "Starting SBFspot run: $(date)"

  if command -v python3 >/dev/null 2>&1 && [ -f /app/main.py ]; then
    python3 /app/main.py || true
  elif command -v SBFspot >/dev/null 2>&1; then
    SBFspot -v -finq -cfg"$CFG" || true
  else
    echo "ERROR: No runnable app found. Neither /app/main.py nor SBFspot exists."
  fi

  echo "Sleeping ${INTERVAL}s..."
  sleep "$INTERVAL"
done