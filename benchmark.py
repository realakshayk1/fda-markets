"""
benchmark.py — a transparent, pre-registered FDA-population fair value.

Turns published FDA population statistics (benchmark_params.json, in turn cited
to population/fda_reference_rates.csv) into a fair price for each market, using
ONLY pre-decision inputs. It is a *reference line* — a defensible base rate to
measure the crowd against — NOT ground truth. Its own out-of-sample error is
reported by edge.py.

Leakage safety is structural: `ALLOWED_INPUTS` whitelists pre-decision columns
only, and `_read(row, key)` refuses any key outside it, so the model physically
cannot read an outcome. audit.py §12 asserts this and scans the source.

    from benchmark import load_params, fair_value
    fv = fair_value(row, load_params())   # -> FairValue(p_ever, p_on_time, fair_price, rationale)

Pure & deterministic: reads one JSON, no other I/O, no randomness.
"""

import json
import math
from collections import namedtuple

PARAMS_PATH = "benchmark_params.json"

# Pre-decision inputs ONLY. Everything the model is allowed to look at. Note
# `manufacturing_inspection_required` is deliberately EXCLUDED — the validity
# audit found it collinear with the realized CMC outcome (can't be certified
# pre-knowable), so it must not feed a leakage-safe benchmark.
ALLOWED_INPUTS = frozenset({
    "application_type", "review_type", "designations", "prior_crl",
    "pdufa_date", "pdufa_matches_market_date", "end_date", "adcom_scheduled",
    "drug", "indication",
})

# Columns the benchmark must NEVER read (outcome / price / realized state).
FORBIDDEN_INPUTS = frozenset({
    "outcome", "outcome_date", "outcome_reason", "resolved_yes", "closed",
    "crl_reason_class", "crl_date", "eventually_approved", "eventually_approved_date",
    "yes_price", "no_price", "last_trade_price", "prob_7d", "prob_3d", "prob_1d",
    "correct_7d", "correct_1d", "brier_1d", "surprise", "manufacturing_inspection_required",
})

FairValue = namedtuple("FairValue", ["p_ever", "p_on_time", "fair_price", "rationale"])


