# 03 — Run full N-sweep and pick the best N / strategy

**What to build:** The actual comparison result. Run the full segmented N-sweep (N = {2, 3, 5} × {uniform_hd, coefficient_first}) against the orthogonal N=1 baseline at the shared data_fields, then read the numbers and settle which segmented variant is best. Ranking is recovery-rate-first (correct-decode), overhead as tiebreaker, with time/ops now trustworthy thanks to ticket 01. Produce a short findings note and prune the losing strategy if the result is clear-cut.

**Blocked by:** 01, 02.

**Status:** ready-for-agent

- [ ] Full sweep completed at a meaningful trial count across all N × strategy cells (using the per-cell cap from 02 so it terminates).
- [ ] The four comparison figures + summary CSV are produced and archived under `logs/`.
- [ ] A short findings note in `docs/` states the best N and strategy, ranked recovery-rate-first with overhead tiebreak, and reports the directional time/ops.
- [ ] If one recovery strategy is clearly dominated, it is called out (and a follow-up to prune it noted) rather than carried silently.
