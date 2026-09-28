"""Shared building blocks for the ticket-17 security sims.

Part A = simulation/splice_attack_sim.py   (segment splice / scale test)
Part B = simulation/knowledge_attack_sim.py (partial-knowledge forgery)
Plan: docs/plans/security-analysis-plan.md (attacks A3 + A5). Ticket:
.scratch/segmented-orthogonal-sim/issues/17-splice-test-and-partial-knowledge-forgery.md

Only attack-agnostic plumbing lives here:
  - a PAIRED source: one seed fixes the data rows for every arm; keyless salts and keyed
    keys come from arm-specific seeds derived from it (common random numbers);
  - honest traffic recoded with EXPLICIT coefficient rows (`recode`), so every arm sees
    the identical coefficient sequence;
  - the receiver (`run_receiver`): append arrivals to a pool, run the PRODUCTION admit
    path (SegmentedScheme / SegmentedMacScheme / OrthogonalScheme .admit), try to decode,
    grade against ground truth (`_try_decode`);
  - a strict oracle (`passes_oracle`): does a packet pass every per-segment check against
    a given honest pool -- no repair, no trust heuristics. This is the q^-u quantity.

No channel noise anywhere: honest packets are clean, so any admitted code row that is not
an honest code row IS the injected packet (possibly modified by the repair machinery).

Arms:
  keyless     SegmentedScheme     N >= 2, per-segment orthogonal self+cross tag (+1 salt/seg)
  keyed       SegmentedMacScheme  N >= 2, per-segment homomorphic MAC, V = gen_size keys/seg
  keyless_n1  OrthogonalScheme    N = 1 whole-packet orthogonal tag (control)
  keyed_n1    whole-packet homomorphic MAC over [coeff|data], gen_size keys (control). No
              production class exists (ADR-0012: an N=1 MAC has no counterpart), so its
              admit is the plain detect-and-drop verify defined here (no repair).
"""

import random
from dataclasses import dataclass
from functools import lru_cache

from binary_ext_fields.custom_field import CountingField, TableField, create_field
from binary_ext_fields.generate_symbols import (
    check_orth, check_orth_packet, code_with_given_coefficients, generate_identity_coefficients,
)
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.orthogonal_tag_creator import OrthogonalTagGenerator
from binary_ext_fields.pollution import _gf_row_reduce
from binary_ext_fields.segmented_tagging import tag_generation_segmented
from binary_ext_fields.segmented_mac_tagging import (
    layout_mac_segments, generate_keyset, tag_generation_mac, mac_tag_vector, mac_verify_segment,
)
from simulation.integrity_schemes import (
    AdmitConfig, OrthogonalScheme, SegmentedScheme, SegmentedMacScheme,
    SegmentedInstrument, SegmentedMacInstrument,
)
from simulation.recovery_decode_sim import _try_decode


ARMS = ("keyless", "keyed", "keyless_n1", "keyed_n1")
SEGMENTED_ARMS = ("keyless", "keyed")
N1_ARMS = ("keyless_n1", "keyed_n1")
STRATEGY = "coefficient_first"   # irrelevant without noise (nothing honest is broken); the headline one
MAX_SOURCE_DRAWS = 50            # data redraws if keyless tagging gives up (small fields, ADR-0010)


@lru_cache(maxsize=None)
def field_for(m: int) -> TableField:
    """GF(2^m), built once per process (create_field rebuilds the full mul table, ~0.5 s at
    m=8 -- far more than a trial). TableField is read-only after construction, so sharing
    it is safe; per-trial op counting always wraps it in a fresh CountingField."""
    return create_field(m)


def default_cfg(gen_size: int) -> AdmitConfig:
    """Production defaults except min_pool_size = gen_size: the receiver tries to decode as
    soon as it holds gen_size packets (ticket 17 decision; the default 10 would shift u)."""
    return AdmitConfig(min_pool_size=gen_size)


# ── Coefficient-row linear algebra (attacker/harness side, uncounted) ─────────

def row_rank(field: TableField, rows) -> int:
    rows = [list(r) for r in rows]
    return len(_gf_row_reduce(field, rows)) if rows else 0


def in_row_span(field: TableField, row, rows) -> bool:
    return row_rank(field, list(rows) + [row]) == row_rank(field, rows)


def random_row(rng: random.Random, field: TableField, length: int) -> bytearray:
    return bytearray(rng.randint(0, field.max_value) for _ in range(length))


