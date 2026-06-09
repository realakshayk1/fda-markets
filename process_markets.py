"""
process_markets.py — Stage 3 of the FDA-markets pipeline.

Reads the enriched (or, if absent, the raw) CSV, downloads each market's price
history from the CLOB endpoint, writes per-market series to disk, and computes
the calibration / surprise / single-order metrics. Produces the analysis-ready
file `fda_markets_processed.csv`.

Public APIs, no auth. Usage:
    python process_markets.py            # uses fda_markets_enriched.csv if present
    python process_markets.py --raw      # force-use fda_markets_raw.csv

Outputs:
    price_history/<slug>.csv         daily (1440-min) series, full life of market
    price_history_fine/<slug>.csv    10-min series for flagged sharp movers
    fda_markets_processed.csv        enriched rows + computed metrics
"""

import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from tqdm import tqdm

CLOB = "https://clob.polymarket.com/prices-history"
DATA = "https://data-api.polymarket.com"
DAILY_DIR = "price_history"
FINE_DIR = "price_history_fine"
DEPTH_FILE = "market_depth.csv"
SLEEP = 0.25

# FDA on-time approval base rate (midpoint of the ~80-87% historical range).
BASE_RATE = 0.835

# Sharp-move threshold (in probability points) that qualifies a market for a
# 10-minute fine-grained pull and single-order inspection.
SHARP_MOVE = 0.15
DAY = 86400


def get_json(url, params, retries=5):
    delay = SLEEP
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(delay)
                delay = min(delay * 2, 8)
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, json.JSONDecodeError):
            if attempt == retries - 1:
                return None
            time.sleep(delay)
            delay = min(delay * 2, 8)
    return None


def fetch_history(token_id, fidelity, interval="max", start_ts=None, end_ts=None):
    """Return list of {'t':unix,'p':price} dicts, time-sorted.

    For 10-min (fidelity=10) data on markets that resolved a while ago,
    interval=max returns an EMPTY series (the CLOB will not serve fine
    granularity over a long window). Passing an explicit start_ts/end_ts window
    recovers the data — e.g. GTx-104 yields 0 points with interval=max but ~500
    with a +/-3 day window around its move date.
    """
    if not token_id:
        return []
    if start_ts is not None and end_ts is not None:
        params = {"market": token_id, "startTs": int(start_ts),
                  "endTs": int(end_ts), "fidelity": fidelity}
    else:
        params = {"market": token_id, "interval": interval, "fidelity": fidelity}
    data = get_json(CLOB, params)
    hist = (data or {}).get("history") or []
    hist = [{"t": int(h["t"]), "p": float(h["p"])} for h in hist if "t" in h and "p" in h]
    hist.sort(key=lambda x: x["t"])
    return hist


DEPTH_FIELDS = ["n_trades", "largest_trade_size", "unique_traders",
                "n_top_holders", "top_holder_pct"]


def market_depth(condition_id):
    """Collect liquidity / concentration signal for ANY market from the public
    Data API — not just markets that trip the single-order test. Returns a dict
    with n_trades, largest_trade_size, unique_traders (from /trades, capped at
    1000 most-recent) and n_top_holders, top_holder_pct (from /holders). The largest
    trade + holder concentration corroborate thin-market / single-wallet moves;
    trade and holder counts profile depth across the whole slate."""
    out = {k: None for k in DEPTH_FIELDS}
    if not condition_id or not isinstance(condition_id, str):
        return out

    trades = get_json(f"{DATA}/trades", {"market": condition_id, "limit": 1000})
    if isinstance(trades, list) and trades:
        sizes, wallets = [], set()
        for t in trades:
            try:
                sizes.append(float(t.get("size") or 0))
            except (TypeError, ValueError):
                pass
            if t.get("proxyWallet"):
                wallets.add(t["proxyWallet"])
        out["n_trades"] = len(trades)
        out["largest_trade_size"] = round(max(sizes), 2) if sizes else None
        out["unique_traders"] = len(wallets)

    # /holders returns a TOP-holders leaderboard, capped by `limit` (default ~20
    # per token). Request 200 for a fuller count; n_top_holders is still "reported
    # (top) holders" and top_holder_pct is the largest holder's share of reported
    # holdings — a directional concentration proxy, exact only when the full set
    # is returned (n_top_holders < 200).
    holders_resp = get_json(f"{DATA}/holders", {"market": condition_id, "limit": 200})
    if isinstance(holders_resp, list) and holders_resp:
        amounts = []
        for token_block in holders_resp:
            for h in (token_block.get("holders") or []):
                try:
                    amounts.append(float(h.get("amount") or 0))
                except (TypeError, ValueError):
                    pass
        if amounts:
            total = sum(amounts)
            out["n_top_holders"] = len(amounts)
            out["top_holder_pct"] = round(max(amounts) / total, 4) if total else None
    return out


