# Sudan rainfall extremes — subgroup A

Part A of the ACMAD group project: define extreme rainfall at Khartoum, Kassala,
Gedaref, El Obeid and Nyala using CMORPH annual maxima from 1998–2024. Other
subgroups compare these levels with June–August 2025 ECMWF forecasts.

## Run on Colab or Kaggle

1. Open `notebooks/part_a_thresholds.ipynb` on Colab or Kaggle. Choose a CPU
   runtime and enable Internet access.
2. Upload `dist/part_a_source.zip` in Colab's Files panel, or attach the ZIP as a
   Kaggle dataset. This bundle is generated locally; it is not tracked in Git.
3. Run Setup and Inspect first. If inspection fails, return `inspection.json`
   and `coverage.csv` from the printed output directory before continuing.
4. If inspection passes, run Extract, Plot, Review and Download. Return
   `part_a_results.zip` for review. No API keys, AWS credentials or GPU are needed.

The notebook uses uv to create its own Python 3.12 environment. Its kernel does
not need scientific packages installed. Package downloads and public data access
require Internet. The source bundle includes `uv.lock` for the analysis environment.

## Local development

```sh
uv sync --group dev --python 3.12
uv run pytest
uv run python -m scripts.build_notebook
uv run python -m scripts.package_part_a
```

Heavy data reads are intended for the hosted notebook. The equivalent commands are:

```sh
uv run python -m scripts.part_a_thresholds inspect
uv run python -m scripts.part_a_thresholds extract
uv run python -m scripts.part_a_thresholds plots
```

`plots` runs offline against `out/part_a`. To use returned cloud results, unzip
the `results/` directory and pass its path with `--out`. If settings have changed,
also pass `--config PATH/TO/results/settings_used.json`.

## Settings and methods

`scripts/common.py` loads the shared `grid.json`. The regional map box encloses
the five town extents; it includes neighbouring areas and is not a Sudan boundary
mask. Town thresholds use the nearest CMORPH pixel to the town centre, not the
maximum or mean within a town extent. Coverage in both stores is checked before
nearest-point selection. Forecast data values are not read by Part A.

Part A requires 24-hour and 48-hour durations and 2-, 10-, 50-year return periods.
If 48hr is absent, inspection lists available durations and stops; agree a second
duration and update the configuration before repackaging. Forecast start dates
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

Do not commit downloaded data, generated results or executed notebook outputs.
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
