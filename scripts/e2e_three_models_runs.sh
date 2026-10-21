#!/usr/bin/env bash
# ADR-0015 follow-up (2026-10-17): end-to-end single hop under THREE channel-error models x max search depth.
# Same layout as scripts/e2e_throughput_runs.sh (gen 4, GF(2^8), 50 B data segments: df100/300/1000 -> N 3/7/21,
# 7 BERs, cap 64 packets, min_pool_size 4, budget 20000 per search step), but
#   error scope  data_payload | data_tags_only | data_segment   (real BER: every bit of the scope flips iid;
#                coefficients always clean -- ACR-only rule)
#   repair span  segment for every scope (the search may flip salt/tag/MAC/CRC bytes -> tag errors repairable)
#   max HD       1..4   (--hamming-distance)
#   arms         keyless, keyed, crc_acr per HD; crc_arq once per scope (no repair -> HD-independent, run at HD 2)
#   admit        --no-final-check (AdmitConfig.final_check=False: identical admitted packets, fewer ops; tested)
# Order: crc_arq (all scopes, cheap), then HD 2, 4, 1, 3; per HD all scopes; per scope keyless, crc_acr, keyed -> an early stop
# loses HD 3 / keyed first. Re-running resumes every run dir (--resume).
#   bash scripts/e2e_three_models_runs.sh
#   SMOKE=1 bash scripts/e2e_three_models_runs.sh          (3 trials/cell -> $OUT/_smoke)
#   HDS="2 4" SCOPES="data_payload" ARMS="keyless" TRIALS=100 BUDGET=600 WORKERS=4 bash ...
# Output E:/projects/studienarbeit/logs/e2e_throughput/three_models_hd1-4/<scope>/hd<k>/<arm>/raw_trials.csv
# (crc_arq: <scope>/arq/crc_arq), driver log _run.log there.
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH=. LOG_FOLDER=./logs
PY=E:/projects/studienarbeit/.venv/Scripts/python.exe
OUT=E:/projects/studienarbeit/logs/e2e_throughput/three_models_hd1-4
WORKERS=${WORKERS:-4}
TRIALS=${TRIALS:-200}; BUDGET=${BUDGET:-1800}
HDS=${HDS:-"2 4 1 3"}
SCOPES=${SCOPES:-"data_payload data_tags_only data_segment"}
ARMS=${ARMS:-"keyless crc_acr keyed"}
ARQ=${ARQ:-1}
if [ "${SMOKE:-0}" = 1 ]; then TRIALS=${TRIALS_SMOKE:-3}; BUDGET=100000; OUT=$OUT/_smoke; fi
mkdir -p $OUT
exec >> $OUT/_run.log 2>&1
echo "[$(date '+%F %T')] code at $(git rev-parse --short HEAD) + $(git status --porcelain | wc -l) changed files; HDS $HDS SCOPES $SCOPES ARMS $ARMS ARQ $ARQ workers $WORKERS trials $TRIALS budget $BUDGET"

run() {   # run <scope> <hd> <arm> <dir>
  local scope=$1 hd=$2 arm=$3 dir=$4 S=$SECONDS
  mkdir -p "$(dirname $dir)"
  echo "[$(date '+%F %T')] $scope hd$hd $arm start"
  $PY scripts/pareto_sweep.py --stage full --arm $arm --configs "100:3,300:7,1000:21" \
      --bers 1e-5,3e-5,1e-4,3e-4,1e-3,3e-3,1e-2 --trials $TRIALS --cell-budget-s $BUDGET --trial-deadline-s 900 \
      --workers $WORKERS --max-inflight-per-cell $WORKERS --gen-size 4 --strategy acr_only --error-scope $scope \
      --repair-span segment --min-pool-size 4 --pair-budget 20000 --max-packets-factor 16 \
      --hamming-distance $hd --no-final-check --resume $dir >> $dir.log 2>&1
  echo "  exit $?; $(grep -cE '^\[' $dir.log) trial lines; $(grep -E 'done in' $dir.log | tail -1)"
  grep -E "capped|Traceback|Error" $dir.log | tail -40
  echo "[$(date '+%F %T')] $scope hd$hd $arm took $(( (SECONDS-S)/60 )) min"
}

if [ "$ARQ" = 1 ]; then for scope in $SCOPES; do run $scope 2 crc_arq $OUT/$scope/arq/crc_arq; done; fi
for hd in $HDS; do
  for scope in $SCOPES; do
    for arm in $ARMS; do
      [ "$arm" = none ] && continue
      run $scope $hd $arm $OUT/$scope/hd$hd/$arm
    done
  done
done
echo "[$(date '+%F %T')] ALL DONE"
