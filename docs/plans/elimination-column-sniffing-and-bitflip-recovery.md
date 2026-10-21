status: proposed
owner: (unassigned)

# Plan: elimination-based column sniffing + joint bit-flip recovery

## Purpose

Add two new functions that recover a broken packet **without requiring `gen_size` trusted
packets** and **without solving a linear system for the byte values** — a deliberately
different arm from the existing ADR-0002/ADR-0003 pipeline (`localize_errors` +
`recover_packet_linear`), for comparison purposes (see "Open question" below).

1. **`sniff_columns`** — identifies which column(s) of a broken packet are corrupted, using
   only however many trusted packets are actually available (no `gen_size` gate), and over
   the packet's full width (coefficients included, not just data+tag columns).
2. **`recover_columns_bitflip`** — given the candidate columns from (1), repairs them purely
   by brute-force bit-flipping + orthogonality re-check (reusing the existing bit-flip
   primitives), never solving `Ax=b`.

Read `CONTEXT.md` and ADR-0001 through ADR-0004 before touching code — this plan assumes
that vocabulary (Generation, Self-tag, Cross-tag, Localization, Sniffing, Acceptance oracle)
and does not redefine it here.

## Why this is a different arm, not a replacement

ADR-0002 chose the linear solve over bit-flip search *because* bit-flip alone has no
discriminating power (self-tag "passes" at any column — see CONTEXT.md's Self-tag entry).
That reasoning still holds. This plan does not reopen ADR-0002/ADR-0003 for the case where
`gen_size` trusted packets are available — that path is fine as-is.

What's new: the *localization* step no longer needs a full decode, so it no longer needs
`gen_size` trusted packets (see conversation history / the elimination argument below). Once
localization narrows things down to a small candidate column set, this plan intentionally
recovers the *value* via bit-flip instead of the linear solve — even though the linear solve
would already be available almost for free at that point (see open question).

## Prerequisite bug found — must fix before `sniff_columns` will work

`solve_recovery_system` (`playground/new_recovery.py:51`) is supposed to get a free
consistency check from surplus trusted rows beyond the `K` needed to solve (this is exactly
what ADR-0002 documents: *"Any surplus rows beyond K aren't needed for the solve but double
as a free consistency check"*). **It currently does not do this.** It only checks that the
first `K` pivot rows equal 1; it never inspects rows `K..len(matrix)-1` for a nonzero
residual in the appended `b` column.

Verified by running against the real field/tagging code (not the toy example from the
conversation): `create_field(4)`, `gen_size=3`, `data_fields=2`, 6 recoded packets, 1
corrupted, 5 trusted packets passed in (`K=1`, so 4 rows are pure surplus). Both the *true*
broken column and a deliberately *wrong* column returned a "solved" value instead of the
wrong one returning `None`:

```
num trusted: 5
true column 3  -> solved: [14]
wrong column 4 -> solved: [6]      # should be None — 5 trusted rows is 5x more than needed to reject this
```

This means today, with any number of trusted packets, a single-column hypothesis on the
*wrong* column will still "solve" — surplus trusted packets currently buy zero extra
confidence. `sniff_columns`'s entire elimination mechanism depends on this being fixed, since
elimination *is* "reject the hypothesis whose surplus rows are inconsistent."

**Proposed minimal fix**, in `solve_recovery_system` after the existing pivot-value loop:

```python
for i in range(K, len(solved_rref)):
    if solved_rref[i][K] != 0:
        return None
```

`_cleanup_rref` already reduces columns `0..K-1` to zero in every row (pivot rows included),
so surplus rows should already carry `0` in those columns and only the appended `b` column
is left to check — this is a small addition, not a new algorithm. Confirm this against a
handful of known-good and known-bad cases (see Testing plan) before relying on it.

## Function 1: `sniff_columns`

**Location**: new file `playground/elimination_localize.py`, alongside `arc_pl.py` (don't
edit `localize_errors` itself — it's the correct implementation of the ADR-0002/0003 path
and should stay untouched).

**Signature (draft)**:
```python
def sniff_columns(
    field: TableField,
    broken_packet: bytearray,
    trusted_packets: list[bytearray],
    max_error_columns: int = 3,
    column_range: range | None = None,   # default: range(0, len(broken_packet)) — coefficients included
) -> set[int] | None:
```
Returns the identified candidate column set, or `None` if nothing resolves within
`max_error_columns`.

**Algorithm** (reuses `build_recovery_system` / `solve_recovery_system` unchanged, once the
prerequisite fix above lands):

```
for K' in 1 .. max_error_columns:
    if len(trusted_packets) < K': continue   # can't even attempt this size yet
    survivors = []
    for S in combinations(column_range, K'):
        matrix = build_recovery_system(field, broken_packet, list(S), trusted_packets)
        solved = solve_recovery_system(field, matrix, K')
        if solved is not None:
            survivors.append(S)
    if len(survivors) == 1:
        return set(survivors[0])          # uniquely localized
    if len(survivors) > 1:
        return None-or-ambiguous-signal    # see "ambiguous result" below — do not guess
    # len(survivors) == 0 -> escalate to K'+1
return None   # nothing found up to max_error_columns
```

**Do not prune across `K'` levels.** A true simultaneous 2-column error will generally leave
*zero* single-column survivors (see the worked example from the conversation — a genuine
multi-column error is exactly the signal to escalate, not to seed the next round from). Each
`K'` round searches the full `column_range` combinations, not just descendants of the
previous round's survivors.

**Ambiguous result contract**: if more than one candidate set of the same size `K'` survives,
that means the currently-available trusted packets can't disambiguate — don't guess. Return
a distinguishable "ambiguous" result (e.g. return the list of tied candidate sets, or `None`
plus a logged reason) so the caller can choose to wait for more trusted packets or hand all
tied candidates to `recover_columns_bitflip` for a final acceptance-oracle-based tiebreak.

**Complexity**: `C(N, K')` subsets per round, `N = len(broken_packet)` (now includes the
coefficient prefix per the "coefficients are data-like too" decision). Cheap for `K' <= 3` at
realistic packet widths; cap `max_error_columns` to keep it that way.

## Function 2: `recover_columns_bitflip`

**Location**: `playground/new_recovery.py`, next to the existing `recover_packet_bitflip`
(generalizes it from one column to a set — keep the original single-column function as-is
for anything still calling it, add a new one rather than changing its signature).

**Signature (draft)**:
```python
def recover_columns_bitflip(
    field: TableField,
    broken_packet: bytearray,
    candidate_columns: set[int],
    trusted_packets: list[bytearray],
    hamming_distance: int = 1,
) -> tuple[bytearray, bool]:
```

**Algorithm**: for each column in `candidate_columns`, enumerate flip candidates via the
existing `bit_flip_candidates` (`binary_ext_fields/bitops.py:13`) up to `hamming_distance`;
try the **joint Cartesian product** across all candidate columns (not one column at a time —
a genuine joint error at 2+ columns generally won't verify as orthogonal until all of them
are simultaneously corrected). For each combination, apply it to a working copy and check:

- `check_orth_packet(field, candidate)` (self-tag), **and**
- `check_orth(field, trusted_packets + [candidate])` (full acceptance oracle, per ADR-0001 —
  self-tag alone has no discriminating power per CONTEXT.md's Self-tag entry, so it is
  necessary but never sufficient).

First combination that passes both wins. Return `(candidate_packet, True)`, or
`(broken_packet, False)` if the whole joint search space is exhausted.

**Cost caveat, flag prominently**: the joint search space is
`product_over_columns(sum_{d=1..hamming_distance} C(8, d))`. For `|candidate_columns| = 1`
this is identical in cost to the existing `recover_packet_bitflip`. For `|candidate_columns|
= 2, hamming_distance = 1` it's `8 * 8 = 64` combinations — still cheap. Growth is
multiplicative per extra candidate column, so this only stays viable because
`sniff_columns` is expected to return small `K'` (1–3) in the common case; if it doesn't,
that's a signal to fall back rather than brute-force a large joint space.

## Open question to resolve before/while implementing

`solve_recovery_system`, once the prerequisite fix lands, will already produce the exact
solved byte values as part of confirming a candidate set is consistent inside
`sniff_columns` — the linear-solve answer is sitting right there. Using bit-flip instead for
the actual value-recovery step is presumably intentional, to give the thesis two independently
measurable recovery strategies (linear-solve cost vs. bit-flip cost, via `CountingField`'s
op-counting — see `binary_ext_fields/custom_field.py` and the recent
"Countingfield Subclass" commit) that share the same localization step. **Confirm this
reading before implementing** — if it's right, `sniff_columns`'s internal solve step should
discard the solved values and only keep the column indices, to avoid smuggling the "cheaper"
answer into what's supposed to be a bit-flip-only comparison arm.

## Coefficients in scope for corruption — what this changes

- `column_range` for `sniff_columns` defaults to the *whole* packet (`0..len(packet)-1`), not
  `broken_packet[gen_size:]` like `localize_errors` uses. This is a deliberate difference from
  the existing ACR localization, not an oversight.
- `sniff_pool` (`playground/sniffing.py`) should already catch a corrupted coefficient in a
  *trusted* packet candidate, since `check_orth_packet`/cross-checks operate on the whole
  vector including the coefficient prefix — but this has not been explicitly tested with a
  coefficient-column corruption case. Add a test for this rather than assuming it (see
  Testing plan).

## Integration point (later, not required for a first working version)

Once both functions work standalone, `recover_generation`
(`playground/new_recovery.py:139`) could gain an alternate branch that runs
`sniff_columns` + `recover_columns_bitflip` when `len(trusted_idx) < gen_size` (today it
just returns `"waiting"` in that case — see ADR-0003). Not in scope for this plan; call it
out as a follow-up so it doesn't get bundled into the same change.

## Files to touch

- New: `playground/elimination_localize.py` (`sniff_columns`)
- Edit: `playground/new_recovery.py` (fix `solve_recovery_system`; add
  `recover_columns_bitflip`)
- Tests: extend `binary_ext_fields/tests/recovery_pipeline_test.py`, or add
  `playground/tests/elimination_localize_test.py` if a clean split is preferred

## Testing plan

1. Unit test the prerequisite fix in isolation: reproduce the exact repro above
   (`create_field(4)`, `gen_size=3`, `data_fields=2`, wrong-column hypothesis with surplus
   trusted rows) and assert it now returns `None`.
2. `sniff_columns`: single corrupted data column, single corrupted tag column, single
   corrupted **coefficient** column, and a genuine 2-column simultaneous corruption — assert
   the right set is returned for each, and that the 2-column case doesn't falsely resolve at
   `K'=1`.
3. `sniff_columns` ambiguity case: deliberately supply too few trusted packets so more than
   one column survives at some `K'`, assert the ambiguous-result contract fires instead of
   guessing.
4. `recover_columns_bitflip`: single-column case should match `recover_packet_bitflip`'s
   existing behavior; 2-column joint case should require both flips together (assert flipping
   only one column does not pass the acceptance oracle first).
5. End-to-end: corrupt a packet with `< gen_size` trusted packets available, run
   `sniff_columns` → `recover_columns_bitflip`, assert `check_orth` over the whole pool
   afterward (ADR-0001's ground-truth check, same as `recover_generation`'s final check).

## References

- `CONTEXT.md` — Generation, Self-tag, Cross-tag, Localization, Recovery, Sniffing,
  Acceptance oracle
- `docs/adr/0001-recovery-acceptance-oracle.md`
- `docs/adr/0002-recovery-solves-linear-system-instead-of-bitflip-search.md`
- `docs/adr/0003-defer-recovery-until-enough-trusted-packets.md`
- `docs/adr/0004-sniffing-trust-model.md`
- `playground/arc_pl.py` (`localize_errors` — untouched by this plan)
- `playground/new_recovery.py` (`build_recovery_system`, `solve_recovery_system`,
  `recover_packet_bitflip`, `recover_packet_linear`, `recover_generation`)
- `playground/sniffing.py` (`sniff_pool`)
- `binary_ext_fields/bitops.py` (`bit_flip_candidates`)
- `binary_ext_fields/rref.py` (`calculate_rref`, `invert_pivot_rows`, `_cleanup_rref`)
