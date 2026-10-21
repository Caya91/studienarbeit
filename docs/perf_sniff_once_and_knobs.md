# Per-round sniff-once plan + knob inventory

Written 2026-09-17. Context: high-BER feasibility (`docs/high_ber_feasibility` discussion),
tkt 03 findings, and the idea_list "Option B" perf item.

---

## Part 1 — Plan: per-round sniff-once + incremental trust

### The cost today (measured in code)
`SegmentedScheme.admit` ([integrity_schemes.py:443](../simulation/integrity_schemes.py)) runs **two full
pool-sniffs per round**, each looping over all N segments and calling
`classify_segment_trust` over the *entire* pool:
- **pre-check** ([:465-468](../simulation/integrity_schemes.py)) on `wire_pool` — skip-if-already-decodable gate.
- **post-repair** ([:491-496](../simulation/integrity_schemes.py)) on `report.packets` — the decode-admission gate.

`classify_segment_trust` is stateless and cross-checks every packet against the trusted
core → ~O(pool² · segment) per segment. And `admit` is called on **every arrival**, so the
whole pool is re-sniffed from scratch each time one packet is added. That is the
~2·gen³/round the idea_list flags. (The combined *search* is already memoized by
`pair_cache`, ticket 01 — that part is done; this plan is only about the sniff.)

### The change (two parts)
1. **Share the two sniffs.** Packets untouched by repair have identical bytes in `wire_pool`
   and `report.packets`; their orthogonality results vs a stable trusted core are reusable.
   Compute once, reuse in the post-repair gate for unchanged packets.
2. **Incremental trust per arrival.** Cache the trusted core per segment in
   `SegmentedInstrument`. On a new arrival, self-check + cross-check only the *new* packet
   against the existing core (O(pool·N)), cascading a recompute only when the core actually
   changes — instead of re-classifying all prior packets (O(pool²·N)).

### Effort: ~2–3 focused days
- Incremental trust cache + invalidation in the instrument: ~1 day.
- Sharing pre/post sniff: ~0.5 day.
- **Differential test harness** (the bulk of the value): prove the incremental path returns
  byte-identical trusted sets to the current stateless path across many random
  pools × BER × repair sequences: ~1 day. Without this the results are not trustworthy.

### What can go wrong (correctness hazards)
- **Non-monotonic trust.** A repair mutates a packet's bytes, which can *add and remove*
  members of the trusted core — the cache must invalidate, not just append. Get this wrong
  and packets get trusted that shouldn't be → **silent decodes**, the one failure mode this
  whole scheme exists to drive to zero. This is the headline risk.
- **verify_count cascades.** Trust depends on cross-checking against `verify_count` witnesses
  from the core; if the core changes, previously-trusted packets can flip. Incremental update
  needs a correct dependency cascade, or it silently diverges from the reference.
- **Stale cache after repair** — keying the cache on packet-bytes (hash) not just index is
  mandatory, since repair changes bytes at a fixed index.

### Downsides even if it works
- **Fairness of the compute comparison.** The MAC benchmark arm has the *same* two-sniff
  structure ([:615 & :640](../simulation/integrity_schemes.py)). Optimizing only the keyless arm biases the
  keyless-vs-keyed op-count/wall-clock comparison in the keyless arm's favor. To stay
  like-for-like you must refactor **both** arms, or clearly scope which numbers use which
  algorithm. This roughly doubles the work and the test surface.
- **Result versioning.** tkt 03's op-counts are on the current algorithm; post-refactor
  numbers aren't comparable to them. Note the algorithm version in any mixed reporting.
- **Readability / thesis explainability.** Current `admit` is honest and easy to explain;
  a mutable incremental cache is harder to describe and to defend in the report.

### Sequencing recommendation (important)
This refactor attacks **Wall B (compute/trial-time), not Wall A (decodability)**. It makes
trials cheaper; it does **not** move the BER floor. If the floor at the target BER is
*fundamental* (the overnight vc-sweep suggests it may be at ≥5e-3), doing this refactor first
is wasted effort. **Gate it behind the cheap arrival-cap / verify_count experiment**: only
build sniff-once if (a) trials are decoding but too slow for statistics, or (b) you need
gen≥20, which the current O(gen³)/round makes intractable. Otherwise defer.

---

## Part 2 — Full knob inventory

Vehicle = `scripts/segmented_retransmit_sweep.py`. "CLI?" = settable from that script's
argparse today.

