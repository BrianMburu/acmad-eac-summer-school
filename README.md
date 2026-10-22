# Sudan rainfall extremes

ACMAD group project: define extreme rainfall at Khartoum, Kassala, Gedaref,
El Obeid and Nyala using CMORPH annual maxima from 1998–2024 (Part A), then
compare warning thresholds using June–August 2025 ECMWF forecasts (Part B).

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

The default output directory is `out/rainfall_thresholds`. The completed run's generated
files are ignored by Git and are not included in a fresh clone; the completed run is
retained locally in `out/part_a_local`, with its result archive at `out/part_a_results.zip`.
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
| `FORECAST_START_DATES` | Selected forecast initializations: 16 June, 16 July and 16 August 2025 |
| `CMORPH_YEARS` | 1998–2024 |
| `CMORPH_STORE`, `FORECAST_STORE` | Public store locations, coordinate order and pinned snapshots |
| `DURATIONS`, `RETURN_PERIODS` | 24/48 hours and 2/10/50 years |
| `MAP_DURATION`, `MAP_RETURN_PERIOD` | 24 hours, 10 years |
| `WORKERS`, `OUTPUT_DIRECTORY` | Two workers, `out/rainfall_thresholds` |
| `COMPARISON` | Planned forecast comparison: local 2-year 24-hour level, strict `>` |
| `THRESHOLD_CHOICE` | Part B: all five towns, fixed 20 mm threshold, trace correction, unit fallback, output folder and read budget |

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
duration and return-period requirements separately. Before forecast rainfall reads,
B/C/D must call `validate_common(config, require_forecast_dates=True)` and check
that each selected start actually contains finite data.

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
duration and update the configuration before rerunning. The selected forecast starts
are the 16th of June, July and August 2025; extend this to the agreed event window for C/D.
B/C/D must check finite data for every selected start because unwritten starts may
read as NaN.

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

Do not commit downloaded data or generated result files, except the five
supplementary PNGs noted below. Share reviewed thresholds/results as a release
artifact or another agreed group location, with the corresponding source commit.
The Part A review was completed during branch unification; the corrected Part A
and supplementary analyses now share one code path, and the original review
branch was `part-a-thresholds`.

## Warning threshold comparison (Part B)

The task asks how much the warning signal changes with the definition of extreme
rainfall. At **Khartoum, Kassala, Gedaref, El Obeid and Nyala**, compare the 51-member daily forecast with
three thresholds: fixed **20 mm / 24 h**, the town's **2-year 24-hour** level and
its **10-year 24-hour** level from Part A. The selected forecasts are initialized on
**16 June, 16 July and 16 August 2025**, as requested, with ten forecast days per
start (24-hour intervals ending on the 17th–26th of the corresponding month).
This sample does not represent all June–August rainfall events.

The script adapts workshop **E5** (daily totals and xclim) and **E6** (local
thresholds and member counts), using the shared store and coordinate helpers.
It verifies the Part A manifest, result checksums, geographical settings,
reference years and CMORPH snapshot before consuming its thresholds. In a fresh
clone, run the Part A extraction first. Then run:

```sh
uv run python -m scripts.threshold_choice inspect
uv run python -m scripts.threshold_choice extract
uv run python -m scripts.threshold_choice plots
```

For the completed local Part A results, pass `--thresholds out/part_a_local` to
`inspect` and `extract`. Use `--out PATH` on all stages to select another output
folder. `plots` uses the saved settings and tables and needs no internet access.
Edit `THRESHOLD_CHOICE` and `FORECAST_START_DATES` in `scripts/common.py`, then
refresh `grid.json` with `python -m scripts.common --export grid.json`.

Forecast latitude descends. The script checks the domain before nearest-point
selection and reads all five towns together, selecting daily leads before computing.
The source has no `tp` unit attribute; the explicit, recorded workshop assumption
is **cumulative metres from initialization**. Convert to mm, then difference
consecutive 24-hour endpoints. If lead zero is absent, the 24-hour accumulation
is the first day's total. Contradictory units, partial missing data, nonzero
initial accumulation and material decreases stop the run. ECMWF documents tiny
positive and negative increments caused by GRIB packing; values below
`THRESHOLD_CHOICE["trace_rainfall_mm"]` (0.04 mm initially) are set to zero,
and decreases beyond that tolerance still fail. The raw minimum and numbers of
corrected traces are recorded per start. This treatment follows the
[ECMWF packing guidance](https://confluence.ecmwf.int/spaces/UDOC/pages/208501579/Why+are+there+sometimes+small+negative+precipitation+accumulations+-+ecCodes+GRIB+FAQ)
for ten-day forecasts and cannot change any of the three warning comparisons,
whose smallest threshold is 20 mm. Entirely NaN starts
are recorded and skipped; a run with no usable starts fails.

All counts use strict **`>`**, including `xclim.indices.wetdays(..., op=">")`.
Equality does not trigger a warning. xclim counts heavy days per member for each
threshold over that start's available forecast horizon, with an independent
direct-count check. It does not produce a full seasonal count from ten days.
Daily intervals are restricted to the configured season; a valid end time of
1 September at 00 UTC closes the last August day.

The three-start selection touches **33 source chunks, about 538 MiB decoded**,
although the selected cumulative point values occupy about 33 KiB. All five towns
share the same map chunks. The script warns above 256 MiB and refuses reads above
`THRESHOLD_CHOICE["max_source_mib"]` (initially 1024 MiB). It processes one start
at a time with `WORKERS` workers. These are decoded source estimates; compressed
network transfer and peak RAM differ. Local execution is the initial workflow;
larger selections should be inspected before deciding whether to use Colab/Kaggle.

| Output under `out/threshold_choice/` | Purpose |
|---|---|
| `daily_member_counts.csv` | Each start × town × forecast day × threshold: count and percentage of 51 members |
| `summary_counts.csv` | Short table: peak daily count, member-days above, members with any heavy day and heavy-day summaries |
| `heavy_rain_days.csv` | xclim heavy-day count for every member, start, town and threshold |
| `daily_rainfall.csv` | Small daily town-series cache in mm per 24 h, with forecast coordinates and valid end times |
| `cache/*.nc`, `cache/*.json` | Raw cumulative point slices, snapshots/input hashes and checksums; completed reads are reused on retry |
| `thresholds_used.csv` | Fifteen thresholds and observed annual-maxima exceedance counts for context |
| `forecast_starts.json` | Used and skipped starts, with reasons |
| `figures/*_threshold_choice.png` | One figure per town, one panel per usable start, all three threshold curves |
| `manifest.json`, `settings_used.json` | Source commit/hashes, snapshots, Part A handoff hashes, versions and result checksums |
| `inspection.json`, `inspection_status.json`, `run_status.json` | Metadata, source-size estimate and separate inspection/extraction status |

The optional extension compares the fraction of the 27 annual maxima above each
level (`thresholds_used.csv`) with the fraction of forecast member-days above it
(`summary_counts.csv`). A 2-year annual-maximum level has approximately a 50%
annual exceedance probability; that does not mean half of individual days should
exceed it. Forecast counts describe this sample of model forecasts, not observed
daily frequencies or verified warning skill. Separate 2025 observations are needed
to assess missed events or false alarms.

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
all other files under `out/` remain ignored. See
[`CMORPH_RETURN_PERIODS.md`](CMORPH_RETURN_PERIODS.md) for the data, method, full
return-level table, figure links and caveats.

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
