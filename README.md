# FDA Drug-Approval Market Data Collection Pipeline

This repository contains scripts to collect and process FDA drug-approval
prediction-market data from Polymarket, producing an analysis-ready dataset:
prices, full price histories, a hand-researched regulatory-metadata layer with a
cited source for every value, computed calibration/depth metrics, and a
transparent base-rate benchmark.

All market data comes from public Polymarket APIs (no key, no auth). Analysis,
findings, and caveats live in `FINDINGS.md` and `LIMITATIONS.md`, not in this
README.

## Prerequisites

```
pip install -r requirements.txt        # pandas requests tqdm matplotlib
```

## Pipeline Overview

```
Step 1: Fetch    →    Step 2: Enrich    →    Step 3: Process    →    Step 4: Benchmark    →    Step 5: Figures + Audit
(1 script)            (manual + 2 scripts)   (1 script)              (3 scripts)               (2 scripts)
```

Run it end to end:

```bash
python fetch_markets.py
python build_enrichment.py
python enrich_markets.py
python process_markets.py        # caches price series; pass --refresh to re-download
python make_figures.py           # writes PNGs to figures/
python benchmark.py              # self-test of the fair-value model
python edge.py                   # writes edge_open.csv
python insights.py               # writes findings.json
python audit.py                  # reproducibility + validity checks
```

## Step 1: Fetch Markets

```
python fetch_markets.py
```

Queries Polymarket's Gamma API for every FDA drug-approval market, open and
closed, under the `fda` and `drug` tags. De-dupes by event id and keeps only
per-drug contracts whose title starts with "FDA approves" (see Scope Filter).
Each row carries prices, token ids, volume, dates, and the market's own
resolution-rules text.

Output: `fda_markets_raw.csv`

## Step 2: Enrich Markets (cited regulatory metadata)

`enrichment_data.json` is the hand-researched layer. For each market slug it
records application type, PDUFA date, prior-cycle CRL and its cause,
designations, manufacturing-inspection flags, outcome, eventual approval, and a
primary `source_url` for every value. Two scripts turn it into a joined table:

```
python build_enrichment.py       # enrichment_data.json -> enrichment.csv
python enrich_markets.py          # joins enrichment onto raw markets, on slug
```

Outputs: `enrichment.csv`, `fda_markets_enriched.csv`

## Step 3: Process Markets (price history + metrics)

```
python process_markets.py         # --raw to read the raw file; --refresh to re-pull
```

Fetches each market's full daily Yes-price series from the CLOB API (and a 10-min
series for sharp movers), caches them to disk, and computes calibration,
surprise, single-order, and depth metrics. It reads `fda_markets_enriched.csv` if
present. Cached series mean re-runs and the audit do not re-hit the API.

Outputs: `fda_markets_processed.csv` (analysis-ready, 74 columns),
`price_history/<slug>.csv`, `price_history_fine/<slug>.csv`, `market_depth.csv`

## Step 4: Benchmark and Edge

```
python benchmark.py               # self-test of the fair-value model
python edge.py                    # backtest + open-slate scoring
python insights.py                # rate table with n + Wilson CIs
```

`benchmark.py` turns cited FDA population base rates (`benchmark_params.json`,
sourced to `population/fda_reference_rates.csv`) into a fair value per market,
using pre-decision inputs only. `edge.py` runs the out-of-sample backtest of the
benchmark against the crowd and scores the open markets. `insights.py` emits
every rate with its sample size and a Wilson 95% interval.

Outputs: `edge_open.csv`, `findings.json`

## Step 5: Figures and Audit

```
python make_figures.py            # writes figures/*.png
python audit.py                   # PASS/FAIL per check
```

