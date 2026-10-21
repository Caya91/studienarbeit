# Intelligent pollution is a white-box on-path relay that forges packets to be silently accepted, measured by attacker work vs. the time-to-decode window

ADR-0007 declared two attacker models — random (baseline) and "intelligent" (detection-evading) — but left the intelligent one as a stub (`pollute_intelligent`, `binary_ext_fields/pollution.py`) with only the shape "craft a corrupted packet that passes the acceptance oracle while differing from the true packet." This ADR fixes the concrete threat model, the success definition, the construction, and what "how much work does the attacker have to do" is measured in. The driving question: *how much effort must an attacker spend to produce a packet that is silently accepted (passes the oracle, enters the decode basis, and corrupts the decode without ever being flagged), and how does that trade against the time it has before the generation decodes?*

**Threat model: an on-path malicious relay that forwards-and-records, then strikes.** The attacker is a relay on the receiver's inbound link (the ADR-0006 relay topology, one relay turned malicious). It honestly forwards legitimate packets for a while — but keeps copies. Because the receiver's trust pool is built out of exactly the packets the attacker forwarded, "the attacker has seen packet X" and "packet X is in the receiver's trust pool" are the *same statement by construction* — no separate overlap/eavesdrop-vantage model is needed for this first pass. After the receiver has accumulated `S` trusted packets (the **strike point**), the relay begins injecting forged polluted packets. Honest nodes keep sending throughout, so polluted packets are only ever a fraction of what the receiver accepts — but see the "one is enough" note below on why that fraction does not confer safety.

**Knowledge: white-box on the scheme (Kerckhoffs), full knowledge of the forwarded set.** The attacker knows the field, the tag scheme, and every packet it forwarded (coefficients, data, and tags). `K`, the count of trusted packets it can forge agreement with, equals `S`, the strike point. A genuinely black-box attacker (no scheme knowledge) is not this model — per ADR-0007 it is not expected to beat the `~1/field_size` per-constraint baseline, and is deferred.

**Success = accepted AND wrong decode.** A forged packet counts as a silent-accept success only if it (1) passes the self-check `<p,p> == 0`, (2) reaches the trust threshold by cross-agreeing with `>= threshold` other self-passing pool packets (ADR-0004), and (3) once in the basis, changes the decoded message relative to ground truth. Merely passing the oracle is not enough — grading re-decodes (`calculate_rref` -> `invert_pivot_rows`) and compares to the known source, matching ADR-0007's silent-failure semantics. This is the honest safety bar; a packet that is accepted but harmless is not scored a success.

**Construction: targeted forgery by linear solve (`pollute_intelligent`).** The forged packet is built white-box: pick a coefficient vector **linearly independent** of the forwarded set (the attacker knows it, so poisoning is deterministic — the packet is guaranteed to pivot into the decode basis and shift the solution); fill in data inconsistent with those coefficients (wrong message); forge the self-tag for free via the square-root lookup (`OrthogonalTagGenerator.generate_tag`) — note the self-check requires *zero* knowledge, since it involves only the packet itself; and solve the cross-orthogonality constraints against exactly `threshold` of the saved packets (minimum work) as a linear system over GF(2^m), reserving the self-tag column to be closed last so its contribution to `<p,p>` is accounted for. Targeting only `threshold` packets rather than all `S` is the minimum-work choice; targeting more is a robustness knob for later.

The honest tag generator (`generate_all_tags`) is *not* reused for this attack. It stays orthogonal to prior packets only because it builds them together in triangular order; against `S` arbitrary already-tagged packets that triangularity is gone, so fixing one cross-constraint disturbs another and a genuine simultaneous solve is required. (The honest generator *is* the natural tool for the deferred flood attack — see below.)

