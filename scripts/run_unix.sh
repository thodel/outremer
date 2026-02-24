#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install requests >/dev/null

# Conservative defaults
export QID_PAGE_SIZE=500
export VALUES_SIZE=200
export SLEEP_S=1.0
export RETRIES=6
export TIMEOUT_QIDS=180
export TIMEOUT_DATA=300

python export_peerage_pre1500.py
echo "Done."
