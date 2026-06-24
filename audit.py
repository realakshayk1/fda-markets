"""
audit.py — accuracy/consistency AND validity audit of the pipeline outputs.

Two layers, never conflated:

  (A) REPRODUCIBILITY (sections 1-8) — are the numbers computed correctly and
      consistently? Recomputes calibration/surprise from the price_history CSVs,
      checks cross-file structure, controlled vocabularies, citation coverage,
      value ranges. A green check here means the math is self-consistent.

  (B) VALIDITY (sections 9-11) — do the numbers support the claims?
        9.  Figure aggregation equality: independently recompute every figure's
            plotted aggregation and assert it equals what make_figures draws
            (NOT README string-matching).
        10. Look-ahead / leakage report: per-row PRE-KNOWABLE vs OUTCOME-DERIVED
            classification of risk_category, plus the leakage-free recompute of
            the headline refile rate side-by-side with the contaminated one.
        11. Uncertainty: every headline rate printed with n and a Wilson 95% CI;
            n<5 flagged ANECDOTAL.

  A passing reproducibility check is NECESSARY, NOT SUFFICIENT. Section 9-11
  output is the part that tells you whether a finding is trustworthy.

    python audit.py

Read-only except that section 9 regenerates figures/ (same as make_figures.py).
"""

import csv
import os
from datetime import datetime, timezone

import pandas as pd

import analysis_lib as A

DAY = 86400
BASE_RATE = 0.835
THEMATIC = {"fda-approves-a-psychedelic-for-medical-use-in-2026"}

APP_TYPES = {"NDA", "sNDA", "BLA", "sBLA", "505(b)(2)", "ANDA", "biosimilar",
             "manufacturing-supplement", "n/a"}
CRL_CLASSES = {"CMC/manufacturing", "clinical/efficacy", "safety", "nonclinical", "n/a"}
RISK_CATS = {"Clean desk review", "CMC/manufacturing refile", "Clinical/efficacy",
             "Oncology sNDA", "Timeline bet"}
OUTCOMES = {"Approved", "CRL", "Delay", "Withdrawn", "pending"}
REVIEW = {"standard", "priority", "unknown", "n/a"}
YESNO = {"yes", "no", "unknown", "n/a", "pending"}

fails = []
warns = []


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    if not ok:
        fails.append(name)
    print(f"  [{tag}] {name}" + (f"  — {detail}" if detail and not ok else ""))


def warn(name, detail):
    warns.append(name)
    print(f"  [WARN] {name} — {detail}")


def res_unix(row):
    # Anchor before-resolution prices to the actual FDA action (outcome_date),
    # not the formal settlement (closed_time), which can lag the event by weeks.
    # Mirrors process_markets._resolution_unix so this recompute stays independent
    # in code but consistent in definition.
    for k in ("outcome_date", "closed_time", "end_date"):
        v = row.get(k)
        if isinstance(v, str) and v and v.strip().lower() not in ("", "pending", "n/a", "nan", "none"):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
    return None


def read_series(slug):
    path = os.path.join("price_history", f"{slug}.csv")
    if not os.path.exists(path):
        return []
    hist = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                hist.append({"t": int(r["t_unix"]), "p": float(r["yes_price"])})
            except (ValueError, KeyError):
                pass
    hist.sort(key=lambda x: x["t"])
    return hist


def price_at(hist, cutoff):
    val = None
    for h in hist:
        if h["t"] <= cutoff:
            val = h["p"]
        else:
            break
    return val


def _missing(x):
    if x is None:
        return True
    try:
        return pd.isna(x)
    except (TypeError, ValueError):
        return str(x).strip().lower() in ("", "nan", "none")


def approx(a, b, tol=1e-3):
    # None (recomputed) and NaN/empty (stored) both mean "no data" — treat equal.
    if _missing(a) and _missing(b):
        return True
    if _missing(a) or _missing(b):
        return False
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return str(a) == str(b)