def independent_rows(rng: random.Random, field: TableField, gen_size: int, count: int) -> list[bytearray]:
    """`count` <= gen_size coefficient rows of full rank `count` (resampled, so the honest
    pool the receiver holds at its first decode attempt has a known rank)."""
    assert count <= gen_size
    rows: list[bytearray] = []
    while len(rows) < count:
        cand = random_row(rng, field, gen_size)
        if any(cand) and not in_row_span(field, cand, rows):
            rows.append(cand)
    return rows


def row_outside_span(rng: random.Random, field: TableField, gen_size: int, rows, exclude=()) -> bytearray:
    """A coefficient row NOT in span(rows) (innovative against them) and not in `exclude`."""
    assert row_rank(field, rows) < gen_size, "rows already span the space -- nothing is innovative"
    while True:
        cand = random_row(rng, field, gen_size)
        if any(cand) and not in_row_span(field, cand, rows) and all(cand != bytes(e) for e in exclude):
            return cand


# ── One arm's tagged generation ───────────────────────────────────────────────

@dataclass
class ArmSetup:
    arm: str
    base_field: TableField
    gen_size: int
    data_fields: int
    n: int                      # segments per packet (1 for the *_n1 controls)
    gen_packets: list           # tagged source packets (identity coefficients)
    data_rows: list             # ground truth: source data row i
    segments: list              # TaggedSegment (keyless) | MacSegment (keyed) | [] (n1)
    keyset: list | None         # keyed: keyset[s] per segment; keyed_n1: [gen_size key vectors]
    scheme: object | None       # production IntegrityScheme (None for keyed_n1)

    @property
    def code_length(self) -> int:
        return self.gen_size + self.data_fields

    def coeff_segment(self):
        return next(s for s in self.segments if s.kind == "coeff")

    def coeff_region(self) -> tuple[int, int]:
        """(start, length) of the coefficient block as the attacker sees it. Segmented:
        the whole coeff-segment slice incl. its salt/tags (they belong to it). N=1: just
        the gen_size coefficient columns -- the whole-packet tag is not separable."""
        if self.n == 1:
            return 0, self.gen_size
        seg = self.coeff_segment()
        return seg.start, seg.total_length

    def data_regions(self) -> list[tuple[int, int]]:
        """(start, length) per data region. Segmented: each data-segment's full slice (payload
        + salt + tags / payload + tags). N=1: the data columns only (tags stay put)."""
        if self.n == 1:
            return [(self.gen_size, self.data_fields)]
        return [(s.start, s.total_length) for s in self.segments if s.kind == "data"]

    def code(self, packet) -> bytearray:
        """[coeffs | data] with every salt/tag byte dropped -- what the RLNC decode sees."""
        if self.n == 1:
            return bytearray(packet[:self.code_length])
        out = bytearray()
        for seg in self.segments:
            out += packet[seg.start: seg.start + seg.payload_length]
        return out

    def new_instrument(self):
        if self.arm == "keyless":
            return SegmentedInstrument(field=CountingField(self.base_field))
        if self.arm == "keyed":
            return SegmentedMacInstrument(field=CountingField(self.base_field), keyset=self.keyset)
        return CountingField(self.base_field)   # keyless_n1 (OrthogonalScheme) / keyed_n1


def _tag_keyless_segmented(field, plain, gen_size, n, salt_seed):
    random.seed(salt_seed)   # tag_generation_segmented draws salts from the global RNG
    result = tag_generation_segmented(field, plain, gen_size, n - 1)
    return (result.packets, result.segments) if result.ok else (None, None)


def _tag_keyless_n1(field, plain, gen_size):
    """Whole-packet orthogonal tags ([coeff | data | gen_size tags], OrthogonalScheme's
    layout). Fixed data can hit a zero self-tag (ADR-0010) -> None, caller redraws data."""
    rows = [bytearray(list(p) + [0] * gen_size) for p in plain]
    tagged = OrthogonalTagGenerator(field).generate_all_tags(rows)
    offset = len(plain[0])
    if any(tagged[k][offset + k] == 0 for k in range(gen_size)) or not check_orth(field, tagged):
        return None
    return [bytearray(p) for p in tagged]


