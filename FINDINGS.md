# FINDINGS — FDA prediction-market audit

**Purpose:** separate the conclusions the data supports from those it does not.
**Snapshot:** `fda_markets_processed.csv`, data date 2026-06-15. 34 resolved
drug-specific markets (thematic psychedelic market excluded), 9 open. (Welireg
was FDA-approved 2026-06-12 but its contract had not formally settled by the
snapshot, so it is recorded Approved in enrichment yet sits outside the 34
settled-cohort metrics — see LIMITATIONS §9.)
**Reproduce:** `python audit.py` (recomputes every number below and asserts the
figures match), `python make_figures.py` (writes `figures/`).

Two layers are kept separate throughout. **(A) Reproducibility** — the numbers
recompute consistently; `audit.py` sections 1–8 are green. **(B) Validity** —
whether a number supports its claim; sections 9–11. *A green reproducibility
check is necessary, not sufficient.* Every rate carries n and a Wilson 95% CI;
**n < 5 is labelled ANECDOTAL.**

---

## The one-paragraph verdict

The **specific** headline gradient — "clean reviews 18/18 = 100%, CMC refiles
1/9 = 11.1%" — is a look-ahead artifact of how the buckets were built, not a
forecastable signal. `risk_category` is not a pre-decision feature: by the
authors' own definition (methodology.md §3) the "CMC/manufacturing refile" and
"Clinical/efficacy" buckets absorb *first-cycle* CRLs — and a first-cycle CRL is
the market's **outcome**. 5 of the 9 "refiles" had **no prior CRL**; they were
filed into a "refile" bucket *because they failed*. Strip the leakage and the
pre-identifiable refile rate is **1/4 = 25%, Wilson 95% [5%, 70%], n = 4.**

Two honest consequences, and no more: (1) the dramatic 11.1%-vs-100% spread is
produced by routing first-cycle failures out of "Clean desk" into the failure
buckets — that part is demonstrable. (2) But de-leaking **removes the evidence
for** a refile penalty without **establishing its absence**: 1/4 vs 20/30 is two
under-powered cohorts whose CIs overlap ([5%,70%] vs [49%,81%]). The correct
verdict is **indeterminate**, not "refiles are fine" and not "refiles fail" —
the data cannot tell. **No mispricing is demonstrated beyond what the price
already reflects** at this sample size; the defensible findings are mostly
already priced (residual
test below).

---

## (i) SUPPORTED conclusions

Tier = ROBUST / SUGGESTIVE / ANECDOTAL. ANECDOTAL ⇒ n < 5 (or CI spanning most
of [0,1]); treat as a hypothesis, not a result.

| # | Conclusion | Tier | Evidence (n, Wilson 95% CI) |
|---|---|---|---|
| S1 | **The market is reasonably well-calibrated 1 day out.** | SUGGESTIVE | mean Brier 0.174 over n=25, measured 1 day before the actual FDA action (`outcome_date`, not the formal settlement — see LIMITATIONS §9). Good, but small n and the curve is sparse in the mid-buckets. |
| S2a | **"Resolved No" ≠ "rejected"** (definitional): a No can be a CRL, a withdrawal, *or* a PDUFA delay; the drug may still be approved later. | ROBUST | Resolution rules + enrichment decompose every No into `outcome` (methodology §1). Not cohort-dependent. |
| S2b | In *this* sample, **22/34 drugs were approved ever vs 21/34 on time.** | SUGGESTIVE | by-date 21/34 = 62% [45%,76%]; ever 22/34 = 65% [48%,79%] (fig8). The specific 1-drug gap is n=34, selection-biased — directional only. |
| S3 | **A prior-CRL refile resolved on time less often than a first-cycle review** in this sample. | ANECDOTAL | refile 1/4 = 25% [5%,70%] **(n=4)** vs first-cycle 20/30 = 67% [49%,81%] (fig6). The two CIs **overlap heavily** — directionally consistent with FDA priors but the data does **not** establish a real difference. Hypothesis, not result. |
| S4 | **Priority-review markets resolved on time more often than standard-review ones.** | SUGGESTIVE | priority 12/15 = 80% [55%,93%] vs standard 9/18 = 50% [29%,71%]. `review_type` is pre-knowable in principle but is a hand-label (`unknown` for Tebipenem) not put through the same leakage audit as `risk_category`; CIs overlap. Plausible, not established. |
| S5 | **The slate ran below the conventional ~83% base rate** (CMC/refile-heavy cohort). | SUGGESTIVE | all-resolved on-time 21/34 = 62% [45%,76%]; CI excludes 0.835. |
| S6 | **Markets can be confidently wrong intraday** (blindsides exist). | ANECDOTAL | `surprise` fires on a handful (fig3); each is n=1, illustrative not rate-bearing. TLX250 ~80%→CRL is the cleanest case. |
| S7 | **The crowd is sharper than a transparent FDA base rate.** A pre-registered benchmark whose coefficients are all cited/derived from real FDA data (`benchmark.py`) *loses* to the market out-of-sample. | SUGGESTIVE | crowd Brier **0.137** vs benchmark **0.258**; the base rate beat the crowd only **11/34** (win 32% [19%,49%], sign-test p≈0.06) — fig13. Evidence the new FDA markets are **roughly efficient**; a static base rate is not an edge. |

