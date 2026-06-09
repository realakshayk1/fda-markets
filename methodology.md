# Methodology

## 1. Resolution semantics (read this first)

These Polymarket contracts resolve **"Yes" only if the drug is FDA-approved by
the market's resolve-by (`end_date`) date.** The rules explicitly make all of the
following resolve **"No"**:

- a **Complete Response Letter (CRL)**,
- a **withdrawal** of the application, or
- a **PDUFA-date extension / delay** past the market date.

Therefore **"Resolved No" ≠ "drug rejected."** Every No is decomposed into
`outcome ∈ {CRL, Delay, Withdrawn}` from the enrichment layer, never from the
price alone. We track **two distinct things** per resolved market:

- `resolved_yes` — did the **market** resolve Yes (approved *on time*)?
- `eventually_approved` — was the drug **approved at all**, possibly later than
  the market date (e.g. EYLEA HD: delayed past the Aug-2025 market date, then
  approved Nov 2025 → market `No`, eventually `yes`).

### The thematic psychedelic market

`fda-approves-a-psychedelic-for-medical-use-in-2026` resolved **Yes on a
technicality**: the market's qualifying-substance list includes dextromethorphan
(DXM), and Axsome's Auvelity (a DXM-bupropion combination) received a new-indication
approval on 2026-04-30, satisfying the literal criteria ~8 months early. It is
**excluded from the drug-by-drug base rate** in `summary.py` and logged as a
resolution-criteria example.

## 2. Field extraction (per event → its single binary market `markets[0]`)

- `outcomes` = `["Yes","No"]`; `outcomePrices[0]` = Yes mid; `lastTradePrice` = last trade.
- `clobTokenIds[0]` = YES token (used for the price-history call); `[1]` = No.
- `conditionId` → trades/holders endpoints.
- Resolved: final `outcomePrices` `["1","0"]` → Yes, `["0","1"]` → No;
  `closedTime` + `umaResolutionStatus` give resolution timing.
- Also captured: `slug`, `title`, `startDate`, `endDate`, `volume`, `liquidity`,
  `volume24hr`, `oneDay/Week/MonthPriceChange`, `spread`, `bestBid`, `bestAsk`,
  and `eventMetadata.context_description` (Polymarket's own auto-generated odds
  explanation, captured verbatim).

## 3. Enrichment fields (web-researched "manual label" layer)

Every value is backed by a primary source in `source_url` (company IR / press
releases, FDA.gov, Endpoints, Fierce, BioPharma Dive, drugs.com, HCPLive, OncLive).

| Field | Vocabulary / notes |
|---|---|
| `sponsor`, `drug`, `indication` | free text |
| `application_type` | NDA / sNDA / BLA / sBLA / 505(b)(2) / ANDA / biosimilar / manufacturing-supplement |
| `pdufa_date` | true FDA action date from a primary source |
| `pdufa_matches_market_date` | yes/no — flags cases where the market's resolve-by ≠ true PDUFA (e.g. a Saturday PDUFA rolling to Monday) |
| `review_type` | standard / priority |
| `designations` | Breakthrough / Fast Track / QIDP / Orphan / Priority Review Voucher / Accelerated Approval / RMAT |
| `prior_crl` | **yes/no — prior-cycle CRL baggage (refiles only)** |
| `crl_date`, `crl_reason_class` | CMC/manufacturing · clinical/efficacy · safety · nonclinical |
| `manufacturing_inspection_required`, `inspection_location` | yes/no · domestic/foreign |
| `adcom_scheduled` | no / date |
| `risk_category` | Clean desk review · CMC/manufacturing refile · Clinical/efficacy · Oncology sNDA · Timeline bet |
| `outcome` (resolved) | Approved / CRL / Delay / Withdrawn + `outcome_date`, `outcome_reason` |
| `eventually_approved` | yes / no / pending (+ date) |

> **`prior_crl`** records whether the application carried a CRL from a *prior*
> review cycle. A first-cycle CRL is the market's `outcome` (=`CRL`), **not**
> `prior_crl` — so `prior_crl = no` for first-cycle CRLs (GTx-104, CTx-1301,
> UX111, Unicycive-OLC, Capricor, vatiquinone) and `yes` only for genuine refiles
> (Telix — its Aug-2025 CRL was its *second*; Outlook; Oclaiz; Tebipenem; the
> 2026 Unicycive refile; KETARx). The two Unicycive markets are the clean
> illustration: the 2025 market resolved `No` on a first-cycle CMC CRL; the 2026
> market is the **refile** of the same drug.
>
> **`crl_reason_class`** is the primary deficiency class of the CRL *operative for
> this market* — the prior CRL for refiles, or this cycle's CRL for first-cycle
> CRL resolutions — so it is populated for every CRL-touched market, not only
> refiles. Of the 8 resolved CRLs, 6 are CMC/manufacturing and 2 are
> clinical/efficacy.
>
> **`risk_category`** classifies the bet by its gating risk. `CMC/manufacturing
> refile` is CMC-gated reviews (refiles *and* first-cycle CMC CRLs);
> `Clinical/efficacy` is reviews gated on efficacy data (e.g. Capricor,
> vatiquinone, Tebipenem); `Timeline bet` is by-deadline timing risk with no firm
> imminent decision (the year-end markets, plus oncology reviews that hinged on
> whether the FDA would rule by the date). Every label is verified against the
> primary sources cited in `enrichment_data.json`.

