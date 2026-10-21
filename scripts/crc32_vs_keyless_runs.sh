#!/usr/bin/env bash
# Keyless vs CRC-32 (ADR-0014): recovery sweeps + detection run.
# gen_size 4 (4 keyless tag bytes/segment == one CRC-32), 50 B data segments (df100 -> 2, df300 -> 6,
# df1000 -> 20 data segments; the layout of the earlier wall-clock/scaling plots), payload errors only
# (arc_only_a), payload repair, HD 1+2, budget 20000, 200 seeds. CRC arms have no W (W = -1 rows).
# CRC = zlib.crc32 (library, C; 2026-10-14). Runtime: ~25 min recovery + ~7 min detection on 10 workers.
# (The first run, pure-Python CRC, is archived in logs/crc32_vs_keyless/_superseded_pure_python_crc/.)
# Output E:/projects/studienarbeit/logs/crc32_vs_keyless/, log _run.log there.
#   bash scripts/crc32_vs_keyless_runs.sh            (from the repo / worktree root)
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH=. LOG_FOLDER=./logs
PY=E:/projects/studienarbeit/.venv/Scripts/python.exe
OUT=E:/projects/studienarbeit/logs/crc32_vs_keyless
mkdir -p $OUT
exec >> $OUT/_run.log 2>&1
echo "[$(date '+%F %T')] code at $(git rev-parse --short HEAD) $(git status --porcelain | wc -l) uncommitted files"

for pair in 100:2 300:6 1000:20; do
  df=${pair%%:*}; n=${pair##*:}
  name=recovery/df${df}_N${n}_seeds200
  echo "[$(date '+%F %T')] $name start"; S=$SECONDS
  $PY simulation/isolated_recovery_sim.py --sweep --workers 10 --seed-start 0 --seeds 200 \
      --gen-size 4 --Ws 1,2,3,4 --configs arc_only_a --spans payload --hds 1,2 --budgets 20000 \
      --data-fields $df --num-data-segments $n --bers 1e-5,3e-5,1e-4,3e-4,1e-3,3e-3,1e-2 \
      --arms keyless,crc_acr,crc_blind --out $OUT/$name 2>&1 | grep --line-buffered -E "sweep done|Error|Traceback"
  echo "[$(date '+%F %T')] $name took $(( (SECONDS-S)/60 )) min"
done

echo "[$(date '+%F %T')] detection start"; S=$SECONDS
$PY simulation/detection_comparison_sim.py --dfs 100,300,1000 --seg-bytes 50 --seeds 50 \
    --mc-k-trials 5000 --mc-ber-rounds 50 --out $OUT/detection/seg50_seeds50 2>&1 | grep -v "^ic|" | tail -80
echo "[$(date '+%F %T')] detection took $(( (SECONDS-S)/60 )) min"
echo "[$(date '+%F %T')] ALL DONE"
