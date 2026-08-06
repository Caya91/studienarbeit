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
from simulation.recovery_decode_sim import _accepted_packets, recover_generation_bitflip
from simulation.crc_recovery import CrcInstrument, recover as crc_recover
from playground.arc_pl import localize_errors
from playground.new_recovery import _basis_full_rank


# ── Tag widths (ADR-0009) ─────────────────────────────────────────────────────
HMAC_TAG_BYTES = 16        # HMAC-SHA-256 truncated to 128 bits
CRC_WIDTH = 16             # comparison CRC width -- CRC-16, the PRAC/S-PRAC/QPPR anchor
CRC_TAG_BYTES = 2          # 16-bit tag = 2 bytes
CRC_WHOLE_BUDGET = 100_000 # whole-packet (no-localization) per-packet candidate cap


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


SCHEMES = {s.name: s for s in (
    OrthogonalScheme(), HmacScheme(),
    CrcScheme(localized=True, name="crc_localized"),
    CrcScheme(localized=False, name="crc_whole"),
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
