"""
make_figures.py — generate the analysis figures from the processed dataset.

Reads fda_markets_processed.csv (+ the per-market series in price_history/) and
writes PNGs to figures/. Run after process_markets.py:

    python make_figures.py

Figures:
    fig1_risk_inversion.png   price the market charged vs realized on-time
                              approval rate, per risk_category (the thesis)
    fig2_calibration.png      reliability curve: predicted prob_1d vs observed
                              approval frequency (+ mean Brier)
    fig3_surprises.png        Yes-price trajectories of the blindside markets,
                              aligned to days-before-resolution
    fig4_open_slate.png       open markets' price vs the 0.835 base rate
    fig5_depth.png            market thinness: top-holder concentration vs
                              holder count, single-order moves highlighted
"""

import os
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")  # headless — write files, no display
import matplotlib.pyplot as plt
import pandas as pd

PROC = "fda_markets_processed.csv"
PH_DIR = "price_history"
OUT_DIR = "figures"
BASE_RATE = 0.835
THEMATIC = {"fda-approves-a-psychedelic-for-medical-use-in-2026"}
DAY = 86400

# Stable colors per risk category.
RC_COLORS = {
    "Clean desk review": "#2ca02c",
    "Oncology sNDA": "#1f77b4",
    "CMC/manufacturing refile": "#d62728",
    "Timeline bet": "#ff7f0e",
}


def _b(x):
    return str(x).strip().lower() == "true"


def _res_unix(row):
    for k in ("closed_time", "end_date"):
        v = row.get(k)
        if isinstance(v, str) and v:
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
    return None


def load():
    df = pd.read_csv(PROC)
    df = df[~df["slug"].isin(THEMATIC)].copy()
    df["is_closed"] = df["closed"].map(_b)
    df["is_yes"] = df["resolved_yes"].map(_b)
    for c in ("prob_7d", "prob_3d", "prob_1d", "yes_price", "price_vs_baserate",
              "n_trades", "n_top_holders", "top_holder_pct", "brier_1d"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Reference price the market "charged": ~7d out for resolved, else current Yes.
    df["ref_price"] = df["prob_7d"].fillna(df["prob_3d"]).fillna(
        df["prob_1d"]).fillna(df["yes_price"])
    return df


def fig1_risk_inversion(df):
    resolved = df[df["is_closed"]]
    cats = [c for c in RC_COLORS if c in set(resolved["risk_category"])]
    price, rate, ns = [], [], []
    for c in cats:
        sub = resolved[resolved["risk_category"] == c]
        price.append(sub["ref_price"].mean())
        rate.append(sub["is_yes"].mean())
        ns.append(len(sub))

    x = range(len(cats))
    w = 0.38
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.bar([i - w / 2 for i in x], price, w, label="Mean Yes price charged (~7d out)",
           color="#9467bd")
    ax.bar([i + w / 2 for i in x], rate, w, label="Realized on-time approval rate",
           color="#8c564b")
    ax.axhline(BASE_RATE, ls="--", c="grey", lw=1, label=f"FDA base rate {BASE_RATE:.0%}")
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{c}\n(n={n})" for c, n in zip(cats, ns)], fontsize=9)
    ax.set_ylabel("Probability")
    ax.set_ylim(0, 1.05)
    ax.set_title("What the market charged vs. what actually happened, by risk class")
    ax.legend(fontsize=9)
    for i, (p, r) in enumerate(zip(price, rate)):
        ax.text(i - w / 2, p + 0.02, f"{p:.2f}", ha="center", fontsize=8)
        ax.text(i + w / 2, r + 0.02, f"{r:.0%}", ha="center", fontsize=8)
    fig.tight_layout()
    return fig


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
    brier = r["brier_1d"].mean()
    ax.set_xlabel("Predicted Yes probability (1 day before resolution)")
    ax.set_ylabel("Observed on-time approval frequency")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_title(f"Calibration of the 1-day-out price\nmean Brier = {brier:.3f}  (n={len(r)})")
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    return fig


def fig3_surprises(df):
    surp = df[df["surprise"].map(_b)]
    fig, ax = plt.subplots(figsize=(9, 5.5))
    plotted = 0
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
    ax.axhline(0.5, ls="--", c="grey", lw=1)
    ax.axvline(0, ls=":", c="black", lw=1)
    ax.set_xlabel("Days before resolution")
    ax.set_ylabel("Yes price")
    ax.set_ylim(0, 1)
    ax.set_title(f"Blindside markets: confident — and wrong — going into the decision (n={plotted})")
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    return fig


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
    return fig


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
    return fig


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    df = load()
    figs = {
        "fig1_risk_inversion.png": fig1_risk_inversion,
        "fig2_calibration.png": fig2_calibration,
        "fig3_surprises.png": fig3_surprises,
        "fig4_open_slate.png": fig4_open_slate,
        "fig5_depth.png": fig5_depth,
    }
    for name, fn in figs.items():
        try:
            fig = fn(df)
            fig.savefig(os.path.join(OUT_DIR, name), dpi=140)
            plt.close(fig)
            print(f"  wrote {OUT_DIR}/{name}")
        except Exception as e:  # one bad figure shouldn't kill the rest
            print(f"  SKIPPED {name}: {e}")
    print(f"Done — {len(figs)} figures in {OUT_DIR}/")


if __name__ == "__main__":
    main()