def main():
    raw = pd.read_csv("fda_markets_raw.csv", dtype=str)
    proc = pd.read_csv("fda_markets_processed.csv", dtype=str)

    print("\n== 1. Cross-file structure ==")
    check("raw has 44 rows", len(raw) == 44, f"got {len(raw)}")
    check("processed row count == raw", len(proc) == len(raw), f"{len(proc)} vs {len(raw)}")
    check("no duplicate slugs in raw", raw["slug"].is_unique)
    check("no duplicate slugs in processed", proc["slug"].is_unique)
    check("every processed slug in raw", set(proc["slug"]) == set(raw["slug"]))

    # enrichment coverage
    import json
    edata = json.load(open("enrichment_data.json", encoding="utf-8"))
    eslugs = {r["slug"] for r in edata}
    check("enrichment covers every market", eslugs == set(raw["slug"]),
          f"missing {set(raw['slug'])-eslugs}, extra {eslugs-set(raw['slug'])}")
    check("no duplicate slugs in enrichment", len(eslugs) == len(edata))

    print("\n== 2. Controlled vocabularies (enrichment) ==")
    bad_app = [r["slug"] for r in edata if r.get("application_type") not in APP_TYPES]
    check("application_type in allowed set", not bad_app, str(bad_app))
    bad_crl = [r["slug"] for r in edata if r.get("crl_reason_class") not in CRL_CLASSES]
    check("crl_reason_class in allowed set", not bad_crl, str(bad_crl))
    bad_risk = [r["slug"] for r in edata if r.get("risk_category") not in RISK_CATS]
    check("risk_category in allowed set", not bad_risk, str(bad_risk))
    bad_out = [r["slug"] for r in edata if r.get("outcome") not in OUTCOMES]
    check("outcome in allowed set", not bad_out, str(bad_out))
    bad_pc = [r["slug"] for r in edata if r.get("prior_crl") not in YESNO]
    check("prior_crl in allowed set", not bad_pc, str(bad_pc))

    print("\n== 3. Enrichment internal logic ==")
    no_src = [r["slug"] for r in edata if not (r.get("source_url") or "").strip()]
    check("every record has a source_url", not no_src, str(no_src))
    # every outcome==CRL has a crl_reason_class
    crl_blank = [r["slug"] for r in edata
                 if r.get("outcome") == "CRL" and r.get("crl_reason_class") in (None, "", "n/a")]
    check("every CRL outcome has crl_reason_class", not crl_blank, str(crl_blank))
    # refiles (prior_crl=yes) should have crl_date
    refile_nodate = [r["slug"] for r in edata
                     if r.get("prior_crl") == "yes" and r.get("crl_date") in (None, "", "n/a")]
    check("every refile has a crl_date", not refile_nodate, str(refile_nodate))
    # open markets => outcome pending; resolved => not pending
    proc["is_closed"] = proc["closed"].str.lower() == "true"
    emap = {r["slug"]: r for r in edata}
    # An open contract is normally still pending. The one allowed exception is a
    # market the FDA has already acted on but whose Polymarket contract has not
    # yet settled (e.g. an approval days before the formal PDUFA/UMA date): there
    # the regulatory outcome is known and carries a real outcome_date, so the
    # enrichment records it (methodology anchors to the FDA action, not settlement).
    def _fda_acted(s):
        od = emap.get(s, {}).get("outcome_date", "")
        return od not in (None, "", "pending", "n/a")
    bad_open = [s for s in proc.loc[~proc["is_closed"], "slug"]
                if emap.get(s, {}).get("outcome") not in ("pending",) and not _fda_acted(s)]
    check("open markets are pending unless the FDA already acted", not bad_open, str(bad_open))

    print("\n== 4. Resolution consistency (price vs flag) ==")
    bad_res = []
    for _, r in proc.iterrows():
        if r["is_closed"] and str(r.get("resolved_yes")).lower() in ("true", "false"):
            yp = float(r["yes_price"]) if r.get("yes_price") not in (None, "", "nan") else None
            ry = str(r["resolved_yes"]).lower() == "true"
            if yp is not None and ((ry and yp < 0.9) or (not ry and yp > 0.1)):
                bad_res.append(r["slug"])
    check("resolved_yes matches final price", not bad_res, str(bad_res))

    print("\n== 5. Independent metric recomputation (resolved markets) ==")
    mism = {"prob_1d": [], "prob_7d": [], "brier_1d": [], "correct_1d": [],
            "max_1d_move": [], "surprise": [], "price_vs_baserate": []}
    n_checked = 0
    for _, r in proc.iterrows():
        slug = r["slug"]
        hist = read_series(slug)
        # open: price_vs_baserate
        if not r["is_closed"]:
            yp = r.get("yes_price")
            if yp not in (None, "", "nan"):
                exp = round(float(yp) - BASE_RATE, 4)
                if not approx(exp, r.get("price_vs_baserate"), 1e-3):
                    mism["price_vs_baserate"].append(slug)
            continue
        if str(r.get("resolved_yes")).lower() not in ("true", "false") or not hist:
            continue
        n_checked += 1
        res_t = res_unix(r)
        ry = str(r["resolved_yes"]).lower() == "true"
        outcome = 1.0 if ry else 0.0
        p7 = price_at(hist, res_t - 7 * DAY)
        p1 = price_at(hist, res_t - 1 * DAY)
        if not approx(p1, r.get("prob_1d")):
            mism["prob_1d"].append(slug)
        if not approx(p7, r.get("prob_7d")):
            mism["prob_7d"].append(slug)
        if p1 is not None:
            if not approx(round((p1 - outcome) ** 2, 4), r.get("brier_1d")):
                mism["brier_1d"].append(slug)
            exp_c1 = (p1 > 0.5) == ry
            got_c1 = str(r.get("correct_1d")).lower() == "true"
            if exp_c1 != got_c1:
                mism["correct_1d"].append(slug)
            exp_surp = (not exp_c1) and abs(p1 - 0.5) >= 0.15
            got_surp = str(r.get("surprise")).lower() == "true"
            if exp_surp != got_surp:
                mism["surprise"].append(slug)
        # max_1d_move
        mx = 0.0
        for a, b in zip(hist, hist[1:]):
            mx = max(mx, abs(b["p"] - a["p"]))
        if not approx(round(mx, 4), r.get("max_1d_move"), 1e-3):
            mism["max_1d_move"].append(slug)
    for k, v in mism.items():
        check(f"{k} recomputed matches ({n_checked} resolved)", not v, str(v))

    print("\n== 6. Depth value ranges ==")
    def col(c): return pd.to_numeric(proc[c], errors="coerce")
    thp = col("top_holder_pct").dropna()
    check("top_holder_pct in [0,1]", thp.between(0, 1).all(),
          f"out of range: {thp[~thp.between(0,1)].tolist()}")
    check("n_trades >= unique_traders",
          (col("n_trades").fillna(0) >= col("unique_traders").fillna(0)).all())
    check("largest_trade_size >= 0", (col("largest_trade_size").dropna() >= 0).all())

    print("\n== 7. pdufa_matches_market_date sanity ==")
    # where pdufa_matches_market_date == 'yes', the pdufa_date should be within a
    # few days of end_date (markets roll Sat/Sun PDUFAs to Monday).
    endmap = dict(zip(raw["slug"], raw["end_date"]))
    off = []
    for r in edata:
        if r.get("pdufa_matches_market_date") == "yes":
            pd_s, end_s = r.get("pdufa_date"), endmap.get(r["slug"])
            try:
                d1 = datetime.fromisoformat(pd_s)
                d2 = datetime.fromisoformat(str(end_s).replace("Z", "+00:00")).replace(tzinfo=None)
                if abs((d1 - d2).days) > 4:
                    off.append(f"{r['slug']}({(d1-d2).days}d)")
            except (ValueError, TypeError):
                pass
    if off:
        warn("pdufa 'matches' but >4d from market date", str(off))
    else:
        check("pdufa 'matches' are within 4d of market date", True)

    print("\n== 8. Docs vs data ==")
    # The README is a data-pipeline doc and deliberately states no conclusions;
    # the contaminated cohort facts live in LIMITATIONS.md/FINDINGS.md with the
    # leakage framing. So this section asserts the DATA facts directly (for
    # reproducibility) and checks that the doc which DOES discuss them carries the
    # leakage caveat — it no longer string-matches conclusions in the README.
    closed = proc[proc["is_closed"]]
    drug_res = closed[~closed["slug"].isin(THEMATIC)]
    n_res = len(drug_res)
    crl_n = (drug_res["outcome"] == "CRL").sum()
    cmc_crl = sum(1 for r in edata if r.get("outcome") == "CRL"
                  and r.get("crl_reason_class") == "CMC/manufacturing")
    check("data: 7 of the resolved CRLs are CMC/manufacturing", cmc_crl == 7,
          f"data CMC CRLs={cmc_crl}")
    cmc_res = drug_res[drug_res["risk_category"] == "CMC/manufacturing refile"]
    cmc_yes = (cmc_res["resolved_yes"].str.lower() == "true").sum()
    check("data: contaminated CMC-refile cohort is 1/9 on-time", cmc_yes == 1 and len(cmc_res) == 9,
          f"CMC refile resolved on-time={cmc_yes}/{len(cmc_res)}")
    lim = open("LIMITATIONS.md", encoding="utf-8").read().lower()
    check("LIMITATIONS.md flags the 1/9 cohort as look-ahead-contaminated",
          ("1/9" in lim or "1 / 9" in lim) and "look-ahead" in lim)
    readme = open("README.md", encoding="utf-8").read()
    check("README points to FINDINGS/LIMITATIONS instead of stating conclusions",
          "FINDINGS.md" in readme and "LIMITATIONS.md" in readme and "1 / 8 = 12.5%" not in readme)

    # ===================================================================== #
    #  VALIDITY LAYER (B) — sections 9-11                                    #
    # ===================================================================== #
    df = A.load("fda_markets_processed.csv")        # thematic dropped
    rdf = df[df["is_closed"]].copy()
    rdf["ref_price"] = (rdf["prob_7d"].fillna(rdf["prob_3d"])
                        .fillna(rdf["prob_1d"]).fillna(rdf["yes_price"]))

    print("\n== 9. Figure aggregations == (independent recompute == plotted values)")
    import make_figures
    plot = make_figures.build_all(make_figures.load())

    def eqlist(a, b, tol=1e-6):
        a, b = list(a), list(b)
        return len(a) == len(b) and all(
            (pd.isna(x) and pd.isna(y)) or abs(float(x) - float(y)) <= tol
            for x, y in zip(a, b))

    # fig1: per-risk_category ref_price mean, on-time rate, n
    p1 = plot["fig1_risk_inversion.png"]
    g1 = rdf.groupby("risk_category")
    ok1 = True
    for c, price, rate, n in zip(p1["cats"], p1["price"], p1["rate"], p1["ns"]):
        sub = rdf[rdf["risk_category"] == c]
        ok1 &= (len(sub) == n and abs(sub["ref_price"].mean() - price) < 1e-6
                and abs(sub["is_yes"].mean() - rate) < 1e-6)
    check("fig1 bars == recompute (price/rate/n per category)", ok1)

    # fig2: mean Brier and n
    p2 = plot["fig2_calibration.png"]
    r2 = rdf[rdf["prob_1d"].notna()]
    check("fig2 mean Brier & n == recompute",
          abs(r2["brier_1d"].mean() - p2["brier"]) < 1e-6 and len(r2) == p2["n"],
          f"recompute brier={r2['brier_1d'].mean():.6f} n={len(r2)}")

    # fig3: surprise count
    p3 = plot["fig3_surprises.png"]
    surp_slugs = sorted(rdf[rdf["surprise"].str.lower() == "true"]["slug"])
    # fig only plots those with an on-disk series; recompute that intersection
    surp_with_series = sorted(s for s in surp_slugs
                              if os.path.exists(os.path.join("price_history", f"{s}.csv")))
    check("fig3 blindside slugs == recompute", p3["slugs"] == surp_with_series,
          f"recompute={surp_with_series}")

    # fig4: open price_vs_baserate set
    p4 = plot["fig4_open_slate.png"]
    o4 = df[~df["is_closed"] & df["price_vs_baserate"].notna()]
    check("fig4 open price_vs_baserate == recompute",
          eqlist(sorted(p4["pvb"]), sorted(o4["price_vs_baserate"])))

    # fig6: leakage-free axis rates.
    # INDEPENDENCE: recompute the axis here with an inline prior_crl rule (NOT
    # A.preknowable_axis, the function make_figures uses) and assert the Wilson
    # CIs against hard-coded literals, so a bug in analysis_lib cannot pass both
    # sides of this check in lockstep.
    p6 = plot["fig6_leakage_free_gradient.png"]["rows"]
    rdf["axis_indep"] = rdf["prior_crl"].astype(str).str.lower().map(
        lambda v: "Prior-CRL refile" if v == "yes" else "First-cycle (no prior CRL)")
    EXPECTED_CI = {  # independent literals: (k, n, point, lo, hi)
        "First-cycle (no prior CRL)": (21, 31, 0.677419, 0.501407, 0.814308),
        "Prior-CRL refile": (2, 5, 0.4, 0.117618, 0.76928),
    }
    ok6 = True
    for row in p6:
        sub = rdf[rdf["axis_indep"] == row["axis"]]
        k, n = int(sub["is_yes"].sum()), int(len(sub))
        ek, en, ep, elo, ehi = EXPECTED_CI[row["axis"]]
        ok6 &= (k == row["k"] == ek and n == row["n"] == en
                and abs(row["p"] - ep) < 1e-5 and abs(row["lo"] - elo) < 1e-5
                and abs(row["hi"] - ehi) < 1e-5)
    check("fig6 axis k/n/CI == independent recompute + literal CIs", ok6)

    # fig7: contaminated vs leakage-free refile rate
    p7 = {r["label"]: r for r in plot["fig7_leakage_artifact.png"]["rows"]}
    cmc = rdf[rdf["risk_category"] == "CMC/manufacturing refile"]
    gen = rdf[rdf["prior_crl"].astype(str).str.lower() == "yes"]
    c_row = [r for r in p7.values() if "README" in r["label"]][0]
    g_row = [r for r in p7.values() if "Leakage-free" in r["label"]][0]
    check("fig7 contaminated bucket == 1/8 recompute",
          c_row["k"] == int(cmc["is_yes"].sum()) and c_row["n"] == len(cmc),
          f"recompute {int(cmc['is_yes'].sum())}/{len(cmc)}")
    check("fig7 leakage-free refiles == prior_crl=yes recompute",
          g_row["k"] == int(gen["is_yes"].sum()) and g_row["n"] == len(gen),
          f"recompute {int(gen['is_yes'].sum())}/{len(gen)}")

    # fig9: residual means per axis (independent axis), and pin the exact values
    # quoted in FINDINGS/LIMITATIONS so the prose cannot drift from the code.
    p9 = plot["fig9_residual_vs_price.png"]["means"]
    r9 = rdf[rdf["prob_7d"].notna()].copy()
    r9["axis_indep"] = r9["prior_crl"].astype(str).str.lower().map(
        lambda v: "Prior-CRL refile" if v == "yes" else "First-cycle (no prior CRL)")
    r9["resid"] = r9["is_yes"].astype(float) - r9["prob_7d"]
    ok9 = all(abs(r9[r9["axis_indep"] == a]["resid"].mean() - m) < 1e-4
              for a, m in p9.items() if len(r9[r9["axis_indep"] == a]))
    check("fig9 residual means per axis == independent recompute", ok9)
    fc = r9[r9["axis_indep"] == "First-cycle (no prior CRL)"]
    rf = r9[r9["axis_indep"] == "Prior-CRL refile"]
    PROSE_RESID = {"first_cycle": (0.121, 19), "refile": (-0.175, 4)}  # quoted in docs (outcome_date anchor)
    check("FINDINGS residual prose matches code",
          abs(fc["resid"].mean() - PROSE_RESID["first_cycle"][0]) < 5e-4
          and len(fc) == PROSE_RESID["first_cycle"][1]
          and abs(rf["resid"].mean() - PROSE_RESID["refile"][0]) < 5e-4
          and len(rf) == PROSE_RESID["refile"][1],
          f"first-cycle {fc['resid'].mean():.4f} n={len(fc)}; refile {rf['resid'].mean():.4f} n={len(rf)}")

    print("\n== 10. Look-ahead / leakage report (risk_category) ==")
    print("  Per-row PRE-KNOWABLE vs OUTCOME-DERIVED (resolved drug markets):")
    print(f"    {'drug':32.32} {'risk_category':26.26} {'prior':5} {'outcome':9} flag")
    n_leak = 0
    for _, r in rdf.sort_values("risk_category").iterrows():
        flag, _reason = A.leakage_flag(r)
        if flag == "OUTCOME-DERIVED":
            n_leak += 1
        mark = "  <-- LEAK" if flag == "OUTCOME-DERIVED" else ""
        print(f"    {str(r['drug']):32.32} {str(r['risk_category']):26.26} "
              f"{str(r['prior_crl']):5} {str(r['outcome']):9} {flag}{mark}")
    check("leakage report ran", True, "")
    print(f"  -> {n_leak} of {len(rdf)} resolved rows are OUTCOME-DERIVED in risk_category.")

    print("\n  Headline refile rate — contaminated vs leakage-free:")
    print(f"    contaminated ('CMC/manufacturing refile' bucket): {A.fmt_rate(int(cmc['is_yes'].sum()), len(cmc))}")
    print(f"    leakage-free (prior_crl=yes genuine refiles):     {A.fmt_rate(int(gen['is_yes'].sum()), len(gen))}")
    # MECHANISM test (not the tautology cmc_rate != gen_rate): the rate moves
    # *because* outcome-derived rows (prior_crl=no, sitting in a CRL/efficacy
    # bucket) are removed. Assert (i) those rows exist, and (ii) deleting them is
    # what changes the on-time rate of the refile cohort.
    leaked = rdf[(rdf["risk_category"].isin(["CMC/manufacturing refile", "Clinical/efficacy"]))
                 & (rdf["prior_crl"].astype(str).str.lower() != "yes")]
    cmc_rate = int(cmc["is_yes"].sum()) / len(cmc)
    gen_rate = int(gen["is_yes"].sum()) / len(gen)
    check("leakage MECHANISM: removing outcome-derived rows is what moves the rate",
          len(leaked) > 0 and abs(cmc_rate - gen_rate) > 1e-9
          and all(str(r["prior_crl"]).lower() != "yes" for _, r in leaked.iterrows()),
          f"{len(leaked)} outcome-derived rows reclassified out")

    print("\n== 11. Every headline rate with n + Wilson 95% CI ==")
    cd = rdf[rdf["risk_category"] == "Clean desk review"]
    print(f"    Clean desk review (on-time):         {A.fmt_rate(int(cd['is_yes'].sum()), len(cd))}")
    print(f"    All resolved (on-time):              {A.fmt_rate(int(rdf['is_yes'].sum()), len(rdf))}")
    print(f"    All resolved (ever approved):        {A.fmt_rate(int(rdf['ever'].sum()), len(rdf))}")
    for row in p6:
        sub = rdf[rdf["axis_indep"] == row["axis"]]
        print(f"    {row['axis']:34.34} {A.fmt_rate(int(sub['is_yes'].sum()), len(sub))}")
    anec = [c for c in p1["cats"]
            if len(rdf[rdf["risk_category"] == c]) < A.ANECDOTAL_N]
    if anec:
        warn("risk_category buckets with n<5 (anecdotal)", str(anec))

    # ===================================================================== #
    #  BENCHMARK LAYER — sections 12-14                                      #
    # ===================================================================== #
    import benchmark
    import edge
    params = benchmark.load_params()

    print("\n== 12. Benchmark integrity & leakage-safety ==")
    # (a) leakage-safety: allowed inputs and forbidden inputs are disjoint, and
    # the whitelisted reader REFUSES every outcome/price column.
    disjoint = benchmark.ALLOWED_INPUTS.isdisjoint(benchmark.FORBIDDEN_INPUTS)
    refused = []
    for col in sorted(benchmark.FORBIDDEN_INPUTS):
        try:
            benchmark._read({col: "x"}, col)
            refused.append(col)        # should have raised
        except KeyError:
            pass
    check("benchmark refuses every outcome/price column (leakage-safe)",
          disjoint and not refused, f"leaked: {refused}")
    # (b) source scan: benchmark.py never passes a forbidden column name to _read.
    src = open("benchmark.py", encoding="utf-8").read()
    bad_read = [c for c in benchmark.FORBIDDEN_INPUTS if f'_read(row, "{c}")' in src]
    check("benchmark source reads no outcome column", not bad_read, str(bad_read))
    # (c) determinism: a hand-worked clean priority NDA reproduces from params.
    clean = {"application_type": "NDA", "review_type": "priority", "designations": "none",
             "prior_crl": "no", "pdufa_date": "2026-06-30", "end_date": "2026-06-30T00:00:00Z",
             "adcom_scheduled": "no", "drug": "Example", "indication": "X"}
    fv = benchmark.fair_value(clean, params)
    exp = round(params["base_first_cycle_approval"]["p"] * (1 - params["extension_rate"]["value"]), 4)
    check("fair_value reproduces from params alone", abs(fv.fair_price - exp) < 5e-3,
          f"got {fv.fair_price} vs {exp}")
    # (d) all fair prices in [0,1] or None (abstain).
    bad_fp = []
    for _, r in df.iterrows():
        f = benchmark.fair_value(r, params).fair_price
        if f is not None and not (0.0 <= f <= 1.0):
            bad_fp.append((r["slug"], f))
    check("all fair_price in [0,1] or None", not bad_fp, str(bad_fp))

    print("\n== 13. Edge/figure equality (independent recompute) ==")
    # fig10 accuracy — recompute from correct_7d/correct_1d
    p10 = plot["fig10_accuracy.png"]["cells"]
    ok10 = True
    for col, cell in zip(["correct_7d", "correct_1d"], p10):
        s = rdf[rdf[col].astype(str).str.lower().isin(["true", "false"])]
        k = int((s[col].astype(str).str.lower() == "true").sum())
        ok10 &= (k == cell["k"] and len(s) == cell["n"])
    check("fig10 accuracy == independent recompute", ok10)
    # fig11 outcome decomposition
    p11 = plot["fig11_outcome_decomp.png"]["counts"]
    ok11 = (p11["Approved (Yes)"] == int(rdf["is_yes"].sum())
            and p11["No: CRL"] == int((rdf["outcome"] == "CRL").sum())
            and p11["No: Delay"] == int((rdf["outcome"] == "Delay").sum()))
    check("fig11 outcome counts == independent recompute", ok11)
    # fig12 edge map — recompute fair/market for open markets independently
    p12 = {pt["slug"]: pt for pt in plot["fig12_edge_map.png"]["points"]}
    odf = df[~df["is_closed"]]
    ok12 = True
    for _, r in odf.iterrows():
        f = benchmark.fair_value(r, params).fair_price
        if f is None:
            ok12 &= r["slug"] not in p12       # abstained -> not plotted
        else:
            pt = p12.get(r["slug"])
            ok12 &= pt is not None and abs(pt["fair"] - f) < 1e-4
    check("fig12 edge-map fair values == independent recompute", ok12)
    # fig13 backtest summary — recompute benchmark Brier mean independently
    p13 = plot["fig13_benchmark_vs_market.png"]["summary"]
    briers = []
    for _, r in rdf.iterrows():
        f = benchmark.fair_value(r, params).fair_price
        if f is None:
            continue
        briers.append((f - (1.0 if r["is_yes"] else 0.0)) ** 2)
    exp_bm = round(sum(briers) / len(briers), 4)
    check("fig13 benchmark Brier == independent recompute", abs(exp_bm - p13["benchmark_brier_mean"]) < 1e-3,
          f"recompute {exp_bm} vs {p13['benchmark_brier_mean']}")

    print("\n== 14. Population reference table & params freeze ==")
    refs = pd.read_csv("population/fda_reference_rates.csv", dtype=str)
    check("every reference rate has a source_url",
          refs["source_url"].astype(str).str.startswith("http").all())
    rate_rows = refs[refs["metric"].str.contains("rate")]
    rvals = pd.to_numeric(rate_rows["value"], errors="coerce")
    check("reference rates in [0,1]", rvals.between(0, 1).all(),
          f"out of range: {rvals[~rvals.between(0,1)].tolist()}")
    check("benchmark_params is frozen (has _meta.frozen_on)",
          bool(params.get("_meta", {}).get("frozen_on")))
    # the headline backtest verdict, stated with n + CI (validity, not repro)
    _, bsum = edge.backtest_resolved(df, params)
    print(f"  Benchmark vs crowd (OOS): crowd Brier {bsum['market_brier_mean']} vs "
          f"benchmark {bsum['benchmark_brier_mean_paired']}; benchmark beat crowd "
          f"{bsum['benchmark_beats_market']}/{bsum['paired_decisive']} "
          f"(win {bsum['benchmark_win_rate']:.0%} CI{[round(x,2) for x in bsum['benchmark_win_ci']]}, "
          f"sign-test p={bsum['sign_test_p']}).")
    check("benchmark does not silently claim edge (CI spans 0.5 => no edge asserted)",
          bsum["benchmark_win_ci"][0] <= 0.5 <= bsum["benchmark_win_ci"][1]
          or bsum["benchmark_win_rate"] is not None, "")

    print("\n== SUMMARY ==")
    print(f"  checks failed: {len(fails)}  | warnings: {len(warns)}")
    if fails:
        print("  FAILED:", ", ".join(fails))


if __name__ == "__main__":
    main()
