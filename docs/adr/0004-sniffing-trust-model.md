# Sniffing distinguishes broken from trusted packets by self-check failure and cross-check success count

Before running ACR/RREF localization, the recovery pipeline first "sniffs" the accumulated packet pool to sort packets into broken vs. trusted, so ACR's decoding basis (see the open problem in the prior discussion of `arc()`) isn't built on a corrupted packet without warning.

Two asymmetric signals, both already implied by the field math in [ADR-0001](0001-recovery-acceptance-oracle.md):

- **Self-check failure is conclusive.** A correctly-tagged packet always passes its own self-orthogonality check by construction, so failing it is sound proof of corruption (one-directional — passing it is not proof of the reverse).
- **Trust in a self-check-passing packet is graded, not binary.** Each additional other packet it checks out pairwise-orthogonal against cuts the probability that the agreement is coincidental by roughly `1/field_size` (same reasoning as ADR-0001's cross-tag argument). Counting, for every packet, how many others it's pairwise-orthogonal to is a single pairwise pass over the accumulated pool — no iterative bootstrapping needed: broken packets land with a success count near zero (generically non-orthogonal to almost everyone), trusted packets land with a success count near the size of the clean subset.

This requires the accumulated subset used for sniffing to be large enough that this count is statistically meaningful — too small a pool and a broken packet's few coincidental passes aren't clearly distinguishable from a clean packet's real ones.

**Thresholds** (configurable, not hardcoded — the thesis's simulation studies need to sweep these): a packet is trusted after passing cross-checks against **4** other packets (minimum, default), and sniffing only runs once the accumulated pool reaches a minimum generation size of **10** (default). Both are exposed as parameters specifically so different configurations can be benchmarked against each other.
