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
| `FORECAST_START_DATES` | `None`, pending the whole-group decision |
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
duration and update the configuration before rerunning. Forecast start dates
are still a group decision (`FORECAST_START_DATES` is `None`); B/C/D must check
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

Do not commit downloaded data or generated result files, except the five
supplementary PNGs noted below. Share reviewed thresholds/results as a release
artifact or another agreed group location, with the corresponding source commit.
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
all other files under `out/` remain ignored. See
[`CMORPH_RETURN_PERIODS.md`](CMORPH_RETURN_PERIODS.md) for the data, method, full
return-level table, figure links and caveats.

## Forecast threshold counts

[`scripts/forecast_threshold_counts.py`](scripts/forecast_threshold_counts.py)
applies workshop exercises E5 and E6 to every town in the settings. It uses the
2025-07-16 forecast initialization (time index 45; override with `--init`),
differences the cumulative forecast `tp` at whole-day leads to obtain ten
24-hour totals, and converts metres to millimetres. For each town it counts
ensemble members above:

- a fixed 20 mm/day threshold,
- the town's nearest-pixel CMORPH 24-hour 2-year level, and
- the town's nearest-pixel CMORPH 24-hour 10-year level.

The comparison is strict `>` (as in E6). An xclim `wetdays` count with
`op=">"` is also computed for each threshold. Run it with the exported JSON
settings or the Python defaults:

```sh
uv run python -m scripts.forecast_threshold_counts --config grid.json
```

`--fixed-threshold-mm`, `--init YYYY-MM-DD` and `--out PATH` are optional. The
run writes an ignored summary and figures under `out/forecast_thresholds/`:

| Output | Purpose |
|---|---|
| `07_forecast_threshold_counts.csv` | Town × threshold counts, including xclim heavy-day summaries |
| `07_forecast_threshold_members_<town>.png` | One three-panel figure per town |
| `07_forecast_threshold_members.png` | Combined town × threshold overview |

The CSV reports unique members above at least once, the maximum number of
members above in one forecast day, total member-days above, days with any
member above, and the xclim total, member count and maximum days per member.
CMORPH levels and both store snapshot IDs are read through the shared settings;
coverage, coordinate order and depth units are checked before selection.

## Forecast lead-time signal (Part C)

[`scripts/forecast_signal_leadtime.py`](scripts/forecast_signal_leadtime.py)
asks how early the forecasts signalled the local 2-year rainfall level. The
default window is the three weeks of daily forecast starts from **1 to 21 July
2025**, including the 16 July initialization used in Part B. Override it with
`--window-start YYYY-MM-DD --window-end YYYY-MM-DD`; the window must contain at
least two starts. The window is passed explicitly to this analysis; it does not
change the shared `FORECAST_START_DATES` setting. The script skips and reports any
selected start that reads back as all-NaN, as required for unwritten forecast
starts.

For every start and town, only the whole-day lead times (0, 24, ..., 240 hours)
are read; the 3-hourly steps are never loaded. Cumulative forecast `tp` is
converted from metres to millimetres, adjacent whole-day values are differenced,
and members strictly above the town's nearest-pixel CMORPH 24-hour 2-year level
are counted. This follows the daily-total and exceedance logic in exercises E5
and E6.

```sh
uv run python -m scripts.forecast_signal_leadtime --config grid.json
```

The run writes ignored output under `out/forecast_leadtime/`:

| Output | Purpose |
|---|---|
| `08_forecast_leadtime_heatmap_<town>.png` | Start date × forecast day heatmap of members above the 2-year level; nonzero cells are annotated |
| `08_forecast_leadtime_plume_<town>_<start>.png` | Daily rainfall plume, threshold line and exceedance-count bars for the most alarming town/start |
| `08_forecast_leadtime_summary.csv` | Per-town earliest signal, number/fraction of starts with a signal, total member-days, peak and longest consecutive run |
| `08_forecast_leadtime_counts.csv` | Long-form counts for every heatmap cell |

