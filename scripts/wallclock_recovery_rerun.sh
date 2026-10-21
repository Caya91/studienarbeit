#!/usr/bin/env bash
# 2026-10-09: rerun of the R2/R3 isolated recovery timings (iso_w, arc_only_a, payload, W 1,6) on current
# code (after keyed pair-fallback fix f63b1be). Same layouts/seeds/BERs as scripts/scaling_acr_runs.sh.
#   bash scripts/wallclock_recovery_rerun.sh
set -u
PY="E:/projects/studienarbeit/.venv/Scripts/python.exe"
ROOT="E:/projects/studienarbeit/logs/wallclock/recovery_rerun"
export LOG_FOLDER=./logs PYTHONPATH=.
BERS="1e-5,3e-5,1e-4,3e-4,1e-3,3e-3,1e-2"
mkdir -p "$ROOT"
log() { echo "[$(date '+%F %T')] $*" | tee -a "$ROOT/_chain.log"; }
run() {  # layouts seeds
  for lay in $1; do
    df=${lay%%:*}; n=${lay##*:}
    log "iso_w df=$df N=$n seeds=$2"
    "$PY" simulation/isolated_recovery_sim.py --sweep --seeds "$2" --workers 6 --gen-size 6 --data-fields "$df" \
      --num-data-segments $((n - 1)) --bers "$BERS" --Ws 1,6 --spans payload --configs arc_only_a \
      --out "$ROOT/iso_w/df${df}_N${n}_payload_errors" >> "$ROOT/iso_w_df${df}_N${n}.log" 2>&1
  done
}
run "100:2 100:3 100:5 100:11 300:2 300:4 300:7 300:13 300:31" 50
run "1000:2 1000:5 1000:11 1000:21 1000:41" 30
log "chain done"
