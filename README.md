# Quality of Life: A Data Integrity Control Framework

An exploratory analysis of quality-of-life indicators across **236 countries and territories**,
and, specifically, a case study in what has to happen to a dataset before any of its numbers
can be trusted. What started as a one-off cleanup is now a reusable control framework: 10 written
controls, 4 severity tiers, and a one-page SOP.

**Stack:** Python · pandas · NumPy · seaborn · Matplotlib · Tableau

**Dashboard:** [What Makes a Country Good To Live In? (Tableau Public)](https://public.tableau.com/app/profile/mahima.ullah/viz/WhatMakesaCountryGoodtoLiveIn/Dashboard1)

---

## The problem

The raw file looks clean in a spreadsheet and is not. Across 4,484 cells there are five distinct
defect classes, most of which fail silently — they produce plausible-looking numbers rather than
errors:

| Defect | Scale | Why it matters |
|---|---|---|
| `0.0` used as a "no data" placeholder | **125 of 236** countries in the Quality of Life column | Averaged in as a real score, it drags the mean from **134.94** down to **63.47** — understating it by **53%** |
| Values stored as `': 104.16'` — a stray colon-space prefix | **114** rows | Forces the whole column to `object` dtype; casts to `NaN` under a naive numeric conversion |
| Numbers quoted with thousands separators (`'2,746.00'`) | **3** rows | Silently dropped by `pd.to_numeric(errors='coerce')`, and they are the three largest values in the column — losing them cuts the observed maximum from **2,746.00** to **450.40** |
| Category labels wrapped in stray single quotes (`'Very High'`) | **9** columns | Breaks grouping, filtering and joins on every categorical field |
| Placeholder zero alongside a populated tier category | **10** rows | The category column is an independent witness to the value column. Where they disagree, the row is *ambiguous*, not certainly missing |

Plus 412 genuine nulls concentrated in two columns (Climate Category and Quality of Life Category
are each missing 122 values).

## What the cleaning does

The pipeline strips the quote and colon artifacts before casting, removes thousands separators so
the three largest property-price values survive the conversion, converts placeholder zeros to true
nulls so they are excluded from aggregates rather than averaged into them, and normalizes the nine
category columns. **111 countries** are left with a complete, trustworthy Quality of Life score —
the honest denominator for anything that follows.

> The `errors='coerce'` → `NaN` path is the interesting failure here. It doesn't raise, it doesn't
> warn, and the resulting column looks fine. The three lost rows were only visible by diffing
> non-null counts before and after the cast.

## The control framework

A cleanup fixes one file once. A control catches the same defect the next time, in any file. Each
of the **10 controls** is written as a specification — a detection rule plus a prescribed
remediation — and assigned to one of **4 severity tiers**. The controls are dataset-agnostic: the
rules live in the specification, not in code tied to this file's column names.

The tiering rests on one distinction. A defect that raises an error is an inconvenience. A defect
that produces a plausible wrong number and raises nothing is a control failure. The silent ones
sit in **Tier 1 (Critical)**.

| | Before cleaning | After cleaning |
|---|---|---|
| Total findings | **694** | **36** |
| Tier 1 (Critical) findings | **541** | **0** |
| Controls failing | 9 of 10 | 3 of 10 |

Out-of-range values are quarantined and referred, never clipped to the boundary. Clipping turns a
visible data problem into an invisible one.

The fifth defect class in the table above was found *by* this framework. It only became visible
once the controls were written down and cross-checked against each other.

Disposition and preventive action are documented in a one-page SOP:
[`docs/SOP-data-integrity-controls.md`](docs/SOP-data-integrity-controls.md) (ref. DQ/SOP/CTRL-2026-01).

## Findings

Across the 111 countries with complete data, **purchasing power is the strongest positive correlate
of quality of life (r = 0.87)** and **pollution the strongest negative one (r = −0.81)** — the two
are nearly equal in magnitude, meaning environmental quality tracks quality of life about as tightly
as economic power does. Cost of living (r = 0.67), health care (r = 0.59) and safety (r = 0.57)
follow. Notably, safety — the intuitive first guess for what makes somewhere good to live — is the
*weakest* of the five.

## Files

| File | What it is |
|---|---|
| `quality_of_life_eda.ipynb` | The full exploratory analysis — inspection, cleaning, four visualizations |
| `Quality_of_Life.csv` | Raw source data, defects intact |
| `quality_of_life_tableau.csv` | Cleaned and typed output, ready for BI tools |
| `docs/SOP-data-integrity-controls.md` | One-page SOP: the 10 controls, severity tiers, disposition and preventive action |

## Reproducing this

```bash
pip install -r requirements.txt
jupyter lab quality_of_life_eda.ipynb
```

## Limitations

The source is crowd-sourced index data, so scores reflect contributor perception and sample depth
rather than official statistics — small territories with few respondents can swing hard. The 125
countries without a Quality of Life score are not missing at random either; they skew toward small
territories and lower-coverage regions, so the 111-country working set is not a neutral sample of
the world. Correlations here are descriptive only: purchasing power and pollution are themselves
related (r = −0.64 across the 111 countries), so neither coefficient should be read as an
independent effect.

---

*Original analysis built for Data Analysis coursework, Rutgers University. Control framework and
SOP added September 2026.*