def _build_arm(arm, field, gen_size, data_fields, n, data_rows, keyless_cache, arm_seed) -> ArmSetup:
    plain = generate_identity_coefficients(field, [bytearray(r) for r in data_rows])
    common = dict(arm=arm, base_field=field, gen_size=gen_size, data_fields=data_fields, n=n,
                  data_rows=[bytearray(r) for r in data_rows])
    if arm == "keyless":
        packets, segments = keyless_cache
        scheme = SegmentedScheme(num_data_segments=n - 1, data_fields=data_fields, strategy=STRATEGY,
                                 name=f"segmented_{STRATEGY}_n{n}")
        return ArmSetup(gen_packets=packets, segments=segments, keyset=None, scheme=scheme, **common)
    if arm == "keyed":
        segments = layout_mac_segments(gen_size, data_fields, n - 1, gen_size)
        keyset = generate_keyset(field, segments, random.Random(arm_seed))
        packets = tag_generation_mac(field, plain, gen_size, n - 1, keyset, gen_size)
        scheme = SegmentedMacScheme(num_data_segments=n - 1, data_fields=data_fields, strategy=STRATEGY,
                                    name=f"mac_{STRATEGY}_n{n}")
        return ArmSetup(gen_packets=packets, segments=segments, keyset=keyset, scheme=scheme, **common)
    if arm == "keyless_n1":
        return ArmSetup(gen_packets=keyless_cache, segments=[], keyset=None, scheme=OrthogonalScheme(), **common)
    if arm == "keyed_n1":
        krng = random.Random(arm_seed)
        keys = [random_row(krng, field, gen_size + data_fields) for _ in range(gen_size)]
        packets = [bytearray(p) + bytearray(mac_tag_vector(field, keys, p)) for p in plain]
        return ArmSetup(gen_packets=packets, segments=[], keyset=keys, scheme=None, **common)
    raise ValueError(f"unknown arm {arm!r}")


def paired_setup(seed, field: TableField, gen_size: int, data_fields: int, n: int, arm: str):
    """Build `arm`'s generation for `seed`. Returns (shared_rng, setup).

    Pairing guarantee: the data rows -- and every later draw from the returned shared_rng
    (honest coefficient rows, victim / forged coefficient rows) -- depend only on (seed,
    gen_size, data_fields, n, field), NEVER on the arm. Keyless tagging feasibility for this
    n is checked for EVERY arm (keyed included), so a small-field salt give-up redraws the
    data identically in every arm instead of desynchronising them."""
    assert (n == 1) == (arm in N1_ARMS), f"arm {arm} does not take n={n}"
    shared = random.Random(seed)
    for attempt in range(MAX_SOURCE_DRAWS):
        data_rows = [random_row(shared, field, data_fields) for _ in range(gen_size)]
        plain = generate_identity_coefficients(field, [bytearray(r) for r in data_rows])
        if n == 1:
            cache = _tag_keyless_n1(field, plain, gen_size)
            feasible = cache is not None
        else:
            packets, segments = _tag_keyless_segmented(field, plain, gen_size, n, f"{seed}/{attempt}/salt")
            cache, feasible = (packets, segments), packets is not None
        if feasible:
            return shared, _build_arm(arm, field, gen_size, data_fields, n, data_rows, cache,
                                      f"{seed}/{attempt}/{arm}")
    raise RuntimeError(f"keyless tagging gave up {MAX_SOURCE_DRAWS}x (seed={seed}, n={n}, "
                       f"GF(2^{field.bit_lenght})) -- field too small for this layout")


def recode(setup: ArmSetup, coeffs) -> bytearray:
    """Honest recoded packet with the given coefficient row (identity source => its
    coefficient block IS `coeffs`). Tags ride along homomorphically in every arm."""
    return code_with_given_coefficients(setup.gen_packets, bytearray(coeffs), setup.base_field)


# ── Admission (production path) + strict oracle ───────────────────────────────

def _keyed_n1_valid(field, setup: ArmSetup, packet) -> bool:
    return list(packet[setup.code_length:]) == mac_tag_vector(field, setup.keyset, packet[:setup.code_length])


def admit_codes(setup: ArmSetup, instrument, pool, cfg: AdmitConfig):
    """Code rows ([coeff|data]) the receiver lets into the decode basis, or None = wait.
    Segmented + keyless_n1 run the real scheme.admit (incl. its repair); keyed_n1 is
    detect-and-drop (see module docstring)."""
    g = setup.gen_size
    if setup.arm in SEGMENTED_ARMS:
        res = setup.scheme.admit(instrument, [bytearray(p) for p in pool], g, cfg)
        return None if res is None else [bytearray(c) for c in res]
    if setup.arm == "keyless_n1":
        res = setup.scheme.admit(instrument, [bytearray(p) for p in pool], g, cfg)
        return None if res is None else [setup.code(p) for p in res]
    if len(pool) < max(g, cfg.min_pool_size):
        return None
    return [setup.code(p) for p in pool if _keyed_n1_valid(instrument, setup, p)]


