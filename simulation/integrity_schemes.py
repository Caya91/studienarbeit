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
(The plain CRC-32 detect-and-drop `CrcScheme`, its short-lived Fly-PRAC dependent-group
replacement, and the later CRC-16 repair `CrcScheme` (crc_localized / crc_whole) were all
retired -- the CRC comparison now lives in the isolated harness as CRC-32 arms, ADR-0014.)
The homomorphic-MAC benchmark that will join this file as a second recovery-capable scheme is the
deferred phase 2 (ADR-0011).
ADR-0015 adds `SegmentedCrcScheme` (zlib CRC-32 per segment, ADR-0014 layout) for the END-TO-END
sweep: repair="none" is the conventional-ARQ baseline (detect, drop, pull another coded packet),
repair="acr" the S-PRAC-like CRC + ACR repair arm. Not registered in SCHEMES (drivers pick it
explicitly), so every existing default path is unchanged.

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
from binary_ext_fields.witness_policy import key_rank_for, witness_rank_for
from binary_ext_fields.segmented_tagging import layout_segments, tag_generation_segmented
from binary_ext_fields.segmented_recovery import (
    classify_segment_trust, recover_acr_only, recover_coefficient_first, recover_uniform_hd,
)
from binary_ext_fields.segmented_mac_tagging import (
    layout_mac_segments, generate_keyset, tag_generation_mac,
)
from binary_ext_fields.segmented_mac_recovery import (
    classify_segment_trust_mac, recover_acr_only_mac, recover_coefficient_first_mac, recover_uniform_hd_mac,
)
from simulation.recovery_decode_sim import _accepted_packets, recover_generation_bitflip
from simulation.segmented_crc import (
    CRC_BYTES, Crc32Instrument, CrcSegment, crc_verify_segment, layout_crc_segments,
    recover_acr_only_crc, segment_slice as crc_segment_slice,
)


# ── Tag widths (ADR-0009) ─────────────────────────────────────────────────────
HMAC_TAG_BYTES = 16        # HMAC-SHA-256 truncated to 128 bits
SEGMENTED_PAIR_BUDGET = 100_000  # recover_pair_by_combined_search candidate cap, per pair (ADR-0012)


@dataclass
class AdmitConfig:
    """Receiver-side admission knobs. Only the orthogonal scheme reads them;
    HMAC ignores all of it (a MAC is self-sufficient -- no cross-verify, no warm-up)."""
    hamming_distance: int = 1
    mode: str = "per_column"
    # Number of trusted witness packets each self-passing packet is cross-checked
    # against before it is trusted; None = check against the whole trusted core.
    # Drives BOTH the orthogonal scheme's repair oracle AND (ADR-0012) the segmented
    # scheme's poisoner-tolerant classify_segment_trust -- the security/cost dial:
    # more witnesses = harder for a forged packet to be admitted, fewer = cheaper.
    # 0 disables the cross-check (self-check only). See classify_segment_trust.
    verify_count: int | None = 4
    min_trust_count: int = 4
    min_pool_size: int = 10
    decode_verify_count: int = 2      # ADR default V=2 (silent-decode fix)
    # Segmented scheme only (ADR-0012): per-pair combined-search candidate cap. Must
    # scale WITH hamming_distance -- a higher HD whose corrections sit past this budget
    # is pure wasted search (measured: HD3 at 100k = same recovery as HD2, 4.4x wall).
    pair_budget: int = SEGMENTED_PAIR_BUDGET
    # Segmented "acr_only" strategy only: which columns the ACR-narrowed bit-flip search may
    # touch -- "payload" (ACR columns only) or "segment" (+ the data segment's salt/tag span).
    repair_span: str = "payload"
    # Segmented "acr_only" strategy, KEYLESS arm: True (default, 2026-09-30) = bit-flip search
    # over the ACR columns, same method as the keyed arm; False = the ADR-0002 exact linear
    # solve (+ whole-segment bit-flip fallback) as before. The keyed arm always bit-flips.
    acr_bitflip_only: bool = True
    # S2 security dial (2026-09-29, binary_ext_fields/witness_policy.py): WHICH verify_count
    # witnesses (keyless) / mac_verify_count keys (keyed) a packet is checked against.
    # "first" = deterministic (today's behaviour, predictable by an attacker); "random" = a
    # per-packet subset from the receiver secret `witness_secret` (never seen by the attacker).
    witness_policy: str = "first"
    witness_secret: int = 0
    # Keyless, S2 security check only (default off): the receiver REMEMBERS a cross-check
    # rejection -- a self-passing packet that once failed its witnesses is never admitted later.
    # Removes the re-evaluation "second chance" a stateless receiver gives a forger under the
    # random policy (the new arrival can enter its witness set). 2026-10-02.
    witness_sticky: bool = False
    # Keyed arm only: MAC tags verified per segment at admission (None = all g, the default).
    # The repair search keeps verifying all g tags (stricter), so this caps only the
    # admission check of unrepaired packets.
    mac_verify_count: int | None = None
    # Segmented / MAC "acr_only" admit only (ADR-0015, opt-in): False skips the strategy's post-repair
    # whole-pool check (report.ok -- keyless check_orth_segmented is O(M^2) per admit round). admit never
    # reads report.ok, so the admitted packets are identical; only ops / wall time drop (cf. ticket 20).
    # Default True = unchanged behaviour of every existing driver.
    final_check: bool = True


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
    cross_rejected: set = field(default_factory=set)  # AdmitConfig.witness_sticky memory (pool indices)
    pairs_recovered: int = 0
    pairs_failed: int = 0
    unpaired_recovered: int = 0
    unpaired_failed: int = 0
    pair_cache: dict = field(default_factory=dict)


