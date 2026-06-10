"""
make_figures.py — generate the analysis figures from the processed dataset.

Reads fda_markets_processed.csv (+ the per-market series in price_history/) and
writes PNGs to figures/. Run after process_markets.py:

    python make_figures.py

Each figure function returns (fig, plotdata). `plotdata` is the exact set of
numbers drawn on the chart; audit.py recomputes those aggregations
independently and asserts equality, so a figure can never silently drift from
the data (or from the audit's own recompute).

Figures
-------
Reproducibility / description (pre-existing):
    fig1_risk_inversion.png   price charged vs realized on-time rate per
                              risk_category.  *** LEAKAGE-CONTAMINATED ***
                              risk_category buckets first-cycle CRLs as
                              "refiles"; annotated with a caveat banner.
    fig2_calibration.png      reliability curve of prob_1d (+ mean Brier)
    fig3_surprises.png        blindside price trajectories
    fig4_open_slate.png       open markets' price vs the 0.835 base rate
    fig5_depth.png            market thinness

Validity (new — leakage-aware, every rate with a Wilson 95% CI):
    fig6_leakage_free_gradient.png   on-time rate by a PRE-KNOWABLE risk axis
                                     (prior_crl-based) with CI error bars
    fig7_leakage_artifact.png        the refile claim: contaminated 1/8 vs
                                     leakage-free 1/3, both with CIs
    fig8_bydate_vs_ever.png          on-time-by-date vs approved-ever per axis
    fig9_residual_vs_price.png       outcome − price the market charged 7d out
                                     (was the risk already priced? = alpha test)
"""

import os
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")  # headless — write files, no display
import matplotlib.pyplot as plt
import pandas as pd

import analysis_lib as A

PROC = "fda_markets_processed.csv"
PH_DIR = "price_history"
OUT_DIR = "figures"
BASE_RATE = A.BASE_RATE
THEMATIC = A.THEMATIC
DAY = 86400

RC_COLORS = {
    "Clean desk review": "#2ca02c",
    "Oncology sNDA": "#1f77b4",
    "CMC/manufacturing refile": "#d62728",
    "Clinical/efficacy": "#e377c2",
    "Timeline bet": "#ff7f0e",
}
AXIS_COLORS = {
    "First-cycle (no prior CRL)": "#2ca02c",
    "Prior-CRL refile": "#d62728",
}


def _b(x):
    return str(x).strip().lower() == "true"


def _res_unix(row):
    # Anchor to the actual FDA action (outcome_date), matching process_markets.
    for k in ("outcome_date", "closed_time", "end_date"):
        v = row.get(k)
        if isinstance(v, str) and v and v.strip().lower() not in ("", "pending", "n/a", "nan", "none"):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
    return None


def load():
    df = A.load(PROC)
    df["ref_price"] = df["prob_7d"].fillna(df["prob_3d"]).fillna(
        df["prob_1d"]).fillna(df["yes_price"])
    return df


# --------------------------------------------------------------------------- #
# Pre-existing figures (now return plotdata)                                   #
# --------------------------------------------------------------------------- #
def fig1_risk_inversion(df):
    resolved = df[df["is_closed"]]
    cats = [c for c in RC_COLORS if c in set(resolved["risk_category"])]
    price, rate, ns = [], [], []
    for c in cats:
        sub = resolved[resolved["risk_category"] == c]
        price.append(round(float(sub["ref_price"].mean()), 6))
        rate.append(round(float(sub["is_yes"].mean()), 6))
        ns.append(int(len(sub)))

    x = range(len(cats))
    w = 0.38
    fig, ax = plt.subplots(figsize=(9, 6.2))
    ax.bar([i - w / 2 for i in x], price, w, label="Mean Yes price charged (~7d out)",
           color="#9467bd")
    ax.bar([i + w / 2 for i in x], rate, w, label="Realized on-time approval rate",
           color="#8c564b")
    ax.axhline(BASE_RATE, ls="--", c="grey", lw=1, label=f"FDA base rate {BASE_RATE:.0%}")
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{c}\n(n={n})" for c, n in zip(cats, ns)], fontsize=9)
    ax.set_ylabel("Probability")
    ax.set_ylim(0, 1.15)
    ax.set_title("What the market charged vs. what actually happened, by risk class")
    ax.legend(fontsize=9, loc="upper right")
    for i, (p, r) in enumerate(zip(price, rate)):
        ax.text(i - w / 2, p + 0.02, f"{p:.2f}", ha="center", fontsize=8)
        ax.text(i + w / 2, r + 0.02, f"{r:.0%}", ha="center", fontsize=8)
    # Caveat banner — this chart's buckets are leakage-contaminated.
    ax.text(0.5, 1.09,
            "⚠ LEAKAGE: 'CMC/manufacturing refile' & 'Clinical/efficacy' include "
            "first-cycle CRLs bucketed FROM the outcome.\nThe 1/8 and 18/18 cells are "
            "look-ahead-contaminated — see fig6/fig7 for the leakage-free version.",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=7.5,
            color="#b30000", style="italic")
    fig.tight_layout()
    return fig, {"cats": cats, "price": price, "rate": rate, "ns": ns}


