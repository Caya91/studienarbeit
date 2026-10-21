Status: PROPOSED (2026-10-16, agent) — implementation on branch `feat/e2e-throughput-twohop` (uncommitted).

# End-to-end throughput vs conventional ARQ, and two-hop recoding

Two follow-ups to ADR-0014 (single hop: CRC-32 + ACR recovers exactly what keyless recovers,
detects as well, is cheaper). Thesis requirements 4+5 need (1) end-to-end transmissions /
goodput against a conventional-ARQ baseline and (2) the multi-hop case, where a CRC does not
survive recoding.

## Shared settings (match ADR-0014)

gen_size 4, GF(2^8), 50 B data segments: df 100 / 300 / 1000 B -> N = 3 / 7 / 21 segments
(incl. the coeff segment). BER 1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2. Max HD 2, candidate
budget 20000, repair span payload, keyless cross-check witnesses verify_count 4.
**Channel errors hit data-payload bytes only** (coefficients, keyless salt/tags, MAC tags and
CRCs are never flipped) — the project's ACR-only rule (acr_only never repairs coefficients).
Limitation: a real channel also hits headers and tags; then every arm loses more packets.
Goodput counts the **real wire bytes**: keyless carries 1 salt byte per segment on top of its
4 tag bytes (ADR-0014 ignored the salt only for the tag-parity argument), keyed and CRC-32
carry 4 tag / CRC bytes per segment. Wire bytes per packet: df100 119 (keyless) / 116
(keyed, CRC); df300 339 / 332; df1000 1109 / 1088.

## Task 1 — end-to-end transmissions + goodput vs BER, conventional-ARQ baseline

1. **Driver**: `scripts/pareto_sweep.py`, extended additively (defaults unchanged). It already
   is the end-to-end send-until-decodable driver of the scaling study (run_recovery_trial,
   process pool, per-trial resume, per-cell budget, bit-efficiency from the real wire length),
   so the new numbers are directly comparable with the R2/R3 "prod" runs. New `--arm` values
   `crc_arq`, `crc_acr`; raw CSV schema v4 adds `n_corrupted_rx`, `repaired_used`, `wrong_used`,
   `n_accepted_final` (from an optional `trace` dict of run_recovery_trial; default path untouched).
2. **Arms**:
   - keyless — SegmentedScheme `acr_only` (production: sniffed trust, ACR-localized bit-flip repair).
   - keyed — SegmentedMacScheme `acr_only` (same repair, MAC oracle).
   - **CRC-32 ARQ (drop + resend)** — new `SegmentedCrcScheme(repair="none")`: zlib CRC-32 per
     segment (ADR-0014 layout), the source CRCs every coded packet; any failing segment drops the
     whole packet, the receiver keeps pulling coded packets until decodable. Each arrival is
     verified once (verdict cached), no repair.
   - CRC-32 + ACR repair (S-PRAC-like) — `SegmentedCrcScheme(repair="acr")`: production
     ACR-only repair with the per-segment CRC as oracle (new `recover_acr_only_crc`: sniffed
     CRC trust per segment, same pairing / combined search / IC halves / budget as keyless).
3. **Run**: cap 64 packets per generation (16 x gen_size, all arms), min_pool_size 4,
   200 trials per cell; per-cell budget 1800 s of summed trial wall time — only the
   decodability-floor cells (all trials time out) hit it and get fewer trials (reported).
4. **Metrics** per generation: transmissions = packets received until decodable (= ticks on
   one link), retransmissions = transmissions - gen_size, goodput = info bytes delivered / wire
   bytes sent (failed trials count their wire bytes, no info), goodput per tick = info bytes /
   transmissions (single link, one packet per tick, ADR-0005), silent wrong decodes, timeouts,
   repair activity (`repaired_used` = wire-corrupted packets inside the final decode basis;
   pairs/unpaired counters), wall-clock only as a within-run ratio (machine shared by 3 agents).
5. **Analytic ARQ reference** (exact for this channel): a packet survives with
   p = (1 - BER)^(8 df); clean packets are uniform coefficient vectors, so E[clean needed] =
   sum_{i<g} 1/(1 - q^(i-g)) = 4.0039 (g = 4, q = 256) and E[transmissions] = 4.0039 / p
   (Wald). Drawn beside the simulated ARQ (validates it where the cap does not bind, extends it
   past the cap).

