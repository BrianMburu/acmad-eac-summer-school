# Sudan rainfall extremes

Part A of the ACMAD group project: define extreme rainfall at Khartoum, Kassala,
Gedaref, El Obeid and Nyala using CMORPH annual maxima from 1998–2024. Other
subgroups compare these levels with June–August 2025 ECMWF forecasts. The
repository also contains the Part B threshold-count, Part C lead-time and Part D
region-risk analyses.

See the [observed rainfall threshold task and results](RAINFALL_THRESHOLDS.md) for the assignment,
acceptance criteria, completed local run and handoff to the other teams.

## Run locally

Part A completed locally on 22 October 2026. Extraction took 67 seconds and used
217 MiB peak RAM. The selected source chunks represent about 66 MiB uncompressed;
the actual compressed network transfer was not measured. Local execution is the
supported workflow for this task.

Use Python 3.12 or newer with uv. The committed `uv.lock` records the dependency
versions. Internet is required for installation, inspection and extraction;
no API keys, AWS credentials or GPU are needed.

```sh
uv sync --locked --group dev --python 3.12
uv run pytest
```

Run the three stages in order. Review the inspection report before extraction;
coverage or unit failures stop the run.

```sh
uv run python -m scripts.rainfall_thresholds inspect
uv run python -m scripts.rainfall_thresholds extract
uv run python -m scripts.rainfall_thresholds plots
```

The default output directory is `out/rainfall_thresholds`. Reviewed tables and
figures are tracked under `out/`. Raw download caches remain local; an earlier
local run is retained in `out/part_a_local` when available.
If that local directory is available, regenerate its figures offline with:

```sh
uv run python -m scripts.rainfall_thresholds plots --out out/part_a_local --config out/part_a_local/settings_used.json
```

Use `--out PATH` to choose another output directory for any stage. If settings
have changed since extraction, plot with the saved `settings_used.json`.

## Settings and methods

**Edit the named settings at the top of `scripts/common.py`.** This is the single
editable settings source for all subgroups. The data-access and coordinate helpers
live in `scripts/data_access.py`. Importing common settings needs no scientific
packages and performs no network access.

| Setting in `common.py` | Current value or purpose |
|---|---|
| `REGION` | 24.25–37°E, 11.5–16.25°N |
| `TOWNS` | Five Sudanese town centres; 1° boxes are derived automatically |
| `FORECAST_START_DATE`, `FORECAST_END_DATE` | 1 June–31 August 2025 |
| `FORECAST_START_DATES` | 16 June, 16 July, 16 August 2025 (Part B) |
| `FORECAST_ANALYSIS` | Part C windows, Part D starts/days, forecast units, trace tolerance, fixed threshold and probability cutoff |
| `CMORPH_YEARS` | 1998–2024 |
| `CMORPH_STORE`, `FORECAST_STORE` | Public store locations, coordinate order and pinned snapshots |
| `DURATIONS`, `RETURN_PERIODS` | 24/48 hours and 2/10/50 years |
| `MAP_DURATION`, `MAP_RETURN_PERIOD` | 24 hours, 10 years |
| `WORKERS`, `OUTPUT_DIRECTORY` | Two workers, `out/rainfall_thresholds` |
| `COMPARISON` | Planned forecast comparison: local 2-year 24-hour level, strict `>` |

Inspect the effective settings or refresh the JSON export after editing:

```sh
uv run python -m scripts.common
uv run python -m scripts.common --export grid.json
```

`grid.json` is a **generated export**, not a second settings source. The analysis
uses `common.py` by default. `--config PATH.json` explicitly loads and validates
an exported override or a previous run's `settings_used.json`. Legacy saved settings
are migrated in memory for offline plotting, preserving their original hash check.

Other scripts can import named values directly:

```python
from scripts.common import REGION, TOWNS, FORECAST_START_DATES, load_config, validate_common

config = load_config()  # a fresh, validated copy of the named settings
```

