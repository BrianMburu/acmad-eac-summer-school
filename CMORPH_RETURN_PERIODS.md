# 27-year CMORPH rainfall extremes — supplementary figures

This document describes the supplementary 27-year return-period figures included with Part A.
They use the same CMORPH 1998–2024 record and the five Sudanese towns as the Part A thresholds,
but focus on a single 24-hour, 27-year return level and one three-panel figure per town.

For each town the workflow extracts the annual maximum 24-hour rainfall, reads the fitted Gumbel
distribution parameters, and produces a figure with:

1. the 27-year 24-hour rainfall map with the town marked,
2. the town's 27 annual maxima with 2-, 10- and 50-year return levels, and
3. the fitted Gumbel return-level curve against the observed annual maxima.

## Study locations

The towns are defined in the shared settings in
[`scripts/common.py`](scripts/common.py); [`grid.json`](grid.json) is the generated
export of the same settings.

| Town | Latitude | Longitude |
|---|---:|---:|
| Khartoum | 15.551772 | 32.532406 |
| Kassala | 15.450992 | 36.399980 |
| Gedaref | 14.034927 | 35.383444 |
| El Obeid | 13.184212 | 30.216694 |
| Nyala | 12.048882 | 24.880694 |

## Data

The analysis reads the public CMORPH return-period store directly; no credentials are required.

| Item | Value |
|---|---|
| Endpoint | `https://data.source.coop` |
| Bucket | `e4drr-project` |
| Prefix | `observations/cmorph_rp_icechunk` |
| Record | 1998–2024 (27 years) |
| Duration | `24hr` |
| Variables | `annual_maxima`, `return_period_precip`, `dist_location`, `dist_scale` |
| Stored return periods | 2, 5, 10, 20, 50, 100 years |

The store is an Icechunk/Zarr v3 dataset read from the pinned snapshot in the shared settings
(`309ZYV7EMDMNPD0EDZK0`). Latitude is ascending (−14.5° to 25.5°) and longitude runs from about
19.5° to 54.0°, covering all five towns.

## Method

For every town the nearest CMORPH pixel to the shared town coordinates is selected, and the
27-year series of annual maxima is read. Town coverage, the reference years and the rainfall
units are validated before selection, using the same helpers as Part A. Return levels follow the
Gumbel distribution

```
x_T = μ − β · ln(−ln(1 − 1/T))
```

where `T` is the return period in years, `μ` is the Gumbel location parameter
(`dist_location`) and `β` is the scale parameter (`dist_scale`).

The store provides return levels for 2, 5, 10, 20, 50 and 100 years. The 27-year level is not
stored, so it is computed from `μ` and `β`; the same formula reproduces every stored level to
stored float32 precision (maximum difference below 0.000005 mm).

### 27-year 24-hour return levels

| Town | 2-yr | 5-yr | 10-yr | 20-yr | **27-yr** | 50-yr | 100-yr |
|---|---:|---:|---:|---:|---:|---:|---:|
| Khartoum | 23.8 | 40.6 | 51.7 | 62.3 | **66.8** | 76.0 | 86.4 |
| Kassala | 37.9 | 51.6 | 60.6 | 69.2 | **72.9** | 80.4 | 88.8 |
| Gedaref | 53.0 | 64.9 | 72.8 | 80.4 | **83.7** | 90.3 | 97.6 |
| El Obeid | 37.2 | 51.9 | 61.7 | 71.0 | **75.0** | 83.2 | 92.2 |
| Nyala | 32.3 | 43.0 | 50.2 | 57.0 | **59.9** | 65.8 | 72.4 |

All values are 24-hour rainfall depths in millimetres.

Gedaref has the highest 27-year level (83.7 mm); Nyala has the lowest (59.9 mm).

## Figures

| Town | Figure |
|---|---|
| Khartoum | [`out/04_cmorph_return_periods_khartoum.png`](out/04_cmorph_return_periods_khartoum.png) |
| Kassala | [`out/04_cmorph_return_periods_kassala.png`](out/04_cmorph_return_periods_kassala.png) |
| Gedaref | [`out/04_cmorph_return_periods_gedaref.png`](out/04_cmorph_return_periods_gedaref.png) |
| El Obeid | [`out/04_cmorph_return_periods_el_obeid.png`](out/04_cmorph_return_periods_el_obeid.png) |
| Nyala | [`out/04_cmorph_return_periods_nyala.png`](out/04_cmorph_return_periods_nyala.png) |

Each figure is a single three-panel plot; one figure is produced per town (five figures total).
These five PNGs are intentionally tracked in Git as the deliverable for this analysis. All other
files under `out/` are covered by the repository `.gitignore`.

![Khartoum](out/04_cmorph_return_periods_khartoum.png)

## Reproducing the analysis

The analysis script is [`scripts/cmorph_return_periods.py`](scripts/cmorph_return_periods.py),
adapted from exercise 04 of
[`icpac-igad/python-workshop`](https://github.com/icpac-igad/python-workshop). It reads the towns
from the shared settings in [`scripts/common.py`](scripts/common.py) (exported to `grid.json`),
loops over them, and writes one PNG per town into `out/`.

From this repository directory, after `uv sync --locked --python 3.12`:

```bash
uv run python -m scripts.cmorph_return_periods
```

It can also run against the generated `grid.json` export, or another saved
configuration, and accepts a different duration, return period or output folder:

```bash
uv run python -m scripts.cmorph_return_periods --config grid.json --duration 24hr \
    --return-period 27 --out out
```

Use `--config PATH` (or its `--grid` alias) to select a saved settings JSON. Results are written as
`out/04_cmorph_return_periods_<town>.png`; re-running overwrites the existing figures. A small
`out/04_cmorph_return_periods_manifest.json` records the snapshot, settings hash, duration, return
period, reference years, units, Gumbel-parameter check and generated files. It is ignored by Git.

Dependencies: the repository environment (Python 3.12+), including `icechunk`, `xarray`, `zarr`,
`numpy` and `matplotlib`.

## Caveats

- Nearest-pixel sampling is not area-conservative regridding. CMORPH is approximately 8 km and the
  forecast grid referenced in `grid.json` is 0.25°.
- The Gumbel fit is based on 27 annual maxima. Return levels are estimates with sampling
  uncertainty, and the 27-year value is close to the length of the record.
- The analysis describes 24-hour rainfall extremes, not seasonal (JJA 2025) totals. The threshold is
  fitted to 1998–2024 observations.
