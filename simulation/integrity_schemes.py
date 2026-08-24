"""Pluggable integrity schemes for the baseline comparison (ADR-0009, ADR-0011).

The recovery/decode loop and the attack loop both reduce to the same skeleton --
build a source generation, then per round: recode -> attach a tag -> pollute ->
append -> admit (verify / repair / drop) -> try to decode. Only *attach* and
*admit* differ between schemes, so we factor those (plus source construction, the
overhead figure, and a native op counter) behind an `IntegrityScheme` and let the
driver (`scheme_comparison_sim.py`) stay scheme-agnostic.

Two schemes here:
- `OrthogonalScheme`  -- the project's own homomorphic self-tag. Its `attach` is a
  no-op (the tag rides along under recoding for free) and its `admit` reuses the
  *unchanged* validated internals `recover_generation_bitflip` + `_accepted_packets`
  from `recovery_decode_sim`, so it reproduces the standalone sim as a cross-check.
- `HmacScheme` -- keyed HMAC-SHA-256 truncated to 128 bits. Detect-and-drop.

The CRC baseline is not here: ADR-0011 refocused it as a standalone single-packet
Hamming-distance recovery study (`simulation/crc_recovery.py` /
`crc_recovery_sim.py`) with its own pure functions, not an `IntegrityScheme`.
(The plain CRC-32 detect-and-drop `CrcScheme` once here, and its short-lived
Fly-PRAC dependent-group replacement, were both retired.) The homomorphic-MAC
benchmark that will join this file as a second recovery-capable scheme is the
deferred phase 2 (ADR-0011).

The decisive asymmetry (see ADR-0009): the orthogonal tag survives RLNC recoding
and REPAIRS, so it needs fewer transmissions; HMAC does not survive recoding
(it only works here because the recovery sim is single-hop) and can only DROP.

Computation is measured in each scheme's *native* primitive (field muls, HMAC
block compressions) -- they are incommensurable, so we never sum them into one
number (ADR-0009, docs/comparison_methodology_notes.md). The RLNC decode itself
is common to all schemes and is charged to a *separate* CountingField by the
driver, kept out of the per-scheme op counts.
"""

import hashlib
import hmac
import math
import os
import random
from dataclasses import dataclass, field

from binary_ext_fields.custom_field import CountingField, TableField
from binary_ext_fields.generate_symbols import (
    generate_identity_coefficients,
    generate_symbols_until_nonzero,
)
from binary_ext_fields.pollution import pollute_intelligent
from binary_ext_fields.segmented_tagging import layout_segments, tag_generation_segmented
from binary_ext_fields.segmented_recovery import (
    classify_segment_trust, recover_coefficient_first, recover_uniform_hd,
)
from binary_ext_fields.segmented_mac_tagging import (
    layout_mac_segments, generate_keyset, tag_generation_mac,
)
from binary_ext_fields.segmented_mac_recovery import (
    classify_segment_trust_mac, recover_coefficient_first_mac, recover_uniform_hd_mac,
)
from simulation.recovery_decode_sim import _accepted_packets, recover_generation_bitflip
from simulation.crc_recovery import CrcInstrument, recover as crc_recover
from playground.arc_pl import localize_errors
from playground.new_recovery import _basis_full_rank


# ── Tag widths (ADR-0009) ─────────────────────────────────────────────────────
HMAC_TAG_BYTES = 16        # HMAC-SHA-256 truncated to 128 bits
CRC_WIDTH = 16             # comparison CRC width -- CRC-16, the PRAC/S-PRAC/QPPR anchor
CRC_TAG_BYTES = 2          # 16-bit tag = 2 bytes
CRC_WHOLE_BUDGET = 100_000 # whole-packet (no-localization) per-packet candidate cap
SEGMENTED_PAIR_BUDGET = 100_000  # recover_pair_by_combined_search candidate cap, per pair (ADR-0012)


@dataclass
class AdmitConfig:
    """Receiver-side admission knobs. Only the orthogonal scheme reads them; CRC and
    HMAC ignore all of it (a MAC is self-sufficient -- no cross-verify, no warm-up)."""
    hamming_distance: int = 1
    mode: str = "per_column"
    verify_count: int | None = 4
    min_trust_count: int = 4
    min_pool_size: int = 10
    decode_verify_count: int = 2      # ADR default V=2 (silent-decode fix)
    # Segmented scheme only (ADR-0012): per-pair combined-search candidate cap. Must
    # scale WITH hamming_distance -- a higher HD whose corrections sit past this budget
    # is pure wasted search (measured: HD3 at 100k = same recovery as HD2, 4.4x wall).
    pair_budget: int = SEGMENTED_PAIR_BUDGET