**Trust rule: the current absolute-count sniff only.** We attack `sniff_pool` (`playground/sniffing.py`) exactly as it stands: a packet is trusted once its count of pairwise agreements reaches an absolute threshold, and disagreements are ignored (only a self-check *failure* marks a packet broken). We deliberately establish the vulnerability against the un-hardened rule first. A key structural observation motivates the deferred defense: every legitimate recoded packet is orthogonal to *every* other legitimate packet (orthogonality is bilinear and the generation is mutually + self-orthogonal), so a clean packet's agreement count is `~pool_size - 1`, while a forger that targeted only `threshold` packets sits at `~threshold`. The absolute-count rule cannot tell them apart, so the honest majority provides **zero** protection — a disagreement-aware ratio rule would, and quantifying that gap is deferred item 2.

**Work is measured in attacker field-operations, symmetric with defender cost.** Following ADR-0007's methodology, the primary work metric is the finite-field mul/add count consumed on the *attacker's* forging path (a `CountingField` wrapper around the solve), reported per silently-accepted packet. Number of candidate attempts and number of constraints solved are logged alongside as interpretable secondaries. This lets an exact solve (few ops) and any future search-based attacker (many ops) sit on one axis.

**Reported KPIs.** All of: **earliest strike** (minimum forwards `S` before the first injection is silently accepted — expected `~threshold`); **attacker field-ops per accepted packet** (vs. `threshold` and field size `m`); **pollution ratio** (forged:clean the receiver tolerates before the decode is wrong); **`silent_decode_rate`** (the safety-critical number, per the incremental recovery+decode sim); and an explicit **success-rate curve** obtained by striking with `S < threshold`, where acceptance is no longer near-certain. Note **one is enough**: a single independent silently-accepted packet corrupts the whole generation's decode, so the honest-majority fraction does not dilute the danger — it only widens the attacker's time window.

**Layout.** `pollute_intelligent` is filled in `binary_ext_fields/pollution.py` (takes the saved/forwarded packets, returns a forged packet). A new standalone harness `simulation/intelligent_attack_sim.py` reuses the incremental sim's building blocks (`CountingField`, the decode-gate `V`, and re-decode grading from `simulation/recovery_decode_sim.py`) and adds the relay forward-and-record + strike loop; a sweep script sweeps field size `m`, generation size, decode-gate `V` (= threshold), and strike point `S`. This keeps the 20k-line decode sim untouched and follows ADR-0007's three-layer separation (harness / KPI metrics / sweep).

**Deferred, explicitly:**
1. **Flood / self-vouching Sybil attack** — inject `b` mutually-orthogonal garbage packets built by `generate_all_tags` on wrong data; they vouch for *each other*, so `b >= threshold + 1` clears the trust gate with zero knowledge of the receiver's packets. This is the true minimum-work / zero-knowledge attack; the honest generator applies verbatim. Sweep batch size `b`.
2. **Ratio / disagreement-aware trust rule** — trust requires agreement with a large *fraction* of the pool. Forces the attacker to forge agreement with the entire pool, so its work scales with `pool_size` rather than the fixed `threshold`. The "fix" contrast to this ADR's baseline.
3. **Seen-may-miss-pool overlap model** — drop the forward-and-record invariant so the attacker's saved packets only partly overlap the current pool, yielding a smooth success curve in overlap probability.
4. **Active relay** — a relay that additionally delays or drops honest packets to widen its strike window.

## Segmented extension — keyless orthogonal vs keyed homomorphic-MAC (ticket 06, 2026-08-31)

This same attacker was carried to the segmented arms (`simulation/segmented_attack_sim.py`)
to answer the security half of the ADR-0012 comparison: what does keylessness buy versus
a keyed benchmark? The relay copies a genuine valid packet and forges exactly **one**
segment — the **coefficient segment** — giving it an independent-but-inconsistent coeff
row (the poison) while the N-1 data segments stay genuine and verify for free. Forge-work
is therefore the cost of breaking ONE segment, independent of N: **N is a recovery knob,
not a security knob.** The per-segment difficulty dial is V = tags/segment = gen_size.

Result (gen=6, data=24, 60 trials/cell, N ∈ {2,3,5}):

| arm | key setting | silent-accept | forge-work (field-muls) |
|---|---|---|---|
| orthogonal (keyless) | n/a | **1.0** (flat over N) | ~76.6, **flat over N** |
| MAC | secret (b) | **0.0** — forgery rejected | n/a (no admit at any finite op cost) |
| MAC | compromised (c) | **1.0** | 36, **flat over N** |