`audit.py` runs reproducibility checks (sections 1-8: independently recompute
every metric and every figure's plotted aggregation from the raw series) and
validity checks (sections 9-14: a per-row look-ahead/leakage report, n + Wilson
CI on every rate, and a leakage-safety scan of the benchmark inputs).

## Output Files

| File | Description |
|---|---|
| `fda_markets_raw.csv` | One row per market from Gamma (prices, tokens, volume, dates, resolution text). |
| `enrichment_data.json` | The cited regulatory-metadata layer, with research notes and a `source_url` per value. |
| `enrichment.csv` | Flattened enrichment table. |
| `fda_markets_enriched.csv` | Raw markets joined with the 22 regulatory fields. |
| `fda_markets_processed.csv` | Analysis-ready file: enriched rows + computed metrics (74-column dictionary in `methodology.md`). |
| `price_history/<slug>.csv` | Daily (1440-min) Yes-price series, full life of each market. |
| `price_history_fine/<slug>.csv` | 10-min series for sharp movers (single-order detection). |
| `market_depth.csv` | Per-market liquidity/concentration from `/trades` + `/holders`. |
| `benchmark_params.json` | Cited, pre-registered base-rate coefficients for the fair-value model. |
| `population/fda_reference_rates.csv` | The published FDA statistics the benchmark coefficients are sourced to. |
| `edge_open.csv` | Open markets: fair value vs market price, gap, and a liquidity flag. |
| `findings.json` | Every reportable rate with its n, Wilson 95% CI, and leakage flag. |
| `figures/*.png` | Charts from `make_figures.py` (see Figures). |
| `methodology.md` | Field definitions, resolution semantics, benchmark method, caveats. |
| `FINDINGS.md`, `LIMITATIONS.md` | Ranked findings (with confidence tiers) and the honest limits. |

## Figures

`python make_figures.py` reads `fda_markets_processed.csv` and the `price_history/`
series and writes these PNGs. Interpretation lives in `FINDINGS.md`.

| File | What it shows |
|---|---|
| `fig1_risk_inversion.png` | Price charged vs realized rate by `risk_category` (carries an on-chart leakage caveat; see LIMITATIONS §1). |
| `fig2_calibration.png` | Reliability curve of the 1-day-out price (mean Brier). |
| `fig3_surprises.png` | Blindside markets: confident and wrong into the decision. |
| `fig4_open_slate.png` | Open markets' price vs the FDA base rate. |
| `fig5_depth.png` | Market thinness: top-holder concentration vs holder count. |
| `fig6_leakage_free_gradient.png` | On-time rate by a pre-knowable (`prior_crl`) axis, with Wilson CIs. |
| `fig7_leakage_artifact.png` | The refile rate: contaminated bucket vs leakage-free cohort. |
| `fig8_bydate_vs_ever.png` | Approved on time vs approved ever, per cohort. |
| `fig9_residual_vs_price.png` | Outcome minus the 7-day price (was the risk already priced). |
| `fig10_accuracy.png` | Majority-side accuracy at 7 days and 1 day out, with CIs. |
| `fig11_outcome_decomp.png` | How resolved markets ended (Yes / CRL / Delay). |
| `fig12_edge_map.png` | Open slate: benchmark fair value vs market price, by depth. |
| `fig13_benchmark_vs_market.png` | Did the base-rate benchmark beat the crowd out-of-sample. |

## Scope Filter

Only per-drug contracts whose title starts with "FDA approves" are kept. This
excludes non-drug FDA markets ("next FDA commissioner", "FDA revokes polio
vaccine", the grouped "FDA approvals in July" event). The thematic
"FDA approves a psychedelic for medical use in 2026" market is kept in the
dataset but excluded from the drug-by-drug base rate, because it resolved Yes on
a substance-list technicality (see `methodology.md`).

## API Reference

- **Gamma, events:** `https://gamma-api.polymarket.com/events?tag_slug={fda|drug}&closed={true|false}&limit=8&offset={N}&order=endDate&ascending=false`. Paged at `limit=8`; both tags, both states, de-duped by event id.
- **Gamma, single event:** `https://gamma-api.polymarket.com/events?slug={slug}`. Small payload, used for clean re-pulls and QA.
- **CLOB, price history:** `https://clob.polymarket.com/prices-history?market={YES_TOKEN_ID}&interval=max&fidelity={min}`. Daily (`1440`) for every market; 10-min (`10`) for flagged movers.
- **Data API:** `https://data-api.polymarket.com/trades` and `/holders`, for depth and single-trader confirmation.

## Rate Limiting

`process_markets.py` caches every price series to `price_history/`, so re-runs
and `audit.py` read from disk rather than re-hitting the API. Use `--refresh` to
force a re-pull. If you hit rate-limit errors on a cold run, add or raise the
`time.sleep()` delays between requests.

## Current Dataset

As of the 2026-06-24 snapshot, `fda_markets_processed.csv` contains 44 markets:

- 36 resolved drug-approval markets, 7 open, plus 1 thematic market (excluded from the base rate).
- Of the 36 resolved: 23 resolved Yes, 13 resolved No (9 CRLs, 4 PDUFA delays).
- Tebipenem (approved 2026-06-17, Utebzi) and Welireg (approved 2026-06-12) both settled Yes since the prior snapshot and are now inside the 36-market settled cohort (see LIMITATIONS §9).
- Total volume across all 44 markets: ~$909K. (These are thin markets; treat per-market liquidity accordingly.)
- A daily price series for all 44 markets; a 10-min series for 29 sharp movers.

Markets resolve continuously, so re-running picks up newly resolved contracts and
updated prices.

## Analysis and Findings

Conclusions are deliberately kept out of this README. `FINDINGS.md` lists the
supported and unsupported conclusions, each tagged ROBUST / SUGGESTIVE /
ANECDOTAL with its sample size and Wilson interval. `LIMITATIONS.md` covers the
load-bearing caveats: look-ahead/leakage in `risk_category`, small sample size,
selection bias, and the by-date vs ever-approved distinction. In short: a
transparent FDA base-rate benchmark loses to the crowd out-of-sample, so these
markets are roughly efficient, and the commonly cited risk-class "gradient" is
look-ahead-contaminated (LIMITATIONS §1). Every regulatory value is verified
against the primary sources cited in `enrichment_data.json`.