# ── Native op-count instruments ───────────────────────────────────────────────
# Orthogonal uses CountingField directly (mul_count / add_count). HMAC uses this
# tiny counter so its tagging/verification work is charged in its own primitive,
# comparable to the field-op count only in spirit, never in units.

@dataclass
class HmacInstrument:
    """HMAC-SHA-256 with a block-compression counter and the shared key. HMAC =
    H((k^opad) || H((k^ipad) || m)); SHA-256 processes 64-byte blocks with a 9-byte
    length/padding tail, and HMAC prepends one keyed block to each of the two hashes.
    block_ops counts total compression-function calls (the dominant HMAC cost)."""
    key: bytes
    block_ops: int = 0

    def mac(self, data: bytes) -> bytes:
        inner_blocks = math.ceil((64 + len(data) + 9) / 64)   # ipad block + message
        outer_blocks = math.ceil((64 + 32 + 9) / 64)          # opad block + inner digest
        self.block_ops += inner_blocks + outer_blocks
        return hmac.new(self.key, data, hashlib.sha256).digest()[:HMAC_TAG_BYTES]


# ── Scheme interface ──────────────────────────────────────────────────────────
class IntegrityScheme:
    """attach/admit are the only per-scheme parts of the loop; the rest is shared."""
    name: str = "base"

    def make_source(self, base_field, data_fields, gen_size):
        """Return (source, source_suffix): the identity-coefficient generation the
        sender codes over, and the ground-truth suffix (per row, the bytes after the
        gen_size coefficient block) that `_try_decode` grades the decode against."""
        raise NotImplementedError

    def new_instrument(self, base_field):
        """A fresh native op counter for one trial (also holds per-trial key state)."""
        raise NotImplementedError

    def attach(self, instrument, code_packet: bytearray) -> bytearray:
        """Sender: produce the on-wire packet from the recoded code packet. Charged
        to `instrument`. Orthogonal = identity (homomorphic tag already present)."""
        raise NotImplementedError

    def admit(self, instrument, wire_pool, gen_size, cfg: AdmitConfig):
        """Receiver: from the polluted on-wire pool, return the list of code packets
        (tag stripped) that may enter the decode basis -- verifying, repairing, or
        dropping per the scheme. Return None to signal "waiting" (skip decode this
        round). Charged to `instrument`."""
        raise NotImplementedError

    def tag_overhead_bits(self, gen_size, m) -> int:
        raise NotImplementedError

    def op_counts(self, instrument) -> dict:
        """Native op counts as a dict (for CSV columns)."""
        raise NotImplementedError

    def primary_ops(self, instrument) -> int:
        """The single headline op count for this scheme's plots."""
        raise NotImplementedError


class OrthogonalScheme(IntegrityScheme):
    """The homomorphic self-tag. attach is free; admit reuses the validated
    recover_generation_bitflip + _accepted_packets unchanged, so this arm reproduces
    recovery_decode_sim (scheme_ops here + the driver's decode ops == that sim's
    mul_ops). Packet layout: [gen_size coeffs | data_fields data | gen_size tags]."""
    name = "orthogonal"

    def make_source(self, base_field, data_fields, gen_size):
        source = generate_symbols_until_nonzero(base_field, data_fields, gen_size, coefficients=True)
        source_suffix = [bytearray(p[gen_size:]) for p in source]
        return source, source_suffix

    def new_instrument(self, base_field):
        return CountingField(base_field)

    def attach(self, instrument, code_packet: bytearray) -> bytearray:
        # Homomorphic: the recoded packet is already self-orthogonal, tag included.
        return bytearray(code_packet)

    def admit(self, instrument, wire_pool, gen_size, cfg: AdmitConfig):
        repaired, status = recover_generation_bitflip(
            instrument, wire_pool, gen_size, cfg.hamming_distance, mode=cfg.mode,
            verify_count=cfg.verify_count, min_trust_count=cfg.min_trust_count,
            min_pool_size=cfg.min_pool_size,
        )
        if status == "waiting":
            return None
        return _accepted_packets(instrument, repaired, cfg.decode_verify_count, cfg.min_pool_size)

    def tag_overhead_bits(self, gen_size, m) -> int:
        return gen_size * m

    def op_counts(self, instrument) -> dict:
        return {"field_mul": instrument.mul_count, "field_add": instrument.add_count}

    def primary_ops(self, instrument) -> int:
        return instrument.mul_count


