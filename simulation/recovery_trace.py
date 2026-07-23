"""Follow-along trace of a SINGLE recovery scenario -- the debug companion to the
recovery_sim.py sweeps.

Where run_sweep aggregates thousands of trials into rates and op-counts, this shows
ONE small generation end to end: the clean pool, the error you injected, how sniffing
classifies the packets, (for arc_localized) which columns ARC localizes, and exactly
what each mode does to each packet. Everything is printed as an aligned byte table
with the corrupted/changed columns marked, so you can literally follow a packet from
clean -> polluted -> recovered.

Tweak the KNOBS block, run, read. When a scenario behaves as you expect here, scale it
up in recovery_sim.py.

Run:
  export LOG_FOLDER="E:\\projects\\studienarbeit\\logs"
  export PYTHONPATH="E:\\projects\\studienarbeit"
  .venv/Scripts/python.exe simulation/recovery_trace.py
"""
import random

from icecream import ic
ic.disable()  # the recoverer/sniffer icecream-dump on every call; keep the trace clean

from binary_ext_fields.custom_field import create_field, CountingField
from binary_ext_fields.generate_symbols import (
    generate_symbols_until_nonzero,
    recode_rlnc_without_coeffs,
    check_orth,
)
from binary_ext_fields.pollution import pollute_generation, pollute_random
from playground.arc_pl import error_into_packet, localize_errors
from playground.sniffing import sniff_pool
from playground.new_recovery import recover_generation_bitflip, _basis_full_rank


# -- KNOBS - tweak these, everything below adapts ------------------------------
FIELD_M       = 8            # GF(2^m)
GEN_SIZE      = 3            # coefficient block width = full-rank basis size
DATA_FIELDS   = 2            # data symbols per packet (before the tag)
POOL_SIZE     = 8            # recoded packets in the pool (> GEN_SIZE so a basis survives)
SEED          = 7            # reproducible pollution + error injection

# How to corrupt the pool. "manual" = precise, deterministic, easy to reason about;
# "random" = the sweep's pollute_random at a given BER (still seeded).
ERROR_MODE    = "manual"
# manual: list of (packet_index, column, hamming_distance) errors. Columns < GEN_SIZE
# are COEFFICIENT columns (watch arc_localized go blind there); columns >= GEN_SIZE are
# data/tag columns (all three modes can repair a single one).
MANUAL_ERRORS = [(0, GEN_SIZE + 1, 1)]   # one data-column single-bit flip in packet 0
BIT_ERROR_RATE = 0.02                    # only used when ERROR_MODE == "random"

MODES_TO_RUN  = ["per_column", "whole_packet", "arc_localized"]
VERIFY_COUNT  = None         # None = check against all trusted packets; int caps the oracle
HAMMING_BUDGET = 1           # bits the recoverer may flip per candidate

# Sniffing thresholds, scaled down for a small pool.
MIN_TRUST_COUNT = 2
MIN_POOL_SIZE   = 4
# ------------------------------------------------------------------------------


def _diff_cols(a: bytearray, b: bytearray) -> list[int]:
    """Column indices where two packets differ."""
    return [i for i in range(min(len(a), len(b))) if a[i] != b[i]]


def print_gen(title: str, gen: list[bytearray], ref: list[bytearray] | None = None,
              gen_size: int = GEN_SIZE, mark_rows: dict[int, str] | None = None) -> None:
    """Aligned byte table. A '|' separates the coefficient block from data/tag columns.
    If `ref` is given, cells that differ from ref are wrapped in >..< so changes pop.
    `mark_rows` maps packet index -> short tag printed after the row (e.g. 'BROKEN').
    """
    mark_rows = mark_rows or {}
    width = max((len(str(v)) for pkt in gen for v in pkt), default=2) + 2

    ncols = max((len(p) for p in gen), default=0)
    header = "        "
    for c in range(ncols):
        if c == gen_size:
            header += " |"
        header += f"{c:>{width}}"
    print(f"\n{title}")
    print(header + "     (| = coeff|data boundary)")

    for idx, pkt in enumerate(gen):
        changed = set(_diff_cols(pkt, ref[idx])) if ref is not None else set()
        row = f"  P[{idx:>2}] "
        for c, v in enumerate(pkt):
            if c == gen_size:
                row += " |"
            cell = f">{v}<" if c in changed else str(v)
            row += f"{cell:>{width}}"
        tag = mark_rows.get(idx, "")
        if changed:
            tag = (tag + f"  dcols={sorted(changed)}").strip()
        if tag:
            row += f"    {tag}"
        print(row)


def build_clean_pool(field):
    source = generate_symbols_until_nonzero(field, DATA_FIELDS, GEN_SIZE, coefficients=True)
    pool = recode_rlnc_without_coeffs(field, source, GEN_SIZE, count=POOL_SIZE)
    assert check_orth(field, pool), "clean recoded pool must be pairwise orthogonal"
    return pool


def inject_errors(field, pool):
    polluted = [bytearray(p) for p in pool]
    if ERROR_MODE == "manual":
        for pkt_idx, col, ham in MANUAL_ERRORS:
            polluted[pkt_idx] = error_into_packet(polluted[pkt_idx], col, ham)
    elif ERROR_MODE == "random":
        polluted = pollute_generation(field, [bytearray(p) for p in pool], BIT_ERROR_RATE, pollute_random)
    else:
        raise ValueError(f"unknown ERROR_MODE {ERROR_MODE!r}")
    return polluted


