# 21 — Benchmark the keyless inner product against galois and pyerasure

**In one line:** time the keyless check (GF(2^8) inner products) with library field code — `galois`
and `pyerasure`, both already in the venv — next to our pure-Python `TableField.inner_product`, so the
keyless-vs-CRC wall-clock can also be stated library vs library.
[ADR-0014](../../../docs/adr/0014-keyless-vs-crc32-comparison.md).

**Why:** since 2026-10-14 the CRC-32 arm uses `zlib.crc32` (C). The keyless arm still runs its inner
products as a Python loop over `mul`/`add` table lookups (`binary_ext_fields/custom_field.py`,
~3.2 µs per 55 B inner product vs ~0.13 µs for `zlib.crc32` on 50 B). So the repair wall-clock in
ADR-0014 compares C (CRC) with Python (keyless); a library keyless check closes that gap.

**Status:** FUTURE WORK (user, 2026-10-14) — not scheduled.

## Build to these
1. Microbenchmark, one accept/reject check of one data segment (50 B payload + salt + 4 tags), keyless
   self + W = 0..4 helpers, three backends: `TableField.inner_product` (today), `galois.GF(2**8)`
   arrays (vectorised multiply + XOR-reduce), `pyerasure` field ops (C++). Same field polynomial as
   ours — check results are identical on random vectors before timing anything.
2. Same table with `zlib.crc32` on the 50 B payload as the reference line.
3. Optional: drop the fastest backend into the isolated harness behind a switch (default = today's
   path, op counts unchanged) and re-time `keyless` vs `crc_acr` on the ADR-0014 grid.

## Done when
- [ ] Results identical across backends (asserted).
- [ ] µs per check per backend and W, plus the zlib reference, in a short table + note in ADR-0014.
- [ ] If (3) is done: repair wall-clock keyless (library) vs crc_acr (zlib), same seeds as ADR-0014.

**Related, separate idea:** both checks are linear in the error, so a repair candidate can be checked
from precomputed single-bit syndromes in O(HD) XORs instead of recomputing over the whole segment —
for keyless and CRC alike. That would make per-candidate cost length-independent for both arms.

**Blocked by:** —.