class _MacScheme(IntegrityScheme):
    """Detect-and-drop machinery, currently used by the keyed HMAC baseline only
    (kept as its own base class in case a second MAC-style scheme is added later).

    Packet layout: [gen_size coeffs | data_fields data] + tag_bytes. The tag covers
    the whole code packet (coeffs+data) and is appended for transmission; the whole
    wire packet (tag included) is exposed to the channel BER. On receipt the tag is
    recomputed over the received code and compared byte-for-byte; a mismatch drops
    the packet (no repair -- RLNC redundancy supplies a replacement). tag_bytes and
    the tag function are provided by subclasses."""
    tag_bytes: int = 0

    def _tag(self, instrument, code: bytes) -> bytes:
        raise NotImplementedError

    def make_source(self, base_field, data_fields, gen_size):
        # Plain random data with identity coefficients -- no orthogonal tag block.
        max_int = base_field.max_value
        symbols = [bytearray(random.randint(0, max_int) for _ in range(data_fields))
                   for _ in range(gen_size)]
        source = generate_identity_coefficients(base_field, symbols)
        source_suffix = [bytearray(p[gen_size:]) for p in source]
        return source, source_suffix

    def attach(self, instrument, code_packet: bytearray) -> bytearray:
        tag = self._tag(instrument, bytes(code_packet))
        return bytearray(code_packet) + bytearray(tag)

    def admit(self, instrument, wire_pool, gen_size, cfg: AdmitConfig):
        accepted = []
        for wire in wire_pool:
            code = wire[:-self.tag_bytes]
            recv_tag = bytes(wire[-self.tag_bytes:])
            if self._tag(instrument, bytes(code)) == recv_tag:
                accepted.append(bytearray(code))   # verified -> strip tag, enter basis
        return accepted

    def tag_overhead_bits(self, gen_size, m) -> int:
        return self.tag_bytes * 8


class HmacScheme(_MacScheme):
    name = "hmac"
    tag_bytes = HMAC_TAG_BYTES

    def new_instrument(self, base_field):
        # Fresh source<->receiver key per trial; the on-path relay never holds it
        # (end-to-end, minimum-scope model of ADR-0009).
        return HmacInstrument(key=os.urandom(32))

    def _tag(self, instrument, code: bytes) -> bytes:
        return instrument.mac(code)

    def op_counts(self, instrument) -> dict:
        return {"hmac_block_ops": instrument.block_ops}

    def primary_ops(self, instrument) -> int:
        return instrument.block_ops


# ── CRC recovery baseline (ADR-0011, phase 3) ─────────────────────────────────
# Unlike HMAC (detect-and-drop), the CRC arm REPAIRS: a packet whose CRC fails is
# bit-flip searched (HD 1..3) for a candidate whose CRC matches, exactly the
# standalone crc_recovery.recover primitive, now embedded in the send-until-decodable
# generation loop. Two variants share this class:
#   crc_localized -- ACR-localized (localize_errors flags the suspect byte-columns
#     from the trusted basis; only those bits are searched). Gives CRC the SAME
#     algebraic localization the orthogonal arm gets -- the fair fight (ADR-0011).
#   crc_whole     -- no localization: search every bit, budget-capped. The bare-CRC
#     floor; slow, and blind to structure.
# Channel model: the whole wire (tag included) rides the BER, same as every other
# arm. A corrupted tag makes the CRC target wrong, so such a packet just fails to
# repair and is dropped -> a retransmission, folded into overhead + completion time.

@dataclass
class CrcBundle:
    """Per-trial CRC state: the field (for ARC localization), the native CRC op
    counter, and a repair cache. Because a failing packet's bytes never change and
    localization is basis-independent once the basis is full rank, each distinct
    failing packet need be searched only once per trial -- the cache makes the
    whole-packet variant tractable inside the every-round pool re-scan."""
    base_field: TableField
    crc: CrcInstrument
    repair_cache: dict = field(default_factory=dict)


def _suspect_bits(base_field, basis, code: bytes, gen_size: int) -> set[int]:
    """ARC-localized suspect bit positions for `code` (coeffs+data, no tag): the bits
    of every byte-column localize_errors flags as corrupted. Empty when the error is
    in the coefficient block (localize_errors' intrinsic blind spot) -> that packet is
    unrepairable in localized mode, a measurable gap vs whole-packet search."""
    cols = localize_errors(base_field, [bytearray(b) for b in basis], bytearray(code), gen_size)
    return {8 * c + b for c in cols for b in range(8)}


