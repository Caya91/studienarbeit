# Domain model — ubiquitous language

Shared vocabulary for the RLNC-with-orthogonal-tagging project. Use these terms consistently in code, comments, docs, and commit messages. Cross-references point to the ADR that defines the concept in depth.

## Core coding / tagging

- **Generation** — a batch of `gen_size` source packets coded together; RLNC decodes one generation at a time. A generation is **decodable** once the receiver holds `gen_size` independent accepted packets (full rank).
- **Packet** — `[coefficients | data | tags]`. Coefficients give the RLNC linear combination; tags are the orthogonality metadata.
- **Self-tag / self-check** — the tag making a packet **self-orthogonal**, `<p,p> == 0`. A correctly-tagged packet always passes; failing the self-check is *conclusive* proof of corruption. Passing it is **not** proof of correctness. Requires zero knowledge to forge (involves only the packet itself). See ADR-0001.
- **Cross-tag / agreement (vouch)** — a packet pair "agrees" when it is pairwise-orthogonal, `<p,q> == 0`. Legitimate packets are mutually orthogonal by construction, so every clean packet agrees with every other clean packet.
- **Trust / trust pool / threshold** — a self-passing packet becomes **trusted** once its count of agreements with other self-passing packets reaches `threshold` (`min_trust_count` for sniffing, the decode gate `V` for the decode basis). The **trust pool** is the set of currently-trusted packets. The current rule is **absolute-count** (ignores disagreements). See ADR-0004.
- **Sniffing** — classifying an accumulated pool into broken / trusted before recovery runs (`playground/sniffing.py`). See ADR-0004.
- **Decode gate `V`** — the cross-verification count required to admit a packet into the decode basis; `V=2` found optimal. See the recovery+decode sim.

## Attack / security (ADR-0007, ADR-0008)

- **Random pollution** — baseline attacker with no knowledge; corrupts uniformly-random bytes.
- **Intelligent pollution** — detection-evading, white-box attacker that forges packets to pass the acceptance oracle while differing from ground truth.
- **Malicious relay** — the intelligent attacker's embodiment: an on-path relay on the receiver's inbound link.
- **Forward-and-record** — the relay honestly forwards legitimate packets while keeping copies; consequently its saved set *is* the receiver's trust pool (**seen = in-pool by construction**).
- **Strike point `S`** — the trust-pool size at which the relay stops merely forwarding and begins injecting forged packets. `K` (packets the attacker can forge agreement with) `= S`.
- **Targeted forgery** — the first intelligent attack: forge *one* packet orthogonal to `threshold` saved (real) packets via a simultaneous linear solve over GF(2^m), with coefficients independent of the forwarded set so it pivots into the basis. "Befriend the locals."
- **Flood / self-vouching Sybil** *(deferred)* — inject `b` mutually-orthogonal garbage packets built by `generate_all_tags`; they vouch for *each other*, clearing the trust gate with zero knowledge. "Bring your own friends."
- **Silent-accept / poison** — a forged packet that passes the oracle, enters the decode basis, and corrupts the decode **without being flagged**. **One is enough**: a single independent silent poison corrupts the whole generation's decode.
- **`silent_decode_rate`** — the safety-critical KPI: fraction of decodes that produce a wrong message the pipeline did not flag.

## Attacker cost / result metrics (ADR-0008)

- **Attacker work** — finite-field mul/add count on the *forging* path (`CountingField`), per silently-accepted packet. Primary work metric; symmetric with defender cost.
- **Earliest strike** — minimum forwards `S` before the first injection is silently accepted (expected `~threshold`).
- **Pollution ratio** — forged:clean packets the receiver tolerates before the decode goes wrong.
- **Time window** — rounds from the strike until the generation decodes; the attacker must land a silent poison inside it. Security is fundamentally *attacker work vs. this window, for a given trust rule*.
