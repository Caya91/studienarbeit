#!/usr/bin/env bash
# Keyless vs CRC-32 repair wall-clock with a LIBRARY keyless check (ticket 21, ADR-0014 addendum 2026-10-16).
# ADR-0014 HD2 grid (gen 4, W 1,4, arc_only_a, payload spans, budget 20000, 7 BERs, arms keyless/crc_acr/
# crc_blind), seeds 0..49. Per payload size the three keyless inner-product backends run back to back in
# one session, so their crc_acr/keyless ratios are compared under the same machine load:
#   galois (library)  -> recovery/df{df}_N{n}_hd2_seeds50/
#   table  (Python)   -> recovery/df{df}_N{n}_hd2_table_seeds50/   (= the main run's code path)
#   numba  (own compiled kernel, reference, not a library) -> recovery/df{df}_N{n}_hd2_numba_seeds50/
# 2 workers (shared machine). Smoke estimate: ~25 min total.
#   bash scripts/crc32_vs_keyless_galois_runs.sh            (from the repo / worktree root)
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH=. LOG_FOLDER=./logs NUMBA_NUM_THREADS=1
PY=E:/projects/studienarbeit/.venv/Scripts/python.exe
OUT=E:/projects/studienarbeit/logs/crc32_vs_keyless_galois
mkdir -p $OUT
exec >> $OUT/_run.log 2>&1
echo "[$(date '+%F %T')] code at $(git rev-parse --short HEAD) $(git status --porcelain | wc -l) uncommitted files"

for pair in 100:2 300:6 1000:20; do
  df=${pair%%:*}; n=${pair##*:}
  for backend in galois table numba; do
    tag=$([ $backend = galois ] && echo "" || echo "_$backend")
    name=recovery/df${df}_N${n}_hd2${tag}_seeds50
    echo "[$(date '+%F %T')] $name start (field backend $backend)"; S=$SECONDS
    $PY simulation/isolated_recovery_sim.py --sweep --workers 2 --seed-start 0 --seeds 50 \
        --gen-size 4 --Ws 1,4 --configs arc_only_a --spans payload --hds 2 --budgets 20000 \
        --data-fields $df --num-data-segments $n --bers 1e-5,3e-5,1e-4,3e-4,1e-3,3e-3,1e-2 \
        --arms keyless,crc_acr,crc_blind --field-backend $backend --out $OUT/$name 2>&1 \
        | grep --line-buffered -E "sweep done|Error|Traceback"
    echo "[$(date '+%F %T')] $name took $(( SECONDS-S )) s"
  done
done
echo "[$(date '+%F %T')] ALL DONE"