def fig2_calibration(df):
    r = df[df["is_closed"] & df["prob_1d"].notna()].copy()
    r["outcome"] = r["is_yes"].astype(float)
    bins = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
    r["bucket"] = pd.cut(r["prob_1d"], bins, include_lowest=True)
    g = r.groupby("bucket", observed=True).agg(
        pred=("prob_1d", "mean"), obs=("outcome", "mean"), n=("outcome", "size")).dropna()

    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    ax.plot([0, 1], [0, 1], ls="--", c="grey", label="perfect calibration")
    ax.scatter(g["pred"], g["obs"], s=g["n"] * 40, c="#1f77b4", zorder=3,
               label="market (size ∝ n)")
    for _, row in g.iterrows():
        ax.annotate(f"n={int(row['n'])}", (row["pred"], row["obs"]),
                    textcoords="offset points", xytext=(6, -4), fontsize=8)
    brier = round(float(r["brier_1d"].mean()), 6)
    ax.set_xlabel("Predicted Yes probability (1 day before resolution)")
    ax.set_ylabel("Observed on-time approval frequency")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_title(f"Calibration of the 1-day-out price\nmean Brier = {brier:.3f}  (n={len(r)})")
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    pdata = {"brier": brier, "n": int(len(r)),
             "pred": [round(float(v), 6) for v in g["pred"]],
             "obs": [round(float(v), 6) for v in g["obs"]],
             "bin_n": [int(v) for v in g["n"]]}
    return fig, pdata


def fig3_surprises(df):
    surp = df[df["surprise"].map(_b)]
    fig, ax = plt.subplots(figsize=(9, 5.5))
    plotted, slugs = 0, []
    for _, row in surp.iterrows():
        path = os.path.join(PH_DIR, f"{row['slug']}.csv")
        res_t = _res_unix(row)
        if not os.path.exists(path) or res_t is None:
            continue
        s = pd.read_csv(path)
        s["days"] = (s["t_unix"] - res_t) / DAY
        s = s[s["days"] >= -75]
        label = f"{row['drug'][:34]} → {'YES' if row['is_yes'] else 'NO'}"
        ax.plot(s["days"], s["yes_price"], marker=".", ms=3, label=label)
        plotted += 1
        slugs.append(row["slug"])
    ax.axhline(0.5, ls="--", c="grey", lw=1)
    ax.axvline(0, ls=":", c="black", lw=1)
    ax.set_xlabel("Days before resolution")
    ax.set_ylabel("Yes price")
    ax.set_ylim(0, 1)
    ax.set_title(f"Blindside markets: confident — and wrong — going into the decision (n={plotted})")
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    return fig, {"plotted": plotted, "slugs": sorted(slugs)}


