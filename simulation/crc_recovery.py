"""CRC single-packet Hamming-distance recovery (ADR-0011).

One opaque data packet is corrupted at a known Hamming distance (some bits
flipped); recovery brute-forces bit-combinations up to HD 3 around the received
packet, checks each against a bare CRC, and stops at the first match. No
dependent groups, no algebraic localization, no segmentation -- the deliberately
minimal "what can a bare CRC do as error *correction*" baseline the supervisors
asked for.

Pure functions + a native op counter. Pure-Python table CRCs (no zlib/C) so the
eventual cross-scheme *wall-clock* comparison is like-for-like against the
pure-Python orthogonal / homomorphic-MAC arms.

Outcome vocabulary (labelled against ground truth, which exists only in the sim
and is used only *after* the search stops): correct / false-repair (a
CRC-passing candidate != original -- the silent-error case) / no-repair (nothing
passed within HD 3) / unresolved-within-budget (search hit the candidate cap
before finding anything -- the "infeasible without localization" case).
"""

from dataclasses import dataclass
from itertools import combinations
from math import comb

# Generator polynomials, MSB-first, init 0, xorout 0. These are real CRCs
# (CRC-8/SMBUS, CRC-16/XMODEM, and the CRC-32 polynomial) -- the exact choice is
# immaterial to the collision rate (~2^-w for random errors), but a genuine
# generator per width keeps the collision behaviour honest at CRC-8/16
CRC_POLYS = {8: 0x07, 16: 0x1021, 32: 0x04C11DB7}


def _build_table(width: int, poly: int) -> list[int]:
    top = 1 << (width - 1)
    mask = (1 << width) - 1
    table = []
    for b in range(256):
        reg = b << (width - 8)
        for _ in range(8):
            reg = ((reg << 1) ^ poly) if (reg & top) else (reg << 1)
            reg &= mask
        table.append(reg)
    return table


_TABLES = {w: _build_table(w, p) for w, p in CRC_POLYS.items()}


def crc(data: bytes, width: int) -> int:
    """MSB-first table CRC of `data` at `width` bits (8/16/32), init 0, xorout 0."""
    table = _TABLES[width]
    shift = width - 8
    mask = (1 << width) - 1
    reg = 0
    for byte in data:
        reg = ((reg << 8) ^ table[((reg >> shift) ^ byte) & 0xFF]) & mask
    return reg


def tag_overhead_bits(width: int) -> int:
    """CRC tag width in bits -- flat per packet (contrast the orthogonal tag's
    gen_size-linear growth)."""
    return width


@dataclass
class CrcInstrument:
    """Native op counter. crc_ops = bytes fed to CRC (attach + every candidate
    recompute); correction_trials = bit-flip candidates tried in the search --
    the same two currencies the retired Fly-PRAC arm tracked."""
    crc_ops: int = 0
    correction_trials: int = 0

    def crc(self, data: bytes, width: int) -> int:
        self.crc_ops += len(data)
        return crc(data, width)


def attach(instrument: CrcInstrument, data: bytes, width: int) -> int:
    """Source-side CRC tag over the (clean) packet -- the reference the receiver
    searches back toward. Assumed transmitted intact (like the coefficient block
    in the RLNC arms); only the data body is corrupted."""
    return instrument.crc(bytes(data), width)


def _flip_bits(data: bytearray, positions) -> bytearray:
    out = bytearray(data)
    for p in positions:
        out[p >> 3] ^= 1 << (p & 7)
    return out


def recover(instrument: CrcInstrument, received: bytes, expected_crc: int, width: int,
            max_hd: int = 3, suspect_bits=None, budget: int | None = None) -> tuple[bytearray | None, bool]:
    """Search bit-combinations around `received` at Hamming distance 1..max_hd
    (bits, not symbols), stop at the first whose CRC == expected_crc.

    `suspect_bits` (an iterable of bit positions) restricts the search space:
    None = every bit (the standalone, no-localization case -- the supervisor's
    version); a caller with algebraic (ACR) localization passes the suspect
    columns' bit positions to give CRC the same localization the other arms get
    (the comparison, ADR-0011).

    `budget` caps candidates tried; on exhaustion the search bails so the sweep
    stays tractable at large packet sizes with a wide (collision-free) CRC.

    Returns (repaired_packet | None, budget_exhausted). None with
    budget_exhausted=False means nothing passed within HD max_hd."""
    n = 8 * len(received)
    positions = range(n) if suspect_bits is None else sorted(suspect_bits)
    base = bytearray(received)
    for dist in range(1, max_hd + 1):
        for combo in combinations(positions, dist):
            if budget is not None and instrument.correction_trials >= budget:
                return None, True
            instrument.correction_trials += 1
            candidate = _flip_bits(base, combo)
            if instrument.crc(bytes(candidate), width) == expected_crc:
                return candidate, False
    return None, False


def candidates_up_to(n_bits: int, max_hd: int) -> int:
    """Total bit-combinations at HD 1..max_hd over n_bits positions."""
    return sum(comb(n_bits, j) for j in range(1, max_hd + 1))


def analytic_false_repair(n_bits: int, true_hd: int, width: int) -> float:
    """Expected number of collision-passes searched *before* the true HD-`true_hd`
    fix: every candidate at strictly lower HD is searched first (sum_{j<hd} C(n,j)),
    plus on average half the true-HD level (C(n,hd)/2), each colliding with prob
    2^-width. An order-of-magnitude estimate that covers the CRC-32 tail Monte
    Carlo can't observe (ADR-0011)."""
    below = sum(comb(n_bits, j) for j in range(1, true_hd))
    at_level = comb(n_bits, true_hd) / 2
    return (below + at_level) * (2.0 ** -width)
