#!/usr/bin/env bash
set -euo pipefail
CONFIG_DIR="${CONFIG_DIR:-/config}"
DATA_DIR="${DATA_DIR:-/data}"
CFG="${SBFSPOT_CFG:-$CONFIG_DIR/SBFspot.cfg}"
APP_CFG="${APP_CONFIG_FILE:-$CONFIG_DIR/config.yaml}"
mkdir -p "$CONFIG_DIR" "$DATA_DIR"
if [[ ! -f "$CFG" ]]; then
  cp /config/SBFspot.cfg.example "$CFG"
  echo "Created default SBFspot config at $CFG. Please edit it and restart the container."
fi
if [[ ! -f "$APP_CFG" ]]; then
  python3 - <<'PY'
from config import ensure_default_config, APP_CONFIG_FILE
if ensure_default_config():
    print(f"Created default app config at {APP_CONFIG_FILE}")
PY
fi
cd /
python3 /app/main.py &
WEB_PID=$!
trap 'kill $WEB_PID 2>/dev/null || true' EXIT
while true; do
  python3 /app/collector.py || true
  INTERVAL_SECONDS="$(python3 - <<'PY'
from config import INTERVAL
print(INTERVAL)
PY
)"
  sleep "${INTERVAL_SECONDS:-300}"
done