class CrcScheme(_MacScheme):
    """CRC-16 tag + bit-flip repair. Reuses _MacScheme's make_source/attach/overhead
    (identical [coeffs|data]+tag layout); only admit differs (repair, not drop)."""
    width = CRC_WIDTH
    tag_bytes = CRC_TAG_BYTES
    whole_budget = CRC_WHOLE_BUDGET

    def __init__(self, localized: bool, name: str):
        self.localized = localized
        self.name = name

    def new_instrument(self, base_field):
        return CrcBundle(base_field=base_field, crc=CrcInstrument())

    def _tag(self, instrument, code: bytes) -> bytes:
        return instrument.crc.crc(bytes(code), self.width).to_bytes(self.tag_bytes, "big")

    def admit(self, instrument, wire_pool, gen_size, cfg: AdmitConfig):
        tb, w = self.tag_bytes, self.width
        verified: list[bytearray] = []
        failing: list[tuple[bytes, int]] = []
        for wire in wire_pool:
            code = bytes(wire[:-tb])
            recv_tag = int.from_bytes(bytes(wire[-tb:]), "big")
            if instrument.crc.crc(code, w) == recv_tag:
                verified.append(bytearray(code))          # CRC-clean -> straight into basis
            else:
                failing.append((code, recv_tag))
        accepted = list(verified)
        if not failing:
            return accepted

        basis = None
        if self.localized:
            # ARC needs a full-rank gen_size basis of CRC-clean packets; until then we
            # admit only the clean ones (the failing ones wait / get retransmitted).
            if len(verified) >= gen_size and _basis_full_rank(instrument.base_field, verified[:gen_size], gen_size):
                basis = verified[:gen_size]
            else:
                return accepted

        max_hd = cfg.hamming_distance          # HD-matched to the orthogonal arm (fair comparison)
        cache = instrument.repair_cache
        for code, recv_tag in failing:
            if code in cache:
                repaired = cache[code]
            elif self.localized:
                suspect = _suspect_bits(instrument.base_field, basis, code, gen_size)
                repaired, _ = crc_recover(instrument.crc, code, recv_tag, w, max_hd=max_hd, suspect_bits=suspect)
                cache[code] = repaired
            else:
                repaired, _ = crc_recover(instrument.crc, code, recv_tag, w, max_hd=max_hd, budget=self.whole_budget)
                cache[code] = repaired
            if repaired is not None:
                accepted.append(bytearray(repaired))
        return accepted

    def op_counts(self, instrument) -> dict:
        return {"crc_checks": instrument.crc.correction_trials, "crc_bytes": instrument.crc.crc_ops}

    def primary_ops(self, instrument) -> int:
        return instrument.crc.correction_trials


# ── Segmented orthogonal tagging (ADR-0012) ────────────────────────────────────
# N = 1 + num_data_segments independent self/cross-orthogonal pools per packet
# (coeff-segment + num_data_segments equal-or-round-robin data-segments), instead
# of the whole-packet scheme's single pool. Two strategies (ADR-0012 Option 1/2),
# measured against each other and against the N=1 baseline (plain OrthogonalScheme,
# already registered above -- segmentation is additive, not a replacement).
#
# data_fields is fixed at construction (not read from make_source's data_fields
# arg beyond an assert) because segment layout -- and therefore the rank-deficiency
# floor from build_segments (each segment's payload length must be >= gen_size-1,
# or that segment is a guaranteed give-up) -- depends on it. ADR-0012's resolution
# (2026-08-11) fixes data_fields=48 for the N-sweep so every N in {1,2,3,5} clears
# that floor with margin; see docs/adr/0012 "Resolved" section.

@dataclass
class SegmentedInstrument:
    """CountingField for native op counting, plus IC-refinement bookkeeping (ADR-0012
    "Resolved": measure-only, not implemented -- pairs_failed is exactly the rate of
    same-bit-position overlapping errors this mechanism cannot split, reported per
    (N, BER) rather than fixed).

    pair_cache persists per-pair combined-search results across admit rounds within
    one receiver lifetime (run_recovery_trial builds one instrument per trial and
    reuses it every round). A pair whose bytes and trusted set are unchanged since
    its last search is not searched again -- ticket 01, ADR-0012's deferred
    "per-pair persistence"."""
    field: CountingField
    pairs_recovered: int = 0
    pairs_failed: int = 0
    unpaired_recovered: int = 0
    unpaired_failed: int = 0
    pair_cache: dict = field(default_factory=dict)


