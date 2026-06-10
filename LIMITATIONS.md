# LIMITATIONS

What this dataset cannot support, stated before any conclusion is drawn from it.
Companion to `FINDINGS.md`. All numbers reproduce via `python audit.py`.

## 1. Look-ahead / circularity (the load-bearing one)

`risk_category` is **not a pre-decision feature.** methodology.md §3 defines the
"CMC/manufacturing refile" bucket to include "first-cycle CMC CRLs" and
"Clinical/efficacy" to include first-cycle efficacy CRLs. A first-cycle CRL is
the market's **outcome** — so those buckets are partly assigned from what
happened.

- **7 of 33** resolved rows are OUTCOME-DERIVED in `risk_category`
  (`audit.py §10` prints the per-row table): OLC, UX111, EYLEA-HD, GTx-104,
  CTx-1301 (→ "CMC refile" with `prior_crl=no`), Deramiocel, Vatiquinone
  (→ "Clinical/efficacy" with `prior_crl=no`).
- Consequence: the **"CMC refile 1/8 = 12.5%"** headline is contaminated. The
  cleanest pre-knowable refile flag is `prior_crl=yes`, giving
  **1/3 = 33%, Wilson 95% [6%, 79%]** (`fig7`).
- **"Clean desk 18/18"** is the mirror image: a *residual* bucket that loses any
  clean-looking drug which later failed (it gets reclassified into a failure
  bucket). 100% is therefore partly definitional; the leakage-free first-cycle
  rate that keeps the failures is **20/30 = 67% [49%,81%]** (`fig6`).
- **De-leaking does not flip the finding — it dissolves it.** 1/3 (refile) vs
  20/30 (first-cycle) are two under-powered cohorts with overlapping CIs. The
  honest read is *indeterminate*, not "refiles are fine" and not "refiles fail."
- **The leakage-free cohort is itself imperfect.** `prior_crl` is the *one* field
  fixed before a market opens, so the axis is binary on it (an earlier
  3-way "structural timeline bet" axis was removed — it keyed on whether a PDUFA
  later firmed up, which correlates with the outcome, re-importing the same
  leakage). But (a) the "First-cycle (no prior CRL)" cohort still mixes in **3
  PDUFA *Delays*** (EYLEA-HD, Sarclisa, Camizestrant) that are timing Nos, not
  decisions — kept in, because excluding-on-outcome would be leakage in reverse,
  but flagged; and (b) `prior_crl` is a **revisable hand-label** (see §7).
- Any feature collinear with the outcome inherits the problem:
  `manufacturing_inspection_required=yes` is the **same 8 rows** as the CMC
  bucket and cannot be certified pre-knowable here.

**Rule for this repo:** report findings on the leakage-free `prior_crl` cohort,
with its heterogeneity stated, or not at all. `fig1` is retained only with an
on-chart leakage banner.

## 2. Sample size (everything is small)

- 33 resolved drug markets; 11 open. Markets became common only in 2025.
- The risk-bearing cohorts are tiny: prior-CRL refiles **n=3**, Oncology sNDA
  **n=2**, Clinical/efficacy **n=2**, structural Timeline bets **n≤3**.
- **No rate may be stated without n and a Wilson 95% CI; n<5 is ANECDOTAL.**
  At n=3, the refile CI is [6%,79%] — it excludes essentially nothing.
- No multiple-comparison correction is applied; with this many small buckets,
  some "gradient" is expected by chance alone.

## 3. Selection / survivorship bias

A Polymarket market exists only for decisions that drew retail interest —
contested refiles, brand-name drugs, binary catalysts. Routine first-cycle
approvals are under-sampled. So:

- The slate's **64% on-time rate is not the FDA base rate** (~80–87%); it is
  biased low by the kinds of decisions that get markets.
- Cross-cohort comparisons inherit the bias: the refile cohort is not a random
  sample of refiles, it is the *interesting* ones.

## 4. "Approved by the date" vs "approved ever"

These contracts resolve **No** on a CRL, a withdrawal, **or a PDUFA delay** past
the market date — so **Resolved No ≠ rejected.** Tracked separately as
`resolved_yes` (on-time) vs `eventually_approved` (ever).

