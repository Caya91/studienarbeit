# HMAC Partial Packet Recovery — Implementation Search

Research note. Task: locate code for the paper below, or the closest reusable building blocks.
Compiled 2026-08-07.

## Paper identification

- **Title:** Enhancing Partial Packet Recovery in RLNC Using Homomorphic Message Authentication Codes
- **Authors:** Amin Fathi, Peyman Pahlevani (Dept. CS & IT, IASBS, Zanjan, Iran)
- **Venue:** IEEE Communications Letters, Vol. 29, No. 9, pp. 2118–2122, September 2025
- **DOI:** [10.1109/LCOMM.2025.3587820](https://doi.org/10.1109/LCOMM.2025.3587820)
- Received May 2025, published 14 July 2025. No arXiv/preprint located; no artifact-availability statement in the paper.

## Scheme summary

Proposes **"Combined Recovery"**: a partial-packet-recovery method for RLNC that replaces the CRC used in PRAC/S-PRAC/QPPR with a **linear (homomorphic) authentication tag** to kill checksum-collision false positives. Sender segments each coded packet (S-PRAC style), appends one outer tag per packet + inner tags per segment. Tag = keyed linear map over GF(2^8): `t_i = XOR_j (p'_j · k_ij)` — m random keys of n symbols each produce an m-element tag vector (paper Eq. 2). Homomorphism (`T(S1 XOR S2) = T1 XOR T2`) lets the decoder correct **two erroneous segments jointly** via their XOR-combined segment (search space `256^e`), then reconstruct each by XOR — roughly halving brute-force correction work vs. per-segment. All GF(2^8), single-byte symbols. Authors state it was **implemented in Python** (Ubuntu 24.04, i7-7600U), 1000-run averages; no repo cited.

Note: despite citing Agrawal–Boneh [8], the actual construction (Eq. 2) is a simple keyed linear inner-product checksum, not the polynomial-evaluation homomorphic MAC of Agrawal–Boneh. This maps directly onto this project's own orthogonal-tag / linear-checksum work.

## Direct implementation — NOT FOUND

No public code for this specific paper. Evidence checked:

- **Author GitHub — no match.** [github.com/Amin-Fathi](https://github.com/Amin-Fathi) has 5 public repos (Persian number-to-word, goal tracker, word game, AngularJS fork, province/city selector) — none RLNC/coding related ([repo listing](https://github.com/Amin-Fathi?tab=repositories)). Peyman Pahlevani has no located public GitHub with this code ([Scholar](https://scholar.google.com/citations?user=Y0fAbOEAAAAJ), [dblp](https://dblp.org/pers/p/Pahlevani:Peyman)).
- **No artifact statement** in the IEEE Communications Letters paper (letters format rarely mandates code release).
- Web/GitHub topic searches for "Combined Recovery" + RLNC + HMAC returned only the publication records, no repo.

Conclusion: to reproduce, it must be re-implemented from the paper (algorithm fully specified — Algorithm 1 + Eqs. 1–4 give segmentation, ACR error estimation, and the pairwise correction loop).

## Closest reusable libraries & building blocks

| Name | URL | Lang / License | Maps to paper component |
|---|---|---|---|
| **galois** (PyPI) | https://pypi.org/project/galois/ | Python (NumPy) / MIT | GF(2^8) symbol arithmetic + matrix ops for the g×g encode/decode (Eqs. 1,3,4) and the linear tag (Eq. 2). Best fit since paper is Python. |
| **Steinwurf Kodo** (kodo-rlnc, kodo-python) | https://github.com/steinwurf/kodo-rlnc · docs http://docs.steinwurf.com/kodo-rlnc/master/ | C++ / Python bindings / **research-and-education license, not free** | Full RLNC encode/decode + generation handling; drop-in RLNC substrate. Finite-field via Steinwurf **Fifi**. License gate for any real deployment. |
| **libmoepgf** | https://github.com/moepinet/libmoepgf | C (SSE/AVX/NEON) / check repo LICENSE | High-performance GF(4/16/256) SIMD arithmetic. From the MOEP ecosystem tied to the Dresden/Fitzek group behind S-PRAC — natural fast backend for the byte ops. |
| **sparsenc** (yeliqseu) | https://github.com/yeliqseu/sparsenc | C / see repo | Sparse RLNC encode/decode library; reusable generation coding core. |
| **itzmeanjan/rlnc** | https://github.com/itzmeanjan/rlnc | Rust / permissive | Clean RLNC (full + recoding) reference for the coding layer. |
| **simple_nc** (fisserL) | https://github.com/fisserL/simple_nc | Python / see repo | Minimal, readable NC over binary field — good scaffold for a from-scratch Python reimplementation of Combined Recovery. |
| **DasIch/gf256**, **galois_2p8**, **jevillegasd/GF2-8** | https://github.com/DasIch/gf256 · https://github.com/djsweet/galois_2p8 · https://github.com/jevillegasd/GF2-8 | Python / Rust / C++ | Standalone GF(2^8) arithmetic alternatives if a lighter dep than `galois` is wanted. |

Mapping guidance: build encode/decode + ACR estimation on **galois** (or Kodo if a hardened RLNC engine is preferred), implement the tag as a keyed GF(2^8) inner product (Eq. 2 — trivial, no crypto lib needed), then port Algorithm 1's pairwise combine/correct/reconstruct loop directly.

## Predecessor / related-work code

The paper builds on PRAC → S-PRAC → QPPR. No public code found for any of these three either, but the author cluster is relevant:

- **PRAC** [2] Angelopoulos, Médard, Chandrakasan (IEEE TWC 2017) — foundational ACR method. No public repo located.
- **S-PRAC** [5] Irianto, Cabrera, Nguyen, Salah, Fitzek (Wireless Days 2019) — segmentation + inner CRCs, the segmentation model this paper adopts. Preprint: [arXiv:1902.10645](https://arxiv.org/abs/1902.10645). No code link in the paper; from TU Dresden 5G Lab (Fitzek) — same ecosystem as libmoepgf/MOEP.
- **QPPR** [6] Gholamian, Nazari, Pahlevani, Fitzek (IEEE Comm. Lett. 2023, [doc](https://ieeexplore.ieee.org/document/10239443/)) — direct predecessor; shares author Pahlevani. Co-author **Hosein Kangavar Nazari** (TU Dresden) publishes NC code in Python: [Reliability-of-Multicast-in-Network-Coding](https://github.com/Hoseinkangavarnazari/Reliability-of-Multicast-in-Network-Coding) and site [hoseinkangavarnazari.github.io](https://hoseinkangavarnazari.github.io/) (lists in-progress "Fly-PRAC"). Closest-to-source code by a person in this exact research line — worth watching / contacting for PPR code.
- **Homomorphic MAC** [8] Agrawal & Boneh, "Homomorphic MACs: MAC-based integrity for network coding," ACNS 2009 — cited primitive. Paper PDF: [crypto.stanford.edu/~dabo/pubs/papers/hommac.pdf](https://crypto.stanford.edu/~dabo/pubs/papers/hommac.pdf). No canonical public implementation found. (The paper's Eq. 2 does not actually use this construction — see scheme note above.)

## Sources

- Paper full text (local): `C:/Users/marti/OneDrive/studienarbeit_docs/Enhancing_Partial_Packet_Recovery_in_RLNC_Using_Homomorphic_Message_Authentication_Codes.pdf`; DOI https://doi.org/10.1109/LCOMM.2025.3587820
- https://github.com/Amin-Fathi?tab=repositories
- https://scholar.google.com/citations?user=Y0fAbOEAAAAJ · https://dblp.org/pers/p/Pahlevani:Peyman
- https://github.com/topics/rlnc
- https://github.com/steinwurf/kodo-rlnc · http://docs.steinwurf.com/kodo-rlnc/master/
- https://github.com/moepinet/libmoepgf
- https://pypi.org/project/galois/
- https://github.com/yeliqseu/sparsenc · https://github.com/itzmeanjan/rlnc · https://github.com/fisserL/simple_nc
- https://github.com/DasIch/gf256 · https://github.com/djsweet/galois_2p8 · https://github.com/jevillegasd/GF2-8
- https://arxiv.org/abs/1902.10645 (S-PRAC) · https://ieeexplore.ieee.org/document/10239443/ (QPPR)
- https://github.com/Hoseinkangavarnazari/Reliability-of-Multicast-in-Network-Coding · https://hoseinkangavarnazari.github.io/
- https://crypto.stanford.edu/~dabo/pubs/papers/hommac.pdf (Agrawal–Boneh)
