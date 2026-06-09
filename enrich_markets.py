"""
enrich_markets.py — Stage 2 of the FDA-markets pipeline.

Merges the hand-researched regulatory metadata (enrichment.csv — one row per
market `slug`, every value backed by a cited source URL) into the raw Gamma
pull, producing fda_markets_enriched.csv.

The enrichment fields are the "manual label" layer: they cannot be scraped from
the market JSON and must be researched from primary sources (company IR / press
releases, FDA.gov approvals + AdCom calendar, Endpoints, Fierce, BioPharma Dive,
drugs.com, etc.). See methodology.md for field definitions and the controlled
vocabularies.

Usage:
    python enrich_markets.py

Inputs:
    fda_markets_raw.csv   (from fetch_markets.py)
    enrichment.csv        (hand-researched; keyed by slug)
Output:
    fda_markets_enriched.csv
"""

import sys
import pandas as pd

RAW = "fda_markets_raw.csv"
ENRICH = "enrichment.csv"
OUT = "fda_markets_enriched.csv"

# Controlled enrichment schema. Order = column order in the output.
ENRICH_FIELDS = [
    "slug",                              # join key
    "sponsor",
    "drug",
    "indication",
    "application_type",                  # NDA/sNDA/BLA/sBLA/505(b)(2)/ANDA/biosimilar/mfg-supplement
    "pdufa_date",                        # primary-source verified
    "pdufa_matches_market_date",         # yes/no — does market resolve-by == true PDUFA
    "review_type",                       # standard/priority
    "designations",                      # Breakthrough/Fast Track/QIDP/Orphan/Priority Voucher (semi-colon list)
    "prior_crl",                         # yes/no  -- THE thesis variable
    "crl_date",
    "crl_reason_class",                  # CMC/manufacturing | clinical/efficacy | safety | nonclinical
    "manufacturing_inspection_required", # yes/no
    "inspection_location",               # domestic/foreign
    "adcom_scheduled",                   # yes/no/date
    "risk_category",                     # Clean desk review | CMC/manufacturing refile | Oncology sNDA | Timeline bet
    "outcome",                           # Approved | CRL | Delay | Withdrawn | (blank for open)
    "outcome_date",
    "outcome_reason",
    "eventually_approved",               # yes/no/pending — approved at all (may be later than market date)
    "eventually_approved_date",
    "source_url",                        # primary citation(s), semicolon-separated
    "enrichment_notes",
]


def main():
    raw = pd.read_csv(RAW, dtype=str)
    try:
        enr = pd.read_csv(ENRICH, dtype=str)
    except FileNotFoundError:
        print(f"ERROR: {ENRICH} not found. Build it from web research first "
              f"(see methodology.md for the field spec).", file=sys.stderr)
        sys.exit(1)

    missing = [c for c in ENRICH_FIELDS if c not in enr.columns]
    if missing:
        print(f"WARNING: enrichment.csv missing columns: {missing}", file=sys.stderr)
        for c in missing:
            enr[c] = pd.NA

    enr = enr[[c for c in ENRICH_FIELDS if c in enr.columns]]

    merged = raw.merge(enr, on="slug", how="left", suffixes=("", "_enr"))

    n_enriched = merged["sponsor"].notna().sum()
    print(f"Raw markets: {len(raw)}  |  enrichment rows: {len(enr)}  |  "
          f"matched: {n_enriched}")

    unmatched = raw.loc[~raw["slug"].isin(enr["slug"]), "title"].tolist()
    if unmatched:
        print(f"{len(unmatched)} markets without enrichment:")
        for t in unmatched:
            print(f"   - {t}")

    merged.to_csv(OUT, index=False, encoding="utf-8")
    print(f"Wrote {OUT}: {len(merged)} rows, {len(merged.columns)} columns")


if __name__ == "__main__":
    main()
