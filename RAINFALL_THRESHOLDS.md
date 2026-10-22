# Part A observed extreme rainfall thresholds for Sudan

Status: required analysis and sensitivity extension completed locally on
22 October 2026. Source and documentation are on `part-a-thresholds`, ready for
group review before merging.

## Task description

Define extreme rainfall at Khartoum, Kassala, Gedaref, El Obeid and Nyala using
CMORPH annual maxima for 1998–2024. Supply observed reference thresholds to the
teams assessing ECMWF forecast signals during June–August 2025.

Source assignment: `GROUP_TASKS_v2.pdf`, Part A, “How extreme is extreme?”
The required work is to extract 27 annual maxima per town, obtain the 2-, 10-
and 50-year levels for 24 hours and one additional duration, compare the fitted
Gumbel levels with the maxima, and identify years with noticeable departures.
Deliver one return-level figure per town, a regional 10-year 24-hour map and a
threshold table. The extension assesses the 50-year level after removing the
single largest year.

## Implementation and acceptance criteria

- [x] Store the regional box, town coordinates and dataset settings as named values
  in `scripts/common.py`, with `grid.json` as a generated export.
- [x] Verify all town centres, town extents and the regional box are inside both
  dataset domains before nearest-pixel selection.
- [x] Check duration availability, years, latitude order, units and missing values.
- [x] Extract 24-hour and 48-hour maxima at the nearest CMORPH town-centre pixels.
- [x] Export 30 thresholds and 270 annual maxima with selected coordinates and units.
- [x] Compare observed maxima with stored Gumbel levels using Weibull plotting
  positions, and label the three largest years per town and duration.
- [x] Generate five town figures and the regional 10-year 24-hour threshold map.
- [x] Refit the full and leave-largest-out series using the same Gumbel MLE method.
- [x] Record source revision, dataset snapshot IDs, settings and quality checks.
- [ ] Obtain the other subgroup's review before merging or publishing the handoff.

The implementation adapts workshop E4 for CMORPH access, annual maxima,
return levels and plots; E6 for coverage checks; and E3/E8 for chunk awareness
and regional selection. The workshop examples remain read-only references.

The analysis entry point is `scripts/rainfall_thresholds.py`. Shared settings and
their validation are exposed through `scripts/common.py`; lazy data access is in
`scripts/data_access.py`. Settings inspections and JSON exports use
`uv run python -m scripts.common`. The common validator is independent of the
observed-threshold requirements so other subgroups can reuse it.

## Completed run

The live run used source commit `0ed75d3b39b3d49e58523bd5fac2ffb5a3e29118`
with a clean working tree. Its CMORPH snapshot is `309ZYV7EMDMNPD0EDZK0`;
the forecast-coordinate snapshot is `212QY6MDW3RZ7PWD7A2G`.

Both variables explicitly report mm. All town values are finite and nonnegative,
the return levels increase with return period, and all 11,440 pixels in the
regional map have valid thresholds. Forecast rainfall arrays were not read.

| Resource measure | Result |
|---|---:|
| Precomputed CMORPH data variables, uncompressed | 313.3 MiB |
| Selected unique source chunks, uncompressed | 65.6 MiB |
| Extraction elapsed time | 67.1 seconds |
| Measured extraction peak RAM | 217.2 MiB |
| Generated figures | 6 |

Compressed network transfer was not measured. The completed run fits local
resources, so Part A uses the command-line workflow in [README.md](README.md).
The notebook and ZIP-based cloud upload workflow have been retired.

## Rainfall thresholds

These are stored Gumbel return levels for annual maxima from 1998–2024.
All values below are rainfall depths in mm, rounded to one decimal place.
A 10-year level corresponds to approximately a 10% annual exceedance chance
under the fitted model.

### 24 hour levels

| Town | 2 year | 10 year | 50 year |
|---|---:|---:|---:|
| Khartoum | 23.8 | 51.7 | 76.0 |
| Kassala | 37.9 | 60.6 | 80.4 |
| Gedaref | 53.0 | 72.8 | 90.3 |
| El Obeid | 37.2 | 61.7 | 83.2 |
| Nyala | 32.3 | 50.2 | 65.8 |

### 48 hour levels

| Town | 2 year | 10 year | 50 year |
|---|---:|---:|---:|
| Khartoum | 25.1 | 53.1 | 77.6 |
| Kassala | 39.9 | 63.8 | 84.7 |
| Gedaref | 59.8 | 84.9 | 107.0 |
| El Obeid | 38.7 | 62.5 | 83.4 |
| Nyala | 35.6 | 56.8 | 75.3 |

Gedaref has the highest thresholds at every selected duration and return period.
The 24-hour 2-year level ranges from 23.8 mm in Khartoum to 53.0 mm in Gedaref,
showing how a fixed threshold would represent different levels of rarity.

## Observed maxima and fit sensitivity

| Town | Largest 24 hour maximum | Year | Change in refitted 50 year level after removing that year |
|---|---:|---:|---:|
| Khartoum | 77.1 mm | 2017 | −9.1% |
| Kassala | 74.3 mm | 2008 | −5.3% |
| Gedaref | 91.1 mm | 2003 | −3.5% |
| El Obeid | 68.2 mm | 1998 | −3.1% |
| Nyala | 63.7 mm | 2022 | −4.5% |

Khartoum's 2006 and 2017 maxima sit above the stored curve at their empirical
return periods; 2006 departs by about 15.0 mm. These are descriptive departures,
not formal goodness-of-fit test rejections or grounds to discard those years.
Gedaref's largest 48-hour maximum is 102.3 mm in 2020.

Removing the largest year reduces the 50-year level by 3.1–9.1% for 24 hours and
2.8–8.4% for 48 hours. These percentages compare two maximum-likelihood refits.
The full-record refits differ from the stored levels, so the sensitivity results
must be interpreted with their fitting method. The stored thresholds remain the
shared reference levels.

## Results and handoff

The existing local outputs are in `out/part_a_local`, and the complete result
archive is `out/part_a_results.zip`. These generated files are ignored by Git;
the numerical summary above preserves the findings in the committed task record.
Use the CLI commands in [README.md](README.md) to reproduce the outputs.

For B/C, use `thresholds.csv`, filter to `duration == "24hr"`, and join on town
and return period. Compare `threshold_mm` with forecast rainfall in mm over
24 hours. Use the full-precision CSV values for computation.

For D, extract the local CMORPH threshold at every forecast pixel as in E8.
Our regional map represents the 10-year level; D's 2-year exceedance maps need
their own spatial threshold field. Forecast start dates still require whole-group
agreement and finite-data checks.

The thresholds use the nearest town-centre pixels and describe annual extremes,
not June–August-only extremes. The 50-year levels extrapolate beyond a 27-year
record. Satellite rainfall and grid-cell estimates differ from gauge measurements.
Observed 2025 rainfall is absent from these stores, so the subsequent forecast
analysis can describe signals and lead times but cannot verify the events here.