**The headline is the SHAPE, not a winner.** MAC security is a *cliff*: excellent while
the key is secret (silent-accept 0 — it genuinely wins forgery resistance here, stated
honestly), and zero the instant the key leaks (silent-accept 1). The keyless orthogonal
scheme is a *flat work floor*: never zero (it is always forgeable by solving the
per-segment orthogonality system), but the cost is a fixed W that never depends on a
secret and never collapses. **The keyless claim is key-freedom + compromise-resilience —
there is no key to distribute and no key whose loss collapses security — NOT that the
orthogonal tag is harder to forge.** Both arms' forge-work is flat in N, confirming
segmentation does not buy forgery resistance (the attacker just targets one segment).

## Addendum 2026-09-23 (ticket 17): segment splice + partial knowledge

Merged to main 2026-09-29 (branch `feat/security-sim`). Code: `simulation/{attack_harness,splice_attack_sim,knowledge_attack_sim}.py`
plus tests. Keys are per generation (user decision), so replay and blast-radius attacks are out
of scope. Both attacks run through the PRODUCTION admit path (`SegmentedScheme.admit` /
`SegmentedMacScheme.admit`), not ticket 06's absolute-count stand-in.

**1. Segment splice: the "MAC key secret → silent 0" result above holds only against ticket
06's naive forger.**
- Both segmented arms verify each segment independently, and both tags are linear per
  segment. So a packet built from segments of DIFFERENT honest combinations passes every
  check: coeff segment of V + data segments of O, one data segment scaled by α, or all data
  segments zeroed.
- Its coefficients no longer match its data, so the decode is wrong.
- Measured: 50/50 silent decodes in both arms for N ∈ {2,3,5} and m ∈ {2,4,8}. Zero field
  muls, and no key or source needed.
- The N=1 whole-packet tag rejects all of them (both arms).
- So segmentation removes the coefficient↔data binding in BOTH schemes. Candidate fix: bind
  the coefficients into every segment's tagged input.
- Fix vs report-as-limitation: **open, user decision.**

Keyless bonus: in char 2, <v,v> = (Σv)², so the self-check is orthogonality to the all-ones
vector. β·1 is therefore a zero-knowledge valid segment whenever the segment length is even.

**2. Partial knowledge (splice-free forger, one packet, c' forced innovative).**
- Axis u = constraints the attacker cannot compute:
  - keyless: r observed packets, u = g−1−r;
  - keyed: k leaked keys, u = g−k.
- The strict oracle gives q^-u in BOTH arms (4000 paired seeds/cell, GF(2^2) and GF(2^4)):
  **at equal knowledge the two tags are equally strong.**
- The production receiver adds two effects:
  - **Keyed repair amplification.** The coeff-segment repair bit-flips over payload + tags
    and "fixes" a guessed tag that is one bit off. Admit rate ≈ q^-u(1+u·m) + payload term.
    Examples: 0.76 vs 0.25 at GF(2^2), u=1; 0.31 vs 0.065 at GF(2^4), u=1. With hd=0 it
    equals the oracle.
  - **Keyless greedy-peel tie-break.** A LATE forger that disagrees with exactly one honest
    packet survives, because the peel removes the lower index. Admit ≈ q^-u(1+u(1−1/q)²),
    e.g. 0.12 vs 0.068 at GF(2^4), u=1.
- Headline for the thesis:
  - equal tag strength per unknown constraint;
  - the keyed production path is weaker at equal u (its repair);
  - the keyless weakness is the price of knowledge: observation is free on-path, while a
    keyed attacker needs a key compromise;
  - the splice attack breaks both segmented arms until they are bound.

**Caveat (2026-09-29):** all numbers above were measured before the unit-tag-column guard (`has_unit_tag_column`, 2026-09-25) entered the tagging code. The guard rejects a small fraction of tag generations (~gen_size/q for a coefficient segment), so re-check the q^-u and amplification figures before quoting them in the thesis. The splice result does not depend on it.
