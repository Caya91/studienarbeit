# 21 — Benchmark the keyless inner product against galois and pyerasure

**In one line:** time the keyless check (GF(2^8) inner products) with library field code — `galois`
and `pyerasure`, both already in the venv — next to our pure-Python `TableField.inner_product`, so the
keyless-vs-CRC wall-clock can also be stated library vs library.
[ADR-0014](../../../docs/adr/0014-keyless-vs-crc32-comparison.md).

**Why:** since 2026-10-14 the CRC-32 arm uses `zlib.crc32` (C). The keyless arm still runs its inner
products as a Python loop over `mul`/`add` table lookups (`binary_ext_fields/custom_field.py`,
~3.2 µs per 55 B inner product vs ~0.13 µs for `zlib.crc32` on 50 B). So the repair wall-clock in
ADR-0014 compares C (CRC) with Python (keyless); a library keyless check closes that gap.

**Status:** DONE (2026-10-16, branch `feat/galois-keyless`) — verdict: the libraries do NOT speed up the
keyless check at 55 B vectors (per-call overhead > the pure-Python loop). Results below.

## Build to these
1. Microbenchmark, one accept/reject check of one data segment (50 B payload + salt + 4 tags), keyless
   self + W = 0..4 helpers, three backends: `TableField.inner_product` (today), `galois.GF(2**8)`
   arrays (vectorised multiply + XOR-reduce), `pyerasure` field ops (C++). Same field polynomial as
   ours — check results are identical on random vectors before timing anything.
2. Same table with `zlib.crc32` on the 50 B payload as the reference line.
3. Optional: drop the fastest backend into the isolated harness behind a switch (default = today's
   path, op counts unchanged) and re-time `keyless` vs `crc_acr` on the ADR-0014 grid.

## Done when
- [x] Results identical across backends (asserted).
- [x] µs per check per backend and W, plus the zlib reference, in a short table + note in ADR-0014.
- [x] If (3) is done: repair wall-clock keyless (library) vs crc_acr (zlib), same seeds as ADR-0014.

## Results (2026-10-16)

Code: `binary_ext_fields/field_backends.py` (backends = CountingField subclasses overriding only
`inner_product`, op counting verbatim), harness `--field-backend table|galois|pyerasure|numba`
(`simulation/isolated_recovery_sim.py`, default `table` = byte-identical smoke), test
`simulation/field_backend_test.py`, bench `scripts/inner_product_backend_bench.py`, runs
`scripts/crc32_vs_keyless_galois_runs.sh`, plot knobs `--runs` / `--keyless-backend`
(`scripts/crc32_vs_keyless_plots.py`). Output `logs/crc32_vs_keyless_galois/` (bench/, recovery/,
plots_{galois,table,numba}/, ratio_by_backend.csv).

- **Identity**: galois / pyerasure full 256x256 mul tables == ours (modulus 0x11D = x^8+x^4+x^3+x^2+1,
  also galois' default); 5000 random vectors + 7500 oracle calls (real slices, bit-flipped, W 0..4)
  identical; harness test: sweep (4 arms, W 0/1/4, BER to 3e-2) + smoke identical outcomes and ops.
  Rerun: target_outcomes + all op/CRC-byte columns identical to the main run (seeds 0..49, 4200 rows)
  for every backend.
- **µs per check** (55 B slice; min of 15 repeats, one process, loaded machine; harness path):

  | backend | IP 55 B | W=0 | W=4 |
  |---|---|---|---|
  | table (pure Python, today) | 5.0 | 6.5 | 31 |
  | galois public API (np.dot per call) | 114 | 98 | 613 |
  | galois public batched (M @ c) | – | 148 | 148 |
  | galois compiled ufunc per call (= harness `galois`) | 8.6 | 13.4 | 56 |
  | galois compiled ufunc batched | – | 13.1 | 14.1 |
  | pyerasure 1.3.0 | 44 | 54 | 217 |
  | numba own kernel (compiled, NOT a library) | 1.3 | 2.3 | 10.2 |
  | zlib: crc32 raw 50 B / crc_verify_segment | 0.13 | 1.2 | 1.2 |

- **Why galois loses**: call overhead, not arithmetic. FieldArray view 3.4 µs (`GF._view`) / 14 µs
  (verifying `.view(GF)`), np.dot 70 µs, `@` 110–290 µs (Python reshape/astype + a numba
  `parallel=True` kernel launch — would also spawn threads on every core). Its compiled ufunc called
  directly still costs ~6–9 µs (ufunc dispatch + XOR-reduce + 2 frombuffers). Batched only wins at
  W >= 2 when every product is computed, but the repair search rejects >= 99 % of candidates at the
  self-check (1 inner product), so per-call cost decides.
- **pyerasure 1.3.0 is pure Python** ("a tool for learning", FullTable lists, Python Encoder) — no C++.
- **Repair wall-clock, crc_acr / keyless W=4** (ratio of means, same session, same seeds):

  | BER | table | galois | numba |
  |---|---|---|---|
  | <= 3e-4 | 0.67–0.99 | 0.57–1.18 | 0.81–0.93 |
  | 1e-3 | 0.55–0.62 | 0.39–0.42 | 0.80–0.85 |
  | 3e-3 | 0.45–0.47 | 0.27–0.28 | 0.75–0.79 |
  | 1e-2 | 0.38–0.39 | 0.20–0.22 | 0.70–0.74 |

  keyless time vs table: galois 1.4–2.0x slower at BER >= 1e-3, numba 0.5–0.9x. crc_acr times agree
  across the three runs within ~0.95–1.25x (load drift), so the within-run ratio is the robust number.
  ACR (row ops on the tables) is identical in all backends and shared by keyless/crc_acr.
- **Recommendation**: keep `table` as the reported keyless implementation; state that galois/pyerasure
  are slower at this vector size. For a compiled-vs-compiled statement cite the numba backend
  (labelled own kernel): per check 2.3 µs vs CRC 1.2 µs (W=0), repair crc_acr/keyless 0.7–0.9.

**Related, separate idea:** both checks are linear in the error, so a repair candidate can be checked
from precomputed single-bit syndromes in O(HD) XORs instead of recomputing over the whole segment —
for keyless and CRC alike. That would make per-candidate cost length-independent for both arms.

**Blocked by:** —.
