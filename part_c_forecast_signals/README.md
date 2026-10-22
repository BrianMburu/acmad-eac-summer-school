# Part C: Did the forecast see it coming?

Inspired by `python-workshop/exercises/06_forecast_vs_local_extremes.py`.
Five towns come from Part A's `grid.json`: Khartoum, Kassala, Gedaref, El Obeid,
and Nyala. Thresholds are the 2-year 24 h levels in Part A's `thresholds.csv`.
Default initialization window: **6–26 July 2025**, inclusive (21 starts).
Change `--start` and `--end` for another inclusive 14–21-day window in JJA.
Each start has its available daily forecast intervals, normally days 1–10.

Run from the repository, using the already installed Part A environment:

```sh
cd /Users/mac/Group1/acmad-eac-summer-school
../part_a_extremes/.venv312/bin/python -u part_c_forecast_signals/analyze.py
```

No new dependencies are required beyond Part A. For a new environment install
`part_c_forecast_signals/requirements.txt`. This run can take several minutes:
21 starts × 11 daily cumulative endpoints = up to 231 map-sized chunk reads.
All five towns are extracted together per start. It selects initialization,
daily steps and town points before computing. There is no full-season download.
Each completed start is cached under `cache/`; rerun the same command to resume.
After the complete extraction, `--offline` regenerates outputs from local caches.

## Outputs saved in this folder

- Five `*_heatmap.png` figures: rows are start dates, columns are forecast days;
  color and positive-cell labels show members above the local threshold, of 51.
  All towns share the same color scale. Gray cells are missing/incomplete data.
- Five `*_strongest_start_plume.png` figures: all members' **daily** rainfall,
  ensemble mean and threshold for that town's strongest initialization.
- `daily_member_counts.csv`: every town/start/day count, valid interval and availability.
- `town_signal_summary.csv`: peak counts, strongest start, earliest lead and persistence.
- `same_valid_day_signals.csv`: signal history across starts targeting the same valid interval.
- `quality_control.csv`: counts of tiny negative increments corrected per start.
- `results.txt`: numerical ranking and explanation, including limitations.
- `run_metadata.json`: source-domain checks, thresholds, script hash, Git commit and QC tolerance.

If a town has no available forecast data, its summary says so and no plume can
be generated. All-zero available forecasts are retained and explicitly labeled.

## Interpretation

Daily rainfall is `(cumulative_tp_end - cumulative_tp_start) × 1000`, in **mm
in 24 h**. Count units are **members**, using strict `>` against the threshold.
Forecast latitude must descend; CMORPH latitude must ascend. Before rainfall
extraction, coordinate metadata verify all towns lie in both domains and Part A
uses the matching nearest CMORPH pixels. Nearest grids have different footprints.
Negative increments up to 0.05 mm are set to zero with a recorded count; larger
decreases stop execution. A missing member makes that whole town/day unavailable.

An exploratory signal defaults to at least **1 of 51 members**, not an operational
warning. Use `--min-members 5` to inspect sensitivity to a stronger criterion.
Most alarming start maximizes the peak count across its days, breaking ties by
total member-day exceedances then earliest start. All-zero ties are labeled.

Earliest signal is greatest forecast lead before the same valid interval.
Consistency is the longest consecutive calendar-day run of starts signaling that
same interval. First issuance dates and fractions of starts with any signal are
also reported, but they answer different questions. At the window edges fewer
starts target a given valid interval; inspect availability before comparing.
Town rankings may reflect different local thresholds, forecast rainfall and
ensemble spread. The counts alone do not identify a causal reason for a ranking.

No observed 2025 event rainfall is provided: annual maxima through 2024 cannot
verify a July 2025 forecast. These outputs describe signals, not hits, misses or
forecast skill. Verification would require observed rainfall for matching dates
and spatial footprints. All-zero signals must not be described as successful warnings.
