#!/usr/bin/env bash
set -e
STATE_FILE="${DATA_DIR:-/data}/state.json"
test -f "$STATE_FILE"
python3 - <<'PY'
import json, os, sys
path=os.path.join(os.environ.get('DATA_DIR','/data'),'state.json')
with open(path, encoding='utf-8') as f: s=json.load(f)
if s.get('status') not in ('online','error','waiting','config_missing'): sys.exit(1)
PY