def _strip_to_code(packet: bytearray, segments) -> bytearray:
    """[coeffs | data...] with every segment's salt+tag bytes dropped -- the shape
    _try_decode's RLNC basis expects, reassembled in the original column order
    since `segments` is already coeff-first then data-0, data-1, ... in order."""
    code = bytearray()
    for segment in segments:
        code += packet[segment.start: segment.start + segment.payload_length]
    return code


class SegmentedScheme(IntegrityScheme):
    """ADR-0012's segmented orthogonal tag. attach is free (homomorphic per segment,
    same as OrthogonalScheme -- recoding a segmented-tagged generation preserves
    self/cross-orthogonality in every segment, verified in
    binary_ext_fields/tests/segmented_recovery_test.py). admit repairs via pairing +
    combined search (recover_uniform_hd / recover_coefficient_first), then admits a
    packet into the decode basis only if EVERY segment ends up trusted for it --
    one still-broken segment makes the whole packet unusable, even if the rest is fine.
    """
    _MAX_TAG_ATTEMPTS = 10  # make_source retries on salt give-up; see docstring below

    def __init__(self, num_data_segments: int, data_fields: int, strategy: str, name: str):
        assert strategy in ("uniform_hd", "coefficient_first")
        self.num_data_segments = num_data_segments
        self.data_fields = data_fields
        self.strategy = strategy
        self.name = name

    def make_source(self, base_field, data_fields, gen_size):
        assert data_fields == self.data_fields, (
            f"{self.name} is fixed to data_fields={self.data_fields} (ADR-0012's rank-deficiency "
            f"floor depends on it), got {data_fields}"
        )
        max_int = base_field.max_value
        for _ in range(self._MAX_TAG_ATTEMPTS):
            data_rows = [bytearray(random.randint(0, max_int) for _ in range(data_fields))
                         for _ in range(gen_size)]
            plain = generate_identity_coefficients(base_field, data_rows)
            result = tag_generation_segmented(base_field, plain, gen_size, self.num_data_segments)
            if result.ok:
                return result.packets, [bytearray(row) for row in data_rows]
        # Retries exhausted: this is the structural give-up build_segments documents
        # (a segment below the gen_size-1 rank floor fails no matter how many salt
        # draws), not bad luck -- surface it loudly rather than silently degrading.
        raise RuntimeError(
            f"{self.name}: segmented tagging gave up {self._MAX_TAG_ATTEMPTS} times in a row "
            f"(N={1 + self.num_data_segments}, data_fields={data_fields}, gen_size={gen_size}) "
            "-- check build_segments' rank-deficiency floor for this N/data_fields/gen_size combo."
        )

    def new_instrument(self, base_field):
        return SegmentedInstrument(field=CountingField(base_field))

    def attach(self, instrument, code_packet: bytearray) -> bytearray:
        return bytearray(code_packet)

    def admit(self, instrument, wire_pool, gen_size, cfg: AdmitConfig):
        # Below gen_size packets, decode is mathematically impossible regardless of
        # repair outcome -- don't pay for the search. cfg.min_pool_size can only
        # push this gate later (a caller-requested extra margin), never earlier.
        if len(wire_pool) < max(gen_size, cfg.min_pool_size):
            return None

        # Per-pair persistence (ticket 01, was ADR-0012's deferred cost): once the
        # gates above pass, a broken pair is combined-searched only when its bytes or
        # the trusted set changed since its last attempt -- instrument.pair_cache
        # returns the prior result otherwise, instead of re-spending up to
        # SEGMENTED_PAIR_BUDGET candidates per round. This is what makes high-BER
        # cells terminate in feasible time and the op-count/wall-clock numbers
        # trustworthy rather than pessimistic.

        segments = layout_segments(gen_size, self.data_fields, self.num_data_segments)
        field = instrument.field

        # Cheap pre-check (self+cross orthogonality only, no combinatorial search):
        # packets already good in every segment, no repair needed. If that alone
        # already reaches gen_size, decode doesn't need this round's repair at all --
        # skip the expensive combined search entirely.
        already_good = set(range(len(wire_pool)))
        for segment in segments:
            already_good &= set(classify_segment_trust(field, wire_pool, segment).trusted)
        if len(already_good) >= gen_size:
            return [_strip_to_code(wire_pool[i], segments) for i in sorted(already_good)]

        if self.strategy == "uniform_hd":
            report = recover_uniform_hd(field, wire_pool, segments, max_combined_hd=cfg.hamming_distance,
                                        candidates_budget=cfg.pair_budget,
                                        pair_cache=instrument.pair_cache)
        else:
            report = recover_coefficient_first(field, wire_pool, segments, gen_size,
                                               max_combined_hd=cfg.hamming_distance,
                                               candidates_budget=cfg.pair_budget,
                                               pair_cache=instrument.pair_cache)

        for outcome in report.per_segment:
            instrument.pairs_recovered += outcome.pairs_recovered
            instrument.pairs_failed += outcome.pairs_failed
            instrument.unpaired_recovered += outcome.unpaired_recovered
            instrument.unpaired_failed += outcome.unpaired_failed

        # A packet enters the decode basis only if EVERY segment trusts it post-repair
        # (self+cross orthogonal to that segment's trusted pool) -- intersect across
        # segments, not union, since one broken segment still corrupts the packet.
        good = set(range(len(report.packets)))
        for segment in segments:
            trust = classify_segment_trust(field, report.packets, segment)
            if len(trust.trusted) < cfg.min_trust_count:
                return None  # not enough trust yet in this segment -- keep waiting
            good &= set(trust.trusted)

        return [_strip_to_code(report.packets[i], segments) for i in sorted(good)]

    def tag_overhead_bits(self, gen_size, m) -> int:
        n = 1 + self.num_data_segments
        return n * (gen_size + 1) * m  # N segments, each: gen_size tag symbols + 1 salt symbol

    def op_counts(self, instrument) -> dict:
        pm = instrument.field.phase_mul
        return {
            "field_mul": instrument.field.mul_count, "field_add": instrument.field.add_count,
            "pairs_recovered": instrument.pairs_recovered, "pairs_failed": instrument.pairs_failed,
            "unpaired_recovered": instrument.unpaired_recovered, "unpaired_failed": instrument.unpaired_failed,
            # muls split by phase (segmented_recovery._count_phase): detection = self/cross
            # orthogonality checks every scheme pays; recovery = the combined/bit-flip search
            # -- the fair recovery-cost axis. "other" (mul_count - the two) is any unattributed
            # mul, e.g. coefficient_first's ARC localization, and should be ~0 for uniform_hd.
            "detection_mul": pm.get("detection", 0), "recovery_mul": pm.get("recovery", 0),
        }

    def primary_ops(self, instrument) -> int:
        return instrument.field.mul_count


