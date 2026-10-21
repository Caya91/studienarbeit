#!/usr/bin/env bash
# ADR-0015 task 2: two-hop recoding S -> relay -> sink, schemes crc | keyless | keyed x relay policy
# verify | blind, df 100/300/1000 (N 3/7/21), BER 1e-5..1e-2 on both hops, payload-only errors, sink = ACR
# repair (HD 2, budget 20000), cap 40 ticks (10 x gen), 200 paired trials/cell. Per-cell budget 400 s of
# summed trial wall: only the expensive cells (blind keyless/keyed relays whose sink stalls on polluted
# mixtures -- production ACR re-localizes every broken packet every round) get fewer trials (reported).
# Re-running continues (same --out).
#   bash scripts/two_hop_runs.sh            WORKERS=1..4 (default 4)
# Output E:/projects/studienarbeit/logs/two_hop_recoding/runs/main/raw_trials.csv, log _run.log there.
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH=. LOG_FOLDER=./logs
PY=E:/projects/studienarbeit/.venv/Scripts/python.exe
OUT=E:/projects/studienarbeit/logs/two_hop_recoding/runs/main
WORKERS=${WORKERS:-4}
mkdir -p $OUT
echo "[$(date '+%F %T')] start workers $WORKERS" >> $OUT/_run.log
$PY simulation/two_hop_sim.py --sweep --trials 200 --workers $WORKERS --cell-budget-s 400 --max-ticks 40 \
    --out $OUT >> $OUT/_run.log 2>&1
echo "[$(date '+%F %T')] exit $?" >> $OUT/_run.log