| Knob | Meaning | Value | CLI? | Where to change if not CLI |
|---|---|---|---|---|
| payload | data bytes/packet | 48 (def) | ✅ `--payload` | — |
| gen_size | generation size | 15 (def) | ✅ `--gen-size` | — |
| N (segments) | segment count | list | ✅ `--segments` | — |
| hamming_distance | per-segment repair HD budget | via `--hd` | ✅ `--hd` | — |
| strategy | uniform_hd / coefficient_first | — | ✅ `--strategy` | — |
| ber | bit error rate (one value) | — | ✅ `--ber` | — |
| trials | trials per cell | 100 | ✅ `--trials` | — |
| **max_packets_factor** | **arrival cap = factor·gen** | **12** | ❌ | call site [retransmit:45](../scripts/segmented_retransmit_sweep.py); default [scheme_comparison_sim.py:57](../simulation/scheme_comparison_sim.py) (global — don't edit) |
| **verify_count** | cross-verify witnesses (trust/security dial; None=whole core, 0=off) | 4 | ❌ | cfg build [retransmit:77](../scripts/segmented_retransmit_sweep.py); default [integrity_schemes.py:85](../simulation/integrity_schemes.py) |
| **pair_budget** | per-pair combined-search candidate cap | `SEGMENTED_PAIR_BUDGET` | ❌ | cfg build :77; constant `SEGMENTED_PAIR_BUDGET` (top of integrity_schemes.py), field [:90](../simulation/integrity_schemes.py) |
| min_trust_count | min trusted/segment to admit | 4 | ❌ | :77 / [integrity_schemes.py:86](../simulation/integrity_schemes.py) |
| min_pool_size | min pool before any search | 10 | ❌ | :77 / [:87](../simulation/integrity_schemes.py) |
| decode_verify_count | V for silent-decode fix (ADR default 2) | 2 | ❌ | :77 / [:88](../simulation/integrity_schemes.py) |
| mode | classify mode | per_column | ❌ | :77 / [:78](../simulation/integrity_schemes.py) |
| field m | GF(2^m) size | 8 | ❌ | `create_field(8)` [retransmit:76](../scripts/segmented_retransmit_sweep.py) |

Note: `scheme_comparison_sim.py` has a parallel set as module constants
(`SEGMENTED_NUM_TRIALS`, `SEGMENTED_BIT_ERROR_RATES`, `SEGMENTED_DATA_FIELDS`,
`SEGMENTED_N_VALUES`, `SEGMENTED_CELL_TIME_BUDGET_S`, `GEN_SIZE`, `FIELD_M`) for the
first-class `segmented` entrypoint; those are edited in-source, not by CLI (except
`--cell-time-budget-s`).

Not a knob: **sniff-once / incremental trust** (Part 1) — code, not a parameter.
Not a knob: **robust-trust** — already the only path (`classify_segment_trust` is the
poisoner-tolerant impl); no toggle exists.

---

## Part 3 — Recommendation: which to make CLI knobs

**Add these three to `segmented_retransmit_sweep.py`** (~6 lines: three `add_argument`s +
thread into the `run_recovery_trial` call and `AdmitConfig(...)`):

1. **`--max-packets-factor`** (default 12) — the #1 high-BER measurability lever; turns
   flat-timeout cells into measured overhead numbers. Thread into the `run_recovery_trial`
   call at [retransmit:45](../scripts/segmented_retransmit_sweep.py).
2. **`--verify-count`** (default 4) — the exact dial the overnight vc-sweep was studying;
   security/cost + poisoning behaviour at high BER. Into `AdmitConfig` at :77.
3. **`--pair-budget`** (default = SEGMENTED_PAIR_BUDGET) — governs search cost/trial-time at
   high BER; lets you trade recovery vs wall-clock without editing source. Into `AdmitConfig`.

**Leave in-source (low value as CLI):** `min_trust_count`, `min_pool_size`,
`decode_verify_count`, `mode` — only touched during trust-model studies; expose ad hoc.

**Optional:** `--field-m` only if you revisit small-field (m=4) zero-tag behaviour.
`mode` — no (single mode in use).

Rationale: the three recommended flags are exactly the high-BER experiment's needs — arrival
cap (Wall A / measurability), trust dial (the research question), search budget (Wall B /
trial-time) — and none require touching the shared `AdmitConfig` defaults, so other sims are
unaffected.
