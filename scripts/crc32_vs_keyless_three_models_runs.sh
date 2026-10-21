#!/usr/bin/env bash
# Keyless vs CRC-32 (ADR-0014), three channel-error models x HD 1..4 (user 2026-10-17):
#   arc_only_a         payload only        (data_only)
#   acr_only_tags      tag only            (data_tags_only: salt+tags / CRC bytes, payload clean)
#   acr_only_data_tags payload + tag       (data_segment = payload flips + the same tag flips)
# Real BER injection, repair span = segment (search may flip tag bytes) for all three, budget 20000,
# arms keyless (W 1..4) + crc_acr (blind CRC dropped by the user). 200 seeds, 6 workers.
# Estimate (2-seed smoke, 1 worker, contended): ~380 s/seed -> ~3.5-4.5 h at 6 workers.
#   bash scripts/crc32_vs_keyless_three_models_runs.sh
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH=. LOG_FOLDER=./logs
PY=E:/projects/studienarbeit/.venv/Scripts/python.exe
OUT=E:/projects/studienarbeit/logs/crc32_vs_keyless/recovery_three_models
mkdir -p $OUT
exec >> $OUT/_run.log 2>&1
for pair in 100:2 300:6 1000:20; do
  df=${pair%%:*}; n=${pair##*:}
  name=df${df}_N${n}_seeds200
  echo "[$(date '+%F %T')] $name start"; S=$SECONDS
  $PY simulation/isolated_recovery_sim.py --sweep --workers 6 --seed-start 0 --seeds 200 \
      --gen-size 4 --Ws 1,2,3,4 --configs arc_only_a,acr_only_tags,acr_only_data_tags --spans segment \
      --hds 1,2,3,4 --budgets 20000 --data-fields $df --num-data-segments $n \
      --bers 1e-5,3e-5,1e-4,3e-4,1e-3,3e-3,1e-2 --arms keyless,crc_acr --out $OUT/$name 2>&1 \
      | grep --line-buffered -E "sweep done|Error|Traceback"
  echo "[$(date '+%F %T')] $name took $(( (SECONDS-S)/60 )) min"
done
echo "[$(date '+%F %T')] ALL DONE"
