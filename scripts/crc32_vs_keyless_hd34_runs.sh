#!/usr/bin/env bash
# Keyless vs CRC-32 (ADR-0014): HD3 + HD4 recovery sweeps, extending scripts/crc32_vs_keyless_runs.sh (HD1+2).
# Same grid and code as that run -- gen_size 4, 50 B data segments (df100 -> 2, df300 -> 6, df1000 -> 20
# data segments), payload errors only (arc_only_a), payload repair, budget 20000, seeds 0..199 (paired
# with the HD1/2 run: same pools + same bit flips per seed/BER) -- only --hds 3,4 and 4 workers.
# No detection step (HD-independent, already in detection/).
# Runtime 2026-10-16 (4 workers, machine shared with other runs): df100 9 min, df300 34 min, df1000 ~100 min.
# (That run's df1000 died after seeds 0..9 -- machine-level fork failure; seeds 10..199 were rerun with the
# same args, --seed-start 10 --seeds 190, into recovery/df1000_N20_hd34_seeds10-199; seeds 0..9 are in
# recovery/df1000_N20_hd34_seeds0-9. The plot script pools both.)
# Output E:/projects/studienarbeit/logs/crc32_vs_keyless/recovery/df*_N*_hd34_seeds200 (same root:
# scripts/crc32_vs_keyless_plots.py pools them with the HD1/2 runs), log _run_hd34.log there.
#   bash scripts/crc32_vs_keyless_hd34_runs.sh            (from the repo / worktree root)
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH=. LOG_FOLDER=./logs
PY=E:/projects/studienarbeit/.venv/Scripts/python.exe
OUT=E:/projects/studienarbeit/logs/crc32_vs_keyless
WS=1,2,3,4
BERS=1e-5,3e-5,1e-4,3e-4,1e-3,3e-3,1e-2
SEEDS=200
mkdir -p $OUT
exec >> $OUT/_run_hd34.log 2>&1
echo "[$(date '+%F %T')] code at $(git rev-parse --short HEAD) $(git status --porcelain | wc -l) uncommitted files;" \
     "Ws $WS, BERs $BERS, seeds 0..$((SEEDS-1)), hds 3,4, 4 workers"

for pair in 100:2 300:6 1000:20; do
  df=${pair%%:*}; n=${pair##*:}
  name=recovery/df${df}_N${n}_hd34_seeds${SEEDS}
  echo "[$(date '+%F %T')] $name start"; S=$SECONDS
  $PY simulation/isolated_recovery_sim.py --sweep --workers 4 --seed-start 0 --seeds $SEEDS \
      --gen-size 4 --Ws $WS --configs arc_only_a --spans payload --hds 3,4 --budgets 20000 \
      --data-fields $df --num-data-segments $n --bers $BERS \
      --arms keyless,crc_acr,crc_blind --out $OUT/$name 2>&1 | grep --line-buffered -E "sweep done|Error|Traceback"
  echo "[$(date '+%F %T')] $name took $(( (SECONDS-S)/60 )) min"
done
echo "[$(date '+%F %T')] ALL DONE"
