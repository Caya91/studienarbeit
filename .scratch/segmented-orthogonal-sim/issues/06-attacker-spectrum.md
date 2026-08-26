# 06 — Attacker comparison: keyless orthogonal vs keyed MAC

**In one line:** the security half of the thesis. We already compare the two schemes
on *recovery* (tickets 03/04). Here we compare them on *how well they resist a
deliberate attacker* who tries to sneak a forged packet into the decode.

**Decisions made 2026-08-26 (this session) — build to these:**

### 1. Who is the attacker? (two settings, run both)
A malicious relay that forwards honest packets, records them, then at some point
injects forged ones. It knows the scheme fully (white-box / Kerckhoffs). The one
thing that changes between the two settings is **whether it holds the MAC's secret
key**:

- **Setting b — key stays secret:** the attacker does NOT have the MAC key.
  - Against the **MAC**: it cannot make a valid tag → forgeries are rejected →
    silent-accept ≈ 0. MAC wins this setting. Say so plainly.
  - Against the **orthogonal** scheme: no key exists anyway, so it forges by
    *solving the orthogonality equations* — possible, but it costs measurable
    work W (field operations).
- **Setting c — key is compromised** (a node got captured / the key leaked):
  - Against the **MAC**: it now makes valid tags for free → silent-accept ≈ 1.
    MAC gives zero protection.
  - Against the **orthogonal** scheme: unchanged — still costs the same work W
    (there was never a key to leak).

**The headline result is the SHAPE, not a winner:** MAC security is a *cliff* — great
while the key is secret, gone the moment it isn't. Orthogonal is a *flat work floor*
— never zero, never depends on a secret. Thesis point: *"keyless means there is no
key to distribute and no key whose loss collapses your security,"* NOT "orthogonal is
harder to forge." (In setting b the MAC is genuinely harder to forge — report that
honestly.)

Optional extension (the "spectrum" in the old title): instead of just secret/leaked,
sweep *how many of a packet's N segment-keys the attacker holds* (0 → all N). This
draws the cliff as a curve. Nice-to-have; the two end-points (b and c) are the
required part.

### 2. What we measure (the two schemes don't share one number)
- **Silently-accepted pollution rate** = fraction of trials where a forged packet was
  accepted AND the decode came out wrong (see #5). This is the common outcome axis.
- **Attacker work** = field operations / number of equation-constraints the attacker
  had to solve to land one accepted forgery. Only meaningful for the orthogonal
  scheme (the MAC attacker either can't forge at all, or forges for free) — so report
  it *beside* the rate, not merged into it. This is the "work-based security vs
  secret-based security" framing from the HMAC-papers notes.

### 3. Does N (segments per packet) make forging harder? NO — and show why
**Correction (2026-08-26):** N is a recovery knob, **not** a security knob. A packet is
admitted only if every segment trusts it, but the attacker does **not** have to forge
all N segments. It takes an already-**valid** packet (which passes every segment) and
forges **just one** segment — the poison — leaving the other N−1 genuine and untouched
so they still pass for free. The poisoned segment's payload is part of the decoded data,
so that one forged segment corrupts the decode while the packet is still admitted.

So forge-work = the cost of breaking **one** segment, independent of N:
- Orthogonal: solve ONE segment's orthogonality system.
- MAC (no key): collide ONE segment's tag ≈ q^(−V).

The per-segment parameter that actually sets forge difficulty is **V = tags per segment
(= gen_size)**, not N. Still sweep N in the experiment, but to **demonstrate the curve is
flat** — the honest message is "segmentation does not buy forgery resistance; if
anything the attacker just targets the easiest segment," not "more segments = safer."
(N = number of segments per packet, e.g. {2,3,5}; V is the per-segment tag count.)

### 4. How to build it: one small standalone sim (chosen for simplicity)
Write a new file `simulation/segmented_attack_sim.py`. Do NOT try to make the existing
generic recovery driver do attacks — the attack loops differ too much between schemes
to share cleanly. This file contains:
- `forge_segmented_orthogonal(...)` — solve the per-segment orthogonality system to
  build an accepted forgery; count the attacker's field-ops (reuse the existing
  `pollute_intelligent` / `forge_orthogonal` machinery, extended per-segment).
- `forge_segmented_mac(..., key=None)` — `key=None` (setting b) → bogus tags that get
  rejected; `key=<the real keyset>` (setting c) → valid tags that pass.
- one attack loop (mirror `run_hmac_attack_trial`) that forwards honest packets,
  injects a forgery at a strike point, and grades the decode.
- output: a side-by-side table/figure of the two schemes × the two key settings ×
  the metrics in #2, swept over N (and optionally strike point).

Keep everything for the attack in this one file so it reads top-to-bottom.

### 5. What counts as a successful attack
Same definition as ADR-0008: **the forged packet is accepted AND the final decode is
wrong** (graded against ground truth). Not "the packet merely passed the check."

**Blocked by:** 04 (need the matched homomorphic-MAC arm to attack — done/available now).

**Status:** ready-for-agent

**Done when:**
- [ ] Both key settings (secret / compromised) run against the segmented MAC; the
      orthogonal scheme is attacked white-box in both.
- [ ] Per scheme × setting: silently-accepted pollution rate + attacker forge-work
      (field-ops to one accepted forgery), reported side by side.
- [ ] The forge targets a SINGLE segment of a copied valid packet (not all N).
- [ ] Forge-work and silent-accept shown vs N, demonstrating they are ~flat (N is not
      a security knob); the real per-segment dial is V (tags/segment = gen_size).
- [ ] A figure/table that makes the "MAC secrecy-cliff vs orthogonal flat work floor"
      shape obvious.
- [ ] The secret-key setting honestly shows the MAC winning forgery resistance; the
      orthogonal argument is stated as key-freedom + compromise-resilience.
- [ ] Conclusion recorded (ADR update) for the keyless-alternative claim.
