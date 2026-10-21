#!/usr/bin/env bash
# ADR-0015 task 1: end-to-end transmissions + goodput vs BER, conventional ARQ baseline.
# scripts/pareto_sweep.py, one run dir per arm: keyless / keyed (acr_only repair), crc_arq (CRC-32 ARQ:
# drop + resend), crc_acr (CRC-32 + ACR repair, S-PRAC-like). gen_size 4, GF(2^8), 50 B data segments
# (df100 -> N3, df300 -> N7, df1000 -> N21), payload-only errors, HD 2, budget 20000, cap 64 packets
# (16 x gen), 200 trials/cell; per-cell budget 1800 s of summed trial wall -> only the decodability-floor
# cells (every trial times out) get fewer trials. Re-running continues each arm (--resume <arm dir>).
#   bash scripts/e2e_throughput_runs.sh [arm ...]        (default: keyless keyed crc_arq crc_acr)
#   SMOKE=1 bash scripts/e2e_throughput_runs.sh          (2 trials/cell -> $OUT/_smoke)
#   WORKERS=3 ...                                         (default 4; machine shared with other agents)
# Output E:/projects/studienarbeit/logs/e2e_throughput/runs/<arm>/raw_trials.csv, log _run.log there.
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH=. LOG_FOLDER=./logs
PY=E:/projects/studienarbeit/.venv/Scripts/python.exe
OUT=E:/projects/studienarbeit/logs/e2e_throughput
WORKERS=${WORKERS:-4}
TRIALS=200; BUDGET=1800; SUB=runs
if [ "${SMOKE:-0}" = 1 ]; then TRIALS=2; BUDGET=100000; SUB=_smoke; fi
mkdir -p $OUT/$SUB
exec >> $OUT/$SUB/_run.log 2>&1
arms=("$@"); [ ${#arms[@]} -eq 0 ] && arms=(keyless keyed crc_arq crc_acr)
echo "[$(date '+%F %T')] code at $(git rev-parse --short HEAD) + $(git status --porcelain | wc -l) changed files; arms ${arms[*]} workers $WORKERS trials $TRIALS"
for arm in "${arms[@]}"; do
  echo "[$(date '+%F %T')] $arm start"; S=$SECONDS
  $PY scripts/pareto_sweep.py --stage full --arm $arm --configs "100:3,300:7,1000:21" \
      --bers 1e-5,3e-5,1e-4,3e-4,1e-3,3e-3,1e-2 --trials $TRIALS --cell-budget-s $BUDGET --trial-deadline-s 900 \
      --workers $WORKERS --max-inflight-per-cell $WORKERS --gen-size 4 --strategy acr_only --error-scope data_payload \
      --repair-span payload --min-pool-size 4 --pair-budget 20000 --max-packets-factor 16 \
      --resume $OUT/$SUB/$arm >> $OUT/$SUB/$arm.log 2>&1
  echo "  exit $?; $(grep -cE '^\[' $OUT/$SUB/$arm.log) trial lines; $(grep -E 'done in' $OUT/$SUB/$arm.log | tail -1)"
  grep -E "capped|Traceback|Error" $OUT/$SUB/$arm.log | tail -40
  echo "[$(date '+%F %T')] $arm took $(( (SECONDS-S)/60 )) min"
done
echo "[$(date '+%F %T')] ALL DONE"
