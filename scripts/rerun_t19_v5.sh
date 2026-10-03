#!/usr/bin/env bash
# Ticket-19 HD sweeps rerun after the keyed pair-fallback budget fix (f63b1be), main branch.
# Same args/seeds as logs/isolated_recovery_v4/_run_t18_t19_v4.sh (T19a + T19b only).
# Output logs/isolated_recovery_v5/, plots logs/isolated_recovery_plots/v5_*, log _run.log.
#   bash scripts/rerun_t19_v5.sh
set -u
cd E:/projects/studienarbeit
export PYTHONPATH=. LOG_FOLDER=./logs
PY=E:/projects/studienarbeit/.venv/Scripts/python.exe
V4=E:/projects/studienarbeit/logs/isolated_recovery_v4
V5=E:/projects/studienarbeit/logs/isolated_recovery_v5
PL=E:/projects/studienarbeit/logs/isolated_recovery_plots
mkdir -p $V5
exec >> $V5/_run.log 2>&1
step() {  # name, sweep args..., last arg = plot out dir
  local name=$1; shift; local plots=${@: -1}; set -- "${@:1:$(($#-1))}"
  echo "[$(date '+%F %T')] $name start"; local S=$SECONDS
  $PY simulation/isolated_recovery_sim.py --sweep --workers 10 --gen-size 6 --data-fields 18 \
      --configs arc_only_a,arc_only_b --out $V5/$name "$@" 2>&1 | grep --line-buffered -E "sweep done|Error|Traceback"
  echo "[$(date '+%F %T')] $name sweep took $(( (SECONDS-S)/60 )) min"
  $PY scripts/isolated_recovery_plots_from_csv.py --runs $V5/$name --out $PL/$plots 2>&1 | grep -v Warning | tail -12
  $PY scripts/compare_keyed_fix_runs.py $V4/$name $V5/$name --out $V5/$name/compare_v4_v5.csv
}
step t19a_payload_hd1-5_seeds0-799 --seed-start 0 --seeds 800 --Ws 1,2,3 --spans payload \
     --hds 1,2,3,4,5 --budgets 20000,none v5_t19a_hd_payload
step t19b_segment_hd1-5_seeds0-299 --seed-start 0 --seeds 300 --Ws 1,2,3 --spans segment \
     --hds 1,2,3,4,5 --budgets 20000 v5_t19b_hd_segment
echo "[$(date '+%F %T')] ALL DONE (v5)"