## Task 2 — two-hop recoding (why keyless / keyed exist)

6. **Module**: new `simulation/two_hop_sim.py` (not network_sim.py: that one is clean-channel,
   S -> {R1, R2} -> D, untagged; a focused module keeps its default path untouched). Reuses
   `RELAY_BUFFER_THRESHOLD` and the tick model (ADR-0005/0006).
7. **Topology / timing**: Source -> Relay -> Sink. One packet per link per tick; the source sends
   every tick until the sink decodes; the relay forwards a fresh random combination of its whole
   usable buffer every tick once it holds >= 3 usable packets (ADR-0006, buffer uncapped). Cap
   40 ticks (10 x gen; lowered from 64 after the smoke: a stalled sink re-runs production ACR on every
   polluted packet every round, ~100-190 s per df1000 trial at 64); no decode by then = timeout (stall).
   Sink admit with `AdmitConfig.final_check=False` (new opt-in knob, default True = unchanged): skips the
   acr_only post-repair whole-pool check whose result admit never reads (O(M^2) keyless) -- identical
   admitted packets (tested). Task 1 keeps the default (it was already running; ops include that check).
8. **Channel**: payload-only errors on both hops, same BER on both (asymmetric supported).
9. **Schemes x relay policies**:
   - CRC-32 `verify`: relay checks every segment's CRC on arrival, drops failures, buffers the
     stripped [coeff | data], recodes clean packets only, recomputes the CRCs (trusted relay).
   - CRC-32 `blind`: relay strips CRCs unchecked, recodes everything, recomputes CRCs -> a hop-1
     error gets a fresh valid CRC.
   - keyless `verify`: relay runs the production trust classification (self-check + cross-check
     against up to 4 core witnesses, `classify_segment_trust`) on its whole buffer every tick
     and recodes only packets trusted in every segment; never re-tags (tags are linear).
   - keyless `blind`: relay recodes everything; corrupted inputs propagate (scaled) into every
     later combination; the sink still detects them end to end.
   - keyed `blind` (no key at the relay) / `verify` (relay holds the key, MAC check on arrival).
10. **Sink**: the same per-scheme production admit as Task 1's repair arms (keyless / keyed
    `acr_only`, CRC = `crc_acr`), so all sinks have the same repair capability; only the tag
    and the relay policy differ.
11. **Metrics**: silent wrong decodes at the sink (headline), decode / timeout (stall), hop-1 and
    hop-2 packets until the sink decodes, hop-1 corrupted arrivals that entered the relay's
    recoding set, polluted relay emissions, relay work (CRC bytes; field muls of the check; field
    muls of recoding, common to all schemes), sink repaired_used.
12. **Grid**: df 100 / 300 / 1000, the 7 BERs, 200 paired trials per (scheme, policy, df, BER); per-cell
    budget 400 s of summed trial wall (only blind keyless/keyed stall cells hit it).

Expected (sanity): CRC verify fine for pure noise (2^-32 miss per hop) but needs a trusted,
re-tagging relay that discards partial packets; CRC blind silently corrupts; keyless blind
detects end to end (~0 silent) but stalls once a corrupted packet sits in the relay buffer;
keyless verify ~ fine.

## Results (2026-10-16)

Runs: `logs/e2e_throughput/runs/<arm>/` (scripts/e2e_throughput_runs.sh, 3 workers, ~1 h 50 min incl. one
resume after a session cut) and `logs/two_hop_recoding/runs/main/` (scripts/two_hop_runs.sh, 1 worker, 4 h 14 min).
Plots + tables: `logs/e2e_throughput/plots/` (transmissions_vs_ber, goodput_vs_ber, repair_activity,
e2e_summary.csv), `logs/two_hop_recoding/plots/` (silent_stall_vs_ber, packets_per_hop_vs_ber,
relay_pollution_vs_ber, two_hop_summary.csv). Same-run wall-clock: `logs/e2e_throughput/wallclock/`.

