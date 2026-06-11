"""
insights.py — harvest the evidence base (NOT a narrative).

Recomputes every reportable rate with n + a Wilson 95% CI + a leakage flag, plus
the benchmark-vs-crowd verdict, and writes a machine-readable findings.json. This
is the raw material any later write-up draws from; it chooses no story. A rate is
auto-tiered ROBUST / SUGGESTIVE / ANECDOTAL purely by n and CI width, never by
whether it is "interesting."

    python insights.py        # prints the harvest, writes findings.json
"""

import json

import analysis_lib as A
import benchmark
import edge


def tier(k, n):
    if n < A.ANECDOTAL_N:
        return "ANECDOTAL"
    _, lo, hi = A.wilson(k, n)
    return "SUGGESTIVE" if (hi - lo) > 0.33 else "ROBUST"


def rate_entry(label, k, n, leakage="n/a", note=""):
    p, lo, hi = A.wilson(k, n)
    return {"label": label, "k": int(k), "n": int(n),
            "point": None if n == 0 else round(p, 4),
            "ci": [round(lo, 4), round(hi, 4)], "tier": tier(k, n),
            "leakage": leakage, "note": note}


def main():
    df = A.load()
    rdf = df[df["is_closed"]].copy()
    params = benchmark.load_params()
    F = {"cohort": {"resolved": int(len(rdf)), "open": int((~df["is_closed"]).sum())},
         "rates": [], "benchmark": {}, "open_edge": {}}

    # Q1 sharpness
    for col, lab in [("correct_7d", "crowd correct @7d"), ("correct_1d", "crowd correct @1d")]:
        s = rdf[rdf[col].astype(str).str.lower().isin(["true", "false"])]
        k = int((s[col].astype(str).str.lower() == "true").sum())
        F["rates"].append(rate_entry(lab, k, len(s), "none",
                                     "majority-side accuracy; pre-decision price vs realized"))

    # Q5 heterogeneity by pre-knowable features (+ leakage-free prior_crl axis)
    rdf["axis"] = rdf["prior_crl"].astype(str).str.lower().map(
        lambda v: "Prior-CRL refile" if v == "yes" else "First-cycle (no prior CRL)")
    for v, sub in rdf.groupby("axis"):
        F["rates"].append(rate_entry(f"on-time | {v}", int(sub["is_yes"].sum()), len(sub),
                                     "leakage-free (prior_crl is pre-decision)"))
    for col in ["application_type", "review_type"]:
        for v, sub in rdf.groupby(col):
            if len(sub) >= 3:
                F["rates"].append(rate_entry(f"on-time | {col}={v}", int(sub["is_yes"].sum()),
                                             len(sub), "pre-decision feature"))
    # contaminated vs leakage-free refile (the headline correction)
    cmc = rdf[rdf["risk_category"] == "CMC/manufacturing refile"]
    gen = rdf[rdf["prior_crl"].astype(str).str.lower() == "yes"]
    F["rates"].append(rate_entry("CONTAMINATED 'CMC refile' bucket", int(cmc["is_yes"].sum()),
                                 len(cmc), "OUTCOME-DERIVED — do not report as a base rate"))
    F["rates"].append(rate_entry("LEAKAGE-FREE refile (prior_crl=yes)", int(gen["is_yes"].sum()),
                                 len(gen), "leakage-free"))

    # Q6 by-date vs ever
    F["rates"].append(rate_entry("approved ON TIME (all resolved)", int(rdf["is_yes"].sum()), len(rdf), "none"))
    F["rates"].append(rate_entry("approved EVER (all resolved)", int(rdf["ever"].sum()), len(rdf), "none"))

    # Q2 benchmark verdict
    _, bsum = edge.backtest_resolved(df, params)
    F["benchmark"] = bsum
    F["benchmark"]["verdict"] = (
        "crowd SHARPER than the cited base rate" if bsum["market_brier_mean"] < bsum["benchmark_brier_mean_paired"]
        else "base rate beat the crowd")

    # Q2/Q4 open edge
    op = edge.score_open(df, params)
    scored = op[op["fair_price"] != "N/A"]
    F["open_edge"] = {
        "n_scored": int(len(scored)),
        "n_benchmark_NA": int((op["fair_price"] == "N/A").sum()),
        "max_abs_gap": round(float(scored["abs_gap"].astype(float).max()), 4) if len(scored) else None,
        "n_gap_over_0.10_and_depth_ok": int(((scored["abs_gap"].astype(float) > 0.10)
                                             & (scored["depth_ok"])).sum()),
    }

    with open("findings.json", "w", encoding="utf-8") as f:
        json.dump(F, f, indent=2)

    print("== Evidence harvest (every rate: n, Wilson 95% CI, tier, leakage) ==")
    for r in F["rates"]:
        pt = "n/a" if r["point"] is None else f"{r['point']:.0%}"
        print(f"  [{r['tier']:10}] {r['label']:42.42} {r['k']}/{r['n']} = {pt} "
              f"CI{r['ci']}  <{r['leakage']}>")
    print(f"\n  Q2 benchmark: {F['benchmark']['verdict']} — crowd Brier "
          f"{bsum['market_brier_mean']} vs benchmark {bsum['benchmark_brier_mean_paired']}; "
          f"benchmark won {bsum['benchmark_beats_market']}/{bsum['paired_decisive']} "
          f"(p={bsum['sign_test_p']}).")
    print(f"  Open edge: {F['open_edge']['n_scored']} scored, "
          f"{F['open_edge']['n_benchmark_NA']} N/A; max |gap| {F['open_edge']['max_abs_gap']}; "
          f"{F['open_edge']['n_gap_over_0.10_and_depth_ok']} depth-supported gaps > 0.10.")
    print("\n  Wrote findings.json. No narrative selected — this is the raw evidence base.")


if __name__ == "__main__":
    main()
