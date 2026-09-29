#!/usr/bin/env bash
# R2/R3 scaling study (2026-09-29), ACR-only recovery, gen_size 6, GF(2^8).
# Chain of long background runs; each step appends to $ROOT/_chain.log. Re-running a step with
# the same --out/--resume continues it (isolated: use a fresh --seed-start to extend).
# Estimated wall (6 workers, fast inner product): ~9-10 h total, see the S/R notes.
#   bash scripts/scaling_acr_runs.sh [step ...]     steps: iso_w_small prod_main iso_w_large iso_hd prod_tags_pay prod_tags_seg
set -u
PY="E:/projects/studienarbeit/.venv/Scripts/python.exe"
ROOT="E:/projects/studienarbeit/logs/scaling_acr"
export LOG_FOLDER=./logs PYTHONPATH=.
BERS="1e-5,3e-5,1e-4,3e-4,1e-3,3e-3,1e-2"
SMALL="100:2 100:3 100:5 100:11 300:2 300:4 300:7 300:13 300:31"
LARGE="1000:2 1000:5 1000:11 1000:21 1000:41"
ALL_CFG="100:2,100:3,100:5,100:11,300:2,300:4,300:7,300:13,300:31,1000:2,1000:5,1000:11,1000:21,1000:41"
mkdir -p "$ROOT"
log() { echo "[$(date '+%F %T')] $*" | tee -a "$ROOT/_chain.log"; }

iso_w() {  # layouts seeds
  for lay in $1; do
    df=${lay%%:*}; n=${lay##*:}
    log "iso_w df=$df N=$n seeds=$2 (arc_only_a/payload)"
    "$PY" simulation/isolated_recovery_sim.py --sweep --seeds "$2" --workers 6 --gen-size 6 --data-fields "$df" \
      --num-data-segments $((n - 1)) --bers "$BERS" --Ws 1,2,3,6 --spans payload --configs arc_only_a \
      --out "$ROOT/iso_w/df${df}_N${n}_payload_errors" >> "$ROOT/iso_w_df${df}_N${n}.log" 2>&1
    log "iso_w df=$df N=$n seeds=$2 (acr_only_data_tags/payload,segment)"
    "$PY" simulation/isolated_recovery_sim.py --sweep --seeds "$2" --workers 6 --gen-size 6 --data-fields "$df" \
      --num-data-segments $((n - 1)) --bers "$BERS" --Ws 1,2,3,6 --spans payload,segment --configs acr_only_data_tags \
      --out "$ROOT/iso_w/df${df}_N${n}_tag_errors" >> "$ROOT/iso_w_df${df}_N${n}.log" 2>&1
  done
}

iso_hd() {
  for lay in $SMALL $LARGE; do
    df=${lay%%:*}; n=${lay##*:}
    log "iso_hd df=$df N=$n seeds=30"
    "$PY" simulation/isolated_recovery_sim.py --sweep --seeds 30 --workers 6 --gen-size 6 --data-fields "$df" \
      --num-data-segments $((n - 1)) --bers "$BERS" --Ws 1,3 --hds 1,2,3,4,5 --budgets 20000 --spans payload \
      --configs arc_only_a --out "$ROOT/iso_hd/df${df}_N${n}" >> "$ROOT/iso_hd_df${df}_N${n}.log" 2>&1
  done
}

prod() {  # scope span trials
  for arm in keyless keyed; do
    log "prod $arm scope=$1 span=$2 trials=$3"
    "$PY" scripts/pareto_sweep.py --stage full --arm "$arm" --configs "$ALL_CFG" --bers "$BERS" --trials "$3" \
      --cell-budget-s 100000 --trial-deadline-s 900 --workers 6 --max-inflight-per-cell 6 --gen-size 6 \
      --strategy acr_only --error-scope "$1" --repair-span "$2" --min-pool-size 6 --pair-budget 20000 \
      --out-root "$ROOT/prod" >> "$ROOT/prod_${1}_${2}_${arm}.log" 2>&1
  done
}

steps=("$@")
[ ${#steps[@]} -eq 0 ] && steps=(iso_w_small prod_main iso_w_large iso_hd prod_tags_pay prod_tags_seg)
for s in "${steps[@]}"; do
  case "$s" in
    iso_w_small)   iso_w "$SMALL" 50 ;;
    iso_w_large)   iso_w "$LARGE" 30 ;;
    iso_hd)        iso_hd ;;
    prod_main)     prod data_payload payload 30 ;;
    prod_tags_pay) prod data_segment payload 20 ;;
    prod_tags_seg) prod data_segment segment 20 ;;
    *) log "unknown step $s" ;;
  esac
  log "step $s done"
done
log "chain done"
