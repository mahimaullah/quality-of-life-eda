# SOP — Data Integrity Controls for Inbound Reference Datasets

| | |
|---|---|
| **Document ref** | DQ/SOP/CTRL-2026-01 |
| **Version** | 1.0 |
| **Owner** | Data Analyst — reference data |
| **Applies to** | Any externally sourced tabular dataset before analysis or publication |
| **Review** | On every source refresh, or quarterly, whichever is sooner |

---

## 1. Purpose

Defines the controls that must run against an inbound dataset before it is used
for analysis, and the action required for each class of finding. The control is
preventative: defects are detected and dispositioned *before* the data reaches a
model, a dashboard or a decision, not explained afterwards.

## 2. Principle

Rank defects by what happens if nobody looks.

A defect that raises an error is an inconvenience — the toolchain stops and
someone fixes it. A defect that produces a plausible wrong number and raises
nothing is a control failure. Tier 1 exists for the second kind, and Tier 1
findings block release.

## 3. Control set

| ID | Control | Tier | Detects |
|---|---|---|---|
| DQ-001 | PLACEHOLDER_ZERO | 1 | a sentinel value (`0.0`, `-1`, `9999`) standing in for missing data |
| DQ-006 | TYPE_DRIFT | 1 | a declared-numeric column carried as object dtype |
| DQ-008 | COERCION_LOSS | 1 | rows a naive `to_numeric(errors="coerce")` discards without warning |
| DQ-002 | EMBEDDED_PREFIX | 2 | numeric stored as text behind a non-numeric prefix |
| DQ-003 | GROUPED_NUMERIC | 2 | numeric stored with thousands separators |
| DQ-007 | RANGE_VIOLATION | 2 | value outside the range the source's own definition allows |
| DQ-004 | QUOTE_WRAPPED | 3 | categorical wrapped in stray quote characters |
| DQ-009 | DOMAIN_VIOLATION | 3 | categorical outside its declared domain |
| DQ-010 | PAIR_INCONSISTENCY | 3 | a value present without its category, or the reverse |
| DQ-005 | REQUIRED_NULL | 4 | genuine missing data |

Thresholds and domains are declared in the dataset **specification**, from the
source's published definition. A threshold derived from the data it is checking
cannot fail and is not a control.

## 4. Procedure

1. **Specify.** Write the `DatasetSpec`: for each column, its kind, whether it is
   required, its plausible range, its categorical domain, its sentinel values,
   and its paired value/category partner.
2. **Run.** `python src/run_controls.py`. This writes
   `output/data_quality_exceptions.csv` (row level) and
   `output/control_summary.csv` (control level, PASS/FAIL).
3. **Disposition** every finding per §5. Nothing is closed silently.
4. **Remediate** in tier order, applying only the prescribed action.
5. **Re-run** the full control set against the remediated file. A remediation
   that does not close its control is not a remediation.
6. **Certify.** Record the source row count, the certified working-set row
   count, and any control still failing with the reason it is accepted.
7. **Release.** Publish `quality_of_life_controlled.csv` together with both
   control summaries. The dataset does not travel without its control report.

## 5. Disposition rules

| Tier | Action | Release |
|---|---|---|
| 1 | Remediate before any aggregation. Never impute a sentinel. Never coerce without reconciling the parsed count against the source count. | **Blocked** until zero |
| 2 | Repair parseable defects. Quarantine out-of-range rows and refer them to the source owner — **never clip to the boundary**, which converts a visible data problem into an invisible one. | Blocked unless each open item is accepted in writing |
| 3 | Normalise structural noise. Where a value and its category disagree, treat the row as *ambiguous*, not missing — the category is an independent witness. | Permitted with the open list attached |
| 4 | Report the null rate. Do not fill. An undocumented change in the null rate between refreshes is itself a signal. | Permitted |

## 6. Evidence

Each run produces, and each must be retained with the released dataset:

- `data_quality_exceptions.csv` — one row per finding: control, tier, column,
  key, observed value, finding, prescribed remediation
- `control_summary.csv` — one row per control: findings, columns affected, PASS/FAIL
- the same two files re-run post-remediation
- `quality_of_life_controlled.csv` — the certified dataset

## 7. Result of the current run

Source: 236 rows × 19 columns = 4,484 cells.

| | Pre | Post |
|---|---|---|
| Total findings | 694 | 36 |
| Tier 1 (Critical) | 541 | **0** |
| Controls failing | 9 of 10 | 3 of 10 |

Material Tier 1 impact prevented:

- **125 of 236** Quality of Life values were `0.0` placeholders. Averaged as
  observations they give a mean of **63.47** against a true mean of **134.94** —
  a **53.0% understatement** of the headline metric.
- **3 rows** of Property Price to Income carried thousands separators and were
  discarded silently by `pd.to_numeric(errors="coerce")`. They are the three
  largest values in the column: the observed maximum moves from **450.40** to
  **2,746.00** once recovered — a **6.1×** change to the column's range from
  three rows nobody was told about.
- **114 values** were stored behind a `': '` prefix, holding the column at
  object dtype and making every arithmetic operation on it either fail or
  coerce.

Open by design after remediation: 8 range violations quarantined for source
referral, 10 ambiguous value/category pairs, 18 documented nulls.

Certified working set: **111 countries** with complete data across the six
analysed metrics.
