# RLNC Orthogonal-Tag Recovery

Random Linear Network Coding (RLNC) over GF(2^m), where every packet in a generation carries an appended orthogonal tag so a receiver can detect and recover bit-level corruption without a separate MAC. Recovery exists to avoid resending broken packets — which makes a silently wrong recovery worse than no recovery at all, since it feeds bad data downstream undetected instead of triggering a resend.

## Language

### Tagging & recovery

**Generation**:
A batch of packets, each shaped as `[coefficients | data] [tags]`, that are coded together and must be pairwise- and self-orthogonal (inner product 0) when uncorrupted.
_Avoid_: batch, block

**Self-tag**:
The tag column making a packet's inner product with itself equal 0. Because field addition is XOR (char-2), squaring is additive and bijective on GF(2^m) — so for any single unknown byte in a packet, some value *always* exists that zeroes the self-tag equation. Self-tag alone therefore has no discriminating power for verifying a recovered byte: it "passes" at every column you try, right or wrong.
_Avoid_: self-orthogonality (use for the property; "self-tag" for the mechanism)

**Cross-tag**:
The tag column between two specific packets making their inner product equal 0. Constructed pairwise by the `OrthogonalTagGenerator` (OTC) for every pair in the generation.

**Zero-tag failure**:
The degenerate case where a packet's self-tag comes out `0` — i.e. the packet's bytes already XOR to zero. It is not just a useless tag: later packets build their cross-tags against this one via `t1 * t2 = d` with `t1 =` this self-tag, which is unsolvable when `t1 = 0`, so the whole generation loses orthogonality. In factorization terms it is a zero pivot in the Cholesky-style `T·Tᵀ = G` (tag matrix × its transpose = payload Gram matrix); provably unavoidable by reordering when `G` is *alternating*. Probability `1/q` per packet. See [ADR-0010](docs/adr/0010-zero-self-tag-resample-appended-block.md) and `docs/zero_tag_probability.md`.
_Avoid_: zero tag error (use "zero-tag failure" for the event)

**Salt byte**:
One extra per-packet symbol appended to a packet's tagged input, chosen (resampled as a vector) so every self-tag is nonzero, used when the real payload is fixed and cannot be regenerated. It enters the Gram matrix like any payload symbol, so cross-orthogonality is enforced normally. Adds the minimal ("rank+1") degree of freedom, but is *not* a hard guarantee — effectively a guarantee in GF(2⁸), degrading in small fields (multiplier-zero case). Fix for a [[zero-tag failure]] with fixed data. See [ADR-0010](docs/adr/0010-zero-self-tag-resample-appended-block.md). [[Segmented orthogonal tagging]] applies one salt byte per segment independently, inheriting ADR-0010's give-up fallback (`ok=False`) unchanged per segment rather than special-casing it away.

**Localization** (ACR):
The linear-algebra step (RREF + coefficient replay, in `arc_pl.py`) that produces a *set* of candidate corrupted byte columns for the generation. It does not cleanly attribute a single column to a single row — recovery must still search over which candidate column is the real one for a given broken packet.
_Avoid_: detection

**ACR** (algebraic consistency check):
The correct name of the localization step above. Earlier docs and all code call it "ARC" — that was a naming slip (renamed in the docs 2026-09-29). Code identifiers keep the old spelling for now and are NOT to be renamed: `arc_pl.py`, `recover_arc_only`, `recover_arc_only_mac`, configs `arc_only_a` / `arc_only_b` / `arc_only_b_info`, etc. In prose always write ACR / "ACR-only".
_Avoid_: ARC

**Recovery**:
The step that, given ACR's candidate columns, determines the byte value that makes a broken packet valid again (`new_recovery.py`). Must still search over column *identity*, since localization doesn't hand it a clean (row, column) pair — but per [ADR-0002](docs/adr/0002-recovery-solves-linear-system-instead-of-bitflip-search.md), the byte *value* for a fixed candidate column set is solved directly via a linear system over the other trusted packets' cross-tags, not brute-force bit-flipping.

