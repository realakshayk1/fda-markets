"""
audit.py — internal accuracy/consistency audit of the pipeline outputs.

Independently recomputes the calibration/surprise metrics from the price_history
CSVs and compares them to fda_markets_processed.csv; validates cross-file row/slug
consistency, controlled vocabularies, citation coverage, and value ranges. Prints
PASS/FAIL per check. Read-only — does not modify any data.

    python audit.py
"""

import csv
import os
from datetime import datetime, timezone

import pandas as pd

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
    for k in ("closed_time", "end_date"):
        v = row.get(k)
        if isinstance(v, str) and v:
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
    bad_open = [s for s in proc.loc[~proc["is_closed"], "slug"]
                if emap.get(s, {}).get("outcome") not in ("pending",)]
    check("open markets have outcome=pending", not bad_open, str(bad_open))

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
    closed = proc[proc["is_closed"]]
    drug_res = closed[~closed["slug"].isin(THEMATIC)]
    n_res = len(drug_res)
    crl_n = (drug_res["outcome"] == "CRL").sum()
    cmc_crl = sum(1 for r in edata if r.get("outcome") == "CRL"
                  and r.get("crl_reason_class") == "CMC/manufacturing")
    readme = open("README.md", encoding="utf-8").read()
    check("README '6 ... CMC' matches data", ("6 were CMC" in readme) == (cmc_crl == 6),
          f"data CMC CRLs={cmc_crl}")
    cmc_res = drug_res[drug_res["risk_category"] == "CMC/manufacturing refile"]
    cmc_yes = (cmc_res["resolved_yes"].str.lower() == "true").sum()
    check("README '1 / 8 = 12.5%' matches data",
          ("1 / 8 = 12.5%" in readme) and (cmc_yes == 1) and (len(cmc_res) == 8),
          f"CMC refile resolved on-time={cmc_yes}/{len(cmc_res)}")

    print("\n== SUMMARY ==")
    print(f"  checks failed: {len(fails)}  | warnings: {len(warns)}")
    if fails:
        print("  FAILED:", ", ".join(fails))


if __name__ == "__main__":
    main()
