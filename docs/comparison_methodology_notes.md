# Comparing orthogonal tagging vs CRC vs HMAC: methodology problems

Discussion note for supervisors. Context: we add CRC (keyless) and end-to-end HMAC (keyed) as baselines for the orthogonal self-tag and compare **detection/recovery outcome, transmission overhead, and computation** (ADR-0009). Outcome and overhead compare cleanly. **Computation does not** — the three schemes do not perform the same kind of operation, and the request for a wall-clock comparison runs into several confounds. This note lists the problems so we can decide the measurement together.

## What compares cleanly

- **Transmission overhead** — tag-block bytes per packet. Directly comparable: orthogonal = `gen_size·m` bits (grows with generation), CRC-32 = 32 bits, HMAC-SHA-256 = 128 bits (truncated). No methodology issue.
- **Outcome metrics** — decode-success rate, silent-decode/silent-accept rate, transmissions-to-decode (overhead in packets). Same experiment, same units, comparable.

The problem is confined to the **computation** axis.

## The computation-comparison problems

### 1. Incommensurable primitive operations
The three verifications are not the same operation, so there is no natural shared unit:
- Orthogonal verify = a GF(2^m) inner product: `2·gen_size + data_fields` **field multiplications** per self-check (`×V` for the cross-verify gate).
- CRC-32 = one **table lookup + XOR per byte** → O(L).
- HMAC-SHA-256 = `⌈(L+9)/64⌉` **SHA-256 block compressions**, ×2 for the two-pass HMAC → O(L) with a large fixed per-block constant (64 rounds).

A "field multiplication" is not a "byte XOR" is not a "compression round." Any single combined number requires an exchange rate between them that we would have to justify.

### 2. Wall-clock measures the implementation, not the algorithm
Our orthogonal tag runs as **pure-Python interpreted loops**; CRC and HMAC call **optimized C** (`zlib.crc32`, `hashlib`). The gap between interpreted Python and compiled C is easily 10–1000× and has **nothing to do with the algorithms** — it is the language. A raw wall-clock chart would show our scheme as catastrophically slow for a reason that is an artifact of the prototype, and a reviewer asking "why is your scheme 100× slower?" would be correct that the chart does not answer the real question.

### 3. Wall-clock is only fair if all three are at the same implementation level
To make wall-clock meaningful, all three must be measured at one level:
- **All pure-Python** — reimplement CRC and HMAC as Python loops. Then the comparison is fair *as Python*, but it measures Python overhead, not deployable performance.
- **All optimized** — Cython/C the field operations (the repo already lists Cython/ctypes as future work). This is real effort but is the only path to a wall-clock number that reflects the methods rather than the language.

Either way we must **pick one level and state it**; mixing levels (our current state) makes the number meaningless.

### 4. Hardware dependence, especially SHA hardware acceleration
Wall-clock is platform-specific and non-reproducible across machines. In particular, modern CPUs have **SHA-NI instructions** that accelerate HMAC-SHA-256 by ~5–10× with no equivalent speedup for our field arithmetic. So HMAC's wall-clock number swings dramatically with the exact CPU — an advantage that is real in deployment but makes cross-machine comparison and reproducibility hard. Any wall-clock figure must pin the CPU and note whether SHA-NI is active.

### 5. Fixed constants dominate at our small packet sizes — asymptotics hide them
Our packets are small (tens of bytes). HMAC has a large fixed per-block cost (a full 64-round compression) that dominates at these sizes; CRC's per-byte constant is tiny; the orthogonal cost scales with `gen_size + data_fields`. So the O(·) expressions (all roughly linear in length) hide the constants that actually decide the outcome at our scale. We must report **measured constants / per-packet counts**, not just complexity classes.

### 6. Per-packet vs system-level cost — the capabilities are asymmetric
"Computation per verification" is not the whole story because the schemes do different amounts of work per decoded generation:
- The orthogonal tag is **homomorphic**: recoding is free, no re-tag on recode, and it **repairs** in place (bit-flip search — a real cost CRC/HMAC do not pay).
- CRC/HMAC **detect and drop**, then rely on **retransmission** — extra packets, each of which costs another round of verification.

So there are two legitimate computation figures, and we should report both:
1. **Per-verification primitive cost** (the pure algorithmic cost of one check).
2. **Cumulative cost to reach a decodable basis per trial** (the fair *system* cost — this charges the orthogonal scheme for its repair search and charges CRC/HMAC for the extra transmissions they trigger).

### 7. Where the boundary of "the computation" sits
We must fix what is counted: sender-side tagging, receiver-side verification, cross-verify (orthogonal only), and repair (orthogonal only). Drawing this boundary differently changes the story, so it must be stated once and held fixed.

## Recommendation (what we implemented)

- **Primary computation metric: native operation counts + asymptotic complexity, reported side by side** — field-muls (orthogonal), byte-lookups (CRC), block-compressions (HMAC) — at **two levels**: per-verification and cumulative-per-trial. No forced single number. This is the framing that survives review.
- **Wall-clock: secondary, and only if we commit to one implementation level.** If supervisors want it, the defensible path is to level the implementations (option 3, all-Python quickest, all-optimized most representative), fix the hardware, and label it "implementation-dependent," reporting it *alongside* the op-counts rather than as the headline.

## Question for supervisors

Given problems 2–4, do we (a) keep wall-clock as a clearly-labeled secondary at a single stated implementation level and hardware, or (b) invest in leveling all three implementations (Cython field ops) so a wall-clock comparison reflects the algorithms rather than Python-vs-C? The op-count + complexity comparison is unaffected either way and stands as the primary result.
