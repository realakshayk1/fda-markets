"""
build_enrichment.py — converts the hand-researched enrichment_data.json
(one cited record per market slug) into the flat enrichment.csv consumed by
enrich_markets.py. Keeping the source as JSON preserves the provenance/notes
verbatim and makes the regulatory-research layer reproducible.

Usage: python build_enrichment.py
"""

import csv
import json

from enrich_markets import ENRICH_FIELDS

with open("enrichment_data.json", encoding="utf-8") as f:
    records = json.load(f)

with open("enrichment.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=ENRICH_FIELDS)
    w.writeheader()
    for r in records:
        w.writerow({k: r.get(k, "") for k in ENRICH_FIELDS})

print(f"Wrote enrichment.csv: {len(records)} rows, {len(ENRICH_FIELDS)} columns")
