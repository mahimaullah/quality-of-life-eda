"""
validation_rules.py
===================
A reusable data integrity control framework.

The rules here are not specific to the Quality of Life dataset. Each is a
function over (DataFrame, column specification) that returns zero or more
exception records. A dataset is onboarded by writing a *specification* — which
columns are numeric, what range each one may occupy, which categorical domains
are legal — and the same ten controls then run against it unchanged.

Severity tiers
--------------
The tier answers one question: *if nobody looks at this, what happens?*

  TIER 1  CRITICAL  The defect changes analytical results and raises no error.
                    Nothing in the toolchain will tell you. Placeholder zeros
                    averaged as real values, and rows silently dropped by
                    `to_numeric(errors="coerce")`, both land here.
  TIER 2  HIGH      The defect blocks or distorts analysis but is visible once
                    you look — a numeric column stuck at object dtype, a value
                    outside its declared range.
  TIER 3  MEDIUM    Structural noise that survives into joins, filters and
                    chart legends — quote-wrapped categoricals, values outside
                    a declared domain.
  TIER 4  LOW       Genuine missing data. Expected, documented, not a defect —
                    but counted, because an undocumented change in the null
                    rate is itself a signal.

The distinction that matters is TIER 1 vs everything else. A TIER 2 defect
announces itself the first time you try to compute on it. A TIER 1 defect
produces a number that is wrong and looks fine.

Controls
--------
DQ-001  PLACEHOLDER_ZERO        0.0 standing in for missing data
DQ-002  EMBEDDED_PREFIX         numeric stored as text with a junk prefix
DQ-003  GROUPED_NUMERIC         numeric stored with thousands separators
DQ-004  QUOTE_WRAPPED           categorical wrapped in stray quote characters
DQ-005  REQUIRED_NULL           null in a field declared required
DQ-006  TYPE_DRIFT              declared-numeric column carrying object dtype
DQ-007  RANGE_VIOLATION         value outside its declared plausible range
DQ-008  COERCION_LOSS           rows a naive numeric coercion would drop
DQ-009  DOMAIN_VIOLATION        categorical value outside its declared domain
DQ-010  PAIR_INCONSISTENCY      value present without its category, or inverse
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

TIERS = {
    "DQ-001": ("TIER 1", "CRITICAL"),
    "DQ-008": ("TIER 1", "CRITICAL"),
    "DQ-006": ("TIER 1", "CRITICAL"),
    "DQ-002": ("TIER 2", "HIGH"),
    "DQ-003": ("TIER 2", "HIGH"),
    "DQ-007": ("TIER 2", "HIGH"),
    "DQ-004": ("TIER 3", "MEDIUM"),
    "DQ-009": ("TIER 3", "MEDIUM"),
    "DQ-010": ("TIER 3", "MEDIUM"),
    "DQ-005": ("TIER 4", "LOW"),
}

CONTROL_NAMES = {
    "DQ-001": "PLACEHOLDER_ZERO",
    "DQ-002": "EMBEDDED_PREFIX",
    "DQ-003": "GROUPED_NUMERIC",
    "DQ-004": "QUOTE_WRAPPED",
    "DQ-005": "REQUIRED_NULL",
    "DQ-006": "TYPE_DRIFT",
    "DQ-007": "RANGE_VIOLATION",
    "DQ-008": "COERCION_LOSS",
    "DQ-009": "DOMAIN_VIOLATION",
    "DQ-010": "PAIR_INCONSISTENCY",
}

REMEDIATION = {
    "DQ-001": "Replace the placeholder with NULL before any aggregation; never impute silently.",
    "DQ-002": "Strip the prefix with a whitelist regex, then parse; reject anything still unparseable.",
    "DQ-003": "Remove grouping separators before parsing; assert the parsed count equals the source count.",
    "DQ-004": "Strip the wrapping quote characters and re-assert the categorical domain.",
    "DQ-005": "Leave as NULL and document the coverage rate; do not fill.",
    "DQ-006": "Repair the underlying string defects, then cast explicitly and assert the dtype.",
    "DQ-007": "Quarantine the row and refer it to the source owner; do not clip to the boundary.",
    "DQ-008": "Never use errors='coerce' without reconciling the parsed count against the source count.",
    "DQ-009": "Map to the declared domain where the intent is unambiguous; otherwise quarantine.",
    "DQ-010": "Re-derive the category from the value using the published tier boundaries.",
}


# --------------------------------------------------------------------------- #
# Specification
# --------------------------------------------------------------------------- #
@dataclass
class ColumnSpec:
    """What a column is supposed to contain. The controls read this, not the data."""
    name: str
    kind: str                                  # "numeric" | "categorical" | "key"
    required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    domain: set[str] | None = None
    placeholder_values: tuple = ()              # values that mean "missing"
    pair_with: str | None = None                # companion value/category column


@dataclass
class DatasetSpec:
    name: str
    key: str
    columns: list[ColumnSpec]
    quote_chars: str = "'\""

    def by_name(self) -> dict[str, ColumnSpec]:
        return {c.name: c for c in self.columns}


# --------------------------------------------------------------------------- #
# Exception record
# --------------------------------------------------------------------------- #
EXC_COLUMNS = [
    "control_id", "control_name", "tier", "severity",
    "column", "key_value", "observed_value", "finding", "remediation",
]


def _exc(control_id, column, key_value, observed, finding) -> dict:
    tier, severity = TIERS[control_id]
    return dict(
        control_id=control_id, control_name=CONTROL_NAMES[control_id],
        tier=tier, severity=severity, column=column, key_value=key_value,
        observed_value=observed, finding=finding,
        remediation=REMEDIATION[control_id],
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
PREFIX_RE = re.compile(r"^\s*[^0-9\-+.]+\s*")          # leading junk before a number
GROUPED_RE = re.compile(r"^\s*-?\d{1,3}(,\d{3})+(\.\d+)?\s*$")


def _as_text(s: pd.Series) -> pd.Series:
    return s.astype("string")


def repair_numeric(raw: pd.Series) -> pd.Series:
    """
    Parse a numeric column that may carry junk prefixes, grouping separators and
    wrapping quotes. This is the *repaired* parse the COERCION_LOSS control is
    measured against.
    """
    t = _as_text(raw).str.strip().str.strip("'\"").str.strip()
    t = t.str.replace(PREFIX_RE, "", regex=True)
    t = t.str.replace(",", "", regex=False)
    return pd.to_numeric(t, errors="coerce")


def naive_numeric(raw: pd.Series) -> pd.Series:
    """The parse most people write. Kept here so the loss can be measured."""
    return pd.to_numeric(raw, errors="coerce")


# --------------------------------------------------------------------------- #
# Controls
# --------------------------------------------------------------------------- #
def dq001_placeholder_zero(df: pd.DataFrame, spec: DatasetSpec) -> list[dict]:
    out = []
    for c in spec.columns:
        if c.kind != "numeric" or not c.placeholder_values:
            continue
        parsed = repair_numeric(df[c.name])
        for ph in c.placeholder_values:
            hit = df[parsed == ph]
            real = parsed[(parsed != ph) & parsed.notna()]
            true_mean = float(real.mean()) if len(real) else float("nan")
            contaminated = float(parsed[parsed.notna()].mean()) if parsed.notna().any() else float("nan")
            for k in hit[spec.key]:
                out.append(_exc(
                    "DQ-001", c.name, k, ph,
                    f"{ph} is a missing-data placeholder, not an observation; "
                    f"averaging it yields {contaminated:.2f} against a true mean of {true_mean:.2f}"))
    return out


def dq002_embedded_prefix(df: pd.DataFrame, spec: DatasetSpec) -> list[dict]:
    out = []
    for c in spec.columns:
        if c.kind != "numeric":
            continue
        t = _as_text(df[c.name]).str.strip().str.strip("'\"")
        hit = t[t.notna() & t.str.contains(PREFIX_RE, regex=True, na=False)]
        for k, v in zip(df.loc[hit.index, spec.key], hit):
            out.append(_exc("DQ-002", c.name, k, v,
                            "numeric value stored as text behind a non-numeric prefix; "
                            "forces the whole column to object dtype"))
    return out


def dq003_grouped_numeric(df: pd.DataFrame, spec: DatasetSpec) -> list[dict]:
    out = []
    for c in spec.columns:
        if c.kind != "numeric":
            continue
        t = _as_text(df[c.name]).str.strip().str.strip("'\"")
        hit = t[t.notna() & t.str.match(GROUPED_RE, na=False)]
        for k, v in zip(df.loc[hit.index, spec.key], hit):
            out.append(_exc("DQ-003", c.name, k, v,
                            "numeric stored with thousands separators; a naive "
                            "pd.to_numeric(errors='coerce') discards it silently"))
    return out


def dq004_quote_wrapped(df: pd.DataFrame, spec: DatasetSpec) -> list[dict]:
    out = []
    for c in spec.columns:
        if c.kind != "categorical":
            continue
        t = _as_text(df[c.name])
        hit = t[t.notna() & t.str.match(rf"^\s*[{re.escape(spec.quote_chars)}].*[{re.escape(spec.quote_chars)}]\s*$", na=False)]
        if len(hit) == 0:
            continue
        out.append(_exc("DQ-004", c.name, f"{len(hit)} rows", hit.iloc[0],
                        f"{len(hit)} of {len(df)} values are wrapped in stray quote characters; "
                        f"the wrapped form will not join or filter against the clean form"))
    return out


def dq005_required_null(df: pd.DataFrame, spec: DatasetSpec) -> list[dict]:
    out = []
    for c in spec.columns:
        n = int(df[c.name].isna().sum())
        if n == 0:
            continue
        tier_note = "required field" if c.required else "optional field"
        out.append(_exc("DQ-005", c.name, f"{n} rows", None,
                        f"{n} of {len(df)} values are null ({n/len(df):.1%} of rows), {tier_note}"))
    return out


def dq006_type_drift(df: pd.DataFrame, spec: DatasetSpec) -> list[dict]:
    out = []
    for c in spec.columns:
        if c.kind != "numeric":
            continue
        if not pd.api.types.is_numeric_dtype(df[c.name]):
            out.append(_exc("DQ-006", c.name, "column", str(df[c.name].dtype),
                            f"declared numeric but carried as {df[c.name].dtype}; every "
                            f"arithmetic operation on it will either fail or coerce silently"))
    return out


def dq007_range_violation(df: pd.DataFrame, spec: DatasetSpec) -> list[dict]:
    out = []
    for c in spec.columns:
        if c.kind != "numeric" or (c.min_value is None and c.max_value is None):
            continue
        parsed = repair_numeric(df[c.name])
        lo = -np.inf if c.min_value is None else c.min_value
        hi = np.inf if c.max_value is None else c.max_value
        mask = parsed.notna() & ((parsed < lo) | (parsed > hi))
        # a declared placeholder is DQ-001's finding, not a range violation
        for ph in c.placeholder_values:
            mask &= parsed != ph
        for k, v in zip(df.loc[mask, spec.key], parsed[mask]):
            out.append(_exc("DQ-007", c.name, k, v,
                            f"outside the declared range [{c.min_value}, {c.max_value}]"))
    return out


def dq008_coercion_loss(df: pd.DataFrame, spec: DatasetSpec) -> list[dict]:
    """
    The headline control. Compare the naive parse against the repaired parse and
    report every row the naive parse would have thrown away without an error.
    """
    out = []
    for c in spec.columns:
        if c.kind != "numeric":
            continue
        naive = naive_numeric(df[c.name])
        fixed = repair_numeric(df[c.name])
        lost = fixed.notna() & naive.isna()
        if not lost.any():
            continue
        recovered = fixed[lost]
        naive_max = float(naive.max()) if naive.notna().any() else float("nan")
        fixed_max = float(fixed.max()) if fixed.notna().any() else float("nan")
        for k, v in zip(df.loc[lost, spec.key], recovered):
            note = (f"recoverable value {v:,.2f} is discarded by "
                    f"pd.to_numeric(errors='coerce') with no warning")
            if abs(fixed_max - naive_max) > 1e-9:
                note += (f"; the column maximum moves from {naive_max:,.2f} "
                         f"to {fixed_max:,.2f} once repaired")
            out.append(_exc("DQ-008", c.name, k, v, note))
    return out


def dq009_domain_violation(df: pd.DataFrame, spec: DatasetSpec) -> list[dict]:
    out = []
    for c in spec.columns:
        if c.kind != "categorical" or not c.domain:
            continue
        t = _as_text(df[c.name]).str.strip().str.strip(spec.quote_chars).str.strip()
        bad = t[t.notna() & ~t.isin(c.domain)]
        for k, v in zip(df.loc[bad.index, spec.key], bad):
            out.append(_exc("DQ-009", c.name, k, v,
                            f"value is outside the declared domain {sorted(c.domain)}"))
    return out


def dq010_pair_inconsistency(df: pd.DataFrame, spec: DatasetSpec) -> list[dict]:
    out = []
    specs = spec.by_name()
    for c in spec.columns:
        if not c.pair_with or c.pair_with not in specs:
            continue
        if c.kind != "numeric":
            continue
        value = repair_numeric(df[c.name])
        for ph in c.placeholder_values:
            value = value.mask(value == ph)
        cat = _as_text(df[c.pair_with]).str.strip().str.strip(spec.quote_chars)
        cat = cat.mask(cat.isin(["None", "nan", ""]))
        mismatch = value.notna() != cat.notna()
        for k, v, cv in zip(df.loc[mismatch, spec.key], value[mismatch], cat[mismatch]):
            side = "value present, category missing" if pd.notna(v) else "category present, value missing"
            out.append(_exc("DQ-010", c.name, k, v if pd.notna(v) else cv,
                            f"{side} ({c.name} / {c.pair_with})"))
    return out


CONTROLS: list[Callable[[pd.DataFrame, DatasetSpec], list[dict]]] = [
    dq001_placeholder_zero,
    dq002_embedded_prefix,
    dq003_grouped_numeric,
    dq004_quote_wrapped,
    dq005_required_null,
    dq006_type_drift,
    dq007_range_violation,
    dq008_coercion_loss,
    dq009_domain_violation,
    dq010_pair_inconsistency,
]


def run_controls(df: pd.DataFrame, spec: DatasetSpec) -> pd.DataFrame:
    """Run every control and return the severity-tiered exception report."""
    records: list[dict] = []
    for control in CONTROLS:
        records.extend(control(df, spec))
    report = pd.DataFrame(records, columns=EXC_COLUMNS)
    if report.empty:
        return report
    report.insert(0, "exception_id", [f"DQX{i:05d}" for i in range(1, len(report) + 1)])
    return report.sort_values(["tier", "control_id", "column", "key_value"]).reset_index(drop=True)


def control_summary(report: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """One row per control: tier, findings, columns affected, pass/fail."""
    rows = []
    for cid, cname in CONTROL_NAMES.items():
        tier, sev = TIERS[cid]
        hits = report[report["control_id"] == cid] if len(report) else report
        rows.append(dict(
            control_id=cid, control_name=cname, tier=tier, severity=sev,
            findings=len(hits),
            columns_affected=hits["column"].nunique() if len(hits) else 0,
            result="FAIL" if len(hits) else "PASS",
            remediation=REMEDIATION[cid],
        ))
    return pd.DataFrame(rows).sort_values(["tier", "control_id"]).reset_index(drop=True)
