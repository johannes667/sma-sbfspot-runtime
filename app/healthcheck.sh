#!/usr/bin/env bash
test -f "${DATA_DIR:-/data}/state.json" || exit 1
python3 - <<'PY'
import json, os, sys
with open(os.path.join(os.environ.get('DATA_DIR','/data'),'state.json')) as f: s=json.load(f)
sys.exit(0 if s.get('status') in ('online','error','config_missing','waiting') else 1)
PY