def fig4_open_slate(df):
    o = df[~df["is_closed"] & df["price_vs_baserate"].notna()].copy()
    o = o.sort_values("price_vs_baserate")
    colors = [RC_COLORS.get(c, "#777777") for c in o["risk_category"]]
    labels = [f"{d[:32]}" for d in o["drug"]]
    fig, ax = plt.subplots(figsize=(9, max(4, 0.5 * len(o))))
    ax.barh(range(len(o)), o["price_vs_baserate"], color=colors)
    ax.axvline(0, c="black", lw=1)
    ax.set_yticks(range(len(o)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel(f"Yes price − base rate ({BASE_RATE:.3f})   (negative = priced below history)")
    ax.set_title("Open slate vs. the FDA on-time base rate")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in RC_COLORS.values()]
    ax.legend(handles, RC_COLORS.keys(), fontsize=8, loc="lower right")
    fig.tight_layout()
    return fig, {"drugs": list(o["drug"]),
                 "pvb": [round(float(v), 6) for v in o["price_vs_baserate"]]}


def fig5_depth(df):
    d = df[df["n_top_holders"].notna() & df["top_holder_pct"].notna()].copy()
    so = d["single_order_move"].map(_b)
    fig, ax = plt.subplots(figsize=(8.5, 6))
    ax.scatter(d.loc[~so, "n_top_holders"], d.loc[~so, "top_holder_pct"],
               s=(d.loc[~so, "n_trades"].clip(upper=1000) / 8 + 10),
               c="#1f77b4", alpha=0.6, label="market")
    ax.scatter(d.loc[so, "n_top_holders"], d.loc[so, "top_holder_pct"],
               s=(d.loc[so, "n_trades"].clip(upper=1000) / 8 + 10),
               c="#d62728", alpha=0.85, label="single-order flagged")
    ax.set_xscale("log")
    ax.set_xlabel("Reported top holders (log scale)")
    ax.set_ylabel("Top-holder share of reported holdings")
    ax.set_title("Market thinness (point size ∝ trade count)")
    ax.legend(fontsize=9)
    fig.tight_layout()
    return fig, {"n_points": int(len(d))}


# --------------------------------------------------------------------------- #
# New validity figures (leakage-aware, CI on every rate)                       #
# --------------------------------------------------------------------------- #
def _axis_rates(resolved):
    """Per pre-knowable axis: (label, k, n, point, lo, hi) ordered, plus 'ever'."""
    resolved = resolved.copy()
    resolved["axis"] = resolved.apply(A.preknowable_axis, axis=1)
    order = ["First-cycle (no prior CRL)", "Prior-CRL refile"]
    rows = []
    for ax_name in order:
        sub = resolved[resolved["axis"] == ax_name]
        if not len(sub):
            continue
        k, n = int(sub["is_yes"].sum()), int(len(sub))
        p, lo, hi = A.wilson(k, n)
        ke = int(sub["ever"].sum())
        pe, loe, hie = A.wilson(ke, n)
        rows.append({"axis": ax_name, "k": k, "n": n, "p": round(p, 6),
                     "lo": round(lo, 6), "hi": round(hi, 6),
                     "ke": ke, "pe": round(pe, 6), "loe": round(loe, 6),
                     "hie": round(hie, 6)})
    return rows


def fig6_leakage_free_gradient(df):
    resolved = df[df["is_closed"]]
    rows = _axis_rates(resolved)
    labels = [f"{r['axis']}\n(n={r['n']})" + ("  ⚠anec" if r["n"] < A.ANECDOTAL_N else "")
              for r in rows]
    pts = [r["p"] for r in rows]
    err = [[r["p"] - r["lo"] for r in rows], [r["hi"] - r["p"] for r in rows]]
    colors = [AXIS_COLORS.get(r["axis"], "#777") for r in rows]
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    x = range(len(rows))
    ax.bar(x, pts, color=colors, alpha=0.85)
    ax.errorbar(x, pts, yerr=err, fmt="none", ecolor="black", capsize=6, lw=1.4)
    ax.axhline(BASE_RATE, ls="--", c="grey", lw=1, label=f"FDA base rate {BASE_RATE:.0%}")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("On-time approval rate (Wilson 95% CI)")
    ax.set_ylim(0, 1.05)
    ax.set_title("Leakage-free risk gradient\n(buckets from PRE-DECISION fields only — prior_crl + structure)")
    for i, r in enumerate(rows):
        ax.text(i, r["hi"] + 0.02, f"{r['k']}/{r['n']}", ha="center", fontsize=9)
    ax.legend(fontsize=9)
    fig.tight_layout()
    return fig, {"rows": rows}


def fig7_leakage_artifact(df):
    """The refile claim, contaminated vs leakage-free, side by side."""
    resolved = df[df["is_closed"]]
    cmc = resolved[resolved["risk_category"] == "CMC/manufacturing refile"]
    k_c, n_c = int(cmc["is_yes"].sum()), int(len(cmc))            # 1/8 contaminated
    gen = resolved[resolved["prior_crl"].astype(str).str.lower() == "yes"]
    k_g, n_g = int(gen["is_yes"].sum()), int(len(gen))           # 1/3 leakage-free
    items = [("README headline\n'CMC refile' bucket", k_c, n_c, "#d62728"),
             ("Leakage-free\nprior_crl=yes refiles", k_g, n_g, "#1f77b4")]
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    rows = []
    for i, (lab, k, n, c) in enumerate(items):
        p, lo, hi = A.wilson(k, n)
        ax.bar(i, p, color=c, alpha=0.85)
        ax.errorbar(i, p, yerr=[[p - lo], [hi - p]], fmt="none", ecolor="black",
                    capsize=7, lw=1.5)
        ax.text(i, hi + 0.03, f"{k}/{n} = {p:.0%}", ha="center", fontsize=10)
        rows.append({"label": lab.replace("\n", " "), "k": k, "n": n,
                     "p": round(p, 6), "lo": round(lo, 6), "hi": round(hi, 6)})
    ax.set_xticks([0, 1])
    ax.set_xticklabels([it[0] for it in items], fontsize=9)
    ax.set_ylabel("On-time approval rate (Wilson 95% CI)")
    ax.set_ylim(0, 1.05)
    ax.set_title("How much of '12.5%' is look-ahead bias?\n5 of the 8 'refiles' are "
                 "first-cycle CRLs bucketed FROM the outcome")
    fig.tight_layout()
    return fig, {"rows": rows}


def fig8_bydate_vs_ever(df):
    resolved = df[df["is_closed"]]
    rows = _axis_rates(resolved)
    x = range(len(rows))
    w = 0.38
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    ax.bar([i - w / 2 for i in x], [r["p"] for r in rows], w,
           color="#8c564b", label="Approved ON TIME (resolved Yes)")
    ax.bar([i + w / 2 for i in x], [r["pe"] for r in rows], w,
           color="#2ca02c", alpha=0.7, label="Approved EVER (incl. later)")
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{r['axis']}\n(n={r['n']})" for r in rows], fontsize=9)
    ax.set_ylabel("Approval rate")
    ax.set_ylim(0, 1.1)
    for i, r in enumerate(rows):
        ax.text(i - w / 2, r["p"] + 0.02, f"{r['k']}/{r['n']}", ha="center", fontsize=8)
        ax.text(i + w / 2, r["pe"] + 0.02, f"{r['ke']}/{r['n']}", ha="center", fontsize=8)
    ax.set_title("'Resolved No' ≠ 'rejected': on-time vs ever-approved, by pre-knowable axis")
    ax.legend(fontsize=9)
    fig.tight_layout()
    return fig, {"rows": rows}


def fig9_residual_vs_price(df):
    """Outcome − price charged 7d out. Tests whether the risk was already priced.

    A negative bar = the market charged MORE than the outcome delivered (it
    already 'knew'); positive = the market under-charged (potential edge). Alpha
    requires a SYSTEMATIC sign per cohort, not noise. n is tiny — descriptive.
    """
    resolved = df[df["is_closed"] & df["prob_7d"].notna()].copy()
    resolved["axis"] = resolved.apply(A.preknowable_axis, axis=1)
    resolved["resid"] = resolved["is_yes"].astype(float) - resolved["prob_7d"]
    resolved = resolved.sort_values("resid")
    colors = [AXIS_COLORS.get(a, "#777") for a in resolved["axis"]]
    fig, ax = plt.subplots(figsize=(9, max(4, 0.42 * len(resolved))))
    ax.barh(range(len(resolved)), resolved["resid"], color=colors)
    ax.axvline(0, c="black", lw=1)
    ax.set_yticks(range(len(resolved)))
    ax.set_yticklabels([d[:30] for d in resolved["drug"]], fontsize=7.5)
    ax.set_xlabel("outcome (1/0) − Yes price 7d out   (>0: market under-charged · <0: over-charged)")
    ax.set_title("Was the risk already priced? Residual vs the ~7-day price\n"
                 "(per-cohort mean must be systematic to be alpha — see annotation)")
    means = {}
    for a in AXIS_COLORS:
        sub = resolved[resolved["axis"] == a]
        if len(sub):
            means[a] = round(float(sub["resid"].mean()), 4)
    txt = " · ".join(f"{a.split()[0]} mean={m:+.2f} (n={int((resolved['axis']==a).sum())})"
                     for a, m in means.items())
    ax.text(0.5, -0.13, txt, transform=ax.transAxes, ha="center", fontsize=8, color="#333")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in AXIS_COLORS.values()]
    ax.legend(handles, AXIS_COLORS.keys(), fontsize=8, loc="lower right")
    fig.tight_layout()
    return fig, {"means": means,
                 "resid": {r["slug"]: round(float(r["is_yes"]) - float(r["prob_7d"]), 6)
                           for _, r in resolved.iterrows()}}