Shared validation checks required fields, unknown keys, types, finite coordinates,
complete extent containment, dates, store endpoints and reference years. Errors
identify the setting to fix. `validate_thresholds(config)` checks this analysis's
duration and return-period requirements separately. B requires shared start dates; C/D use their named window and risk selections.
Each analysis validates its selected dates and checks finite data before counting.

Store `snapshot_id` values pin the completed run's data. Set a snapshot to `None`
to follow that store's `branch`; each run records the actual snapshot it reads.
Plotting checks the configured snapshot, the extraction hash and result-file
checksums, and refuses a run whose `run_status.json` is not `ok`. Extraction
stages all result files and promotes them together, so a failed rerun cannot
silently mix new tables with an old map or manifest.
Metadata-only inspection records its status separately in `inspection_status.json`,
preserving existing extraction status and cached results even if inspection fails.
Plotting replaces its named figure outputs and preserves other files in the figures folder.

The regional box includes neighbouring areas and is not a Sudan boundary mask.
Town thresholds use the nearest CMORPH pixel to the town centre. Coverage in both
stores is checked before nearest-point selection. Forecast rainfall arrays are
not read by the observed-threshold analysis.

Part A requires 24-hour and 48-hour durations and 2-, 10-, 50-year return periods.
If 48hr is absent, inspection lists available durations and stops; agree a second
duration and update the configuration before rerunning. The agreed starts and windows are recorded in `common.py`; B/C/D check
finite data for every selected start because unwritten starts may read as NaN.

Annual maxima and return levels must be rainfall **depths** in mm (equivalent
kg/m² depths are accepted). If units metadata is absent, the explicit E4 mm
assumption is recorded in inspection; contradictory metadata is rejected. CMORPH
latitude ascends, forecast latitude descends. Missing town values stop export;
missing regional threshold pixels remain masked and their count is reported.

The figures compare stored Gumbel levels with the 27 annual maxima, using Weibull
positions `(n + 1) / rank`. The top three years are labelled and tabulated with
their departures from the stored curve. These departures are descriptive, not a
formal goodness-of-fit test. No years are excluded from the required thresholds.

The optional extension uses SciPy's Gumbel maximum-likelihood fits on the full
series and after removing one largest year (earliest year if tied). It reports the
50-year change between those two fits and the difference between the full refit
and the stored level. This separates removal sensitivity from estimator differences.

## Outputs and handoff

| Output | Purpose |
|---|---|
| `inspection.json`, `coverage.csv` | Coverage, available coordinates, units and selected pixels |
| `thresholds.csv` | 30 rows: town × two durations × three return periods |
| `annual_maxima.csv` | 270 rows: town × two durations × 27 years |
| `fit_departures.csv` | Three largest years per town/duration and descriptive departures |
| `sensitivity_50yr.csv` | Full and leave-largest-out refits, differences in mm and percent |
| `regional_10yr_24hr.npz` | Small regional map cache for offline plotting |
| `figures/` | Five town figures and the regional 10-year, 24-hour map |
| `manifest.json`, `settings_used.json` | Data snapshot IDs, source hashes, versions, checks, result checksums and settings |
| `run_status.json` | Extraction status: `running`, `ok` or `failed`; plotting requires `ok` when present |
| `inspection_status.json` | Separate status for metadata-only inspection |

For B/C, filter `thresholds.csv` to `duration == "24hr"`, then join by `town` and
`return_period_years`. Use `threshold_mm` against forecast **mm in 24 hours**.
Each row includes requested and selected coordinates, units and reference years.
For D, town thresholds are insufficient: obtain a local CMORPH threshold at each
forecast pixel as in E8. Our 10-year map is a reference map, not D's 2-year map.

Commit reviewed summary tables, figures and provenance with their source code.
Keep raw downloads, NetCDF caches, logs and temporary results outside Git.
The Part A review was completed during branch unification; the corrected Part A
and supplementary analyses now share one code path, and the original review
branch was `part-a-thresholds`.

## Supplementary 27-year return-period figures