def passes_oracle(setup: ArmSetup, packet, honest_pool, field=None) -> bool:
    """Strict acceptance: every segment of `packet` passes its check against EVERY packet in
    `honest_pool` (keyless: self + cross orthogonality; keyed: all MAC tags). No repair and
    no trust heuristics -- the pure tag-strength event whose theory is q^-u."""
    f = field or setup.base_field
    if setup.arm == "keyed":
        return all(mac_verify_segment(f, setup.keyset[s], packet[seg.start:seg.start + seg.total_length], seg)
                   for s, seg in enumerate(setup.segments))
    if setup.arm == "keyed_n1":
        return _keyed_n1_valid(f, setup, packet)
    regions = ([(0, len(packet))] if setup.arm == "keyless_n1"
               else [(s.start, s.total_length) for s in setup.segments])
    for start, length in regions:
        sl = packet[start:start + length]
        if not check_orth_packet(f, sl):
            return False
        if any(inner_product_bytes(f, sl, h[start:start + length]) != 0 for h in honest_pool):
            return False
    return True


# ── Receiver ───────────────────────────────────────────────────────────────────

@dataclass
class ReceiverOutcome:
    decoded: bool               # admitted set reached full rank (receiver stops, can't tell right from wrong)
    correct: bool               # decoded == source
    admitted: list              # code rows admitted at the LAST admit call
    packets_received: int
    admit_calls: int


def run_receiver(setup: ArmSetup, arrivals, cfg: AdmitConfig, max_packets: int, instrument=None) -> ReceiverOutcome:
    """Feed `arrivals` (an iterable of wire packets) into the pool; from gen_size packets on,
    admit + try to decode after every arrival; stop on decode or at max_packets."""
    instrument = instrument if instrument is not None else setup.new_instrument()
    pool, admitted = [], []
    decoded = correct = False
    admit_calls = 0
    for pkt in arrivals:
        pool.append(bytearray(pkt))
        if len(pool) >= setup.gen_size:
            res = admit_codes(setup, instrument, pool, cfg)
            admit_calls += 1
            if res is not None:
                admitted = res
                decoded, correct = _try_decode(setup.base_field, [bytearray(c) for c in res],
                                               setup.gen_size, setup.data_rows)
                if decoded:
                    break
        if len(pool) >= max_packets:
            break
    return ReceiverOutcome(decoded=decoded, correct=correct, admitted=admitted,
                           packets_received=len(pool), admit_calls=admit_calls)


def injected_status(setup: ArmSetup, outcome: ReceiverOutcome, injected, honest_packets) -> tuple[bool, bool]:
    """(admitted, modified): was the injected packet in the final admitted set, and if so,
    was it admitted in a MODIFIED form (the repair machinery changed it)? Without channel
    noise every honest packet is clean and never modified, so any admitted code row outside
    the honest code rows is the injected packet."""
    honest_codes = {bytes(setup.code(h)) for h in honest_packets}
    foreign = [c for c in outcome.admitted if bytes(c) not in honest_codes]
    if not foreign:
        return False, False
    return True, all(bytes(c) != bytes(setup.code(injected)) for c in foreign)


def arrivals_with_injection(setup: ArmSetup, head_rows, injected, strike_index: int, tail_rng: random.Random,
                            honest_log: list):
    """Arrival stream: honest recodes of `head_rows` with `injected` inserted at position
    strike_index (0 = first), then endless fresh honest recodes drawn from tail_rng. Every
    honest packet produced is appended to honest_log (for injected_status)."""
    assert 0 <= strike_index <= len(head_rows)
    for i, row in enumerate(head_rows):
        if i == strike_index:
            yield injected
        pkt = recode(setup, row)
        honest_log.append(pkt)
        yield pkt
    if strike_index == len(head_rows):
        yield injected
    while True:
        pkt = recode(setup, random_row(tail_rng, setup.base_field, setup.gen_size))
        honest_log.append(pkt)
        yield pkt