def narrate_sniff(field, polluted, original):
    broken_idx, trusted_idx = sniff_pool(field, polluted, MIN_TRUST_COUNT, MIN_POOL_SIZE)
    truly_polluted = [i for i in range(len(polluted)) if polluted[i] != original[i]]
    print("\n-- Sniffing --")
    print(f"  broken (self-check failed): {broken_idx}")
    print(f"  trusted:                    {trusted_idx}")
    print(f"  ground-truth polluted:      {truly_polluted}")
    missed = sorted(set(truly_polluted) - set(broken_idx))
    if missed:
        print(f"  ! sniff MISSED (polluted but not flagged broken): {missed}")
    return broken_idx, trusted_idx


def narrate_localize(field, polluted, original, broken_idx, trusted_idx):
    """arc_localized only: show the full-rank gate and per-packet localized columns,
    and cross-check them against the ground-truth corrupted columns so the ARC blind
    spot (coefficient-block errors it can never localize) is called out explicitly.
    """
    trusted_packets = [bytearray(polluted[i]) for i in trusted_idx]
    basis = trusted_packets[:GEN_SIZE]
    print("\n-- ARC localization (arc_localized) --")
    if len(trusted_idx) < GEN_SIZE:
        print(f"  only {len(trusted_idx)} trusted < gen_size={GEN_SIZE} -> mode would return 'waiting'")
        return
    full_rank = _basis_full_rank(field, basis, GEN_SIZE)
    print(f"  basis = trusted[:{GEN_SIZE}] = {trusted_idx[:GEN_SIZE]}  full_rank={full_rank}")
    if not full_rank:
        print("  basis not full rank -> mode would return 'waiting'")
        return
    for row in broken_idx:
        cols = sorted(localize_errors(field, [bytearray(p) for p in basis], bytearray(polluted[row]), GEN_SIZE))
        true_cols = _diff_cols(polluted[row], original[row])
        # Any real error inside the coefficient block (< GEN_SIZE) can never appear in
        # candidate_columns -- ARC re-encodes FROM those coefficients, so it trusts them.
        missed = [c for c in true_cols if c not in cols]
        print(f"  packet {row}: candidate_columns={cols}  actual_corrupted={true_cols}")
        if any(c < GEN_SIZE for c in true_cols):
            print(f"      -> BLIND SPOT: real error(s) in coefficient block {[c for c in true_cols if c < GEN_SIZE]} "
                  f"cannot be localized; candidate_columns point at data columns instead.")
        elif missed:
            print(f"      -> localization did not cover corrupted columns {missed}.")


def verdict(original, polluted, recovered):
    """Per-packet outcome for the packets that were actually polluted."""
    print("  per-packet verdict:")
    any_polluted = False
    for i in range(len(original)):
        if polluted[i] == original[i]:
            continue
        any_polluted = True
        if recovered[i] == original[i]:
            v = "RECOVERED (== original)"
        elif recovered[i] != polluted[i]:
            v = f"SILENT FAILURE (changed to a wrong value; dorig={_diff_cols(recovered[i], original[i])})"
        else:
            v = "unrecovered (left as polluted)"
        print(f"    P[{i:>2}]: {v}")
    if not any_polluted:
        print("    (nothing was polluted)")


def main():
    random.seed(SEED)
    field = create_field(FIELD_M)

    print("=" * 70)
    print(f"RECOVERY TRACE  m={FIELD_M} gen_size={GEN_SIZE} data={DATA_FIELDS} "
          f"pool={POOL_SIZE} seed={SEED}")
    print(f"error_mode={ERROR_MODE}  verify_count={VERIFY_COUNT}  hamming_budget={HAMMING_BUDGET}")
    print("=" * 70)

    pool = build_clean_pool(field)
    original = [bytearray(p) for p in pool]
    print_gen("[1] CLEAN generation (pairwise orthogonal)", original)

    polluted = inject_errors(field, pool)
    print_gen("[2] POLLUTED generation (>v< = changed vs clean)", polluted, ref=original)

    broken_idx, trusted_idx = narrate_sniff(field, polluted, original)

    for mode in MODES_TO_RUN:
        print("\n" + "-" * 70)
        print(f"MODE: {mode}")
        if mode == "arc_localized":
            narrate_localize(field, polluted, original, broken_idx, trusted_idx)

        cnt = CountingField(field)
        recovered, status = recover_generation_bitflip(
            cnt, polluted, GEN_SIZE, HAMMING_BUDGET, mode=mode, verify_count=VERIFY_COUNT,
            min_trust_count=MIN_TRUST_COUNT, min_pool_size=MIN_POOL_SIZE,
        )
        print(f"\n  status={status}  mul_ops={cnt.mul_count}  add_ops={cnt.add_count}")
        # Compare recovered against the clean original: >v< marks columns still/again wrong.
        print_gen(f"[3] RECOVERED via {mode} (>v< = differs from clean original)",
                  recovered, ref=original)
        verdict(original, polluted, recovered)

    print("\n" + "=" * 70)
    print("Tip: set MANUAL_ERRORS to a COEFFICIENT column (< gen_size) to watch")
    print("arc_localized go blind while per_column still repairs it.")


if __name__ == "__main__":
    main()
