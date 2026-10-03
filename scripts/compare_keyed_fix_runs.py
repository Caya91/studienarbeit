"""Before/after the keyed pair-fallback budget fix (f63b1be): compare two isolated-recovery runs
with the same seeds. Keyless must be identical row for row; keyed outcome deltas are tabulated.

    python scripts/compare_keyed_fix_runs.py <old raw_trials.csv | dir> <new ...> [--out summary.csv]
"""
import argparse
import pathlib

import pandas as pd

KEY = ["config", "arm", "repair_span", "data_fields", "num_data_segments", "W", "bit_error_rate",
       "max_combined_hd", "candidates_budget", "seed"]
OUT = ["recovered", "silent", "failed"]


def _load(p):
    p = pathlib.Path(p)
    files = [p] if p.is_file() else sorted(p.rglob("raw_trials.csv"))
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def compare(old, new):
    a, b = _load(old).set_index(KEY), _load(new).set_index(KEY)
    common = a.index.intersection(b.index)
    print(f"rows old {len(a)}, new {len(b)}, common {len(common)}")
    a, b = a.loc[common], b.loc[common]
    kl = a.index.get_level_values("arm") == "keyless"
    kl_same = a.loc[kl, OUT].sort_index().equals(b.loc[kl, OUT].sort_index())
    print(f"keyless outcomes identical: {kl_same}")
    g = [k for k in KEY if k != "seed"]
    old_s = a.loc[~kl, OUT + ["recovery_ops"]].groupby(g).sum()
    new_s = b.loc[~kl, OUT + ["recovery_ops"]].groupby(g).sum()
    kless = b.loc[kl, OUT].groupby([k for k in g if k != "arm"]).sum()
    tot = old_s[OUT].sum(axis=1)
    d = pd.DataFrame({"targets": tot,
                      "rec_old": old_s["recovered"], "rec_new": new_s["recovered"],
                      "sil_old": old_s["silent"], "sil_new": new_s["silent"],
                      "ops_ratio_new_old": new_s["recovery_ops"] / old_s["recovery_ops"].where(old_s["recovery_ops"] > 0)})
    d = d.reset_index()
    d = d.merge(kless.rename(columns={"recovered": "rec_keyless", "silent": "sil_keyless"})[["rec_keyless", "sil_keyless"]]
                .reset_index(), on=[k for k in g if k != "arm"], how="left")
    d["d_rec"] = d["rec_new"] - d["rec_old"]
    d["d_sil"] = d["sil_new"] - d["sil_old"]
    ch = d[(d["d_rec"] != 0) | (d["d_sil"] != 0)]
    print(f"keyed cells: {len(d)}, changed: {len(ch)} "
          f"(recovered +{int(ch['d_rec'].clip(lower=0).sum())}/-{int((-ch['d_rec']).clip(lower=0).sum())}, "
          f"silent +{int(ch['d_sil'].clip(lower=0).sum())}/-{int((-ch['d_sil']).clip(lower=0).sum())})")
    print("changed cells by HD:", ch.groupby("max_combined_hd").size().to_dict())
    print("per (W, HD), summed over cells: recovered keyed old -> new | keyless ; silent keyed old -> new | keyless")
    for (w, hd), s in d.groupby(["W", "max_combined_hd"]):
        print(f"  W{w} HD{hd}: rec {int(s['rec_old'].sum())} -> {int(s['rec_new'].sum())} | {int(s['rec_keyless'].sum())}"
              f" ; sil {int(s['sil_old'].sum())} -> {int(s['sil_new'].sum())} | {int(s['sil_keyless'].sum())}"
              f"  (of {int(s['targets'].sum())})")
    return d


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    d = compare(args.old, args.new)
    if args.out:
        d.to_csv(args.out, index=False)
        print("->", args.out)
