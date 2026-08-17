# 05 — IC-refinement: port vs stay measure-only

**What to build:** Decide, from evidence, whether Combined Recovery's IC-refinement (paper Case 1/2 — the cheap single-position swap search for overlapping-error pairs) is worth porting to the segmented pool structure, or whether staying measure-only is fine. Today the sweep reports `pairs_failed` (the overlapping-error failure rate) but does not attempt the paper's refinement. Use the observed rate from ticket 03 to make the call, and port it if the rate is high enough to matter.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] The observed IC-refinement failure rate (from ticket 03) is stated with a threshold for "matters".
- [ ] A decision is recorded (port / stay measure-only), with the reason, in ADR-0012's deferred section.
- [ ] If the decision is to port: the single-position swap search is implemented for segmented pairs and the `pairs_failed` rate drops correspondingly in a re-run.