The most alarming start is the town/start pair with the largest total
member-days above the threshold, breaking ties by the largest single-day member
count and then the earliest start. “Earliest” is deliberately reported in three
complementary ways: the first start date with any signal, the shortest whole-day
lead with any signal, and the earliest valid calendar date with a signal. These
need not come from the same start or town, so the summary reports all three.
“Most consistent” is the number and fraction of start dates with at least one
member above, supported by the total member-days and the longest consecutive run
of starts with a signal. All counts use the strict `>` operator.

### Completed run, 1–21 July 2025

The default run used all 21 daily starts and 51 members (forecast snapshot
`212QY6MDW3RZ7PWD7A2G`; CMORPH snapshot `309ZYV7EMDMNPD0EDZK0`).

| Town | 24-h 2-year level (mm) | First start with signal | First-signal lead (that start) | Earliest valid date (any start) | Shortest lead (any start) | Starts with signal | Member-days | Peak members/day |
|---|---:|---|---:|---|---:|---:|---:|---:|
| Khartoum | 23.8 | 2025-07-01 | 9 | 2025-07-08 | 2 | 18/21 (85.7%) | 36 | 3 |
| Kassala | 37.9 | 2025-07-02 | 2 | **2025-07-04** | 2 | 9/21 (42.9%) | 13 | 1 |
| Gedaref | 53.0 | 2025-07-02 | 6 | 2025-07-07 | 4 | 3/21 (14.3%) | 4 | 1 |
| El Obeid | 37.2 | 2025-07-02 | 8 | 2025-07-10 | 1 | 13/21 (61.9%) | 26 | 4 |
| Nyala | 32.3 | 2025-07-01 | 8 | 2025-07-06 | 1 | **20/21 (95.2%)** | **72** | 4 |

The lead columns have different meanings. “First-signal lead (that start)” is
the first day on which the earliest signal-bearing start crosses the threshold;
for example, the 1 July Nyala start first crosses on day 8 (valid 9 July). A
later start can therefore produce an earlier valid date: the 2 July Nyala start
crosses on day 4 (valid 6 July). “Shortest lead (any start)” is the minimum day
number with any signal across all 21 starts, regardless of start date.

**Kassala produced the earliest valid-date signal, on 4 July 2025**, from its
2 July start at day 2. **Nyala was the most consistent and strongest signal**:
20 of 21 starts had at least one member above the level, with 72 member-days,
a peak of 4 members in a day and a run of 19 consecutive signal-bearing starts.
Nyala also shared the earliest first start date with Khartoum (1 July); its first
signal within that particular start was later, on day 8. If one headline is
needed, Nyala is the best overall early-warning signal, while Kassala is the
single earliest valid-date signal.

The most alarming single start was **Nyala initialized 2025-07-07**: 10
member-days above the threshold, first crossing on day 6 (13 July) and peaking at
4 members on day 7 (14 July). El Obeid also reached 4 members on 7 July, but had
only 5 member-days in that start. The plume is
`out/forecast_leadtime/08_forecast_leadtime_plume_nyala_20250707.png`.

The ranking reflects both threshold height and forecast rainfall. Gedaref's
53.0 mm level is the highest, so only 3 starts cross it; Khartoum has the lowest
level (23.8 mm) but its members cross less often than Nyala's. Nyala combines a
relatively low 32.3 mm level with repeated wet members, while Kassala's early
4 July signal is isolated (9/21 starts). These are member counts, not
probabilities, and the window starts on 1 July, so the analysis cannot establish
whether a warning existed before the window.

## Region-risk probability and frequency maps (Part D)

[`scripts/region_risk_maps.py`](scripts/region_risk_maps.py) asks where across
the region the forecast risk was highest. It adapts the E8 local-threshold
probability map and the E3 pan-chunk lesson: the region and whole-day steps are
selected before the remote data are computed, so each forecast day is one map
read rather than a point time series.