def load_params(path=PARAMS_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read(row, key):
    """Whitelisted accessor — refuses any non-pre-decision column."""
    if key not in ALLOWED_INPUTS:
        raise KeyError(f"benchmark may not read non-pre-decision column {key!r}")
    try:
        v = row.get(key)
    except AttributeError:
        v = row[key]
    return "" if v is None else str(v).strip()


def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def classify_modality(row, params):
    text = (_read(row, "drug") + " " + _read(row, "indication")).lower()
    rules = params.get("modality_rules", {})
    for kw in rules.get("gene_cell", []):
        if kw in text:
            return "gene_cell"
    return "other"


def _designations(row):
    return _read(row, "designations").lower()


def p_approved_ever(row, params):
    """First-action approval probability from CITED/DERIVED modifiers only.

    Only two terms exist, both grounded (see benchmark_params.json): a priority
    review null (cited as non-causal) and the novel-mechanism penalty (derived
    from the FDA First-Cycle evaluation's 64% vs 84%). Modifiers with no published
    rate (prior_crl, breakthrough, 505b2) are intentionally absent, not guessed.
    """
    lo = params["base_first_cycle_approval"]["logodds"]
    mods = params["approval_modifiers_logodds"]
    applied = []

    if _read(row, "review_type").lower() == "priority":
        lo += mods["priority_review"]["value"]
        applied.append(("priority_review", mods["priority_review"]["value"]))
    if classify_modality(row, params) == "gene_cell":
        lo += mods["modality_novel_mechanism"]["value"]
        applied.append(("modality_novel_mechanism", mods["modality_novel_mechanism"]["value"]))

    return _sigmoid(lo), applied


def p_on_time_given_approved(row, params):
    """Probability the action lands by the market date (1 - cited extension rate).

    No per-market timing modifiers: there is no published AdCom->extension rate to
    ground one, so the flat cited slip rate is used for every dated market.
    """
    rate = min(max(params["extension_rate"]["value"], 0.0), 1.0)
    return 1.0 - rate, []


def _is_open_ended(row):
    """Year-deadline markets with no firm imminent PDUFA: timing isn't the gate
    in the same way (e.g. 'FDA approves X this year'). Detected pre-decision from
    a missing/unknown PDUFA date plus a year-end resolve-by."""
    pdufa = _read(row, "pdufa_date").lower()
    end = _read(row, "end_date")
    return pdufa in ("", "unknown", "nan", "n/a") and (end.startswith("2026-12") or end.startswith("2025-12"))


def fair_value(row, params):
    # ABSTAIN on open-ended "will X be approved this year" markets: the base rate
    # assumes an application is under review with a decision dated near the market.
    # For a year-end bet with no firm PDUFA, the benchmark has no signal on whether
    # a decision is even pending — emitting 0.84 would be a false edge (e.g.
    # Retatrutide). Returning None is the honest answer; edge.py marks it N/A.
    if _is_open_ended(row):
        p_ever, _ = p_approved_ever(row, params)
        return FairValue(round(p_ever, 4), None, None,
                         "benchmark N/A: open-ended year-end market with no firm PDUFA decision "
                         "dated in-window — base rate does not apply (no pending decision signal)")
    p_ever, approval_terms = p_approved_ever(row, params)
    p_on_time, timing_terms = p_on_time_given_approved(row, params)
    fair = p_ever * p_on_time

    base_p = params["base_first_cycle_approval"]["p"]
    parts = [f"base first-cycle approval {base_p:.2f}"]
    parts += [f"{name} ({val:+.2f} logodds)" for name, val in approval_terms]
    parts.append(f"=> P(approved)={p_ever:.2f}")
    parts += [f"timing {name} x{val}" if isinstance(val, (int, float)) else f"timing {name}: {val}"
              for name, val in timing_terms]
    parts.append(f"=> P(on time)={p_on_time:.2f}; fair={fair:.3f}")
    return FairValue(round(p_ever, 4), round(p_on_time, 4), round(fair, 4), "; ".join(parts))


# --------------------------------------------------------------------------- #
# Self-test: deterministic hand-worked examples (run `python benchmark.py`).   #
# --------------------------------------------------------------------------- #
def _selftest():
    params = load_params()
    # A clean priority NDA, firm PDUFA: fair = base * (1 - extension_rate).
    clean = {"application_type": "NDA", "review_type": "priority", "designations": "none",
             "prior_crl": "no", "pdufa_date": "2026-06-30", "end_date": "2026-06-30T00:00:00Z",
             "adcom_scheduled": "no", "drug": "Example", "indication": "X"}
    fv = fair_value(clean, params)
    er = params["extension_rate"]["value"]
    assert abs(fv.p_ever - 0.84) < 0.01, fv
    assert abs(fv.p_on_time - (1 - er)) < 0.001, fv
    assert abs(fv.fair_price - round(0.84 * (1 - er), 4)) < 0.005, fv

    # A gene therapy should price lower via the cited novel-mechanism penalty.
    gene = dict(clean, drug="AAV9 gene therapy", application_type="BLA")
    fv2 = fair_value(gene, params)
    assert fv2.fair_price < fv.fair_price - 0.1, (fv, fv2)

    # Leakage guard: reading an outcome column must raise.
    try:
        _read(clean, "outcome")
        raise AssertionError("ALLOWED_INPUTS did not block 'outcome'")
    except KeyError:
        pass
    print("benchmark self-test PASS")
    print("  clean priority NDA :", fv.fair_price, "|", fv.rationale)
    print("  gene-therapy refile:", fv2.fair_price, "|", fv2.rationale)


if __name__ == "__main__":
    _selftest()
