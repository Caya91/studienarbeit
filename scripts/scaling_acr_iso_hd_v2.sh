#!/usr/bin/env bash
# Rerun of scaling_acr_runs.sh step iso_hd after the keyed pair-fallback budget fix (f63b1be).
# Same args; output to iso_hd_v2/ so the stale iso_hd/ stays for comparison. ~2.2-2.5 h (6 workers).
#   bash scripts/scaling_acr_iso_hd_v2.sh
set -u
cd E:/projects/studienarbeit
export LOG_FOLDER=./logs PYTHONPATH=.
PY="E:/projects/studienarbeit/.venv/Scripts/python.exe"
ROOT="E:/projects/studienarbeit/logs/scaling_acr"
BERS="1e-5,3e-5,1e-4,3e-4,1e-3,3e-3,1e-2"
LAYOUTS="100:2 100:3 100:5 100:11 300:2 300:4 300:7 300:13 300:31 1000:2 1000:5 1000:11 1000:21 1000:41"
log() { echo "[$(date '+%F %T')] $*" | tee -a "$ROOT/_chain_iso_hd_v2.log"; }

for lay in $LAYOUTS; do
  df=${lay%%:*}; n=${lay##*:}
  log "iso_hd_v2 df=$df N=$n seeds=30"
  "$PY" simulation/isolated_recovery_sim.py --sweep --seeds 30 --workers 6 --gen-size 6 --data-fields "$df" \
    --num-data-segments $((n - 1)) --bers "$BERS" --Ws 1,3 --hds 1,2,3,4,5 --budgets 20000 --spans payload \
    --configs arc_only_a --out "$ROOT/iso_hd_v2/df${df}_N${n}" >> "$ROOT/iso_hd_v2_df${df}_N${n}.log" 2>&1
done
log "iso_hd_v2 done"