The repository also includes a separate 24-hour analysis that produces one
three-panel figure per town for the 27-year return level. The script is
[`scripts/cmorph_return_periods.py`](scripts/cmorph_return_periods.py), adapted from
workshop exercise E4. It uses the same shared settings, pinned CMORPH snapshot,
coverage/unit checks and Gumbel helpers as the Part A pipeline; `grid.json` remains
the generated export. Run it with:

```sh
uv run python -m scripts.cmorph_return_periods
```

It writes one PNG per town to `out/` and a small ignored
`out/04_cmorph_return_periods_manifest.json` recording the snapshot, settings hash,
units, years and output files.

| Town | 27-year 24-hour level (mm) |
|---|---:|
| Khartoum | 66.8 |
| Kassala | 72.9 |
| Gedaref | 83.7 |
| El Obeid | 75.0 |
| Nyala | 59.9 |

The 27-year level is not stored by the CMORPH dataset, so it is computed from the
fitted Gumbel parameters as `x_T = μ − β ln(−ln(1 − 1/T))`. The five PNGs
`out/04_cmorph_return_periods_<town>.png` are intentionally tracked as deliverables;
the reviewed A–D summary outputs are also tracked. See
[`CMORPH_RETURN_PERIODS.md`](CMORPH_RETURN_PERIODS.md) for the data, method, full
return-level table, figure links and caveats.

## Forecast settings and rainfall validation (B–D)

The defaults in `common.py` reproduce the agreed experiment at all five towns:

| Analysis | Forecast starts | Whole-day leads |
|---|---|---|
| B: threshold choice | 16 June, 16 July, 16 August 2025 | Days 1–10 |
| C: warning lead time | 9–22 June, 9–22 July, 9–22 August 2025 (42 starts) | Days 1–10 |
| D: regional risk | 16 June, 16 July, 13 August, 16 August 2025 | Days 1–10 |

The additional 13 August D start samples the strong signal found in C. Each C
window contains its corresponding monthly B start. D's selection is explicit
and reproducible. JSON overrides are optional; refresh `grid.json` after editing
`common.py`.

[`scripts/forecast_rainfall.py`](scripts/forecast_rainfall.py) provides shared
conversion and validation. Explicit metres are multiplied by 1000; millimetres
and equivalent kg/m² depths retain their scale. Missing forecast unit metadata
uses the explicit workshop E5/E6 assumption of cumulative metres and records that
fallback in each run's `forecast_manifest.json`. Unsupported units fail.

