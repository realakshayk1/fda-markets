"""
analysis_lib.py — shared, leakage-aware analysis primitives.

This module exists so the *validity* layer (figures + audit) computes rates the
same way everywhere, and so look-ahead bias is handled in exactly one place.

Two ideas drive everything here:

  (A) Reproducibility  — recompute numbers correctly and consistently.
  (B) Validity         — make sure a number actually supports the claim.

The functions below are validity-aware: every rate carries its n and a Wilson
95% interval, and every market is tagged PRE-KNOWABLE vs OUTCOME-DERIVED for the
feature used to bucket it.

Pure functions only; no plotting, no I/O side effects beyond reading the CSVs.
"""

import math

import pandas as pd

THEMATIC = {"fda-approves-a-psychedelic-for-medical-use-in-2026"}
BASE_RATE = 0.835
PROC = "fda_markets_processed.csv"


# --------------------------------------------------------------------------- #
# Uncertainty                                                                  #
# --------------------------------------------------------------------------- #
def wilson(k, n, z=1.96):
    """Wilson score interval for a binomial proportion k/n.

    Returns (point, lo, hi). For n == 0 returns (nan, 0, 1) — no information.
    Use this for EVERY rate. A bare '100%' or '0%' is forbidden in this repo;
    18/18 is point=1.0 but lo=0.824, and 0/3 is point=0 but hi=0.56.
    """
    if n == 0:
        return (float("nan"), 0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, centre - half), min(1.0, centre + half))
    # Reference values (used in docs/tests): wilson(18,18)=(1.0,0.8241,1.0);
    # wilson(1,3)=(0.333,0.061,0.792); wilson(20,30)=(0.667,0.486,0.807);
    # wilson(1,8)=(0.125,0.022,0.470).


def fmt_rate(k, n):
    """'k/n = NN% (Wilson95 [lo,hi]; ANECDOTAL if n<5)'."""
    p, lo, hi = wilson(k, n)
    tag = "  ANECDOTAL n<5" if n < 5 else ""
    if n == 0:
        return f"{k}/{n} = n/a{tag}"
    return f"{k}/{n} = {p:.0%} (Wilson95 [{lo:.0%},{hi:.0%}]){tag}"


ANECDOTAL_N = 5  # n below this is flagged anecdotal wherever a rate is used


# --------------------------------------------------------------------------- #
# Look-ahead / leakage classification                                         #
# --------------------------------------------------------------------------- #
# A feature value is PRE-KNOWABLE if it is derivable only from information that
# existed before the market's resolution. It is OUTCOME-DERIVED if assigning it
# required knowing what happened.
#
# risk_category is the offender. methodology.md §3 states the
# "CMC/manufacturing refile" bucket holds "refiles *and* first-cycle CMC CRLs",
# and "Clinical/efficacy" holds first-cycle efficacy CRLs. A *first-cycle* CRL
# is the market's OUTCOME — so any row placed in those buckets with no prior CRL
# was bucketed using the outcome. prior_crl == "yes" is the one unambiguously
# pre-knowable refile signal (a prior cycle's CRL existed before this market).

OUTCOME_DERIVED_BUCKETS = {"CMC/manufacturing refile", "Clinical/efficacy"}


def leakage_flag(row):
    """('PRE-KNOWABLE'|'OUTCOME-DERIVED', reason) for this row's risk_category.

    Rule: buckets that, by methodology, absorb first-cycle CRLs are PRE-KNOWABLE
    only when prior_crl == 'yes' (a genuine, pre-identifiable refile). Otherwise
    the row landed in a failure bucket *because* a CRL/Delay occurred.
    """
    rc = (row.get("risk_category") or "").strip()
    prior = (str(row.get("prior_crl")) or "").strip().lower()
    if rc in OUTCOME_DERIVED_BUCKETS:
        if prior == "yes":
            return ("PRE-KNOWABLE", "prior_crl=yes (genuine refile, identifiable pre-decision)")
        return ("OUTCOME-DERIVED",
                f"bucket '{rc}' but prior_crl={prior or 'no'} — assigned from the realized CRL/Delay")
    # Clean desk / Oncology sNDA / Timeline bet labels do not require the outcome,
    # but Clean desk is a *residual* bucket (failures are pulled out of it), so it
    # is survivorship-contaminated at the bucket boundary — see preknowable_axis.
    return ("PRE-KNOWABLE", f"bucket '{rc}' assignable from pre-decision facts")


def preknowable_axis(row):
    """A leakage-free risk axis built from ONE pre-decision field: prior_crl.

    Deliberately binary. An earlier version added a "Timeline bet (structural)"
    class keyed on whether a PDUFA date was firm — but whether a PDUFA later
    firmed up correlates with the outcome, so that rule re-imported look-ahead
    (the exact sin this module indicts). `prior_crl` (a prior cycle's CRL existed
    before this market) is the only field whose value is fixed before the market
    opens, independent of how it resolves.

    NOTE the "First-cycle (no prior CRL)" cohort is HETEROGENEOUS: it still
    contains markets that resolved No via a PDUFA *Delay* (EYLEA-HD, Sarclisa,
    Camizestrant) rather than a first-cycle adjudication. We do NOT route those
    out, because "it got delayed" is itself an outcome — excluding them would be
    the same leakage in reverse. The heterogeneity is reported, not hidden
    (see FINDINGS confound (d) / LIMITATIONS §4), and `prior_crl` itself is a
    revisable hand-label (LIMITATIONS §1/§7).
    """
    prior = (str(row.get("prior_crl")) or "").strip().lower()
    return "Prior-CRL refile" if prior == "yes" else "First-cycle (no prior CRL)"


# --------------------------------------------------------------------------- #
# Cohort loading                                                              #
# --------------------------------------------------------------------------- #
def _b(x):
    return str(x).strip().lower() == "true"


def load(path=PROC, drop_thematic=True):
    df = pd.read_csv(path, dtype=str)
    if drop_thematic:
        df = df[~df["slug"].isin(THEMATIC)].copy()
    df["is_closed"] = df["closed"].map(_b)
    df["is_yes"] = df["resolved_yes"].map(_b)
    for c in ("prob_7d", "prob_3d", "prob_1d", "yes_price", "price_vs_baserate",
              "brier_1d", "n_trades", "n_top_holders", "top_holder_pct"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ever"] = df["eventually_approved"].astype(str).str.strip().str.lower() == "yes"
    return df


def resolved(df):
    return df[df["is_closed"]].copy()


def open_slate(df):
    return df[~df["is_closed"]].copy()