For each randomly selected start, the script reads the cumulative `tp` at 0 and
24–120 hours, differences the whole-day steps, and converts metres to millimetres.
At every forecast grid point the threshold is the nearest-pixel CMORPH 24-hour
2-year level. The probability is the fraction of the 51 members **strictly above**
that local threshold for each forecast day 1–5. The season frequency at a grid
point is the number of selected **start/day cases** whose probability reaches the
chosen level; with four starts and five days there are 20 possible cases. The
default chosen probability is **20%**. Any start that reads back as all-NaN is
skipped and reported.

The random starts are stratified over four equal blocks of the configured June–August
season, using seed 42 by default. This guarantees samples spread through the season
while remaining reproducible; `--start-dates` accepts an explicit set of three or
four dates. The five Part C town centres are drawn on every map.

```sh
uv run python -m scripts.region_risk_maps --config grid.json --n-starts 4 --seed 42
```

Useful overrides are `--start-dates YYYY-MM-DD ...`, `--days 1,2,3,4,5`,
`--probability 0.20` (a fraction) and `--out PATH`. The run writes ignored output
under `out/region_risk/`:

| Output | Purpose |
|---|---|
| `09_probability_map_<YYYYMMDD>_p20.png` | Five-panel probability map for one start, days 1–5, with the 20% contour and Part C towns |
| `09_frequency_map_p20.png` | One season map: number of the 20 start/day cases at or above 20% probability |
| `09_region_risk_summary.csv` | Peak probability, peak location/day, number of grid points at or above the chosen level, and map-read seconds for each start |
| `09_region_risk_hotspots.csv` | Top 15 grid points ranked by frequency, then peak probability |

### Completed run, four stratified starts

The default run used forecast snapshot `212QY6MDW3RZ7PWD7A2G` and CMORPH snapshot
`309ZYV7EMDMNPD0EDZK0`. With seed 42 it selected **3 June, 11 July, 1 August and
19 August 2025**; no selected start was all-NaN. The local 2-year threshold over
the 20 × 52 forecast subset ranged from 7.7 to 93.8 mm/day. The four starts took
about 40 seconds of map reads, and the complete run including the threshold map
and figures took 61 seconds.

| Start | Maximum probability | Peak location | Peak day | Grid points with p ≥ 20% |
|---|---:|---|---:|---:|
| 2025-06-03 | 0.0% | — | — | 0 |
| 2025-07-11 | 29.4% | 15.25°N, 26.50°E | 4 | 1 |
| 2025-08-01 | 23.5% | 14.50°N, 25.00°E | 4 | 1 |
| 2025-08-19 | **39.2%** | **12.75°N, 24.25°E** | **5** | **16** |
| Season | **39.2%** | 12.75°N, 24.25°E | 5 | 18 |

The highest risk was in the **west/south-west**, especially the strip around
24.25–25.0°E and 11.5–13.25°N near and west of Nyala. The single strongest cell
was 12.75°N, 24.25°E on day 5 of the 19 August start (valid 24 August), at 39.2%
probability. The 19 August start supplied 16 of the 18 grid points that reached
20% at least once. Two weaker, isolated 20% cells appeared near 14.5°N, 25°E and
15.25°N, 26.5°E; the eastern towns (Khartoum, Kassala, Gedaref) had no 20%
probability area in these four starts.

The frequency map is deliberately strict: no grid point reached 20% in more than
**1 of the 20 start/day cases**, so the 20% signal was isolated rather than
widespread. A sensitivity run at 10% probability (`--probability 0.10`) keeps the
same western/south-western focus, but the maximum frequency rises to 5 of 20 cases
at 13.0°N, 24.25°E and more of the west is highlighted. Eastern Sudan remains
quiet at either level. The frequency counts are descriptive: the five days within
one start are not independent samples, and four starts do not sample the whole
season exhaustively.

The forecast `tp` chunks are pan chunks of shape `(1, 1, 51, 321, 261)`: each
selected start/day is one complete member × map slab. Selecting the 20 × 52 region
and only six whole-day steps before `.compute()` therefore reads 24 pan chunks
for the four starts; the script does not materialise all 65 steps or read pencil
time series. This is why the map reads are cheap compared with a point-by-point
loop, as demonstrated in E3.

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
