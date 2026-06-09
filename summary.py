"""
summary.py — prints the analysis summary from fda_markets_processed.csv:
counts, on-time approval rate, mean Brier, the CMC-refile vs clean-desk price
inversion, surprise markets, and the open-slate price-vs-baserate comparison.

Usage: python summary.py
"""

import pandas as pd

BASE_RATE = 0.835
# Thematic market that resolved on a substance-list technicality — kept OUT of
# the drug-by-drug base rate (logged as a resolution-criteria example instead).
THEMATIC = {"fda-approves-a-psychedelic-for-medical-use-in-2026"}


def b(x):
    return str(x).strip().lower() == "true"


def main():
    df = pd.read_csv("fda_markets_processed.csv")
    df["is_closed"] = df["closed"].map(b)
    df["is_yes"] = df["resolved_yes"].map(b)

    drug = df[~df["slug"].isin(THEMATIC)]
    resolved = drug[drug["is_closed"]].copy()
    open_m = drug[~drug["is_closed"]].copy()

    print("=" * 64)
    print("FDA DRUG-APPROVAL PREDICTION MARKETS — SUMMARY")
    print("=" * 64)
    print(f"Total markets:            {len(df)}  (drug-specific: {len(drug)}, "
          f"thematic excluded: {len(THEMATIC)})")
    print(f"  Open (unresolved):      {len(open_m)}")
    print(f"  Resolved:               {len(resolved)}")

    # On-time approval rate (resolved Yes = approved by the market date).
    n_yes = int(resolved["is_yes"].sum())
    rate = n_yes / len(resolved) if len(resolved) else float("nan")
    print(f"\nON-TIME APPROVAL RATE:    {n_yes}/{len(resolved)} = {rate:.1%}")
    print(f"  (historical base rate assumed ~80-87%, midpoint {BASE_RATE:.0%})")

    # Decompose the 'No' outcomes.
    no = resolved[~resolved["is_yes"]]
    print(f"\nResolved NO breakdown ({len(no)}):")
    print(no["outcome"].value_counts().to_string())

    # Eventual-approval tracking (approved at all, even if late).
    print("\nEventually approved (incl. later than market date):")
    print(resolved["eventually_approved"].value_counts().to_string())

    # Calibration.
    mb = resolved["brier_1d"].dropna()
    print(f"\nMEAN BRIER (1-day-out, n={len(mb)}): {mb.mean():.4f}")
    for k in ("correct_7d", "correct_1d"):
        s = resolved[k].map(b)
        valid = resolved[k].notna()
        print(f"  {k}: {int(s[valid].sum())}/{int(valid.sum())} correct")

    # CMC-vs-clean PRICE INVERSION (the thesis). Use price 7d-out for resolved,
    # current Yes price for open — i.e. what the market charged for each risk class.
    df2 = drug.copy()
    df2["ref_price"] = df2.apply(
        lambda r: r["prob_7d"] if r["is_closed"] and pd.notna(r["prob_7d"])
        else r["yes_price"], axis=1)
    print("\nPRICE BY RISK CATEGORY (mean Yes price the market charged):")
    g = df2.groupby("risk_category")["ref_price"].agg(["mean", "count"])
    for cat, row in g.iterrows():
        print(f"  {cat:28s} {row['mean']:.3f}  (n={int(row['count'])})")
    try:
        cmc = g.loc["CMC/manufacturing refile", "mean"]
        clean = g.loc["Clean desk review", "mean"]
        print(f"\n  INVERSION: CMC/manufacturing refiles priced {cmc:.3f} vs "
              f"clean desk reviews {clean:.3f}  (gap {clean - cmc:+.3f})")
    except KeyError:
        pass

    # On-time rate by risk category (does the discount match reality?).
    print("\nON-TIME APPROVAL RATE BY RISK CATEGORY (resolved only):")
    for cat, sub in resolved.groupby("risk_category"):
        y = int(sub["is_yes"].sum())
        print(f"  {cat:28s} {y}/{len(sub)} = {y/len(sub):.0%}")

    # Surprises.
    surp = drug[drug["surprise"].map(b)]
    print(f"\nSURPRISE / BLINDSIDE markets ({len(surp)}):")
    for _, r in surp.iterrows():
        print(f"  - {r['drug']}: prob_1d={r['prob_1d']}, resolved "
              f"{'YES' if r['is_yes'] else 'NO'} ({r['outcome']}), brier={r['brier_1d']}")

    so = drug[drug["single_order_move"].map(b)]
    if len(so):
        print(f"\nSingle-order (thin-market) moves, confirmed vs /trades ({len(so)}):")
        for _, r in so.iterrows():
            print(f"  - {r['drug']}: {r['single_order_jump']:+} jump @ "
                  f"{r['single_order_date']} | largest taker trade = {r['largest_trade_size']}")

    # Market depth / thinness (collected for every market from /trades+/holders).
    if "n_top_holders" in drug.columns:
        d = drug.copy()
        for c in ("n_trades", "n_top_holders", "top_holder_pct", "largest_trade_size"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        thin = d.sort_values(["n_top_holders", "n_trades"]).head(5)
        print("\nTHINNEST markets (fewest holders — single-order risk is highest here):")
        for _, r in thin.iterrows():
            print(f"  {r['n_top_holders']:>4.0f} holders, {r['n_trades']:>4.0f} trades, "
                  f"top-holder {r['top_holder_pct']:.0%}, max trade {r['largest_trade_size']:.0f}"
                  f"  | {r['drug']}")

    # Open slate vs base rate.
    print("\nOPEN SLATE — price vs base rate (neg = priced below history):")
    om = open_m.sort_values("price_vs_baserate")
    for _, r in om.iterrows():
        pv = r["price_vs_baserate"]
        pv = f"{pv:+.3f}" if pd.notna(pv) else "  n/a"
        print(f"  {pv}  Yes={r['yes_price']:<6}  [{r['risk_category']}]  {r['drug']}")


if __name__ == "__main__":
    main()