# Segmented strategies: uniform_hd / coefficient_first (ADR-0012) and acr_only (2026-09-29:
# no coeff repair, data segments repaired only where ACR localizes, else wait for packets).
SEGMENTED_STRATEGY_NAMES = ("uniform_hd", "coefficient_first", "acr_only")

# Channel-error scopes for run_recovery_trial (2026-09-29). "whole_packet" = every wire byte
# (the original model); the two restricted scopes never touch the coeff segment:
#   data_payload -- data-segment payload bytes only
#   data_segment -- data-segment payload + that segment's salt/tag bytes
#   data_tags_only -- (2026-10-17, ADR-0015) ONLY the data segments' redundancy bytes: keyless salt +
#                     tags, keyed MAC tags, CRC-32 bytes; payload clean. Same byte set as the isolated
#                     harness's inject_paired model "data_tags_only" (ADR-0014): the complement of
#                     data_payload inside data_segment, coeff segment never hit.
ERROR_SCOPES = ("whole_packet", "data_payload", "data_segment", "data_tags_only")


def _segment_error_positions(segments, scope: str) -> list[int]:
    """Wire byte indices a channel error may hit under `scope` (restricted scopes only)."""
    assert scope in ("data_payload", "data_segment", "data_tags_only"), f"no position list for scope {scope!r}"
    out = []
    for seg in segments:
        if seg.kind != "data":
            continue
        begin = seg.payload_length if scope == "data_tags_only" else 0
        end = seg.payload_length if scope == "data_payload" else seg.total_length
        out.extend(range(seg.start + begin, seg.start + end))
    return out


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
        assert strategy in SEGMENTED_STRATEGY_NAMES
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
        wrank = witness_rank_for(cfg.witness_policy, cfg.witness_secret)

        # Cheap pre-check (self+cross orthogonality only, no combinatorial search):
        # packets already good in every segment, no repair needed. If that alone
        # already reaches gen_size, decode doesn't need this round's repair at all --
        # skip the expensive combined search entirely.
        def trusted_set(trust, n):
            if not cfg.witness_sticky:
                return set(trust.trusted)
            instrument.cross_rejected |= set(range(n)) - set(trust.broken) - set(trust.trusted)
            return set(trust.trusted) - instrument.cross_rejected

        already_good = set(range(len(wire_pool)))
        for segment in segments:
            already_good &= trusted_set(classify_segment_trust(field, wire_pool, segment,
                                                               verify_count=cfg.verify_count, witness_rank=wrank),
                                        len(wire_pool))
        if len(already_good) >= gen_size:
            return [_strip_to_code(wire_pool[i], segments) for i in sorted(already_good)]

        if self.strategy == "uniform_hd":
            report = recover_uniform_hd(field, wire_pool, segments, max_combined_hd=cfg.hamming_distance,
                                        candidates_budget=cfg.pair_budget,
                                        pair_cache=instrument.pair_cache, verify_count=cfg.verify_count,
                                        witness_rank=wrank)
        elif self.strategy == "acr_only":
            report = recover_acr_only(field, wire_pool, segments, gen_size,
                                      max_combined_hd=cfg.hamming_distance, candidates_budget=cfg.pair_budget,
                                      pair_cache=instrument.pair_cache, verify_count=cfg.verify_count,
                                      repair_span=cfg.repair_span, witness_rank=wrank,
                                      bitflip_only=cfg.acr_bitflip_only, final_check=cfg.final_check)
        else:
            report = recover_coefficient_first(field, wire_pool, segments, gen_size,
                                               max_combined_hd=cfg.hamming_distance,
                                               candidates_budget=cfg.pair_budget,
                                               pair_cache=instrument.pair_cache, verify_count=cfg.verify_count,
                                               witness_rank=wrank)

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
            trust = classify_segment_trust(field, report.packets, segment, verify_count=cfg.verify_count,
                                           witness_rank=wrank)
            if len(trust.trusted) < cfg.min_trust_count:
                return None  # not enough trust yet in this segment -- keep waiting
            good &= trusted_set(trust, len(report.packets))

        return [_strip_to_code(report.packets[i], segments) for i in sorted(good)]

    def error_positions(self, gen_size, scope: str) -> list[int]:
        return _segment_error_positions(layout_segments(gen_size, self.data_fields, self.num_data_segments), scope)

    def tag_overhead_bits(self, gen_size, m) -> int:
        n = 1 + self.num_data_segments
        # Tag-only overhead for the parity comparison: N segments x gen_size tag symbols,
        # matching the MAC arm's N*gen_size keyed tags exactly. The scheme ALSO spends 1
        # salt symbol per segment on the wire (a zero self-tag is degenerate, ADR-0010),
        # a real keyless cost -- but by decision it is EXCLUDED here so the two arms report
        # identical tag overhead and the figure compares tag-for-tag cleanly. Add back
        # n*m bits if/when the salt is put back on the overhead axis.
        return n * gen_size * m

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
        assert strategy in SEGMENTED_STRATEGY_NAMES
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
        krank = key_rank_for(cfg.witness_policy, cfg.witness_secret)
        W = cfg.mac_verify_count

        # Cheap pre-check: packets already MAC-good in every segment need no repair.
        # If that alone reaches gen_size, skip the expensive combined search entirely.
        already_good = set(range(len(wire_pool)))
        for s, segment in enumerate(segments):
            already_good &= set(classify_segment_trust_mac(field, keyset[s], wire_pool, segment,
                                                           verify_count=W, key_rank=krank).trusted)
        if len(already_good) >= gen_size:
            return [_strip_to_code(wire_pool[i], segments) for i in sorted(already_good)]

        if self.strategy == "uniform_hd":
            report = recover_uniform_hd_mac(field, keyset, wire_pool, segments,
                                            max_combined_hd=cfg.hamming_distance,
                                            candidates_budget=cfg.pair_budget,
                                            pair_cache=instrument.pair_cache)
        elif self.strategy == "acr_only":
            # early_exit (ticket 18): keyed verify stops at the first bad tag, like the keyless
            # self-check short-circuit -- same outcomes, fair op counts.
            report = recover_acr_only_mac(field, keyset, wire_pool, segments, gen_size,
                                          max_combined_hd=cfg.hamming_distance,
                                          candidates_budget=cfg.pair_budget,
                                          pair_cache=instrument.pair_cache, early_exit=True,
                                          repair_span=cfg.repair_span, final_check=cfg.final_check)
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
            good &= set(classify_segment_trust_mac(field, keyset[s], report.packets, segment,
                                                   verify_count=W, key_rank=krank).trusted)

        return [_strip_to_code(report.packets[i], segments) for i in sorted(good)]

    def error_positions(self, gen_size, scope: str) -> list[int]:
        segments = layout_mac_segments(gen_size, self.data_fields, self.num_data_segments, self._num_keys(gen_size))
        return _segment_error_positions(segments, scope)

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