## 4. Computed metrics (`process_markets.py`)

From each resolved market's **daily** price history, with resolution time taken
from `closed_time` (fallback `end_date`). Prices are carried forward to the
target instant.

- `prob_7d`, `prob_3d`, `prob_1d` — Yes price at 7 / 3 / 1 days before resolution.
- `correct_7d`, `correct_1d` — did the market's >50% side match the on-time outcome.
- `lead_days_to_correct` — days before resolution that the price first crossed to
  the correct side **and stayed there** through resolution (foresight measure).
- `max_1d_move`, `max_1d_move_date` — largest single-day jump.
- `late_swing` — a ≥0.30 daily move within ~2 days of resolution (informational).
- **`surprise`** — the market's **confident 1-day-out call was wrong**:
  `correct_1d` is False **and** `|prob_1d − 0.5| ≥ 0.15`.
  > A late swing onto the *correct* side is foresight, not a blindside, so it is
  > kept in `late_swing` and deliberately **not** folded into `surprise`.
  > Note the CLOB daily series ends at the last *pre-resolution* trade, so a
  > same-day collapse (e.g. GTx-104, sitting ~71% the day before a CRL) never
  > appears as an in-series move — it surfaces only as a confidently-wrong final
  > price, which is exactly what `surprise` captures.
- `brier_1d` = (`prob_1d` − outcome)²; the mean across resolved markets is the
  headline calibration number.
- `single_order_move` (+ `single_order_jump`, `single_order_date`,
  `largest_trade_size`) — from the **10-min** series of sharp movers: a tight
  plateau (~6 candles within 2 pts), then a >15-point jump in ONE ≤10-min candle,
  then another tight plateau, with **no other big candle nearby** (an isolated
  step, not ordinary discovery). When it fires, it is **confirmed against the
  Data API `/trades` endpoint** — `largest_trade_size` is the biggest single
  taker order on the market, which corroborates a one-wallet move.
  > The 10-min series is fetched with an explicit `startTs`/`endTs` window
  > (±3 days around the move date). `interval=max&fidelity=10` returns an **empty**
  > series for markets that resolved a while ago — e.g. GTx-104 yields 0 fine
  > points that way but ~500 with the window — so the windowed pull is required
  > to analyze historical movers at all.

**Market depth** (collected for *every* market, not only flagged movers, and
cached to `market_depth.csv`):

- `n_trades`, `unique_traders`, `largest_trade_size` — from the Data API
  `/trades` endpoint (most-recent 1000 trades).
- `n_top_holders`, `top_holder_pct` — from `/holders`, which returns a TOP-holders
  leaderboard capped by `limit` (we request 200). `n_top_holders` is therefore the
  count of *reported* (largest) holders, not necessarily every holder;
  `top_holder_pct` is the largest holder's share of reported holdings — a
  directional concentration proxy, exact only when the full set is returned
  (`n_top_holders` < 200). `n_trades` is likewise capped at the 1000 most-recent.

These profile liquidity across the whole slate and contextualize the
single-order flags — a flagged jump in a market with 4 holders and a 58%
top-holder share (e.g. PRGN-2012) is far more plausibly one wallet than the same
jump in a 380-trader market. `largest_trade_size` is now populated for all
markets (previously only when the single-order test fired).

For the **open slate**:

- `price_vs_baserate` = current Yes price − **0.835** (midpoint of the assumed
  ~80–87% FDA on-time base rate). Negative = priced below history.

## 5. Base rate

The ~80–87% on-time-approval band is the conventional figure for first-cycle FDA
approvals; we use the midpoint **0.835**. Note this collected 2025–2026 sample
came in **well below** that (≈64% on-time), driven by an unusually CMC/refile-heavy
slate — see the risk-category breakdown.

## 6. Caveats

- **Sample is young and small.** Individual FDA drug-approval markets only became
  common in 2025; the resolved set here is 33 drug-specific contracts (2025–2026).
  Treat all rates as directional, not statistically powered.
- **Survey snapshot.** Prices/resolutions are as of 2026-06-09. Re-running updates
  everything.
- **Daily-fidelity limitation.** Intra-day blindsides are invisible in the daily
  series; `surprise` is engineered around this (§4).
