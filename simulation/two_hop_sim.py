r"""Two-hop recoding simulation (ADR-0015 task 2): Source -> Relay (recodes) -> Sink.

Why: on ONE hop a per-segment CRC-32 (+ ACR repair) does everything the keyless tag does, cheaper
(ADR-0014). The keyless (and keyed) tag exists for the multi-hop case: it is linear over GF(2^8), so
a relay's RLNC recoding carries it along for free, while a CRC is only GF(2)-linear -- a recoded
packet's CRC is invalid, so a relay that recodes must recompute the CRCs and therefore either trust
what it received (blind) or verify it first (verify).

Model (ADR-0005/0006 tick semantics, single path):
- one packet per link per tick; the source sends one fresh coded packet per tick until the sink
  decodes; the relay forwards a fresh random combination of its whole USABLE buffer every tick once
  it holds >= RELAY_BUFFER_THRESHOLD (3) usable packets (buffer uncapped, ADR-0006). Cap MAX_TICKS.
- channel errors on BOTH hops, data-payload bytes only (coefficients and tags/CRCs clean, the
  ACR-only rule), iid bit flips at ber1 / ber2.
- relay policies per scheme (ADR-0015 point 9):
    crc     verify: CRC every segment on arrival, drop failures, buffer the stripped [coeff | data],
                    recode clean packets only, recompute the CRCs (a trusted, re-tagging relay).
            blind : strip CRCs unchecked, recode everything, recompute CRCs -> a hop-1 error gets a
                    fresh valid CRC (undetectable at the sink).
    keyless verify: production trust classification (classify_segment_trust: self-check + cross-check
                    against up to verify_count core witnesses) re-evaluated on the whole buffer every
                    tick (IncrementalSegmentTrust = the same result, cached inner products); recode only
                    packets trusted in every segment. Never re-tags (the tags are linear).
            blind : recode everything -- a corrupted input pollutes every later combination (scaled
                    by its random coefficient); the sink still detects it end to end.
    keyed   verify: relay holds the MAC key, verifies every segment on arrival, drops failures.
            blind : no key -- recode everything (MAC tags are linear too).
- sink: the scheme's production admit (keyless / keyed acr_only, CRC = SegmentedCrcScheme("acr"), the
  S-PRAC-like CRC + ACR repair) -> RLNC decode, graded against the source (silent = full rank, wrong data).

Common random numbers: one trial seed (independent of scheme and policy) fixes the source data, the
source coefficients and the hop-1 error pattern (dedicated RNG streams; the error positions are the
same data-payload bits in every layout), so every scheme x policy sees the same hop-1 corruption.

Metrics per trial (TwoHopTrial): status, silent decode (headline), hop-1 / hop-2 packets until the sink
decodes, relay drops, corrupted hop-1 packets that entered a recoding, polluted relay emissions, sink
repairs, relay work (CRC bytes; field muls of the check; field muls of recoding), wall-clock (secondary).

Run (PowerShell; LOG_FOLDER + PYTHONPATH as for every sim):
  $env:PYTHONPATH="."; $env:LOG_FOLDER="./logs"; & "E:/projects/studienarbeit/.venv/Scripts/python.exe" simulation/two_hop_sim.py --smoke
  ... simulation/two_hop_sim.py --sweep --workers 4 --trials 200 --out E:/projects/studienarbeit/logs/two_hop_recoding/runs/main
Plots: scripts/two_hop_plots.py. Full run: scripts/two_hop_runs.sh.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
import time
import zlib
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("LOG_FOLDER", str(_ROOT / "logs"))

from binary_ext_fields.custom_field import CountingField, create_field
from binary_ext_fields.generate_symbols import check_orth_packet
from binary_ext_fields.operations import inner_product_bytes
from binary_ext_fields.segmented_mac_tagging import layout_mac_segments, mac_verify_segment
from binary_ext_fields.segmented_recovery import SegmentTrust, segment_slice
from binary_ext_fields.segmented_tagging import layout_segments
from simulation.integrity_schemes import (
    AdmitConfig, SegmentedCrcScheme, SegmentedMacScheme, SegmentedScheme, _strip_to_code,
)
from simulation.network_sim import RELAY_BUFFER_THRESHOLD
from simulation.recovery_decode_sim import _try_decode
from simulation.segmented_crc import Crc32Instrument

SCHEMA_VERSION = 1
SCHEMES = ("crc", "keyless", "keyed")
POLICIES = ("verify", "blind")
GEN_SIZE = 4
FIELD_M = 8
MAX_TICKS = 64                          # 16 x gen_size, as Task 1's packet cap
CONFIGS = ((100, 3), (300, 7), (1000, 21))   # (df, N incl. coeff segment): 50 B data segments
BERS = (1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2)


def default_admit_config() -> AdmitConfig:
    """Sink (and keyless relay) knobs = Task 1's repair arms: HD 2, budget 20000, payload span,
    verify_count 4 (AdmitConfig default), min_pool_size = gen_size. final_check=False skips the unused
    post-repair whole-pool check (identical admitted packets, test in two_hop_test) -- the O(M^2) keyless
    check dominated the cost of stalled generations."""
    return AdmitConfig(hamming_distance=2, pair_budget=20000, repair_span="payload", min_pool_size=GEN_SIZE,
                       final_check=False)


# ── GF helpers with explicit RNGs (common random numbers) ─────────────────────

def combine(field, packets, coeffs) -> bytearray:
    """sum_j coeffs[j] * packets[j] over GF(2^m) by table lookups (field add = the field's add table)."""
    mul, add = field._mul, field._add
    out = [0] * len(packets[0])
    for c, p in zip(coeffs, packets):
        if c:
            row = mul[c]
            out = [add[o][row[b]] for o, b in zip(out, p)]
    return bytearray(out)


def pollute(packet, ber: float, positions, rng: random.Random, bits_per_symbol: int = FIELD_M) -> bytearray:
    """Flip each of the low `bits_per_symbol` bits of every byte in `positions` independently with
    probability `ber` (same channel as scheme_comparison_sim._pollute_positions), drawn by geometric
    gaps -- O(#flips) draws, and the same number of candidate bits in every layout."""
    out = bytearray(packet)
    if ber <= 0:
        return out
    n = len(positions) * bits_per_symbol
    log_q = math.log1p(-ber)
    k = -1
    while True:
        k += 1 + int(math.log(1.0 - rng.random()) / log_q)
        if k >= n:
            return out
        byte_i, bit = divmod(k, bits_per_symbol)
        out[positions[byte_i]] ^= 1 << bit


# ── Keyless relay trust: classify_segment_trust with cached inner products ────

class IncrementalSegmentTrust:
    """classify_segment_trust(field, pool, segment, verify_count) for an APPEND-ONLY pool: the
    self-checks and the pairwise agreement among self-passers are cached, so an arrival costs
    1 + #self-passers inner products (charged to `field`) instead of the full O(m^2) matrix per call.
    classify() then runs the identical greedy peel + witness check -> identical SegmentTrust
    (two_hop_test compares them on random corrupted pools)."""

    def __init__(self, field, segment, verify_count: int | None):
        self.field, self.segment, self.verify_count = field, segment, verify_count
        self.slices: list[bytearray] = []
        self.self_pass: list[int] = []
        self.bad: dict[tuple[int, int], bool] = {}   # (a, b), a < b self-passers -> not orthogonal

    def add(self, packet) -> None:
        s = segment_slice(packet, self.segment)
        i = len(self.slices)
        self.slices.append(s)
        if check_orth_packet(self.field, s):
            for j in self.self_pass:
                self.bad[(j, i)] = inner_product_bytes(self.field, self.slices[j], s) != 0
            self.self_pass.append(i)

    def classify(self) -> SegmentTrust:
        self_pass = self.self_pass
        sp = set(self_pass)
        broken = [i for i in range(len(self.slices)) if i not in sp]
        m = len(self_pass)
        disagree = [[False] * m for _ in range(m)]
        for a in range(m):
            for b in range(a + 1, m):
                disagree[a][b] = disagree[b][a] = self.bad[(self_pass[a], self_pass[b])]
        # -- verbatim segmented_recovery.classify_segment_trust (witness_rank=None) from here --
        alive = set(range(m))
        while alive:
            counts = {a: sum(1 for b in alive if b != a and disagree[a][b]) for a in alive}
            worst = max(alive, key=lambda a: counts[a])
            if counts[worst] == 0:
                break
            alive.discard(worst)
        core = sorted(alive)
        trusted = []
        for a in range(m):
            witnesses = [c for c in core if c != a]
            if self.verify_count is not None:
                witnesses = witnesses[:self.verify_count]
            if all(not disagree[a][c] for c in witnesses):
                trusted.append(self_pass[a])
        return SegmentTrust(self.segment.name, broken=broken, trusted=sorted(trusted))


# ── Relays ────────────────────────────────────────────────────────────────────

class Relay:
    """Buffer + policy + recoding of the usable set. Work counters: recode_mul (k x L field muls per
    emission, common to every scheme), check_mul (keyless / keyed verification), verify_crc_bytes /
    retag_crc_bytes (CRC relay), check_time_s (wall-clock of the policy check, secondary)."""

    def __init__(self, field, policy: str, rng: random.Random, threshold: int = RELAY_BUFFER_THRESHOLD):
        assert policy in POLICIES, f"policy must be one of {POLICIES}, got {policy!r}"
        self.field, self.policy, self.rng, self.threshold = field, policy, rng, threshold
        self.check_field = CountingField(field)
        self.buffer: list[bytearray] = []
        self.corrupted: list[bool] = []    # ground truth per buffer entry (hop-1 flip)
        self.used: list[bool] = []         # entered >= 1 recoding
        self.received = self.dropped = 0
        self.recode_mul = 0
        self.verify_crc_bytes = self.retag_crc_bytes = 0
        self.check_time_s = 0.0

    def receive(self, wire: bytearray, corrupted: bool) -> None:
        self.received += 1
        t0 = time.perf_counter()
        keep = self._accept(wire)
        self.check_time_s += time.perf_counter() - t0
        if keep is None:
            self.dropped += 1
            return
        self.buffer.append(keep)
        self.corrupted.append(corrupted)
        self.used.append(False)

    def _accept(self, wire):            # -> buffer entry, or None (dropped at arrival)
        return bytearray(wire)

    def usable(self) -> list[int]:
        return list(range(len(self.buffer)))

    def emit(self):
        """(wire packet, its [coeff | data] info code) or None when fewer than `threshold` are usable."""
        t0 = time.perf_counter()
        idx = self.usable()
        self.check_time_s += time.perf_counter() - t0
        if len(idx) < self.threshold:
            return None
        coeffs = [self.rng.randint(0, self.field.max_value) for _ in idx]
        out = combine(self.field, [self.buffer[i] for i in idx], coeffs)
        self.recode_mul += len(idx) * len(out)
        for i in idx:
            self.used[i] = True
        return self._frame(out)

    def _frame(self, out):              # -> (wire, info code)
        raise NotImplementedError

    def polluted_inputs_used(self) -> int:
        return sum(1 for c, u in zip(self.corrupted, self.used) if c and u)


class CrcRelay(Relay):
    """Buffers [coeff | data] (CRCs stripped); verify = every segment's CRC on arrival; re-CRCs."""

    def __init__(self, field, policy, rng, scheme: SegmentedCrcScheme, gen_size: int):
        super().__init__(field, policy, rng)
        self.scheme = scheme
        self.segments = scheme.wire_segments(gen_size)
        self.crc_verify, self.crc_tag = Crc32Instrument(), Crc32Instrument()

    def _accept(self, wire):
        if self.policy == "verify" and not self.scheme.packet_ok(self.crc_verify, wire, self.segments):
            return None
        return _strip_to_code(wire, self.segments)

    def _frame(self, out):
        wire = self.scheme.frame(self.crc_tag, out)
        self.verify_crc_bytes, self.retag_crc_bytes = self.crc_verify.crc_ops, self.crc_tag.crc_ops
        return wire, out


class KeylessRelay(Relay):
    """Buffers whole tagged packets; verify = production trust classification, every tick."""

    def __init__(self, field, policy, rng, segments, verify_count: int | None):
        super().__init__(field, policy, rng)
        self.segments = segments
        self.trust = [IncrementalSegmentTrust(self.check_field, s, verify_count) for s in segments] \
            if policy == "verify" else []

    def _accept(self, wire):
        for t in self.trust:
            t.add(wire)
        return bytearray(wire)

    def usable(self):
        if self.policy == "blind":
            return list(range(len(self.buffer)))
        good = set(range(len(self.buffer)))
        for t in self.trust:
            good &= set(t.classify().trusted)
        return sorted(good)

    def _frame(self, out):
        return out, _strip_to_code(out, self.segments)


class KeyedRelay(Relay):
    """Buffers whole MAC-tagged packets; verify = the relay holds the key, MAC check on arrival."""

    def __init__(self, field, policy, rng, segments, keyset):
        super().__init__(field, policy, rng)
        self.segments, self.keyset = segments, keyset

    def _accept(self, wire):
        if self.policy == "verify":
            for keys, seg in zip(self.keyset, self.segments):
                if not mac_verify_segment(self.check_field, keys, segment_slice(wire, seg), seg, early_exit=True):
                    return None
        return bytearray(wire)

    def _frame(self, out):
        return out, _strip_to_code(out, self.segments)


# ── One trial ─────────────────────────────────────────────────────────────────

def make_sink_scheme(scheme: str, n_segments: int, df: int):
    """The sink's production admit per scheme (ADR-0015 point 10)."""
    if scheme == "crc":
        return SegmentedCrcScheme(n_segments - 1, df, repair="acr", name=f"crc_acr_n{n_segments}_df{df}")
    if scheme == "keyless":
        return SegmentedScheme(n_segments - 1, df, "acr_only", name=f"keyless_n{n_segments}_df{df}")
    assert scheme == "keyed", f"scheme must be one of {SCHEMES}, got {scheme!r}"
    return SegmentedMacScheme(n_segments - 1, df, "acr_only", name=f"keyed_n{n_segments}_df{df}")


def wire_segments_for(scheme: str, sink_scheme, gen_size: int, df: int, n_segments: int):
    if scheme == "crc":
        return sink_scheme.wire_segments(gen_size)
    if scheme == "keyless":
        return layout_segments(gen_size, df, n_segments - 1)
    return layout_mac_segments(gen_size, df, n_segments - 1, gen_size)


@dataclass
class TwoHopTrial:
    scheme: str
    policy: str
    data_fields: int
    n_segments: int
    ber1: float
    ber2: float
    trial_idx: int
    seed: int
    max_ticks: int
    wire_bytes: int
    status: str                  # decoded | silent_decode | timeout
    decoded: bool
    correct: bool
    silent_decode: bool
    ticks: int                   # = hop-1 packets (the source sends every tick)
    hop1_packets: int
    hop2_packets: int            # relay emissions
    first_emit_tick: int         # 0 = the relay never forwarded (starved)
    relay_corrupted_rx: int      # hop-1 arrivals with >= 1 flipped bit
    relay_dropped: int           # crc / keyed verify: refused at arrival; keyless verify: not trusted at the end
    relay_polluted_inputs: int   # corrupted arrivals that entered >= 1 recoding
    hop2_polluted_emitted: int   # relay emissions carrying hop-1 pollution (before hop 2)
    sink_corrupted_rx: int       # sink arrivals with wrong information (hop-1 pollution and/or hop-2 flips)
    sink_accepted_final: int
    sink_repaired_used: int      # corrupted sink arrivals inside the final decode basis with the right info
    sink_wrong_used: int         # admitted packets with wrong information
    relay_verify_crc_bytes: int
    relay_retag_crc_bytes: int
    relay_check_mul: int
    relay_recode_mul: int
    sink_scheme_mul: int
    sink_crc_bytes: int
    sink_decode_mul: int
    relay_check_time_s: float
    wall_time_s: float
    schema_version: int = SCHEMA_VERSION


def trial_seed(df: int, n_segments: int, ber1: float, ber2: float, trial_idx: int) -> int:
    """Independent of scheme and policy -> every scheme x policy is paired on the same hop 1."""
    return zlib.crc32(f"twohop|{GEN_SIZE}|{FIELD_M}|{df}|{n_segments}|{ber1!r}|{ber2!r}|{trial_idx}".encode())


def run_two_hop_trial(field, scheme: str, policy: str, df: int, n_segments: int, ber1: float, ber2: float,
                      trial_idx: int = 0, seed: int | None = None, cfg: AdmitConfig | None = None,
                      gen_size: int = GEN_SIZE, max_ticks: int = MAX_TICKS,
                      hop1_hook=None) -> TwoHopTrial:
    """One generation through Source -> Relay -> Sink. `hop1_hook(tick, wire) -> wire` (tests only)
    replaces the hop-1 channel output, e.g. to plant one exact corruption."""
    cfg = cfg or default_admit_config()
    seed = trial_seed(df, n_segments, ber1, ber2, trial_idx) if seed is None else seed
    random.seed(seed)                                       # source data (+ keyless salts, keyed keys)
    rng_src, rng_h1, rng_relay, rng_h2 = (random.Random(seed * 4 + k) for k in (1, 2, 3, 4))

    sink_scheme = make_sink_scheme(scheme, n_segments, df)
    source, source_data = sink_scheme.make_source(field, df, gen_size)
    sink_inst = sink_scheme.new_instrument(field)           # keyed: takes the keyset (source + sink)
    src_inst = sink_scheme.new_instrument(field) if scheme == "crc" else sink_inst
    segments = wire_segments_for(scheme, sink_scheme, gen_size, df, n_segments)
    positions = sink_scheme.error_positions(gen_size, "data_payload")
    if scheme == "crc":
        relay = CrcRelay(field, policy, rng_relay, sink_scheme, gen_size)
    elif scheme == "keyless":
        relay = KeylessRelay(field, policy, rng_relay, segments, cfg.verify_count)
    else:
        relay = KeyedRelay(field, policy, rng_relay, segments, sink_inst.keyset)

    def info_wrong(code) -> bool:
        return bytes(code[gen_size:]) != bytes(combine(field, source_data, code[:gen_size]))

    cnt_decode = CountingField(field)
    pool: list[bytearray] = []
    decoded = correct = False
    accepted = None
    corrupted_keys: set = set()
    tick = hop2 = first_emit = relay_corrupted = hop2_polluted = sink_corrupted = 0
    wire_bytes = 0
    start = time.perf_counter()
    for tick in range(1, max_ticks + 1):
        code = combine(field, source, [rng_src.randint(0, field.max_value) for _ in range(gen_size)])
        wire = sink_scheme.attach(src_inst, code)
        wire_bytes = len(wire)
        rx1 = pollute(wire, ber1, positions, rng_h1, field.bit_lenght)
        if hop1_hook is not None:
            rx1 = hop1_hook(tick, rx1)
        hit1 = rx1 != wire
        relay_corrupted += hit1
        relay.receive(rx1, hit1)

        emitted = relay.emit()
        if emitted is None:
            continue
        out, out_code = emitted
        hop2 += 1
        first_emit = first_emit or tick
        polluted = info_wrong(out_code)
        hop2_polluted += polluted
        rx2 = pollute(out, ber2, positions, rng_h2, field.bit_lenght)
        if polluted or rx2 != out:
            sink_corrupted += 1
            corrupted_keys.add(bytes(out_code[:gen_size]))
        pool.append(rx2)
        accepted = sink_scheme.admit(sink_inst, pool, gen_size, cfg)
        if accepted is None:
            continue
        decoded, correct = _try_decode(cnt_decode, accepted, gen_size, source_data)
        if decoded:
            break
    wall = time.perf_counter() - start

    repaired_used = wrong_used = 0
    for c in accepted or []:
        if info_wrong(c):
            wrong_used += 1
        elif bytes(c[:gen_size]) in corrupted_keys:
            repaired_used += 1
    ops = sink_scheme.op_counts(sink_inst)
    if isinstance(relay, CrcRelay):
        relay.verify_crc_bytes, relay.retag_crc_bytes = relay.crc_verify.crc_ops, relay.crc_tag.crc_ops
    if isinstance(relay, KeylessRelay) and policy == "verify":
        relay.dropped = len(relay.buffer) - len(relay.usable())   # not trusted at the end (never refused)
    silent = decoded and not correct
    return TwoHopTrial(
        scheme=scheme, policy=policy, data_fields=df, n_segments=n_segments, ber1=ber1, ber2=ber2,
        trial_idx=trial_idx, seed=seed, max_ticks=max_ticks, wire_bytes=wire_bytes,
        status="decoded" if correct else ("silent_decode" if decoded else "timeout"),
        decoded=decoded, correct=correct, silent_decode=silent,
        ticks=tick, hop1_packets=tick, hop2_packets=hop2, first_emit_tick=first_emit,
        relay_corrupted_rx=relay_corrupted, relay_dropped=relay.dropped,
        relay_polluted_inputs=relay.polluted_inputs_used(), hop2_polluted_emitted=hop2_polluted,
        sink_corrupted_rx=sink_corrupted, sink_accepted_final=len(accepted or []),
        sink_repaired_used=repaired_used, sink_wrong_used=wrong_used,
        relay_verify_crc_bytes=relay.verify_crc_bytes, relay_retag_crc_bytes=relay.retag_crc_bytes,
        relay_check_mul=relay.check_field.mul_count, relay_recode_mul=relay.recode_mul,
        sink_scheme_mul=sink_scheme.primary_ops(sink_inst), sink_crc_bytes=ops.get("crc_bytes", 0),
        sink_decode_mul=cnt_decode.mul_count, relay_check_time_s=relay.check_time_s, wall_time_s=wall,
    )


# ── Sweep driver (process pool, per-trial append + resume, per-cell budget) ───

CSV_COLUMNS = [f.name for f in fields(TwoHopTrial)]
_FIELD_CACHE = {}


def _run_task(task: tuple) -> dict:
    from icecream import ic
    ic.disable()   # playground/arc_pl.py debug prints
    scheme, policy, df, n, ber1, ber2, t, max_ticks = task
    field = _FIELD_CACHE.setdefault(FIELD_M, create_field(FIELD_M))
    return asdict(run_two_hop_trial(field, scheme, policy, df, n, ber1, ber2, trial_idx=t, max_ticks=max_ticks))


def _cell(row) -> tuple:
    return (row["scheme"], row["policy"], int(row["data_fields"]), int(row["n_segments"]),
            float(row["ber1"]), float(row["ber2"]))


def run_sweep(out_dir: Path, schemes=SCHEMES, policies=POLICIES, configs=CONFIGS, bers=BERS, ber2=None,
              trials: int = 200, workers: int = 4, cell_budget_s: float = 1800.0,
              max_ticks: int = MAX_TICKS) -> Path:
    """Every (scheme, policy, df, BER) cell, `trials` paired trials each. ber2=None -> same BER on both
    hops; a float -> hop 2 fixed at that BER (asymmetric). A cell stops getting new trials once its
    summed trial wall time reaches cell_budget_s (every cell gets >= 1 trial)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "raw_trials.csv"
    done = {}
    if raw.exists():
        with raw.open(newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames and reader.fieldnames != CSV_COLUMNS:
                raise SystemExit(f"{raw}: other schema, resume with the code that wrote it")
            for row in reader:
                done[(_cell(row), int(row["trial_idx"]))] = float(row["wall_time_s"])
    cells = [(s, p, df, n, b, b if ber2 is None else ber2)
             for (df, n) in configs for b in bers for s in schemes for p in policies]
    # cheap first: expected flips per packet x packet length (ordering heuristic only)
    cells.sort(key=lambda c: c[4] * c[2] * c[2])
    (out_dir / "run_config.json").write_text(json.dumps({
        "schema_version": SCHEMA_VERSION, "gen_size": GEN_SIZE, "field_m": FIELD_M, "schemes": list(schemes),
        "policies": list(policies), "configs": [list(c) for c in configs], "bers": list(bers), "ber2": ber2,
        "trials": trials, "workers": workers, "cell_budget_s": cell_budget_s, "max_ticks": max_ticks,
        "relay_buffer_threshold": RELAY_BUFFER_THRESHOLD, "admit_config": asdict(default_admit_config()),
        "started": datetime.now().isoformat(timespec="seconds"),
    }, indent=2))

    spent = {c: 0.0 for c in cells}
    count = {c: 0 for c in cells}
    inflight = {c: 0 for c in cells}
    queue = []
    for c in cells:
        for t in range(trials):
            if (c, t) in done:
                spent[c] += done[(c, t)]
                count[c] += 1
            else:
                queue.append((c, t))
    print(f"out: {out_dir}\n{len(cells)} cells, {len(queue)} trials queued ({len(done)} resumed), "
          f"workers={workers}, cell budget {cell_budget_s:g}s, max_ticks {max_ticks}", flush=True)

    skipped = 0
    t0 = time.perf_counter()
    new_file = not raw.exists()
    with raw.open("a", newline="") as f, ProcessPoolExecutor(max_workers=workers) as ex:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if new_file:
            writer.writeheader()
            f.flush()
        futs = {}
        while queue or futs:
            kept = []
            for c, t in queue:
                if count[c] > 0 and spent[c] >= cell_budget_s and inflight[c] == 0:
                    skipped += 1
                else:
                    kept.append((c, t))
            queue = kept
            while len(futs) < workers:
                pick = next(((c, t) for c, t in queue
                             if count[c] + inflight[c] == 0 or spent[c] < cell_budget_s), None)
                if pick is None:
                    break
                queue.remove(pick)
                c, t = pick
                inflight[c] += 1
                futs[ex.submit(_run_task, (*c, t, max_ticks))] = pick
            if not futs:
                break
            finished, _ = wait(futs, return_when=FIRST_COMPLETED)
            for fut in finished:
                c, t = futs.pop(fut)
                inflight[c] -= 1
                row = fut.result()
                writer.writerow(row)
                f.flush()
                spent[c] += row["wall_time_s"]
                count[c] += 1
                print(f"[{time.perf_counter() - t0:7.0f}s] {c[0]:<7} {c[1]:<6} df={c[2]:<4} ber={c[4]:.0e} "
                      f"t{t:<3} {row['status']:<13} h1={row['hop1_packets']:<3} h2={row['hop2_packets']:<3} "
                      f"wall={row['wall_time_s']:.2f}s cell {count[c]}/{trials}", flush=True)
    print(f"done in {time.perf_counter() - t0:.0f}s; {skipped} trials skipped by cell budget", flush=True)
    for c in cells:
        if count[c] < trials:
            print(f"  capped: {c} -> {count[c]}/{trials} trials", flush=True)
    return out_dir


# ── Readable smoke ────────────────────────────────────────────────────────────

def run_smoke(df: int = 100, n: int = 3, bers=(1e-4, 1e-3), trials: int = 4) -> None:
    from icecream import ic
    ic.disable()
    field = create_field(FIELD_M)
    print(f"two-hop smoke: df={df} N={n} g={GEN_SIZE} cap {MAX_TICKS} ticks, same BER both hops, paired trials")
    print(f"{'scheme':<8}{'policy':<7}{'BER':>7} | per trial: status h1/h2 relay(drop, polluted-used) sink(repaired, wrong)")
    for ber in bers:
        for s in SCHEMES:
            for p in POLICIES:
                cells = []
                for t in range(trials):
                    r = run_two_hop_trial(field, s, p, df, n, ber, ber, trial_idx=t)
                    tag = {"decoded": "OK", "silent_decode": "SILENT", "timeout": "STALL"}[r.status]
                    cells.append(f"{tag} {r.hop1_packets}/{r.hop2_packets} ({r.relay_dropped},{r.relay_polluted_inputs})"
                                 f" ({r.sink_repaired_used},{r.sink_wrong_used})")
                print(f"{s:<8}{p:<7}{ber:>7.0e} | " + " | ".join(cells), flush=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Two-hop recoding sim (ADR-0015 task 2).")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--schemes", default=",".join(SCHEMES))
    ap.add_argument("--policies", default=",".join(POLICIES))
    ap.add_argument("--configs", default=",".join(f"{d}:{n}" for d, n in CONFIGS), help='"df:N,..."')
    ap.add_argument("--bers", default=",".join(repr(b) for b in BERS))
    ap.add_argument("--ber2", type=float, default=None, help="fixed hop-2 BER (default: same as hop 1)")
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cell-budget-s", type=float, default=1800.0)
    ap.add_argument("--max-ticks", type=int, default=MAX_TICKS)
    a = ap.parse_args(argv)
    if a.smoke:
        run_smoke()
    elif a.sweep:
        out = a.out or _ROOT / "logs" / "two_hop_recoding" / f"{datetime.now():%Y%m%d_%H%M%S}"
        run_sweep(out, schemes=tuple(a.schemes.split(",")), policies=tuple(a.policies.split(",")),
                  configs=tuple(tuple(int(x) for x in c.split(":")) for c in a.configs.split(",")),
                  bers=tuple(float(b) for b in a.bers.split(",")), ber2=a.ber2, trials=a.trials,
                  workers=a.workers, cell_budget_s=a.cell_budget_s, max_ticks=a.max_ticks)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