# ── Segmented homomorphic-MAC benchmark arm (Fathi & Pahlevani Combined Recovery) ─
# ADR-0012 line 11's deferred "benchmark homomorphic-MAC arm": the KEYED competitor
# to the keyless orthogonal segmented scheme, segmented identically so overhead and
# structure match and only the tag/oracle differs. The thesis argues the keyless
# orthogonal self-tag is a viable alternative to THIS scheme. Faithful port:
# homomorphic MAC t_j = XOR_i(p_i . k_ij) over GF(2^m), V = gen_size key vectors per
# segment (overhead-matched to the orthogonal per-segment tag width), no salt (a MAC
# tag of 0 is valid -- no zero-tag problem). Keys fresh per trial, held by source +
# receiver; relays recode WITHOUT the key (the tag is homomorphic). IC-refinement /
# Case-2 single-position-swap is DEFERRED (measure-only): an overlapping-error pair
# is counted in pairs_failed, never silently mishandled.

@dataclass
class SegmentedMacInstrument:
    """CountingField for native op counting (same primitive as the orthogonal arm),
    the per-trial secret keyset (V key vectors per segment), and the same per-pair
    persistence cache + IC-refinement bookkeeping as SegmentedInstrument."""
    field: CountingField
    keyset: list = field(default_factory=list)
    pairs_recovered: int = 0
    pairs_failed: int = 0
    unpaired_recovered: int = 0
    unpaired_failed: int = 0
    pair_cache: dict = field(default_factory=dict)