**Combined recovery**:
A planned phase-2 technique (`recover_packet_combined`, from a paper related to the thesis) that XORs two broken packets together to shrink the error search space. Deferred until single-packet recovery (sniffing → ACR → linear solve) works; not dropped. Same XOR-the-pair idea as the benchmark's [[combined-recovery-benchmark]] (Fathi & Pahlevani); see that entry under Comparison baselines.

**Sniffing**:
The pre-filtering pass over the accumulated packet pool that runs before ACR/localization, sorting packets into broken (failed self-check) and trusted (high cross-check success count) before any of them are used as an ACR decoding basis or a recovery equation row. See [ADR-0004](docs/adr/0004-sniffing-trust-model.md).

**Acceptance oracle**:
The check a recovery candidate must pass to be accepted as correct. [ADR-0001](docs/adr/0001-recovery-acceptance-oracle.md): must be full-generation orthogonality (self + every cross-tag), not self-tag alone.

### Segmented orthogonal tagging

**Segment**:
One of a packet's independently-tagged byte ranges: a fixed **coeff-segment** (the coefficient block) plus `N-1` equal-length **data-segments** the data block is split into, for a total of `N` segments per packet (`N=1` collapses to today's whole-packet, unsegmented scheme — the baseline anchor for the planned sweep). Each segment is self- and cross-orthogonal only against same-type segments across the generation; coeff-segments and data-segments are never checked against each other.
_Avoid_: the paper's own "segment" (`E:/teach_me/hmac_papers`) — theirs is the *whole* coded packet split into `s` *equal*-length pieces; ours fixes the coefficient block apart and only subdivides the data block.

**Segmented orthogonal tagging**:
The scheme built from [[Segment]]s: `N` independent self/cross-tag pools instead of one whole-packet pool. Built to let [[Segment pairing]] mimic Fathi & Pahlevani's Combined Recovery on this project's own keyless scheme, and to close a real gap in ACR — `localize_errors` (`playground/arc_pl.py`) trusts a broken packet's coefficients unconditionally to re-derive its data, with no way today to detect or repair corruption inside the coefficient block itself. An `N`-segment sweep (starting at `N=2`) is planned to measure how KPIs move as the data block is subdivided further.