- All resolved: **21/33 on time vs 22/33 ever.**
- CMC bucket: **1/8 on time but 2/8 ever** — CMC issues are often curable, just
  not on the market's timeline (`fig8`). Conclusions about "failure" must say
  *which* failure they mean.

## 5. "Already priced" — the alpha caveat

A risk the price already reflects is not an edge. Residual = outcome − price 7d
out (n=23 with a 7-day price): refiles **−0.14 (n=3)**, first-cycle **+0.11
(n=20)** — no systematic, sign-stable mispricing, and the refile mean is one
market (TLX250) deep (`fig9`). Any alpha claim must be made on the **residual**
vs the market price, never on the raw outcome, and must be out-of-sample.

## 6. Price-series and metric caveats (inherited from methodology.md)

- **Daily fidelity:** intraday blindsides are invisible in the daily series;
  `surprise` is engineered around this and a same-day collapse appears only as a
  confidently-wrong final price.
- **Sparse histories:** 3 resolved markets have a single daily point; 10 lack a
  point a full 7 days out — their `prob_7d`/`prob_1d` are legitimately blank, so
  calibration n (23) < resolved n (33).
- **Depth proxies:** `top_holder_pct`/`n_top_holders` come from a capped
  top-holders leaderboard (≤200) and `n_trades` from the ≤1000 most-recent
  trades — concentration is directional, exact only when the full set fits.
- **`pdufa_matches_market_date=no`** conflates clerical mismatch, PDUFA
  extension, and early approval — read `outcome`/`outcome_date`, not the flag.

## 7. Enrichment is human-labelled, point-in-time

Regulatory fields are web-researched with a cited `source_url` each, but they are
manual labels: subject to labelling error, point-in-time as of 2026-06-09, and —
critically for §1 — some (`risk_category`, `crl_reason_class`,
`manufacturing_inspection_required`) were assigned with knowledge of the outcome.
**`prior_crl` is not exempt:** it anchors the leakage-free analysis, yet TLX250's
value was hindsight-corrected no→yes and its `crl_date` is "approximate to month"
(Tebipenem's too) — so even the clean axis rests partly on revisable labels.
Two markets have ambiguous referents: **Truqap** (enrichment flags an
INDICATION DISCREPANCY) and **Camizestrant** (No via ODAC-against + extension);
both sit in the first-cycle cohort. `crl_date` for two refiles is approximate
(flagged in `enrichment_notes`).

## 8. The benchmark is a reference line, not truth

`benchmark.py` turns cited FDA *population* rates into a fair value. Honest
limits:

- **It loses to the crowd** (crowd Brier 0.137 vs benchmark 0.247, S7), so a
  gap vs the benchmark is a *hypothesis*, never a signal. Treat the benchmark as
  "what a transparent base rate would say," not "what's true."
- **Every coefficient is cited or derived — none is a guess.** Base rate (0.84)
  and the extension rate (6%) are directly cited; the novel-modality penalty is
  *arithmetically derived* from the cited 64%-vs-84% first-cycle figures; priority
  review is a cited null. Modifiers with **no published rate** — post-CRL
  resubmission success, gene/cell-specific rates, AdCom→extension, breakthrough
  causal effect — were **intentionally omitted, not estimated** (listed in
  `benchmark_params.json._meta.omitted`). Consequence: the benchmark is coarse
  (most dated markets get ≈0.79), which is *why* it loses to the crowd.
- **It abstains** on open-ended "approved this year" markets (no firm PDUFA → no
  pending-decision signal). Emitting a base rate there would be a false edge
  (e.g. Retatrutide). Abstention is the honest output; those rows are marked N/A.
- **Population ≠ this slate.** The cited rates come from the full FDA population;
  the Polymarket slate is a selection-biased subset (§3), so the benchmark is a
  population anchor applied to a non-random sample.

## 9. What `audit.py` does and does not prove

`audit.py` sections 1–8 prove **reproducibility** (the numbers are
self-consistent and the figures match the data). They do **not** prove
**validity**. Sections 9–11 add the validity layer (figure-equality, leakage
report, CIs) but cannot fix leakage that lives in the labels — they can only
*surface and quantify* it. A green audit means "computed correctly," never
"finding is sound."