class SegmentedMacScheme(IntegrityScheme):
    """The keyed homomorphic-MAC benchmark, segmented exactly like SegmentedScheme.
    attach is free (homomorphic per segment -- recoding preserves each segment's tag,
    verified in binary_ext_fields/tests/segmented_mac_recovery_test.py). admit repairs
    via pairing + combined search (recover_uniform_hd_mac / recover_coefficient_first_mac),
    then admits a packet only if EVERY segment's MAC verifies for it post-repair.

    The keyset is generated fresh in make_source (which needs it to tag the source) and
    handed to new_instrument via self._pending_keyset -- run_recovery_trial always calls
    make_source immediately before new_instrument, sequentially, so this hand-off is safe
    (a MAC needs the same secret key at both sender tagging and receiver verification,
    unlike the orthogonal self-tag which the receiver checks with no key)."""

    def __init__(self, num_data_segments: int, data_fields: int, strategy: str, name: str):
        assert strategy in ("uniform_hd", "coefficient_first")
        self.num_data_segments = num_data_segments
        self.data_fields = data_fields
        self.strategy = strategy
        self.name = name
        self._pending_keyset = None

    def _num_keys(self, gen_size: int) -> int:
        return gen_size  # V = gen_size: overhead-matched to the orthogonal per-segment tag width

    def make_source(self, base_field, data_fields, gen_size):
        assert data_fields == self.data_fields, (
            f"{self.name} is fixed to data_fields={self.data_fields} (segment layout / rank floor "
            f"depends on it), got {data_fields}"
        )
        num_keys = self._num_keys(gen_size)
        max_int = base_field.max_value
        data_rows = [bytearray(random.randint(0, max_int) for _ in range(data_fields))
                     for _ in range(gen_size)]
        plain = generate_identity_coefficients(base_field, data_rows)
        segments = layout_mac_segments(gen_size, data_fields, self.num_data_segments, num_keys)
        keyset = generate_keyset(base_field, segments, random)   # fresh secret keyset per trial
        packets = tag_generation_mac(base_field, plain, gen_size, self.num_data_segments, keyset, num_keys)
        self._pending_keyset = keyset
        return packets, [bytearray(row) for row in data_rows]

    def new_instrument(self, base_field):
        assert self._pending_keyset is not None, "new_instrument must follow make_source (keyset hand-off)"
        keyset, self._pending_keyset = self._pending_keyset, None
        return SegmentedMacInstrument(field=CountingField(base_field), keyset=keyset)

    def attach(self, instrument, code_packet: bytearray) -> bytearray:
        return bytearray(code_packet)

    def admit(self, instrument, wire_pool, gen_size, cfg: AdmitConfig):
        # Below gen_size packets decode is impossible -- don't pay for the search.
        if len(wire_pool) < max(gen_size, cfg.min_pool_size):
            return None

        num_keys = self._num_keys(gen_size)
        segments = layout_mac_segments(gen_size, self.data_fields, self.num_data_segments, num_keys)
        field = instrument.field
        keyset = instrument.keyset

        # Cheap pre-check: packets already MAC-good in every segment need no repair.
        # If that alone reaches gen_size, skip the expensive combined search entirely.
        already_good = set(range(len(wire_pool)))
        for s, segment in enumerate(segments):
            already_good &= set(classify_segment_trust_mac(field, keyset[s], wire_pool, segment).trusted)
        if len(already_good) >= gen_size:
            return [_strip_to_code(wire_pool[i], segments) for i in sorted(already_good)]

        if self.strategy == "uniform_hd":
            report = recover_uniform_hd_mac(field, keyset, wire_pool, segments,
                                            max_combined_hd=cfg.hamming_distance,
                                            candidates_budget=cfg.pair_budget,
                                            pair_cache=instrument.pair_cache)
        else:
            report = recover_coefficient_first_mac(field, keyset, wire_pool, segments, gen_size,
                                                   max_combined_hd=cfg.hamming_distance,
                                                   candidates_budget=cfg.pair_budget,
                                                   pair_cache=instrument.pair_cache)

        for outcome in report.per_segment:
            instrument.pairs_recovered += outcome.pairs_recovered
            instrument.pairs_failed += outcome.pairs_failed
            instrument.unpaired_recovered += outcome.unpaired_recovered
            instrument.unpaired_failed += outcome.unpaired_failed

        # A packet enters the decode basis only if EVERY segment MAC-verifies for it
        # (intersect, not union). No min_trust warm-up gate: a MAC is self-sufficient.
        good = set(range(len(report.packets)))
        for s, segment in enumerate(segments):
            good &= set(classify_segment_trust_mac(field, keyset[s], report.packets, segment).trusted)

        return [_strip_to_code(report.packets[i], segments) for i in sorted(good)]

    def tag_overhead_bits(self, gen_size, m) -> int:
        n = 1 + self.num_data_segments
        return n * gen_size * m  # N segments, each gen_size MAC tag symbols (no salt)

    def op_counts(self, instrument) -> dict:
        return {
            "field_mul": instrument.field.mul_count, "field_add": instrument.field.add_count,
            "pairs_recovered": instrument.pairs_recovered, "pairs_failed": instrument.pairs_failed,
            "unpaired_recovered": instrument.unpaired_recovered, "unpaired_failed": instrument.unpaired_failed,
        }

    def primary_ops(self, instrument) -> int:
        return instrument.field.mul_count


