# Sudan rainfall extremes

Part A of the ACMAD group project: define extreme rainfall at Khartoum, Kassala,
Gedaref, El Obeid and Nyala using CMORPH annual maxima from 1998–2024. Other
subgroups compare these levels with June–August 2025 ECMWF forecasts.

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