**Task 1 (single hop, 200 generations/cell; budget-capped floor cells: df1000 3e-3 keyless 18 / keyed 31 /
crc_acr 32, df1000 1e-2 keyless 102).** Transmissions per decoded generation (keyless / keyed / CRC+ACR /
CRC-32 ARQ; ARQ exact expectation in brackets):
- df100: 1e-4 4.33 / 4.31 / 4.29 / 4.39 (4.34); 1e-3 6.85 / 6.86 / 6.82 / 9.07 (8.91); 3e-3 16.1 / 17.1 / 16.4 /
  38.6 with 78.5 % decoded within 64 (44.3).
- df300: 1e-4 4.71 / 4.65 / 4.68 / 5.11 (5.09); 1e-3 8.40 / 8.34 / 8.57 / 39.1, 87.5 % decoded (44.2);
  3e-3 24.6 / 24.0 / 23.4 / ARQ 0 % decoded (5421).
- df1000: 1e-4 5.25 / 5.29 / 5.19 / 9.23 (8.91); 1e-3 10.2 / 10.1 / 10.3 / ARQ 0 % (11983); 3e-3 every arm ~0 %
  (HD-2 floor). ARQ simulation matches the closed form wherever the cap does not bind.
- Goodput (info / wire bytes): df1000 1e-4 keyless 0.69, keyed 0.70, CRC+ACR 0.71, ARQ 0.40; df300 1e-3 0.42 / 0.43
  / 0.42 / 0.075; at low BER keyless is ~1-3 pp below keyed / CRC (salt byte per segment).
- Repair happens: repaired packets inside the final decode basis per generation, e.g. df1000 1e-3 keyless 6.2,
  keyed 7.5, CRC+ACR 7.3; df100 3e-3 7.6 / 8.8 / 8.5. 0 silent decodes, 0 wrong admitted packets in 16 183 generations.
- CRC + ACR (S-PRAC-like) == keyless / keyed in transmissions and goodput within CI (same ACR + search; ADR-0014).
- Wall-clock, same-run interleaved bench (30 gen/cell, 1 process, ratio to keyless; keyless/keyed incl. the unused
  final pool check): CRC+ACR 0.70-0.78, keyed 0.87-1.03, ARQ 0.21-0.76 per generation (ARQ cheaper per generation
  where it still decodes, but needs 1.3-5x the packets).

**Task 2 (two hop, paired generations, cap 40 ticks; blind keyless/keyed cells budget-capped to 45-193 trials).**
- Silent wrong decodes: CRC blind 2261 / 3930 generations (e.g. df100 1e-4 44 %, df300 1e-4 81 %, df1000 1e-5 38 %,
  -> 100 % by 1e-3; drops to 0 only where nothing decodes). Every other scheme x policy: 0 silent (keyless verify,
  keyless blind, keyed verify, keyed blind, CRC verify; 4200 / 3660 / 4200 / 3854 / 4200 generations).
- Keyless / keyed blind: detected end to end but STALL whenever a corrupted hop-1 packet enters the relay buffer
  (the relay mixes its whole buffer, so every later combination is polluted with a GF-scaled, multi-bit error the
  HD-2 repair cannot fix and the sink has no ACR basis in that segment): stall rate == CRC-blind silent rate on the
  same paired generations (df100 1e-4 43 %, df1000 1e-4 98 %). Polluted mixtures do stall decoding.
- Verify policies: CRC, keyless and keyed verify give the same per-generation outcome in 99.95 % of paired trials;
  the keyless relay never mixed a corrupted packet (0 / 4200 generations; self-check + cross-check, re-evaluated
  every tick). They stall only by relay starvation at high BER (the relay drops, never repairs): df100 3e-3 68 %,
  df300 1e-3 75 %, df1000 3e-4 75 %. Hops until decode e.g. df1000 1e-4: hop 1 11.7, hop 2 5.8.
- Relay work (verify, median per packet): CRC 104 B checked per arrival + 304 B re-CRC per relayed packet (12 us);
  keyless 1252 field muls per arrival (375 us, Python incremental classification of the whole buffer), keyed 416
  muls (86 us); recoding ~1250-1380 muls per relayed packet for all schemes.