# --------------------------------------------------------------------------- #
# Benchmark figures (Q1-Q4): the crowd vs a pre-registered FDA base rate        #
# --------------------------------------------------------------------------- #
def fig10_accuracy(df):
    """Q1: was the crowd's majority-side call correct at 7d / 1d? (Red-Tilt-style)"""
    r = df[df["is_closed"]]
    cells = []
    for col, lab in [("correct_7d", "7 days out"), ("correct_1d", "1 day out")]:
        s = r[r[col].astype(str).str.lower().isin(["true", "false"])]
        k = int((s[col].astype(str).str.lower() == "true").sum())
        n = int(len(s))
        p, lo, hi = A.wilson(k, n)
        cells.append({"label": lab, "k": k, "n": n, "p": round(p, 6),
                      "lo": round(lo, 6), "hi": round(hi, 6)})
    fig, ax = plt.subplots(figsize=(7, 5))
    x = range(len(cells))
    ax.bar(x, [c["p"] for c in cells], color="#1f77b4", alpha=0.85)
    ax.errorbar(x, [c["p"] for c in cells],
                yerr=[[c["p"] - c["lo"] for c in cells], [c["hi"] - c["p"] for c in cells]],
                fmt="none", ecolor="black", capsize=7, lw=1.4)
    ax.axhline(0.5, ls="--", c="grey", lw=1, label="coin flip")
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{c['label']}\n(n={c['n']})" for c in cells])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Share of markets the crowd called correctly (Wilson 95% CI)")
    ax.set_title("Were the FDA markets right? Majority-side accuracy before resolution")
    for i, c in enumerate(cells):
        ax.text(i, c["hi"] + 0.02, f"{c['k']}/{c['n']}", ha="center", fontsize=9)
    ax.legend(fontsize=9)
    fig.tight_layout()
    return fig, {"cells": cells}


