"""
fetch_markets.py — Stage 1 of the FDA-markets pipeline.

Paginates the Polymarket Gamma API for FDA drug-approval prediction markets,
across BOTH the `fda` and `drug` tags and BOTH open (closed=false) and resolved
(closed=true) states, de-duplicates by event id, keeps only the per-drug
"FDA approves ..." contracts, and writes a flat raw CSV — one row per market.

Public API, no auth. Usage:
    python fetch_markets.py

Output:
    fda_markets_raw.csv
"""

import csv
import json
import time
import sys

import requests
from tqdm import tqdm

GAMMA = "https://gamma-api.polymarket.com/events"
TAGS = ["fda", "drug"]
PAGE = 8          # keep small — large event payloads get truncated by some clients
SLEEP = 0.25      # be polite to the API
OUT = "fda_markets_raw.csv"

# Only per-drug approval contracts. The brief asks us to require the title to
# start with "FDA approves" — this drops "next FDA commissioner", "FDA revokes
# polio vaccine", grouped "FDA approvals in July" multi-markets, etc.
TITLE_PREFIX = "fda approves"


def get_json(url, params, retries=5):
    """GET with exponential backoff on 429 / transient errors."""
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
        except (requests.RequestException, json.JSONDecodeError) as e:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 8)
    return None


def pull_tag(tag, closed):
    """Page through one (tag, closed) combination until an empty page."""
    events = []
    offset = 0
    while True:
        page = get_json(GAMMA, {
            "tag_slug": tag,
            "closed": "true" if closed else "false",
            "limit": PAGE,
            "offset": offset,
            "order": "endDate",
            "ascending": "false",
        })
        if not page:
            break
        events.extend(page)
        offset += PAGE
        time.sleep(SLEEP)
    return events


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _maybe_json_list(x):
    """outcomes / outcomePrices / clobTokenIds come back as JSON strings."""
    if isinstance(x, list):
        return x
    if isinstance(x, str):
        try:
            return json.loads(x)
        except json.JSONDecodeError:
            return None
    return None


def flatten(event):
    """Event -> one row for its single binary market (markets[0])."""
    markets = event.get("markets") or []
    if not markets:
        return None
    m = markets[0]

    outcomes = _maybe_json_list(m.get("outcomes")) or []
    prices = _maybe_json_list(m.get("outcomePrices")) or []
    tokens = _maybe_json_list(m.get("clobTokenIds")) or []

    yes_price = _num(prices[0]) if len(prices) > 0 else None
    no_price = _num(prices[1]) if len(prices) > 1 else None
    yes_token = tokens[0] if len(tokens) > 0 else None
    no_token = tokens[1] if len(tokens) > 1 else None

    closed = bool(m.get("closed") or event.get("closed"))

    # Resolution from final prices: ["1","0"] -> YES, ["0","1"] -> NO.
    resolved_yes = None
    if closed and yes_price is not None and no_price is not None:
        if yes_price >= 0.99 and no_price <= 0.01:
            resolved_yes = True
        elif yes_price <= 0.01 and no_price >= 0.99:
            resolved_yes = False

    meta = event.get("eventMetadata") or {}
    context = meta.get("context_description") if isinstance(meta, dict) else None

    # Prefer market-level numeric fields, fall back to event-level.
    return {
        "event_id": event.get("id"),
        "slug": event.get("slug"),
        "title": event.get("title"),
        "question": m.get("question"),
        "condition_id": m.get("conditionId"),
        "yes_token_id": yes_token,
        "no_token_id": no_token,
        "closed": closed,
        "active": m.get("active"),
        "outcomes": json.dumps(outcomes),
        "yes_price": yes_price,
        "no_price": no_price,
        "last_trade_price": _num(m.get("lastTradePrice")),
        "resolved_yes": resolved_yes,
        "start_date": event.get("startDate") or m.get("startDate"),
        "end_date": event.get("endDate") or m.get("endDate"),
        "closed_time": event.get("closedTime") or m.get("closedTime"),
        "uma_resolution_status": m.get("umaResolutionStatus")
                                 or event.get("umaResolutionStatus"),
        "volume": _num(m.get("volumeNum")) or _num(event.get("volume")),
        "liquidity": _num(m.get("liquidityNum")) or _num(event.get("liquidity")),
        "volume_24hr": _num(m.get("volume24hr")) or _num(event.get("volume24hr")),
        "one_day_price_change": _num(m.get("oneDayPriceChange")),
        "one_week_price_change": _num(m.get("oneWeekPriceChange")),
        "one_month_price_change": _num(m.get("oneMonthPriceChange")),
        "spread": _num(m.get("spread")),
        "best_bid": _num(m.get("bestBid")),
        "best_ask": _num(m.get("bestAsk")),
        "context_description": context,
        "event_description": (event.get("description") or "").strip(),
        "tags": ",".join(sorted({t.get("slug", "") for t in (event.get("tags") or []) if isinstance(t, dict)})),
    }


def main():
    by_id = {}        # event id -> raw event (dedupe across tags/states)
    for tag in TAGS:
        for closed in (True, False):
            evs = pull_tag(tag, closed)
            print(f"  tag={tag:5s} closed={str(closed):5s} -> {len(evs):3d} events")
            for e in evs:
                by_id.setdefault(e["id"], e)
    print(f"Unique events across both tags / both states: {len(by_id)}")

    rows = []
    skipped = []
    for e in tqdm(by_id.values(), desc="flatten"):
        title = (e.get("title") or "").strip().lower()
        if not title.startswith(TITLE_PREFIX):
            skipped.append(e.get("title"))
            continue
        row = flatten(e)
        if row:
            rows.append(row)

    rows.sort(key=lambda r: (r["closed"], r["end_date"] or ""))

    if not rows:
        print("No rows — aborting.", file=sys.stderr)
        sys.exit(1)

    fields = list(rows[0].keys())
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    n_open = sum(1 for r in rows if not r["closed"])
    n_closed = sum(1 for r in rows if r["closed"])
    print(f"\nWrote {OUT}: {len(rows)} markets  ({n_open} open, {n_closed} resolved)")
    print(f"Excluded {len(skipped)} non-'FDA approves' events, e.g.: "
          f"{', '.join(str(s) for s in skipped[:4])}")


if __name__ == "__main__":
    main()