# ── Segmented CRC-32, end to end (ADR-0015) ───────────────────────────────────
# The conventional-ARQ baseline (repair="none") and the S-PRAC-like CRC + ACR arm (repair="acr")
# of the end-to-end sweep. ADR-0014 layout: the keyless payload segments, each followed by one
# zlib CRC-32 (4 B) instead of salt + gen_size tags. A CRC does not survive RLNC recoding over
# GF(2^8), so the SOURCE computes the CRCs of every coded packet (attach) -- single hop, or a relay
# that re-CRCs (two-hop sim). Replaces nothing: the retired CRC-16 CrcScheme stays retired.

CRC_REPAIRS = ("none", "acr")


@dataclass
class SegmentedCrcInstrument:
    """Receiver-side zlib CRC-32 (bytes fed counted), sender-side CRC-32 (attach, counted apart),
    a CountingField for the ACR localization ops (repair="acr"), the per-arrival ARQ verdict cache,
    and the same repair counters + per-pair cache as the keyless/keyed instruments."""
    field: CountingField
    crc: Crc32Instrument = field(default_factory=Crc32Instrument)
    sender: Crc32Instrument = field(default_factory=Crc32Instrument)
    verdict: list = field(default_factory=list)   # ARQ: verdict[i] = every segment of pool[i] passes
    pairs_recovered: int = 0
    pairs_failed: int = 0
    unpaired_recovered: int = 0
    unpaired_failed: int = 0
    pair_cache: dict = field(default_factory=dict)


