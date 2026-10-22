# Sudan rainfall extremes — subgroup A

Part A of the ACMAD group project: define extreme rainfall at Khartoum, Kassala,
Gedaref, El Obeid and Nyala using CMORPH annual maxima from 1998–2024. Other
subgroups compare these levels with June–August 2025 ECMWF forecasts.

See the [Part A task description and results](TASK_A.md) for the assignment,
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
uv run python -m scripts.part_a_thresholds inspect
uv run python -m scripts.part_a_thresholds extract
uv run python -m scripts.part_a_thresholds plots
```

The default output directory is `out/part_a`. The completed run is retained locally
in `out/part_a_local`; its result archive is `out/part_a_results.zip`. Generated
outputs are ignored by Git. To regenerate figures from the completed run offline:

```sh
uv run python -m scripts.part_a_thresholds plots --out out/part_a_local --config out/part_a_local/settings_used.json
```

Use `--out PATH` to choose another output directory for any stage. If settings
have changed since extraction, plot with the saved `settings_used.json`.

## Settings and methods

`scripts/common.py` loads the shared `grid.json`. The regional map box encloses
the five town extents; it includes neighbouring areas and is not a Sudan boundary
mask. Town thresholds use the nearest CMORPH pixel to the town centre, not the
maximum or mean within a town extent. Coverage in both stores is checked before
nearest-point selection. Forecast data values are not read by Part A.

Part A requires 24-hour and 48-hour durations and 2-, 10-, 50-year return periods.
If 48hr is absent, inspection lists available durations and stops; agree a second
duration and update the configuration before rerunning. Forecast start dates
are still a group decision (`forecast.start_dates` is null); B/C/D must check
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
| `manifest.json`, `settings_used.json` | Data snapshot IDs, source hashes, versions, checks and settings |

For B/C, filter `thresholds.csv` to `duration == "24hr"`, then join by `town` and
`return_period_years`. Use `threshold_mm` against forecast **mm in 24 hours**.
Each row includes requested and selected coordinates, units and reference years.
For D, town thresholds are insufficient: obtain a local CMORPH threshold at each
forecast pixel as in E8. Our 10-year map is a reference map, not D's 2-year map.

Do not commit downloaded data or generated result files.
Share reviewed thresholds/results as a release artifact or another agreed group
location, with the corresponding source commit. Changes should be reviewed on
`part-a-thresholds` before merging, as required by the assignment.

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
