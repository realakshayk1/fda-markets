"""
edge.py — compare the pre-registered benchmark to crowd prices.

Two outputs, both deterministic:

  backtest_resolved()  — for resolved markets, the benchmark's fair value vs the
      crowd's ~7d price vs the realized outcome. Because the benchmark
      coefficients come from FDA *population* data (not these 33 markets), this is
      a genuine OUT-OF-SAMPLE test of "does a transparent base rate beat the
      crowd?" Reports benchmark Brier, market Brier, and the paired difference
      with a sign-test p and n. NO claim that the benchmark IS better — it
      reports whichever way the number falls.

  score_open()         — for open markets, fair value vs live price, the gap, and
      LIQUIDITY tags, written to edge_open.csv. `depth_ok` gates any apparent edge
      that the book is too thin to trade.

    python edge.py            # prints the backtest summary, writes edge_open.csv

Uses analysis_lib for the cohort load + Wilson CIs; benchmark for fair value.
"""

import csv
import math

import pandas as pd

import analysis_lib as A
from benchmark import load_params, fair_value

EDGE_OPEN_CSV = "edge_open.csv"
# Liquidity gate (tunable): a market is "tradeable" if it isn't dominated by one
# holder and has some trade history. Thresholds are conservative and documented.
DEPTH_TOP_HOLDER_MAX = 0.50
DEPTH_MIN_TRADES = 30


def _fair_row(row, params):
    fv = fair_value(row, params)
    return fv


def backtest_resolved(df, params):
    res = df[df["is_closed"]].copy()
    rows = []
    for _, r in res.iterrows():
        fv = _fair_row(r, params)
        if fv.fair_price is None:        # benchmark abstained (open-ended market)
            continue
        price7 = r.get("prob_7d")
        price = price7 if pd.notna(price7) else r.get("prob_1d")
        if pd.isna(price):
            price = r.get("yes_price")
        realized = 1.0 if r["is_yes"] else 0.0
        rows.append({
            "slug": r["slug"], "drug": r["drug"],
            "fair_price": fv.fair_price, "market_price": None if pd.isna(price) else round(float(price), 4),
            "realized": realized,
            "benchmark_brier": round((fv.fair_price - realized) ** 2, 4),
            "market_brier": None if pd.isna(price) else round((float(price) - realized) ** 2, 4),
        })
    bt = pd.DataFrame(rows)
    paired = bt[bt["market_price"].notna()].copy()
    out = {
        "n_resolved": int(len(bt)),
        "n_paired": int(len(paired)),
        "benchmark_brier_mean": round(float(bt["benchmark_brier"].mean()), 4),
        "market_brier_mean": round(float(paired["market_brier"].mean()), 4),
        "benchmark_brier_mean_paired": round(float(paired["benchmark_brier"].mean()), 4),
    }
    # Paired sign test: how often does the benchmark have LOWER Brier than market?
    wins = int((paired["benchmark_brier"] < paired["market_brier"]).sum())
    nptot = int((paired["benchmark_brier"] != paired["market_brier"]).sum())
    out["benchmark_beats_market"] = wins
    out["paired_decisive"] = nptot
    p, lo, hi = A.wilson(wins, nptot)
    out["benchmark_win_rate"] = round(p, 4) if nptot else None
    out["benchmark_win_ci"] = [round(lo, 4), round(hi, 4)] if nptot else None
    out["sign_test_p"] = round(_two_sided_sign_p(wins, nptot), 4) if nptot else None
    return bt, out


def _two_sided_sign_p(k, n):
    """Exact two-sided binomial sign test at p=0.5 (no SciPy dependency)."""
    if n == 0:
        return 1.0
    from math import comb
    def tail(x):
        return sum(comb(n, i) for i in range(0, x + 1)) / (2 ** n)
    k2 = min(k, n - k)
    return min(1.0, 2 * tail(k2))


def _depth_ok(row):
    thp = row.get("top_holder_pct")
    ntr = row.get("n_trades")
    thp_ok = pd.isna(thp) or float(thp) <= DEPTH_TOP_HOLDER_MAX
    ntr_ok = pd.notna(ntr) and float(ntr) >= DEPTH_MIN_TRADES
    return bool(thp_ok and ntr_ok)


def score_open(df, params):
    op = df[~df["is_closed"]].copy()
    rows, abstained = [], []
    for _, r in op.iterrows():
        fv = _fair_row(r, params)
        price = r.get("yes_price")
        if pd.isna(price):
            continue
        if fv.fair_price is None:        # benchmark abstained — list separately, no false gap
            abstained.append({"slug": r["slug"], "drug": r["drug"],
                              "market_price": round(float(price), 4), "fair_price": "N/A",
                              "p_ever": fv.p_ever, "p_on_time": "N/A",
                              "gap_fair_minus_market": "N/A", "abs_gap": -1.0,
                              "direction": "benchmark N/A (open-ended year market)",
                              "top_holder_pct": None if pd.isna(r.get("top_holder_pct")) else round(float(r["top_holder_pct"]), 4),
                              "n_trades": None if pd.isna(r.get("n_trades")) else int(float(r["n_trades"])),
                              "depth_ok": _depth_ok(r), "rationale": fv.rationale})
            continue
        gap = round(fv.fair_price - float(price), 4)
        rows.append({
            "slug": r["slug"], "drug": r["drug"],
            "market_price": round(float(price), 4),
            "fair_price": fv.fair_price,
            "p_ever": fv.p_ever, "p_on_time": fv.p_on_time,
            "gap_fair_minus_market": gap,
            "abs_gap": abs(gap),
            "direction": "market RICH vs base rate" if gap < 0 else "market CHEAP vs base rate",
            "top_holder_pct": None if pd.isna(r.get("top_holder_pct")) else round(float(r["top_holder_pct"]), 4),
            "n_trades": None if pd.isna(r.get("n_trades")) else int(float(r["n_trades"])),
            "depth_ok": _depth_ok(r),
            "rationale": fv.rationale,
        })
    out = pd.DataFrame(rows + abstained).sort_values("abs_gap", ascending=False)
    return out


def main():
    df = A.load()
    params = load_params()

    bt, summary = backtest_resolved(df, params)
    print("== Benchmark vs crowd — out-of-sample backtest (resolved markets) ==")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("\n  Interpretation: lower Brier = better. benchmark_win_rate is how often")
    print("  the transparent base rate beat the crowd, with a Wilson CI + sign-test p.")
    print("  Do NOT read a win rate whose CI spans 0.5 as evidence of edge.")

    op = score_open(df, params)
    op.to_csv(EDGE_OPEN_CSV, index=False)
    print(f"\n== Open slate scored -> {EDGE_OPEN_CSV} ({len(op)} markets) ==")
    show = op[["drug", "market_price", "fair_price", "gap_fair_minus_market",
               "depth_ok", "direction"]]
    with pd.option_context("display.max_rows", None, "display.width", 200,
                           "display.max_colwidth", 36):
        print(show.to_string(index=False))
    print("\n  NOTE: every gap is vs a transparent reference line, not truth, and")
    print("  depth_ok=False means the book is too thin to trade the gap. n is tiny;")
    print("  treat each as a hypothesis with the rationale shown in edge_open.csv.")


if __name__ == "__main__":
    main()