- Matches the sanity expectations. Caveats: payload-only errors; wall-clock contended (3 agents) and C (zlib) vs
  Python (keyless) -- secondary only; Task 2 cap 40 (< Task 1's 64) and reduced trials in blind stall cells.

## Follow-up (2026-10-17): three channel-error models x search depth HD (single hop)

User decisions 2026-10-17: real iid BER on three scopes -- payload only (`data_payload`), tag only (NEW
`data_tags_only`: only the data segments' redundancy bytes = keyless salt+tags / keyed MAC tags / CRC-32 bytes,
same byte set as the isolated harness's `inject_paired(model="data_tags_only")`), payload + tag (`data_segment`);
coefficients always clean. Repair span `segment` for all three (search may flip tag bytes), max HD 1..4, budget
20000 per search step; arms keyless, keyed, crc_acr, crc_arq; layout as Task 1.

Code (additive, defaults unchanged; regression vs staged baseline / pre-edit tree: 16 rows x 4 arms identical):
`integrity_schemes.ERROR_SCOPES` + `_segment_error_positions` gain `data_tags_only`; `scripts/pareto_sweep.py`
gains `--hamming-distance` (default 2) and `--no-final-check` (AdmitConfig.final_check=False; tested: identical
status / packets / admitted set / repairs, keyless + keyed, all three scopes, fewer ops) -- schema stays v4.
Tests `simulation/e2e_throughput_test.py` (+5). Run `scripts/e2e_three_models_runs.sh`, plots
`scripts/e2e_three_models_plots.py` -> `logs/e2e_throughput/three_models_hd1-4/plots_three_models/`.

Compute budget (4 workers, shared with a 6-worker sweep): smoke + estimate said ~7 h at full scope, so per the
user's shrink order: keyed DROPPED, repair arms 100 generations/cell (ARQ 200), HD 3 DROPPED (HD 1, 2, 4 run);
per-cell budget 600 s summed trial wall -> expensive cells get fewer (listed in three_models_summary.csv, `trials`):
mostly df300 / df1000 at 3e-3 (5-59 trials) and HD-1 df1000 1e-3 (18-40). Wall 4 h 15 min (16:05-20:18).
Untracked overhead found: keyless `make_source` (salt search) ~1.2 s per df1000 generation, outside trial wall.

Results (packets until decodable / decode % ; keyless HD2, HD4 | CRC+ACR HD2, HD4 | CRC-32 ARQ):
- payload only: df100 1e-3 6.8, 6.8 | 6.7, 6.7 | 9.1; 3e-3 15.7, 15.6 | 16.4, 16.4 | 38.6 (78 %).
  df300 3e-3 27.1, 21.7 | 23.8 (99 %), 21.8 | 0 %. df1000 1e-3 10.3, 10.0 | 10.2, 10.1 | 0 %;
  3e-3 0 %, 31.3 (100 %, 7 gens) | 0 %, 27.0 (97 %) | 0 %. HD 4 moves the df1000 floor from 1e-3 to 3e-3.
- tag only: every repair arm decodes 100 % at every BER/HD (one exception: keyless HD 1 df1000 1e-2 85 %);
  packets ~ the clean-channel 4.0-6.2 at 3e-3 (df1000 6.2 keyless / 6.0 CRC+ACR vs ARQ 26.2). Tag errors are
  REPAIRED (repaired_used ~ corrupted_rx, e.g. df1000 3e-3 5.4 / 5.6 keyless, 5.1 / 5.2 CRC+ACR); ARQ drops them.
  HD barely matters (tag errors per segment are mostly single-bit at these BERs).
- payload + tag: like payload-only plus a small tag share: df300 3e-3 29.7 (94 %), 22.4 | 26.8, 23.9 | 0 %;
  df1000 3e-3 HD4 keyless 35.0 (40 %, 5 gens) vs CRC+ACR 30.2 (89 %).
- HD 1 vs 2: HD 1 loses df300 3e-3 (0-4 %) and df1000 1e-3 (72-97 %); HD 4 vs 2 gains only at the floor cells.
- Silent wrong decodes: 0 in 48 248 generations (all scopes / HD / arms); 0 wrong packets admitted.
- Cost: keyless HD 4 at the floor cells is 10-60x CRC+ACR in trial wall (e.g. df1000 3e-3 payload+tag 600-900 s
  vs ~20 s per generation): CRC check in C vs Python orthogonality check per candidate -- logical ops are in the CSV.
Caveats: keyed not run (budget); HD 3 not run; same per-trial seeds across HD (pairing assumes repair draws no randomness; unverified), not across
scopes; tiny-n floor cells (5-12 gens) are indicative only.