**Segment pairing**:
This project's own use of the [[Combined Recovery (benchmark)]] paper's XOR-pairing trick, applied to [[Segmented orthogonal tagging]] rather than to the benchmark's homomorphic MAC. Pairs two *different* broken packets' same-type segment (never a packet's own coeff-segment with its own data-segment — different lengths, and never mutually orthogonal by design), XORs the segment and its tag, corrects the combined segment once, then cross-reconstructs each original. Only fires when a same-type broken partner is available; an unpaired broken packet always falls back to the existing single-packet linear solve ([ADR-0002](docs/adr/0002-recovery-solves-linear-system-instead-of-bitflip-search.md)), identically regardless of which recovery option below is active — isolates the pairing-availability effect from the search-method effect being measured. Partner choice with 3+ same-type broken packets is FIFO.
_Avoid_: conflating with [[Combined Recovery (benchmark)]]'s own deferred pairing optimization — that note is about the benchmark's keyed homomorphic-MAC arm specifically; this is a separate implementation on the keyless scheme.

**Uniform HD recovery** (Option 1):
One of two [[Segment pairing]] recovery strategies under comparison. Bounds the brute-force correction step only by Hamming distance (reusing the CRC baseline's HD-search technique, [ADR-0011](docs/adr/0011-crc-single-packet-hd-search-recovery.md)) and applies it identically to every segment type — no ACR, no special-casing of the coeff-segment.

**Coefficient-first recovery** (Option 2):
The other strategy: repair the coeff-segment first via the same HD-bounded bit-flip search as [[Uniform HD recovery]], then feed the now-corrected coefficients into ACR exactly as it already works to narrow candidate columns for the data-segment(s) before pairing/solving. Hypothesis under test: ACR-informed narrowing recovers faster, because it makes ACR's existing coefficients-are-trustworthy assumption actually true instead of silently violated.

**Segment-scoped trust**:
An extension of [[Sniffing]] ([ADR-0004](docs/adr/0004-sniffing-trust-model.md)) needed by [[Segmented orthogonal tagging]]: a packet's trust state is now per-segment (e.g. coeff-trusted but data-broken), not one binary flag for the whole packet. Not derived from the Fathi & Pahlevani paper — its ACR operates at the column level (`IC`) with no persistent packet-level trust concept; this is new territory for this project.

### Isolated recovery comparison

**Isolated recovery comparison**:
The keyless↔keyed comparison run so that the *only* surviving difference is the [[acceptance oracle]]: both arms use the identical algorithm (ACR-localize → bit-flip to Hamming distance, keyless bit-flip-only here), trust is *injected* rather than sniffed, and both are scored on identical ground truth. Measures the repair sub-mechanism only, not end-to-end recovery. See [ADR-0013](docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).
_Avoid_: treating its results as end-to-end scheme behaviour — detection/[[sniffing]] is idealized out by construction.

**Helper packet**:
A known-good (ground-truth-clean) packet *given* to recovery in the [[isolated recovery comparison]] — never corrupted. The fixed set of `G = gen_size` helpers is the ACR decoding basis (both arms) and the keyless arm's acceptance witnesses. Distinct from a **target packet**, the corrupted packet recovery is scored on.
_Avoid_: trusted packet (that names a [[sniffing]] outcome; helpers are injected, not classified).

**Recovery-acceptance width** (`W`):
The number of independent checks a repaired candidate must pass to be accepted, matched across arms so silent-decode probability is comparable: keyless = orthogonality to `W` [[helper packet]]s (on top of the free self-check), keyed = `W` of the carried MAC tags. Nominal collision `≈ q⁻ᵂ` (exact for keyed's i.i.d. keys; a floor for keyless, whose helper checks can be dependent). The keyless self-check is uncounted free structure. Recovery-acceptance only — separate from [[sniffing]]'s `verify_count`. See [ADR-0013](docs/adr/0013-isolated-recovery-comparison-injected-trust-matched-width.md).

**ACR-only recovery**:
A recovery config in the [[isolated recovery comparison]] that drops [[Coefficient-first recovery]]'s coeff-repair stage: ACR-localize + bit-flip the data segments directly, coefficients assumed clean. Run two ways — data-only BER (coeffs never corrupted) and whole-packet BER (coeff-broken targets drop symmetrically in both arms) — to isolate the coeff-repair stage as a source of arm-to-arm difference.

**Paired ground truth**:
The common-random-numbers design of the [[isolated recovery comparison]]: a shared seed fixes the same payload, coefficients, and helper/target split for both arms, and the error pattern on the information columns `[coeff | payload]` is applied *identically*. The tag/redundancy region is only seed-matched (layouts differ — salt + orthogonal tags vs MAC tags), not byte-identical. Enables a per-target head-to-head (win/loss/tie) on identical corruption.

### Comparison baselines

**Homomorphic MAC**:
The keyed comparison baseline (Agrawal–Boneh, ACNS 2009), and what *"HMAC"* means in every partial-packet-recovery paper in `E:/teach_me/hmac_papers` — **Homomorphic** MAC, **not** Hash-based MAC. A tag is a field inner product of the code packet with a secret key vector over GF(2^m): `tᵢ = ⊕ⱼ keyᵢⱼ · packetⱼ`; `m` keys give a tag *vector* (paper sizes: "HMAC-8/-16" = tag *bits*). Because it is linear over the field it is **homomorphic — it survives RLNC recoding**, unlike a hash-based MAC. This overturns the original ADR-0009 premise that "HMAC does not survive recoding" (true only for hash-based HMAC-SHA-256).
_Avoid_: HMAC unqualified (acronym clashes with Hash-based MAC — always write "homomorphic MAC" in the thesis); HMAC-SHA-256 (a different, non-homomorphic primitive we are **not** using as the baseline).

**Keyless HMAC**:
The supervisor's name for this project's own [[orthogonal tag]] / self-tag scheme — "keyless" because it needs no shared secret, "HMAC" because it is functionally a *homomorphic* integrity check. So the headline comparison is **keyed homomorphic MAC vs keyless homomorphic tag**: same family, the only axis of difference is the key. See the `OrthogonalScheme` glossary above (Self-tag / Acceptance oracle).
_Avoid_: treating "keyless HMAC" as a distinct fourth scheme — it *is* the orthogonal tag.

**CRC baseline**:
The keyless, **non-homomorphic** checksum baseline (dies under recoding). Its recovery arm is a **single-packet Hamming-distance search** ([ADR-0011](docs/adr/0011-crc-single-packet-hd-search-recovery.md)): corrupt one opaque data packet at HD 1–3, then brute-force bit-combination candidates (up to HD 3) checked against a bare CRC, stop at first match. Real pure-Python CRCs, widths **8/16/32** (CRC-16 = the PRAC/S-PRAC/QPPR anchor; 8 and 32 bracket the collision cliff). Not the earlier (retired) Fly-PRAC segmented/group scheme.
_Avoid_: segmented CRC, ICRC/OCRC, dependent group (retired vocabulary — never used).

**False-repair**:
The CRC/HMAC analogue of a [[zero-tag failure]]'s silent-decode: a repair candidate whose checksum *passes* but which is *not* the original packet — a wrong fix accepted silently, from a checksum collision. The headline hazard the CRC arm measures, and the "silent pollutions" column of the scheme comparison. Its rate ≈ (candidates tried) · `2⁻ʷ` for a `w`-bit checksum; the whole homomorphic-MAC benchmark exists to drive it to ~0. Distinct from **no-repair** (nothing passed the search) and **correct-repair**.

**Combined Recovery** (benchmark):
The homomorphic-MAC partial-packet-recovery scheme of Fathi & Pahlevani 2025 (`E:/teach_me/hmac_papers/Enhancing_...pdf`), the HMAC comparison **benchmark**. Replaces CRC with the Agrawal–Boneh homomorphic MAC to kill checksum collisions, and pairs two broken segments (XOR data *and* tags, `Tc=T1⊕T2`) to correct both in one search. This project implements the *homomorphic-MAC-as-checker* half only (widths HMAC-8/16, shared GF(2⁸) inner product = keyed [[orthogonal tag]]); the segment-pairing optimization (its Algorithm 1) is **deferred** — it changes cost, not outcome. Supersedes the older [[combined recovery]] phase-2 glossary note.
_Avoid_: reproducing the pairing trick as the benchmark (deferred).

### Throughput simulation

**Tick**:
The unit of simulated time in the throughput/KPI network simulator. One tick lets every link carry exactly one packet, independent of that packet's byte size. Ticks are logical, not wall-clock, so a Monte Carlo sweep runs in seconds of real time no matter how many trials it needs. See [ADR-0005](docs/adr/0005-tick-based-simulation-and-goodput-metric.md).
_Avoid_: time step, round, real time

**Goodput**:
The primary throughput KPI: payload bytes the Sink has recovered, divided by ticks elapsed until it reaches full rank. Deliberately excludes coefficient and tag bytes, so it reflects the cost the tagging scheme itself imposes. See [ADR-0005](docs/adr/0005-tick-based-simulation-and-goodput-metric.md).
_Avoid_: throughput (ambiguous between goodput and raw packet rate — say which one is meant)

**Completion time (per packet)**:
The scheme-comparison latency metric, reported **two ways**: logical **[[tick]]s** to full rank / gen_size (fair, implementation-independent, the headline) *and* **wall-clock** seconds (now fair too, because all three arms share a pure-Python substrate — see the shared-substrate note in [ADR-0011](docs/adr/0011-crc-single-packet-hd-search-recovery.md)). One of the comparison's four metrics, alongside recovery rate, silent pollutions ([[false-repair]]), and overhead (bytes of extra retransmitted packets).

**Source / Relay / Sink**:
The three simulated node roles in the throughput network. Source originates and tags a generation's packets. Relay buffers incoming packets and recodes new linear combinations to forward, without ever holding a fully decodable copy of the generation itself. Sink accumulates packets until full rank, then decodes. See [ADR-0006](docs/adr/0006-relay-topology-and-forwarding-policy.md).
