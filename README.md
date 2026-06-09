# fda-markets

A reproducible pipeline that collects every **FDA drug-approval prediction
market** on Polymarket (open and resolved), pulls their full price histories,
attaches hand-researched regulatory metadata, and computes calibration / surprise
metrics — so the market's forecasting accuracy and risk mis-pricing can be analyzed.

All data comes from **public Polymarket APIs (no key, no auth)** plus a
web-researched regulatory-enrichment layer with a cited source for every value.

## Pipeline

```
fetch_markets.py     →  fda_markets_raw.csv          (Gamma API: fda + drug tags, open + closed)
build_enrichment.py  →  enrichment.csv               (from enrichment_data.json — cited regulatory facts)
enrich_markets.py    →  fda_markets_enriched.csv      (raw + regulatory metadata, joined on slug)
process_markets.py   →  fda_markets_processed.csv     (+ price histories + computed metrics)
summary.py           →  console summary + findings
make_figures.py      →  figures/*.png                 (analysis charts)
```

Run it end to end:

```bash
pip install -r requirements.txt        # pandas requests tqdm matplotlib
python fetch_markets.py
python build_enrichment.py
python enrich_markets.py
python process_markets.py              # caches price series; pass --refresh to re-download
python summary.py
python make_figures.py                 # writes PNGs to figures/
```

`process_markets.py` reads `fda_markets_enriched.csv` if present (else the raw
file with `--raw`). It caches each price series to disk, so re-runs and the
reproducibility check don't re-hit the API; use `--refresh` to force a re-pull.

## Outputs

| File | Contents |
|---|---|
| `fda_markets_raw.csv` | One row per market straight from Gamma (prices, tokens, volume, dates, `context_description`). |
| `fda_markets_enriched.csv` | Raw + 22 regulatory fields (sponsor, PDUFA, application type, prior-CRL + reason class, designations, outcome, eventual approval, source URLs). |
| `fda_markets_processed.csv` | The **analysis-ready** file: enriched rows + calibration/surprise/single-order/depth metrics. Full 74-column data dictionary in [methodology.md](methodology.md#7-column-dictionary--fda_markets_processedcsv). |
| `price_history/<slug>.csv` | Daily (1440-min) Yes-price series, full life of each market. |
| `price_history_fine/<slug>.csv` | 10-min series for sharp movers (single-order detection). |
| `market_depth.csv` | Per-market liquidity/concentration from `/trades`+`/holders` (trades, unique traders, largest trade, top holders, top-holder %). |
| `figures/*.png` | Analysis charts from `make_figures.py` (see **Figures** below). |
| `enrichment_data.json` | Source of the enrichment layer — cited, with research notes. |
| `methodology.md` | Field definitions, resolution semantics, base rate, caveats. |

## Figures

`python make_figures.py` reads `fda_markets_processed.csv` + the `price_history/`
series and writes PNGs to `figures/`:

| Figure | Shows |
|---|---|
| `fig1_risk_inversion.png` | Mean Yes price the market charged vs. realized on-time approval rate, per `risk_category` — the headline mis-pricing (clean reviews underpriced at ~0.72→100%; CMC refiles ~0.35→11%). |
| `fig2_calibration.png` | Reliability curve: predicted `prob_1d` vs. observed approval frequency, annotated with mean Brier. |
| `fig3_surprises.png` | Yes-price trajectories of the blindside markets, aligned to days-before-resolution. |
| `fig4_open_slate.png` | Open markets' `price_vs_baserate`, colored by risk category. |
| `fig5_depth.png` | Market thinness — top-holder concentration vs. holder count, single-order moves highlighted. |

## Data sources (all public)

1. **Gamma — events** `https://gamma-api.polymarket.com/events?tag_slug={fda|drug}&closed={true|false}&limit=8&offset={N}&order=endDate&ascending=false`
   Paged at `limit=8` (large event payloads truncate at higher limits). Both
   `fda` and `drug` tags, both states, de-duped by event `id`.
2. **Gamma — single event** `…/events?slug={slug}` — small payload, used for clean re-pulls and QA spot-checks.
3. **CLOB — price history** `https://clob.polymarket.com/prices-history?market={YES_TOKEN_ID}&interval=max&fidelity={min}` — daily (`1440`) for every market; 10-min (`10`) for flagged sharp movers.
4. **Data API** `https://data-api.polymarket.com/trades` and `/holders` — available for single-trader confirmation of suspected single-order moves.

## Scope filter

We keep only per-drug contracts whose title starts with **"FDA approves"**.
This excludes non-drug FDA markets ("next FDA commissioner", "FDA revokes polio
vaccine", the grouped "FDA approvals in July" event). The thematic
**"FDA approves a psychedelic for medical use in 2026"** market is kept in the
dataset but **excluded from the drug-by-drug base rate** — it resolved Yes on a
substance-list technicality (see `methodology.md`).

## Headline result

Splitting resolved markets by regulatory risk class exposes a sharp gradient the
market only partly priced:

| risk_category | mean Yes price charged | on-time approval rate |
|---|---|---|
| Clean desk review | 0.80 | **18 / 18 = 100%** |
| Oncology sNDA | 0.87 | 2 / 2 = 100% |
| CMC/manufacturing refile | 0.37 | **1 / 9 = 11%** |
| Timeline bet | 0.33 | 0 / 4 = 0% |

Clean first-cycle reviews approved on time every single time; CMC/manufacturing
refiles almost never did. See `summary.py` output and the findings in the
project notes.

> Data snapshot: 2026-06-09. Markets resolve continuously, so re-running will
> pick up newly resolved contracts and updated open-market prices.