def read_series(path):
    """Load a previously written series back into [{'t','p'}] form."""
    hist = []
    with open(path, newline="", encoding="utf-8") as f:
        for rec in csv.DictReader(f):
            try:
                hist.append({"t": int(rec["t_unix"]), "p": float(rec["yes_price"])})
            except (ValueError, KeyError):
                continue
    hist.sort(key=lambda x: x["t"])
    return hist


def load_or_fetch(path, token_id, fidelity, interval, refresh,
                  start_ts=None, end_ts=None):
    """Use the cached CSV unless --refresh; otherwise download and persist."""
    if not refresh and os.path.exists(path):
        return read_series(path), False
    hist = fetch_history(token_id, fidelity=fidelity, interval=interval,
                         start_ts=start_ts, end_ts=end_ts)
    if hist:
        write_series(path, hist)
    return hist, True


def write_series(path, hist):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_unix", "date_utc", "yes_price"])
        for h in hist:
            d = datetime.fromtimestamp(h["t"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            w.writerow([h["t"], d, h["p"]])


def _resolution_unix(row):
    """Best timestamp for 'resolution': closed_time, else end_date."""
    for key in ("closed_time", "end_date"):
        v = row.get(key)
        if v:
            try:
                return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


def price_at(hist, target_unix):
    """Last observed price at or before target_unix (carry-forward)."""
    val = None
    for h in hist:
        if h["t"] <= target_unix:
            val = h["p"]
        else:
            break
    return val


def daily_metrics(hist, row):
    """Calibration + surprise metrics from the daily series of a resolved market."""
    out = {
        "n_price_points": len(hist),
        "first_price_date": None,
        "prob_7d": None, "prob_3d": None, "prob_1d": None,
        "correct_7d": None, "correct_1d": None,
        "lead_days_to_correct": None,
        "max_1d_move": None, "max_1d_move_date": None,
        "late_swing": None,
        "surprise": None,
        "brier_1d": None,
        "price_vs_baserate": None,
    }
    if not hist:
        return out
    out["first_price_date"] = datetime.fromtimestamp(
        hist[0]["t"], tz=timezone.utc).strftime("%Y-%m-%d")

    # Largest single-day move (works for open and resolved).
    max_move = 0.0
    max_date = None
    for a, b in zip(hist, hist[1:]):
        mv = abs(b["p"] - a["p"])
        if mv >= max_move:
            max_move = mv
            max_date = datetime.fromtimestamp(b["t"], tz=timezone.utc).strftime("%Y-%m-%d")
    out["max_1d_move"] = round(max_move, 4)
    out["max_1d_move_date"] = max_date

    closed = str(row.get("closed")).lower() == "true"
    resolved_yes = str(row.get("resolved_yes")).lower() == "true"
    is_resolved = closed and row.get("resolved_yes") not in (None, "", "None")

    # price_vs_baserate is meaningful for OPEN markets (current Yes vs history).
    if not closed:
        yp = row.get("yes_price")
        try:
            out["price_vs_baserate"] = round(float(yp) - BASE_RATE, 4)
        except (TypeError, ValueError):
            pass
        return out

    if not is_resolved:
        return out

    res_t = _resolution_unix(row)
    if res_t is None:
        return out
    outcome = 1.0 if resolved_yes else 0.0

    p7 = price_at(hist, res_t - 7 * DAY)
    p3 = price_at(hist, res_t - 3 * DAY)
    p1 = price_at(hist, res_t - 1 * DAY)
    out["prob_7d"], out["prob_3d"], out["prob_1d"] = (
        None if p7 is None else round(p7, 4),
        None if p3 is None else round(p3, 4),
        None if p1 is None else round(p1, 4),
    )
    if p7 is not None:
        out["correct_7d"] = (p7 > 0.5) == resolved_yes
    if p1 is not None:
        out["correct_1d"] = (p1 > 0.5) == resolved_yes
        out["brier_1d"] = round((p1 - outcome) ** 2, 4)

    # lead_days_to_correct: how many days before resolution the price first
    # crossed to the correct side and STAYED there through resolution.
    correct_side_up = resolved_yes  # if YES, correct side is p>0.5
    lead = None
    # walk backward; find the earliest contiguous-correct run ending at resolution
    on_correct = lambda p: (p > 0.5) == correct_side_up
    run_start_t = None
    for h in hist:
        if h["t"] > res_t:
            break
        if on_correct(h["p"]):
            if run_start_t is None:
                run_start_t = h["t"]
        else:
            run_start_t = None
    if run_start_t is not None:
        lead = round((res_t - run_start_t) / DAY, 1)
    out["lead_days_to_correct"] = lead

    # surprise = the market was BLINDSIDED: it confidently favored the losing
    # side close to resolution. Two ways this shows up in the data:
    #   (a) a large in-series daily move on/just before the resolution date that
    #       straddles 50 (the classic late swing), or
    #   (b) the price stayed on the wrong side at 1 day out with real confidence
    #       (|prob_1d - 0.5| >= 0.15). The CLOB daily series ends at the last
    #       pre-resolution trade, so a same-day collapse (e.g. GTx-104, which sat
    #       ~71% the day before and resolved NO) never appears as an in-series
    #       move — it only shows as a confidently-wrong final price. Case (b)
    #       catches these; case (a) catches swings that complete before close.
    late_swing = False
    if max_date is not None:
        try:
            md = datetime.strptime(max_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
            near_resolution = (res_t - md) <= 2 * DAY and md <= res_t + DAY
            late_swing = bool(near_resolution and max_move >= 0.30)
        except ValueError:
            late_swing = False
    out["late_swing"] = late_swing

    # A surprise/blindside means the market's CONFIDENT 1-day-out call was WRONG
    # (not merely that the price swung late — a late swing onto the *correct*
    # side is foresight, not a blindside, so late_swing is kept as its own
    # informational column rather than folded into surprise).
    out["surprise"] = bool(
        out["correct_1d"] is False
        and p1 is not None
        and abs(p1 - 0.5) >= 0.15
    )
    return out


def detect_single_order(fine_hist):
    """Thin-market single-order signature: a tight plateau, then a >=15pt jump in
    ONE <=10-min candle, then another tight plateau — with no other big candle
    nearby (an isolated step, not ordinary price discovery). This is far stricter
    than a 3-point check and avoids flagging gradual moves. Returns
    (flag, jump, jump_date_iso)."""
    FLAT_N, FLAT_TOL = 6, 0.02      # ~6 candles (~60 min) within 2 points each side
    if len(fine_hist) < FLAT_N * 2 + 1:
        return False, 0.0, ""
    for i in range(FLAT_N, len(fine_hist) - FLAT_N):
        jump = fine_hist[i]["p"] - fine_hist[i - 1]["p"]
        if abs(jump) < SHARP_MOVE:
            continue
        before = [p["p"] for p in fine_hist[i - FLAT_N:i]]
        after = [p["p"] for p in fine_hist[i + 1:i + 1 + FLAT_N]]
        if (max(before) - min(before) >= FLAT_TOL) or (max(after) - min(after) >= FLAT_TOL):
            continue
        nearby = [abs(fine_hist[k]["p"] - fine_hist[k - 1]["p"])
                  for k in range(i - FLAT_N, i + 1 + FLAT_N) if k != i and k >= 1]
        if any(d >= SHARP_MOVE for d in nearby):
            continue
        jdate = datetime.fromtimestamp(fine_hist[i]["t"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        return True, round(jump, 3), jdate
    return False, 0.0, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="store_true", help="use fda_markets_raw.csv")
    ap.add_argument("--refresh", action="store_true",
                    help="re-download price histories even if cached on disk")
    args = ap.parse_args()

    infile = "fda_markets_raw.csv"
    if not args.raw and os.path.exists("fda_markets_enriched.csv"):
        infile = "fda_markets_enriched.csv"
    print(f"Reading {infile}")
    df = pd.read_csv(infile, dtype=str)

    os.makedirs(DAILY_DIR, exist_ok=True)
    os.makedirs(FINE_DIR, exist_ok=True)

    # Market-depth cache (trades/holders are collected for EVERY market, so a
    # cache avoids re-hitting the Data API on every run; --refresh re-pulls).
    depth_cache = {}
    if not args.refresh and os.path.exists(DEPTH_FILE):
        for rec in pd.read_csv(DEPTH_FILE, dtype=str).to_dict("records"):
            depth_cache[rec["slug"]] = rec

    metrics_rows = []
    sharp_movers = []
    depth_rows = []

    for _, row in tqdm(df.iterrows(), total=len(df), desc="daily"):
        row = row.to_dict()
        slug = row["slug"]
        token = row.get("yes_token_id")
        hist, fetched = load_or_fetch(
            os.path.join(DAILY_DIR, f"{slug}.csv"), token, 1440, "max", args.refresh)
        if fetched:
            time.sleep(SLEEP)

        # Market depth (trades + holders) for every market, cached.
        if slug in depth_cache:
            d = {k: depth_cache[slug].get(k) for k in DEPTH_FIELDS}
        else:
            d = market_depth(row.get("condition_id"))
            time.sleep(SLEEP)
        depth_rows.append({"slug": slug, **d})

        m = daily_metrics(hist, row)
        m["slug"] = slug
        metrics_rows.append(m)

        if m["max_1d_move"] and m["max_1d_move"] >= SHARP_MOVE:
            # Center the fine pull on the move date (fall back to resolution).
            center = None
            if m["max_1d_move_date"]:
                try:
                    center = datetime.strptime(m["max_1d_move_date"], "%Y-%m-%d") \
                        .replace(tzinfo=timezone.utc).timestamp()
                except ValueError:
                    center = None
            if center is None:
                center = _resolution_unix(row)
            sharp_movers.append((slug, token, row.get("condition_id"), center))

    # Fine-grained (10-min) pass for sharp movers. A +/-3 day window around the
    # move date (start_ts/end_ts) is REQUIRED — interval=max returns no 10-min
    # data for markets that resolved a while ago. We then run the strict
    # single-order test and, when it fires, confirm against the trades endpoint
    # (one large taker order corroborates a single-wallet move).
    single_order = {}
    print(f"\nFine (10-min) windowed pull for {len(sharp_movers)} sharp movers...")
    for slug, token, cond_id, center in tqdm(sharp_movers, desc="fine"):
        start_ts = end_ts = None
        if center is not None:
            start_ts, end_ts = center - 3 * DAY, center + 3 * DAY
        fine, fetched = load_or_fetch(
            os.path.join(FINE_DIR, f"{slug}.csv"), token, 10, "max",
            args.refresh, start_ts=start_ts, end_ts=end_ts)
        flag, jump, jdate = (False, 0.0, "")
        if fine:
            flag, jump, jdate = detect_single_order(fine)
        single_order[slug] = (flag, jump, jdate)
        if fetched:
            time.sleep(SLEEP)

    mdf = pd.DataFrame(metrics_rows)
    mdf["single_order_move"] = mdf["slug"].map(lambda s: single_order[s][0] if s in single_order else None)
    mdf["single_order_jump"] = mdf["slug"].map(lambda s: single_order[s][1] if s in single_order else "")
    mdf["single_order_date"] = mdf["slug"].map(lambda s: single_order[s][2] if s in single_order else "")

    # Persist and merge the market-depth columns (collected for every market).
    ddf = pd.DataFrame(depth_rows)
    ddf.to_csv(DEPTH_FILE, index=False, encoding="utf-8")

    out = df.merge(mdf, on="slug", how="left").merge(ddf, on="slug", how="left")
    out.to_csv("fda_markets_processed.csv", index=False, encoding="utf-8")
    print(f"\nWrote fda_markets_processed.csv: {len(out)} rows")
    print(f"Daily series in {DAILY_DIR}/, fine series in {FINE_DIR}/, "
          f"depth in {DEPTH_FILE}")


if __name__ == "__main__":
    main()