## (ii) TEMPTING conclusions the data does NOT support (or overstates)

Be exhaustive here — listing what the data does *not* support matters as much as listing what it does.

| # | Tempting claim | Why it fails |
|---|---|---|
| U1 | **"CMC/manufacturing refiles approve on time only 11.1% (1/9)."** | **Look-ahead leakage.** 5 of the 9 had `prior_crl=no` — they are first-cycle CRLs/Delays sorted into a *refile* bucket *because the CMC CRL happened* (EYLEA-HD wasn't even a CRL — a Delay with `crl_reason_class` blank). The pre-identifiable rate is **1/4 = 25% [5%,70%], n=4.** The "11.1%" is not a forecastable base rate; it is the failure set describing itself. |
| U2 | **"Clean first-cycle reviews approve on time 100% (18/18)."** | **Survivorship at the bucket boundary.** "Clean desk" is a *residual* category: any clean-looking drug that took a surprise CRL is reclassified into "Clinical/efficacy" or "CMC refile" and removed. So 18/18 is partly definitional. Even at face value it is **18/18 = 100%, Wilson 95% [82%, 100%]** (lower bound 0.824) — not "always." The pre-decision first-cycle rate that *keeps* the failures is **20/30 = 67% [49%,81%]** (this cohort is heterogeneous — see confound (d)). |
| U3 | **"The market forgot its lesson — short the open refiles."** | Fails four ways: (a) base rate is the contaminated 11.1%; the clean comparator is 1/4 = 25%, **n=4, CI [5%,70%]** — too small to support a directional read. (b) **Arcalyst, has `prior_crl=no`** — it is not a refile by the dataset's own flag. (c) The market price **is** the forecast; refiles' mean residual vs the 7-day price is **−0.33 (n=3)** — the market *over*-charged refile risk on average, the opposite of the thesis. (Oclaiz did resolve No on its factory, paying the short — but n=4 still cannot establish the pattern, and the residual shows the price had already charged it.) (d) Each refile may have fixed its specific CMC issue; the data cannot distinguish that from base-rate skepticism. |
| U4 | **"`manufacturing_inspection_required=yes` predicts failure (1/9)."** | The 9 inspection-required rows are **identical** to the contaminated CMC bucket. The flag is collinear with the outcome and cannot be certified pre-knowable from the data (it may have been set *because* the CRL cited a 483/inspection). Promising lead, but **unverifiable here** — do not trade it. |
| U5 | **"The risk gradient proves the market mis-prices regulatory risk."** | The gradient is mostly the leakage of U1–U2. After de-leaking, the only clean axis (prior_crl) has n=4 on the risky side. No mis-pricing is demonstrated *beyond what the price already encoded* (residual test, U3c). |
| U6 | **"64% on-time is the FDA base rate."** | This is a **selection-biased sample** of *drugs that got a Polymarket market* in 2025–26 — skewed toward contested, refile-heavy, retail-interesting decisions. It is not the population FDA first-cycle rate (~80–87%). n=34. |
| U7 | **"Single-order moves show manipulation."** | `single_order_move` is a thin-market signature, confirmed against `/trades` for a few names, but it shows *one wallet moved the price*, not intent or that the move was wrong. n is tiny; descriptive only. |
| U8 | **Any per-cell rate stated as a bare percentage** (100%, 0%, 11.1%). | Forbidden without n + CI. Every n<5 cell (Oncology sNDA n=2, Clinical/efficacy n=2, Timeline bet n≤3, all `designations` cells) is **ANECDOTAL** and must be labelled so wherever used. |
| U9 | **"`prior_crl=yes` is a clean ground-truth anchor."** | It is the *cleanest available* pre-decision signal, but still a **revisable hand-label**: TLX250's value was hindsight-**corrected** no→yes after researching a ~Nov-2024 first CRL (`crl_date` "approximate to month"); Tebipenem's `crl_date` is also approximate. The n=4 leakage-free refile set thus rests partly on 1 hindsight-corrected label (TLX250). Treat the 1/4 as fragile, not authoritative. |
| U10 | **Using Truqap / Camizestrant as clean first-cycle data points.** | Camizestrant resolved No via an **ODAC 6-3-against + PDUFA extension** (a substantive adverse-committee Delay, not a clean review); Truqap's enrichment flags an **INDICATION DISCREPANCY** — the market's breast-cancer referent may not match the only nearby FDA event (an unrelated mHSPC ODAC), so its referent is ambiguous. Both sit in the leakage-free first-cycle cohort and quietly drag 20/30; neither is a clean "first-cycle review." |
| U11 | **"The benchmark identifies mispricing on the open slate."** | It does not. After abstaining on the 2 timeline markets (benchmark has no pending-decision signal → would emit a false 0.84), the **largest gap vs the base rate is ~0.10** (Zoryve), one name, well inside the benchmark's own out-of-sample error (it loses to the crowd, S7). The open gaps in `edge_open.csv` are **hypotheses**, not signals — every name sits within ±0.10 of the base rate. |

---

## Confounds tested (§3 of the brief)

- **(a) Already priced?** Residual = outcome − price 7d out (markets with a
  7-day price, n=21, anchored to the actual FDA action). Refiles mean
  **−0.33 (n=3)**; first-cycle **+0.11 (n=18)**. Neither is a systematic,
  sign-stable edge — the refile mean is one
  market (TLX250) deep; the market had largely charged the gradient already
  (fig9). A gradient the price already reflects is not a mispricing.
- **(b) Selection / survivorship.** Markets exist only for decisions retail
  found interesting — contested refiles and brand-name drugs are
  over-represented; routine approvals under-represented. This *inflates* the
  apparent failure rate and is why 62% ≪ 83% (U6).
- **(c) By-date vs ever.** 21/34 on time, **22/34 ever** (S2, fig8). The refile
  cohort: 1/4 on-time *and* 1/4 ever in this n; the CMC bucket 1/9 on-time but
  **2/9 ever** — CMC problems are often curable, just not by the market's date.
- **(d) Heterogeneity.** The leakage-free "First-cycle (no prior CRL)" cohort is
  **not homogeneous**: it mixes true first-cycle adjudications with **3 PDUFA
  *Delays*** (EYLEA-HD, Sarclisa, Camizestrant) that resolved No on timing, not
  on a decision. Within it, outcomes also split by application type (across all
  resolved: BLA 3/8 = 38% [14%,69%] vs sBLA 6/7 = 86% [49%,97%], descriptive
  only) and review type (S4). A single bucket rate hides all of this — which is
  itself a reason not to over-read 20/30.

---

## Figures (each: the one question it answers, n)

Generated to `figures/` by `make_figures.py`; `audit.py §9` asserts every
plotted aggregation equals an independent recompute.

| File | Question it answers | n | Status |
|---|---|---|---|
| fig1_risk_inversion | What did the market charge vs realize, by risk_category? | 34 | **MISLEADING — annotated** with a leakage banner; kept for transparency only |
| fig2_calibration | Is the 1-day price calibrated? | 25 | defensible |
| fig3_surprises | Which markets were confident and wrong? | ~4 | illustrative (per-line n=1) |
| fig4_open_slate | How is the open slate priced vs base rate? | 9 | defensible (base rate is a prior, not ground truth) |
| fig5_depth | How thin/concentrated are these markets? | 44 | defensible |
| **fig6_leakage_free_gradient** | Does the gradient survive removing look-ahead? | 34 | **defensible — the honest version of fig1** |
| **fig7_leakage_artifact** | How much of "11.1%" is leakage? | 9 vs 4 | **defensible** |
| **fig8_bydate_vs_ever** | Is "No" rejection or just lateness? | 34 | **defensible** |
| **fig9_residual_vs_price** | Was the risk already priced? | 21 | **defensible — descriptive, n small** |
| **fig10_accuracy** | Was the crowd right at 7d/1d? (Red-Tilt-style, anchored to the FDA action) | 21–25 | defensible |
| **fig11_outcome_decomp** | How did "No" markets actually resolve (CRL vs Delay)? | 34 | defensible |
| **fig12_edge_map** | Open slate vs the cited base rate, depth-gated | 7 (+2 N/A) | defensible — gaps are hypotheses |
| **fig13_benchmark_vs_market** | Did a transparent base rate beat the crowd? | 34 | **defensible — the efficiency test (S7)** |

**Refused figures** (would imply false precision): a per-`designations` approval
chart (every cell n≤4), a per-`application_type` × `risk_category` heatmap (cells
of 0–2), and any projected-return / P&L curve (no out-of-sample, n=4 on the
signal side). Reason in each case: n too small to plot a rate without misleading.

---

## Defensible uses and next steps

What this dataset supports, stated objectively:

1. **A calibration scorecard of the market** (S1, S2): how well the prices matched
   outcomes, and where they systematically missed.
2. **One hypothesis worth testing:** refiles and inspection-gated reviews *may*
   resolve below their price. This is not established here — the only clean
   pre-decision signal (`prior_crl`) has n=3, and the apparent risk gradient is
   look-ahead-contaminated (U1–U2). It needs a leakage-free, out-of-sample test on
   a larger forward sample.

The most promising single lead is `manufacturing_inspection_required`, and only
after confirming each value was recorded from pre-decision information (FDA
inspection scheduling), not inferred from the CRL text.
