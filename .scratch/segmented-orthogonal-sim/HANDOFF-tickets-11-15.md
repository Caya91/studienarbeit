# Handoff — Isolated recovery comparison (ADR-0013), tickets 11–15

You are picking up an in-progress work item. Read this file first, then the design
doc and the ticket you're working on. Work **one ticket at a time, test-first, and
report back before starting the next** — do not do all five in one go.

## What this work is

A fair, isolated comparison of the RLNC recovery mechanism between two arms:
- **keyless** (orthogonal self/cross tag) and
- **keyed** (homomorphic MAC).

The goal is that the *only* difference between the arms is the acceptance oracle;
everything else about recovery is identical. Full rationale and every decision:

- **`docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md`** — read this in full first.
- **`CONTEXT.md`** — glossary (terms: isolated recovery comparison, helper packet, recovery-acceptance width W, ARC-only recovery, paired ground truth).
- **`.scratch/segmented-orthogonal-sim/issues/11..15-*.md`** — the tickets. Each has a "Done when" checklist. Build to it.

## Current state

- **Ticket 10 (matched W acceptance oracle) is DONE, tested, and committed.** It is the foundation the rest build on.
- Tickets **11, 12, 13, 14, 15 are TODO**, roughly in dependency order:
  - 11 keyed carries gen_size tags but verifies only W → needs 10.
  - 12 ARC-only recovery variant (both arms) → needs 10.
  - 13 the isolated harness (injected trust, paired errors) → needs 10, 11, 12.
  - 14 W sweep + plots → needs 13.
  - 15 elaborate verification + readable smoke output → needs 13, 14.

## What ticket 10 already gave you (frozen — build on these, do not change their defaults)

Both acceptance oracles now take an optional `W` (number of checks a repaired
candidate must pass). `W=None` means "check everything" = the old behaviour, so
existing callers are untouched.

- `is_orthogonal_to_trusted(field, candidate, trusted_packets, W=None)` in `playground/new_recovery.py`
  — always runs the self-check (free, not counted), then checks orthogonality to the **first W** trusted packets (`trusted_packets[:W]`).
- `mac_verify_segment(field, keys, segment_slice, segment, W=None)` in `binary_ext_fields/segmented_mac_tagging.py`
  — verifies the **first W** tags (`keys[:W]` vs the first W tag symbols); asserts `W <= num_keys`.

`W` is already threaded top-to-bottom through both arms
(`binary_ext_fields/segmented_recovery.py`, `binary_ext_fields/segmented_mac_recovery.py`):
`recover_uniform_hd(_mac)` / `recover_coefficient_first(_mac)` → `repair_segment(_mac)`
→ pair search + IC-refinement + unpaired/bit-flip. **`W` is part of both pair-cache
keys** — keep it that way if you touch caching.

Tests for this live in `binary_ext_fields/tests/w_acceptance_width_test.py` — use them as a style template.

## How to run tests (important — easy to get wrong)

- **There is no `pytest` installed.** Each test file is a plain script with a list of
  test functions at the bottom under `if __name__ == "__main__":`. Run the file directly.
- **You MUST set `LOG_FOLDER`** to some existing folder or every run crashes with a
  `Path(None)` TypeError (a logging path, unrelated to the test).
- Set `PYTHONPATH` to the project root and use the project's `.venv` Python.

PowerShell (the user's shell):
```powershell
$env:PYTHONPATH="."; $env:LOG_FOLDER="$env:TEMP\st_logs"; mkdir $env:LOG_FOLDER -ErrorAction SilentlyContinue; .\.venv\Scripts\python.exe binary_ext_fields\tests\w_acceptance_width_test.py
```
Bash-tool equivalent:
```bash
PYTHONPATH=. LOG_FOLDER=/tmp/st_logs .venv/Scripts/python.exe binary_ext_fields/tests/w_acceptance_width_test.py
```

- **Judge pass/fail by EXIT CODE (0 = pass), not by reading output.** Tests print the
  words "error" and "assert" in normal banners, so text-searching gives false alarms.
- When you add a new test function, also add it to the list at the bottom of the file, or it won't run.
- **Two tests are already broken and are NOT your concern:** `rref_test.py`
  (ImportError) and `procedural_rref_test.py` (NameError). They fail on their own; we
  never touched those files. Everything else in `binary_ext_fields/tests/` passes — keep it that way.

## Rules that apply to every ticket

1. **Silent decodes may increase — that is fine.** They are a measured output, not a
   limit. Never fail a test just because silent decodes went up. (Only exception:
   ticket 13's wiring self-check — clean data + large W should give ~0 silent decodes.)
2. **`W` and `verify_count` are two different dials. Don't merge them.** `W` = how many
   checks a *repair* must pass (new, recovery-acceptance). `verify_count` = trust
   classification width (old, sniffing) — leave it alone.
3. **This work is additive.** Do not modify the end-to-end sim, the sniffing path
   (`classify_segment_trust(_mac)`), or the ground-truth check (`check_mac_segmented`,
   `check_orth_segmented`). Add new code beside them. `W=None` defaults must keep every
   existing caller behaving exactly as before.
4. **The keyless arm uses bit-flip search only in this comparison.** The exact linear
   solve (`recover_packet_linear`) is deliberately off so both arms use the same method.
   Do not reintroduce it "to recover more" — that re-breaks the fairness.
5. **ARC's blind spot is the coefficient block.** A packet whose own coefficients are
   corrupted cannot be ARC-localized (`_make_arc_localizer(_mac)` returns `None` for it).
   That is *why* ticket 12's ARC-only config is run two ways (data-only vs whole-packet).

## Per-ticket notes

- **11:** `num_keys = gen_size` is set where the packet layout is built
  (`layout_mac_segments`), not in recovery. Keyed keys are i.i.d. (from
  `generate_keyset`), so first-W independence is free and the qᵂ bound is exact —
  contrast the keyless helper-dependence caveat (already in ADR-0013; measure it, don't fix it).
- **12:** implement ARC-only as a flag/entry that skips the coeff-repair stage, ARC-
  localizes from the injected helper basis, repairs data segments only. Mirror both arms
  exactly except the oracle. Correctness test: ARC-only == coefficient_first on data
  segments when coefficients are clean.
- **13:** pool = fixed `G = gen_size` clean helper packets (ARC basis + keyless
  witnesses, never corrupted/scored) + `T` target packets (corrupted, scored). Inject
  trust from ground truth (skip sniffing). Paired errors: identical corruption on the
  `[coeff | payload]` columns across arms (assert it), tag bytes seed-matched. Ship the
  readable `--smoke` output (see ticket 15 for the exact table format).
- **14:** freeze the CSV schema first (that's what would let plotting be split off).
  Sweep `W ∈ {1,2,3}` × BER × 3 configs × 2 arms. Silent-decode plot is first-class.
- **15:** the finalization gate — full test run green (except the two known-broken rref
  tests), the elaborate correctness checks, and the human-readable smoke report. Only
  then flip ADR-0013's status to DONE with the measured silent-decode numbers recorded.

## Definition of done for the whole item

All of tickets 11–15 checklists satisfied, every test green (bar the two pre-existing
rref failures), and ADR-0013 updated to DONE with results.