class SegmentedCrcScheme(IntegrityScheme):
    """zlib CRC-32 per segment, end to end.

    repair="none" -- conventional ARQ (docs/arq_baseline_framing.md): every arrival is checked once
      (verdict cached -- the pool is append-only), any failing segment drops the whole packet, the
      receiver keeps pulling coded packets until the clean ones are decodable. No repair.
    repair="acr"  -- S-PRAC-like: production ACR-only repair (recover_acr_only_crc: sniffed CRC trust
      per segment, ACR-localized bit-flip search, same pairing / budget as keyless), then a packet is
      admitted only if EVERY segment's CRC passes."""

    def __init__(self, num_data_segments: int, data_fields: int, repair: str, name: str):
        assert repair in CRC_REPAIRS, f"repair must be one of {CRC_REPAIRS}, got {repair!r}"
        self.num_data_segments = num_data_segments
        self.data_fields = data_fields
        self.repair = repair
        self.name = name

    def wire_segments(self, gen_size) -> list[CrcSegment]:
        """[payload | CRC-32] blocks of the on-wire packet (the keyless payload split)."""
        return layout_crc_segments(layout_segments(gen_size, self.data_fields, self.num_data_segments))

    def _plain_segments(self, gen_size) -> list[CrcSegment]:
        """The same segments inside the untagged [coeff | data] code packet (no CRC bytes)."""
        out, cursor = [], 0
        for seg in layout_segments(gen_size, self.data_fields, self.num_data_segments):
            out.append(CrcSegment(seg.name, seg.kind, cursor, seg.payload_length))
            cursor += seg.payload_length
        return out

    def make_source(self, base_field, data_fields, gen_size):
        assert data_fields == self.data_fields, f"{self.name} is fixed to data_fields={self.data_fields}"
        max_int = base_field.max_value
        data_rows = [bytearray(random.randint(0, max_int) for _ in range(data_fields))
                     for _ in range(gen_size)]
        return generate_identity_coefficients(base_field, data_rows), [bytearray(row) for row in data_rows]

    def new_instrument(self, base_field):
        return SegmentedCrcInstrument(field=CountingField(base_field))

    def frame(self, crc: Crc32Instrument, code_packet: bytearray) -> bytearray:
        """[coeff | data] -> [seg payload | CRC-32] per segment, CRC bytes charged to `crc`. Used by
        the source (attach) and by a re-CRCing relay (two-hop sim)."""
        gen_size = len(code_packet) - self.data_fields
        out = bytearray()
        for seg in self._plain_segments(gen_size):
            payload = bytes(code_packet[seg.start: seg.start + seg.payload_length])
            out += payload + crc.crc(payload).to_bytes(CRC_BYTES, "big")
        return out

    def attach(self, instrument, code_packet: bytearray) -> bytearray:
        return self.frame(instrument.sender, code_packet)

    def packet_ok(self, crc: Crc32Instrument, packet: bytearray, segments) -> bool:
        """Every segment's CRC passes (stops at the first failing segment)."""
        return all(crc_verify_segment(crc, crc_segment_slice(packet, s), s) for s in segments)

    def admit(self, instrument, wire_pool, gen_size, cfg: AdmitConfig):
        segments = self.wire_segments(gen_size)
        if self.repair == "none":
            assert len(instrument.verdict) <= len(wire_pool), "ARQ verdict cache assumes an append-only pool"
            for i in range(len(instrument.verdict), len(wire_pool)):
                instrument.verdict.append(self.packet_ok(instrument.crc, wire_pool[i], segments))
            return [_strip_to_code(wire_pool[i], segments) for i, ok in enumerate(instrument.verdict) if ok]

        if len(wire_pool) < max(gen_size, cfg.min_pool_size):
            return None
        already_good = [i for i, p in enumerate(wire_pool) if self.packet_ok(instrument.crc, p, segments)]
        if len(already_good) >= gen_size:
            return [_strip_to_code(wire_pool[i], segments) for i in already_good]
        report = recover_acr_only_crc(instrument.field, instrument.crc, wire_pool, segments, gen_size,
                                      max_combined_hd=cfg.hamming_distance, candidates_budget=cfg.pair_budget,
                                      pair_cache=instrument.pair_cache, repair_span=cfg.repair_span,
                                      final_check=False)
        for outcome in report.per_segment:
            instrument.pairs_recovered += outcome.pairs_recovered
            instrument.pairs_failed += outcome.pairs_failed
            instrument.unpaired_recovered += outcome.unpaired_recovered
            instrument.unpaired_failed += outcome.unpaired_failed
        return [_strip_to_code(p, segments) for p in report.packets if self.packet_ok(instrument.crc, p, segments)]

    def error_positions(self, gen_size, scope: str) -> list[int]:
        return _segment_error_positions(self.wire_segments(gen_size), scope)

    def tag_overhead_bits(self, gen_size, m) -> int:
        return CRC_BYTES * 8 * (1 + self.num_data_segments)

    def op_counts(self, instrument) -> dict:
        return {
            "field_mul": instrument.field.mul_count, "field_add": instrument.field.add_count,
            "crc_bytes": instrument.crc.crc_ops, "sender_crc_bytes": instrument.sender.crc_ops,
            "correction_trials": instrument.crc.correction_trials,
            "pairs_recovered": instrument.pairs_recovered, "pairs_failed": instrument.pairs_failed,
            "unpaired_recovered": instrument.unpaired_recovered, "unpaired_failed": instrument.unpaired_failed,
        }

    def primary_ops(self, instrument) -> int:
        # field muls, like the keyless/keyed arms (ACR localization; 0 for ARQ). CRC work is in
        # op_counts()["crc_bytes"] -- a different unit, never summed with field ops (ADR-0009).
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
    *SEGMENTED_SCHEMES.values(),
    *SEGMENTED_MAC_SCHEMES.values(),
)}


# ── Attack-side forging (ADR-0009 HMAC arm) ─
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