- **Enrichment is point-in-time research.** Dates and CRL reason classes are from
  the cited primary sources; a handful of inspection details were not publicly
  disclosed and are marked `unknown`. `crl_date` for two refiles is approximate
  and flagged in `enrichment_notes`.
- **`pdufa_matches_market_date`** surfaces where Polymarket's resolve-by date
  differs from the true PDUFA date; verify against the cited source before relying
  on either.

## 7. Column dictionary — `fda_markets_processed.csv`

The analysis-ready file (74 columns) layers four groups: raw market state, the
regulatory enrichment, computed metrics, and market depth.

### Market identity & live state (Gamma `/events`)

| Column | Description |
|---|---|
| `event_id`, `slug`, `title`, `question` | Polymarket event id, URL slug, event title, market question. |
| `condition_id` | On-chain condition id → key for the `/trades` and `/holders` endpoints. |
| `yes_token_id`, `no_token_id` | CLOB token ids; `yes_token_id` keys the price-history call. |
| `closed`, `active` | Market state flags. |
| `outcomes` | JSON `["Yes","No"]`. |
| `yes_price`, `no_price` | `outcomePrices` — Yes/No mid price (final = resolution for closed). |
| `last_trade_price` | Last traded price. |
| `resolved_yes` | `True`/`False` from final prices (`["1","0"]`→Yes); blank if open. |
| `start_date`, `end_date`, `closed_time` | Market open, resolve-by, and actual resolution timestamps. |
| `uma_resolution_status` | UMA oracle resolution status. |
| `volume`, `liquidity`, `volume_24hr` | Traded volume, resting liquidity, 24h volume. |
| `one_day/week/month_price_change` | Yes-price change over those windows. |
| `spread`, `best_bid`, `best_ask` | Order-book spread and top of book. |
| `context_description` | Polymarket's auto-generated odds explanation (verbatim). |
| `event_description` | Full market resolution-rules text. |
| `tags` | Tag slugs the event carries (e.g. `fda,drug`). |

### Regulatory enrichment (web-researched, every value cited in `source_url`)

| Column | Description |
|---|---|
| `sponsor`, `drug`, `indication` | Company, product, and use under review. |
| `application_type` | NDA / sNDA / BLA / sBLA / 505(b)(2) / ANDA / biosimilar / manufacturing-supplement. |
| `pdufa_date`, `pdufa_matches_market_date` | True FDA action date; whether it equals the market resolve-by date. |
| `review_type`, `designations` | standard/priority; expedited designations (Breakthrough, Fast Track, …). |
| `prior_crl`, `crl_date`, `crl_reason_class` | Prior-cycle CRL flag (refiles only); the operative CRL's date and primary class (CMC/manufacturing · clinical/efficacy · safety · nonclinical — populated for every CRL-touched market). |
| `manufacturing_inspection_required`, `inspection_location` | yes/no/unknown; domestic/foreign. |
| `adcom_scheduled` | no / AdCom date. |
| `risk_category` | Clean desk review · CMC/manufacturing refile · Clinical/efficacy · Oncology sNDA · Timeline bet. |
| `outcome`, `outcome_date`, `outcome_reason` | Resolved outcome (Approved/CRL/Delay/Withdrawn) + date + one-line reason. |
| `eventually_approved`, `eventually_approved_date` | Whether the drug was ever approved (may be after the market date). |
| `source_url`, `enrichment_notes` | Primary citation(s) and research notes. |

### Computed metrics (`process_markets.py`, §4)

| Column | Description |
|---|---|
| `n_price_points`, `first_price_date` | Daily-series length and start. |
| `prob_7d`, `prob_3d`, `prob_1d` | Yes price 7 / 3 / 1 days before resolution. |
| `correct_7d`, `correct_1d` | Whether the >50% side at 7d/1d matched the on-time outcome. |
| `lead_days_to_correct` | Days before resolution the price first crossed to and stayed on the correct side. |
| `max_1d_move`, `max_1d_move_date` | Largest single-day move and its date. |
| `late_swing` | ≥0.30 daily move within ~2 days of resolution (informational). |
| `surprise` | Blindside: confident 1-day-out call was wrong (`|prob_1d−0.5|≥0.15`). |
| `brier_1d` | (`prob_1d` − outcome)². |
| `price_vs_baserate` | Open markets only: current Yes − 0.835. |
| `single_order_move`, `single_order_jump`, `single_order_date` | Single-order signature flag, jump size, timestamp (from 10-min series). |

### Market depth (`/trades` + `/holders`, also in `market_depth.csv`)

| Column | Description |
|---|---|
| `n_trades`, `unique_traders` | Trade count (≤1000 most-recent) and distinct wallets. |
| `largest_trade_size` | Biggest single trade — corroborates single-order moves. |
| `n_top_holders`, `top_holder_pct` | Count of reported top holders (≤200) and the largest holder's share of reported holdings (concentration proxy). |
