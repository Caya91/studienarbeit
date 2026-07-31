"""Pluggable integrity schemes for the baseline comparison (ADR-0009).

The recovery/decode loop and the attack loop both reduce to the same skeleton --
build a source generation, then per round: recode -> attach a tag -> pollute ->
append -> admit (verify / repair / drop) -> try to decode. Only *attach* and
*admit* differ between schemes, so we factor those (plus source construction, the
overhead figure, and a native op counter) behind an `IntegrityScheme` and let the
driver (`scheme_comparison_sim.py`) stay scheme-agnostic.

Three schemes:
- `OrthogonalScheme`  -- the project's own homomorphic self-tag. Its `attach` is a
  no-op (the tag rides along under recoding for free) and its `admit` reuses the
  *unchanged* validated internals `recover_generation_bitflip` + `_accepted_packets`
  from `recovery_decode_sim`, so it reproduces the standalone sim as a cross-check.
- `CrcScheme`  -- keyless CRC-32 checksum. Detect-and-drop, no repair, no key.
- `HmacScheme` -- keyed HMAC-SHA-256 truncated to 128 bits. Detect-and-drop.

The decisive asymmetry (see ADR-0009): the orthogonal tag survives RLNC recoding
and REPAIRS, so it needs fewer transmissions; CRC/HMAC do not survive recoding
(they only work here because the recovery sim is single-hop) and can only DROP.

Computation is measured in each scheme's *native* primitive (field muls, CRC byte
ops, HMAC block compressions) -- they are incommensurable, so we never sum them
into one number (ADR-0009, docs/comparison_methodology_notes.md). The RLNC decode
itself is common to all schemes and is charged to a *separate* CountingField by the
driver, kept out of the per-scheme op counts.
"""

import hashlib
import hmac
import math
import os
import random
import zlib
from dataclasses import dataclass, field as dataclass_field

from binary_ext_fields.custom_field import CountingField, TableField
from binary_ext_fields.generate_symbols import (
    generate_identity_coefficients,
    generate_symbols_until_nonzero,
)
from binary_ext_fields.pollution import pollute_intelligent
from simulation.recovery_decode_sim import _accepted_packets, recover_generation_bitflip


# ── Tag widths (ADR-0009) ─────────────────────────────────────────────────────
CRC_TAG_BYTES = 4          # CRC-32
HMAC_TAG_BYTES = 16        # HMAC-SHA-256 truncated to 128 bits


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
# Orthogonal uses CountingField directly (mul_count / add_count). CRC and HMAC use
# these tiny counters so their tagging/verification work is charged in their own
# primitive, comparable to the field-op count only in spirit, never in units.

@dataclass
class CrcInstrument:
    """CRC-32 with a byte-operation counter: table-driven CRC does one lookup+XOR
    per input byte, so byte_ops == total bytes fed through crc() this trial."""
    byte_ops: int = 0

    def crc(self, data: bytes) -> int:
        self.byte_ops += len(data)
        return zlib.crc32(data) & 0xFFFFFFFF


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
    """Shared detect-and-drop machinery for the keyless CRC and keyed HMAC baselines.

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


class CrcScheme(_MacScheme):
    name = "crc"
    tag_bytes = CRC_TAG_BYTES

    def new_instrument(self, base_field):
        return CrcInstrument()

    def _tag(self, instrument, code: bytes) -> bytes:
        return instrument.crc(code).to_bytes(CRC_TAG_BYTES, "big")

    def op_counts(self, instrument) -> dict:
        return {"crc_byte_ops": instrument.byte_ops}

    def primary_ops(self, instrument) -> int:
        return instrument.byte_ops


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


SCHEMES = {s.name: s for s in (OrthogonalScheme(), CrcScheme(), HmacScheme())}


# ── Attack-side forging (ADR-0009 HMAC arm; CRC is not tested vs the attacker) ─
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