def fig11_outcome_decomp(df):
    """Q3/Q6: how the resolved markets actually resolved — 'No' is CRL vs Delay."""
    r = df[df["is_closed"]]
    counts = {}
    counts["Approved (Yes)"] = int(r["is_yes"].sum())
    for o in ["CRL", "Delay", "Withdrawn"]:
        counts[f"No: {o}"] = int((r["outcome"] == o).sum())
    labels = list(counts.keys())
    vals = [counts[k] for k in labels]
    colors = ["#2ca02c", "#d62728", "#ff7f0e", "#7f7f7f"]
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.bar(labels, vals, color=colors[:len(labels)])
    for i, v in enumerate(vals):
        ax.text(i, v + 0.15, str(v), ha="center", fontsize=10)
    ax.set_ylabel("Markets")
    ax.set_title("'Resolved No' ≠ 'rejected': "
                 f"{counts['No: Delay']} of {sum(vals)-counts['Approved (Yes)']} Nos were timing Delays, not CRLs")
    fig.tight_layout()
    return fig, {"counts": counts}


def fig12_edge_map(df):
    """Q2/Q4: open slate — benchmark fair value vs live price, gated by depth."""
    import edge
    op = edge.score_open(df, _bm_params())
    op = op[op["fair_price"] != "N/A"].copy()
    op["fair_price"] = op["fair_price"].astype(float)
    op["market_price"] = op["market_price"].astype(float)
    fig, ax = plt.subplots(figsize=(7.5, 7))
    ax.plot([0, 1], [0, 1], ls="--", c="grey", label="fair = market")
    for ok, color, lab in [(True, "#1f77b4", "tradeable depth"),
                           (False, "#d62728", "too thin")]:
        s = op[op["depth_ok"] == ok]
        ax.scatter(s["market_price"], s["fair_price"], c=color, s=80, alpha=0.8, label=lab)
    for _, r in op.iterrows():
        ax.annotate(str(r["drug"])[:18], (r["market_price"], r["fair_price"]),
                    textcoords="offset points", xytext=(5, 3), fontsize=7)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel("Market price (Yes)")
    ax.set_ylabel("Benchmark fair value (cited base rate)")
    ax.set_title("Open slate vs a transparent base rate\n(above line = base rate higher than crowd; below = crowd richer)")
    ax.legend(fontsize=9, loc="lower right")
    fig.tight_layout()
    pdata = {"points": [{"slug": r["slug"], "market": round(float(r["market_price"]), 4),
                         "fair": round(float(r["fair_price"]), 4), "depth_ok": bool(r["depth_ok"])}
                        for _, r in op.iterrows()]}
    return fig, pdata