Daily totals are differences between consecutive whole-day endpoints, with a
zero initialization baseline. All 51 distinct members must be present. Entirely
NaN starts are skipped and reported; partial missingness, infinities, negative
cumulative totals and substantive decreases fail. A shared **0.08 mm** packing
tolerance zeroes small positive and negative daily traces; larger decreases
raise an error. This follows the approach described in the
[ECMWF GRIB packing guidance](https://confluence.ecmwf.int/spaces/UDOC/pages/208501579/Why+are+there+sometimes+small+negative+precipitation+accumulations+-+ecCodes+GRIB+FAQ).
The tolerance is much smaller than any warning threshold in this experiment.

Select dates, daily steps and town points or the region before computing. C
computes one start at a time using the shared worker limit. The scripts warn
before forecast reads exceeding an estimated 256 MiB of decoded source chunks.
This estimates source I/O rather than compressed network transfer or peak RAM;
42 starts can require several GiB of source reads even for five tiny point
series. Reuse local raw caches when replaying completed experiments.

Each B–D manifest records requested, kept and skipped starts, effective settings,
snapshot IDs, forecast unit conversion, trace cleanup and source-file hashes.
`--out PATH` selects another output directory. Each script retains the workshop
entrypoint used on main:

```sh
uv run python -m scripts.forecast_threshold_counts --config grid.json
uv run python -m scripts.forecast_signal_leadtime --config grid.json
uv run python -m scripts.region_risk_maps --config grid.json
```

## Threshold choice (Part B)

[`scripts/forecast_threshold_counts.py`](scripts/forecast_threshold_counts.py)
compares **20 mm/day**, each town's **2-year 24-hour level**, and its
**10-year 24-hour level**. Rainfall exceedance uses strict `>`. The xclim
`wetdays` calculation uses the same operator and must agree with the direct
member-day counts.

`out/forecast_thresholds/07_forecast_threshold_counts.csv` contains 45 rows:
three starts × five towns × three thresholds. Plots for each start are under
`out/forecast_thresholds/YYYYMMDD/`, including a combined overview and one
three-panel figure per town. `--init YYYY-MM-DD` overrides the shared selection
with one start; `--fixed-threshold-mm` overrides the fixed threshold.

Annual-maxima exceedance is a different quantity from daily forecast
exceedance. For example, 18 of Gedaref's 27 historical annual maxima exceed its
2-year level. That fraction cannot be interpreted as a daily rain probability
or used to assess forecast skill.

## Warning lead time (Part C)

[`scripts/forecast_signal_leadtime.py`](scripts/forecast_signal_leadtime.py)
uses E2/E5/E6 to count members above the local 2-year 24-hour level. It writes
five annotated start × lead heatmaps, a plume for the most alarming town/start,
and these tables in `out/forecast_leadtime/`:

| Output | Meaning |
|---|---|
| `08_forecast_leadtime_counts.csv` | All 2,100 town/start/day count cells |
| `08_forecast_leadtime_summary.csv` | One row per town, valid day and signal criterion |

The summary compares successive forecasts for the **same 24-hour rainfall
period**, identified by its valid end date. Earliest warning is the first
signaling initialization for that day; its lead is the difference between that
initialization and the valid end. Consistency is signaling starts divided by
available sampled starts whose forecast horizon reaches that day. Calendar
gaps break consecutive runs. A table row with one available start has limited
coverage, even when its signaling fraction is 100%.

Two criteria are reported separately: at least one member, and the configured
probability cutoff (20%, requiring at least **11 of 51 members**). Repeated
signals for unrelated valid days do not establish event consistency. These are
forecast signals relative to historical thresholds; observed 2025 event
verification requires separate observations.

The most alarming plume ranks town/start pairs by total member-days above the
level, then the largest daily member count, then earliest start. This ranking
can involve more than one valid day and is separate from the event consistency
summary. `--window-start` and `--window-end` together override the default three
windows with one explicitly selected daily-start window.

## Regional risk (Part D)

[`scripts/region_risk_maps.py`](scripts/region_risk_maps.py) adapts E8 to match
every forecast grid point to its nearest CMORPH 2-year 24-hour threshold. Town
thresholds from B/C are not substituted for this spatial field. Probability is
the fraction of members strictly above each local threshold. The chosen
probability cutoff is 20% (`>=`, at least 11 of 51 members).

`out/region_risk/` contains a ten-day probability figure for each of the four
starts, a frequency map, `09_region_risk_summary.csv` and
`09_region_risk_hotspots.csv`. All maps show the five town centres. The frequency
counts the selected **initialization/forecast-day pairs** that reach 20%.
There are 40 pairs when all four starts are available; overlapping valid days
remain separate cases. Missing threshold pixels stay masked. This is a sampled
forecast-risk summary, not an observed event frequency or exhaustive seasonal
coverage. Read timings in the summary reflect the execution used; cached replays
are faster than cold remote reads.

Overrides: `--start-dates YYYY-MM-DD ...` (three or four dates),
`--days 1,2,3,4,5`, and `--probability 0.20`.

## Limits and workshop sources

These are annual-extreme thresholds from 1998–2024, not seasonal thresholds or
observed 2025 rainfall. A 50-year level extrapolates beyond the 27-year record.
Nearest pixels have different spatial support between CMORPH (~8 km) and forecasts
(0.25°); satellite estimates also differ from gauges. No forecast verification is
possible without separate observations for 2025.

Adapted selectively from workshop E4 (store access, annual maxima, return levels,
Weibull positions), E6 (coverage checks), and E3/E8 (chunk awareness and spatial
selection). Workshop examples are read-only references. Technical references:
[xarray vectorized indexing](https://docs.xarray.dev/en/stable/user-guide/indexing.html#vectorized-indexing)
and [SciPy Gumbel distribution](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.gumbel_r.html).