# N sweep resolved in ADR-0012 (2026-08-11): {1, 2, 3, 5} total segments, i.e.
# num_data_segments in {0, 1, 2, 4}. N=1 is the existing OrthogonalScheme (no
# segmentation, registered above) -- only N>=2 needs a SegmentedScheme instance.
SEGMENTED_DATA_FIELDS = 48    # NEEDS to fulfill: data_fields ≥ (N_max − 1) · (gen_size − 1)
                              # N=5 → 4 data-segs of 12 ≥ gen_size-1=9 (ADR-0012 resolved value)
SEGMENTED_N_VALUES = ([2, 3, 5])  # total segments; num_data_segments = N - 1
SEGMENTED_STRATEGIES = (["uniform_hd", "coefficient_first"])

SEGMENTED_SCHEMES = {
    f"segmented_{strategy}_n{n}": SegmentedScheme(
        num_data_segments=n - 1, data_fields=SEGMENTED_DATA_FIELDS,
        strategy=strategy, name=f"segmented_{strategy}_n{n}",
    )
    for n in SEGMENTED_N_VALUES for strategy in SEGMENTED_STRATEGIES
}

# Homomorphic-MAC benchmark arm: both strategies registered, over the same N set as
# the orthogonal segmented arm (mirror of the block above). N=1 (a whole-packet MAC)
# has no counterpart here, exactly as N=1 orthogonal is the plain OrthogonalScheme
# rather than a SegmentedScheme.
MAC_STRATEGIES = ("uniform_hd", "coefficient_first")
SEGMENTED_MAC_SCHEMES = {
    f"mac_{strategy}_n{n}": SegmentedMacScheme(
        num_data_segments=n - 1, data_fields=SEGMENTED_DATA_FIELDS,
        strategy=strategy, name=f"mac_{strategy}_n{n}",
    )
    for n in SEGMENTED_N_VALUES for strategy in MAC_STRATEGIES
}


SCHEMES = {s.name: s for s in (
    OrthogonalScheme(), HmacScheme(),
    CrcScheme(localized=True, name="crc_localized"),
    CrcScheme(localized=False, name="crc_whole"),
    *SEGMENTED_SCHEMES.values(),
    *SEGMENTED_MAC_SCHEMES.values(),
)}


# ── Attack-side forging (ADR-0009 HMAC arm; CRC/Fly-PRAC not tested vs attacker) ─
def forge_orthogonal(atk_field, saved_code_packets, gen_size, data_fields, threshold,
                     avoid_coeff_rows, rng):
    """Targeted forgery against the orthogonal oracle -- the existing white-box
    attack (`pollute_intelligent`). Returns (wire_packet_or_None, n_constraints).
    The forged self-tag is embedded, so the wire packet IS the code packet."""
    return pollute_intelligent(atk_field, saved_code_packets, gen_size, data_fields,
                               threshold, avoid_coeff_rows=avoid_coeff_rows, rng=rng)


def forge_hmac(saved_code_packets, gen_size, data_fields, max_int, rng):
    """Best the relay can do against HMAC without the key: an independent-coefficient
    packet with wrong data and a *bogus* MAC (it cannot compute a valid one). The
    receiver's HMAC admit recomputes and rejects it -> silent-accept is structurally
    impossible. Returns the on-wire packet. Attacker forging work is negligible (no
    crypto it can actually perform), so no field instrument is charged here."""
    coeff = bytearray(rng.randint(0, max_int) for _ in range(gen_size))
    data = bytearray(rng.randint(0, max_int) for _ in range(data_fields))
    bogus_tag = bytearray(rng.randint(0, 255) for _ in range(HMAC_TAG_BYTES))
    return coeff + data + bogus_tag