def fig13_benchmark_vs_market(df):
    """Q2: did the cited base rate beat the crowd out-of-sample? (Brier)"""
    import edge
    bt, summary = edge.backtest_resolved(df, _bm_params())
    fig, ax = plt.subplots(figsize=(7.5, 6))
    paired = bt[bt["market_price"].notna()]
    sc = ax.scatter(paired["market_price"], paired["fair_price"],
                    c=paired["realized"], cmap="RdYlGn", vmin=0, vmax=1,
                    s=70, edgecolor="k", linewidth=0.4)
    ax.plot([0, 1], [0, 1], ls="--", c="grey")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel("Crowd price (~7d out)")
    ax.set_ylabel("Benchmark fair value")
    ax.set_title("Crowd vs base rate (color = realized: green=Yes, red=No)\n"
                 f"Brier: crowd {summary['market_brier_mean']} vs benchmark "
                 f"{summary['benchmark_brier_mean_paired']}  — "
                 f"benchmark beat crowd {summary['benchmark_beats_market']}/{summary['paired_decisive']} "
                 f"(p={summary['sign_test_p']})")
    fig.colorbar(sc, ax=ax, label="realized outcome")
    fig.tight_layout()
    return fig, {"summary": summary}


_BM_PARAMS_CACHE = {}


def _bm_params():
    if "p" not in _BM_PARAMS_CACHE:
        import benchmark
        _BM_PARAMS_CACHE["p"] = benchmark.load_params()
    return _BM_PARAMS_CACHE["p"]


FIGURES = {
    "fig1_risk_inversion.png": fig1_risk_inversion,
    "fig2_calibration.png": fig2_calibration,
    "fig3_surprises.png": fig3_surprises,
    "fig4_open_slate.png": fig4_open_slate,
    "fig5_depth.png": fig5_depth,
    "fig6_leakage_free_gradient.png": fig6_leakage_free_gradient,
    "fig7_leakage_artifact.png": fig7_leakage_artifact,
    "fig8_bydate_vs_ever.png": fig8_bydate_vs_ever,
    "fig9_residual_vs_price.png": fig9_residual_vs_price,
    "fig10_accuracy.png": fig10_accuracy,
    "fig11_outcome_decomp.png": fig11_outcome_decomp,
    "fig12_edge_map.png": fig12_edge_map,
    "fig13_benchmark_vs_market.png": fig13_benchmark_vs_market,
}


def build_all(df=None):
    """Return {name: plotdata} for every figure, generating PNGs to OUT_DIR.

    Importable so audit.py can request the exact plotted aggregations.
    """
    if df is None:
        df = load()
    os.makedirs(OUT_DIR, exist_ok=True)
    out = {}
    for name, fn in FIGURES.items():
        try:
            fig, pdata = fn(df)
            fig.savefig(os.path.join(OUT_DIR, name), dpi=140)
            plt.close(fig)
            out[name] = pdata
        except Exception as e:  # one bad figure shouldn't kill the rest
            out[name] = {"error": str(e)}
            print(f"  SKIPPED {name}: {e}")
    return out


def main():
    out = build_all()
    for name in FIGURES:
        status = "ERROR" if "error" in out.get(name, {}) else "ok"
        print(f"  [{status}] {OUT_DIR}/{name}")
    print(f"Done — {len(FIGURES)} figures in {OUT_DIR}/")


if __name__ == "__main__":
    main()
