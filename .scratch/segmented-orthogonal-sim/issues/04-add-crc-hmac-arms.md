# 04 — Add CRC + HMAC arms to the segmented comparison axis

**What to build:** Extend the comparison beyond the orthogonal family. Put the best segmented variant (from ticket 03) on one axis against the other integrity schemes already in the project — orthogonal N=1, CRC-localized, CRC-whole, and the HMAC / Combined-Recovery benchmark — so the segmented scheme is measured against non-orthogonal algorithms, not just its own baseline. This was deliberately deferred until the best orthogonal variant was known.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] The best segmented variant appears on a shared comparison figure alongside orthogonal N=1, CRC-localized, CRC-whole, and HMAC.
- [ ] Comparison stays fair: shared single-hop generation, shared data_fields, same per-cell cap.
- [ ] The four headline metrics (recovery rate, silent pollutions, completion time, overhead bytes) are reported per scheme.
- [ ] Tag-overhead differences (segmented N·gen_size vs flat CRC/HMAC widths) are surfaced, not hidden.
