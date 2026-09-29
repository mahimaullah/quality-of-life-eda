"""
run_controls.py
===============
Applies the control framework in ``validation_rules.py`` to the Quality of Life
dataset, writes the severity-tiered exception report and the control summary,
then applies the documented remediations and re-runs the controls to prove the
repairs actually closed the findings.

Run:  python src/run_controls.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from validation_rules import (
    ColumnSpec, DatasetSpec, control_summary, repair_numeric, run_controls,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "output"

SOURCE = DATA / "Quality_of_Life.csv"

TIER_DOMAIN = {"Very Low", "Low", "Moderate", "High", "Very High"}

# These are relative indices benchmarked against a reference city, so they are
# not capped at 100 and a generous upper bound is the honest one. Property price
# to income is a ratio of median price to median annual income; published values
# run to roughly 100 in the most extreme markets, so anything far above that is
# a unit or scale problem in the source rather than a real observation.
#
# The bounds are declared from the source's definition, never derived from the
# data being checked — a threshold computed from its own input cannot fail.
METRICS = [
    ("Purchasing Power",         0.0, 300.0),
    ("Safety",                   0.0, 300.0),
    ("Health Care",              0.0, 300.0),
    ("Climate",                  0.0, 300.0),
    ("Cost of Living",           0.0, 300.0),
    ("Property Price to Income", 0.0, 200.0),
    ("Traffic Commute Time",     0.0, 300.0),
    ("Pollution",                0.0, 300.0),
    ("Quality of Life",          0.0, 300.0),
]


def build_spec() -> DatasetSpec:
    cols = [ColumnSpec(name="country", kind="key", required=True)]
    for metric, lo, hi in METRICS:
        value, category = f"{metric} Value", f"{metric} Category"
        cols.append(ColumnSpec(
            name=value, kind="numeric", required=True,
            min_value=lo, max_value=hi,
            placeholder_values=(0.0,),
            pair_with=category,
        ))
        cols.append(ColumnSpec(
            name=category, kind="categorical", required=False, domain=TIER_DOMAIN,
        ))
    return DatasetSpec(name="Quality of Life", key="country", columns=cols)


def remediate(df: pd.DataFrame, spec: DatasetSpec) -> pd.DataFrame:
    """Apply the remediation each control prescribes, in tier order."""
    clean = df.copy()
    for c in spec.columns:
        if c.kind == "numeric":
            parsed = repair_numeric(clean[c.name])          # DQ-002, DQ-003, DQ-008
            for ph in c.placeholder_values:                 # DQ-001
                parsed = parsed.mask(parsed == ph)
            clean[c.name] = parsed                          # DQ-006
        elif c.kind == "categorical":
            t = clean[c.name].astype("string").str.strip().str.strip("'\"").str.strip()
            clean[c.name] = t.mask(t.isin(["None", "nan", ""]))   # DQ-004
    return clean


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    spec = build_spec()
    raw = pd.read_csv(SOURCE)

    print(f"Source: {SOURCE.name}  |  {raw.shape[0]} rows x {raw.shape[1]} columns "
          f"= {raw.shape[0] * raw.shape[1]:,} cells\n")

    # ---- pre-remediation pass -------------------------------------------
    report = run_controls(raw, spec)
    summary = control_summary(report, raw)
    report.to_csv(OUT / "data_quality_exceptions.csv", index=False)
    summary.to_csv(OUT / "control_summary.csv", index=False)

    by_tier = (report.groupby(["tier", "severity"], observed=True)
               .agg(findings=("exception_id", "count"),
                    controls=("control_id", "nunique"),
                    columns=("column", "nunique"))
               .reset_index())

    print("CONTROL SUMMARY — pre-remediation")
    print(summary[["control_id", "control_name", "tier", "severity",
                   "findings", "columns_affected", "result"]].to_string(index=False))
    print(f"\nFINDINGS BY TIER")
    print(by_tier.to_string(index=False))
    print(f"\nTotal findings: {len(report):,} across "
          f"{summary['result'].eq('FAIL').sum()} failing controls of {len(summary)}")

    # ---- the number that makes the case ---------------------------------
    qol = repair_numeric(raw["Quality of Life Value"])
    contaminated = float(qol.mean())
    true_mean = float(qol[qol != 0.0].mean())
    ppi_naive = pd.to_numeric(raw["Property Price to Income Value"], errors="coerce")
    ppi_fixed = repair_numeric(raw["Property Price to Income Value"])
    print(f"\nTIER 1 IMPACT")
    print(f"  placeholder zeros in Quality of Life Value: "
          f"{int((qol == 0.0).sum())} of {len(qol)}")
    print(f"    mean including placeholders  {contaminated:8.2f}")
    print(f"    mean excluding placeholders  {true_mean:8.2f}"
          f"   ({(true_mean - contaminated)/true_mean:.1%} understatement)")
    print(f"  Property Price to Income maximum")
    print(f"    naive  pd.to_numeric(errors='coerce')  {ppi_naive.max():8.2f}")
    print(f"    repaired parse                         {ppi_fixed.max():8.2f}")
    print(f"    rows silently discarded by the naive parse: "
          f"{int((ppi_fixed.notna() & ppi_naive.isna()).sum())}")

    # ---- remediate and re-run -------------------------------------------
    clean = remediate(raw, spec)
    post = run_controls(clean, spec)
    post_summary = control_summary(post, clean)
    clean.to_csv(OUT / "quality_of_life_controlled.csv", index=False)
    post.to_csv(OUT / "data_quality_exceptions_post_remediation.csv", index=False)
    post_summary.to_csv(OUT / "control_summary_post_remediation.csv", index=False)

    print("\nCONTROL SUMMARY — post-remediation")
    print(post_summary[["control_id", "control_name", "tier", "severity",
                        "findings", "result"]].to_string(index=False))

    open_tier1 = post[post["tier"] == "TIER 1"]
    print(f"\nTier 1 findings: {len(report[report['tier'] == 'TIER 1']):,} before, "
          f"{len(open_tier1):,} after remediation")
    print("Findings that remain open by design:")
    print("  DQ-007  out-of-range values are quarantined and referred to the source")
    print("          owner, never clipped to the boundary")
    print("  DQ-010  rows where a placeholder zero coincides with a populated tier")
    print("          are ambiguous, not certainly missing — the category column is an")
    print("          independent witness and the two disagree")
    print("  DQ-005  genuine missing data is reported and documented, never filled")

    complete = clean.dropna(subset=[f"{m} Value" for m, _, _ in METRICS
                                    if m in {"Quality of Life", "Purchasing Power",
                                             "Cost of Living", "Health Care",
                                             "Safety", "Pollution"}])
    print(f"\nCertified working set: {len(complete)} countries with complete data on "
          f"the six analysed metrics (from {len(raw)} source rows)")

    print(f"\nWrote:")
    for f in ["data_quality_exceptions.csv", "control_summary.csv",
              "quality_of_life_controlled.csv",
              "data_quality_exceptions_post_remediation.csv",
              "control_summary_post_remediation.csv"]:
        print(f"  output/{f}")


if __name__ == "__main__":
    main()
