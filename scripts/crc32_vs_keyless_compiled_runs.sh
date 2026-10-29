#!/usr/bin/env bash
# Keyless vs CRC-32 (ADR-0014) rerun with the COMPILED keyless check (field backend numba_check,
# 2026-10-29): the whole keyless acceptance check = one numba call, CRC = zlib.crc32 (C).
# Same grid, arms and seeds as scripts/crc32_vs_keyless_runs.sh (HD1+2) + _hd34_runs.sh (HD3+4), here
# in ONE sweep per payload size (--hds 1,2,3,4) so all HDs share a session: gen_size 4, 50 B data
# segments (df100 -> 2, df300 -> 6, df1000 -> 20), arc_only_a, payload repair, budget 20000, seeds 0..199.
# Outcomes / op counts are identical to the table run (simulation/field_backend_test.py); only the time
# columns differ. Then the detection run with --field-backend numba_check (changes verify_time only).
# Output E:/projects/studienarbeit/logs/crc32_vs_keyless_compiled/, log _run.log there.
#   bash scripts/crc32_vs_keyless_compiled_runs.sh [SEEDS] [OUT]   (from the repo root; defaults 200, above)
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH=. LOG_FOLDER=./logs NUMBA_NUM_THREADS=1
PY=E:/projects/studienarbeit/.venv/Scripts/python.exe
SEEDS=${1:-200}
OUT=${2:-E:/projects/studienarbeit/logs/crc32_vs_keyless_compiled}
mkdir -p $OUT
exec >> $OUT/_run.log 2>&1
echo "[$(date '+%F %T')] code at $(git rev-parse --short HEAD) $(git status --porcelain | wc -l) uncommitted files;" \
     "seeds 0..$((SEEDS-1)), hds 1-4, 10 workers, field backend numba_check"

for pair in 100:2 300:6 1000:20; do
  df=${pair%%:*}; n=${pair##*:}
  name=recovery/df${df}_N${n}_seeds${SEEDS}
  echo "[$(date '+%F %T')] $name start"; S=$SECONDS
  $PY simulation/isolated_recovery_sim.py --sweep --workers 10 --seed-start 0 --seeds $SEEDS \
      --gen-size 4 --Ws 1,2,3,4 --configs arc_only_a --spans payload --hds 1,2,3,4 --budgets 20000 \
      --data-fields $df --num-data-segments $n --bers 1e-5,3e-5,1e-4,3e-4,1e-3,3e-3,1e-2 \
      --arms keyless,crc_acr,crc_blind --field-backend numba_check --out $OUT/$name 2>&1 \
      | grep --line-buffered -E "sweep done|Error|Traceback"
  echo "[$(date '+%F %T')] $name took $(( SECONDS-S )) s"
done

echo "[$(date '+%F %T')] detection start"; S=$SECONDS
$PY simulation/detection_comparison_sim.py --dfs 100,300,1000 --seg-bytes 50 --seeds 50 \
    --mc-k-trials 5000 --mc-ber-rounds 50 --field-backend numba_check \
    --out $OUT/detection/seg50_seeds50 2>&1 | grep -v "^ic|" | tail -80
echo "[$(date '+%F %T')] detection took $(( SECONDS-S )) s"
echo "[$(date '+%F %T')] ALL DONE"
