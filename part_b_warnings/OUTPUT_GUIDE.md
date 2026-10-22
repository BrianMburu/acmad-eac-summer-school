# Understanding Part B

This analysis follows workshop `05_xclim_heavy_rain.py` and
`06_forecast_vs_local_extremes.py`, using Khartoum and Kassala and the forecast
initialized 16 July 2025. There are 51 ensemble members and ten forecast days.
Day 1 covers 16–17 July; day 10 covers 25–26 July (forecast initialization clock).

## Units and thresholds

| Threshold | Khartoum (mm in 24 h) | Kassala (mm in 24 h) |
|---|---:|---:|
| Fixed | 20.00 | 20.00 |
| CMORPH 2-year annual-maximum level | 23.82 | 37.95 |
| CMORPH 10-year annual-maximum level | 51.65 | 60.56 |

The forecast stores cumulative precipitation in metres. Subtract consecutive
24-hour endpoints, then multiply by 1000: `(tp_end - tp_start) * 1000`.
For example, a cumulative increase of 0.020 m is 20 mm in that 24-hour interval.
For these full-day intervals, 20 mm/day and 20 mm in 24 h are equivalent.
They do not mean 20 mm every hour. Counts on the vertical axis are numbers of
members, not millimetres. Two of 51 members is 3.92% of the ensemble; one is 1.96%.

## Reading the plots and tables

Each line counts members with rainfall strictly greater than its threshold on
that day. Khartoum has zero for all thresholds and days. Kassala's fixed 20 mm
threshold has 2 members on day 1, 2 on day 6, and 1 on day 9; other days have zero.
Both towns have zero members above their 2-year and 10-year thresholds throughout.
Overlapping zero lines are expected. Each plot states the total ensemble size;
the vertical scale is enlarged to show the small counts clearly.

`daily_counts_short.csv` gives one row per town/day and three count columns.
`daily_member_counts.csv` includes exact thresholds and interval start/end times.
`summary_counts.csv` aggregates the 51 × 10 = 510 member-days per town.
Kassala has 5/510 = 0.98% above 20 mm; this is a member-day proportion, not the
probability that rain occurs somewhere during the whole period.

`xclim_heavy_days.csv` counts days at or above each threshold for each member,
using xclim `wetdays` on the ten-day window. These are forecast-window counts,
not counts over a full year. At Kassala five members each have one day >=20 mm;
the mean is 5/51 = 0.098 heavy days/member. Khartoum has none. Equality is included
by xclim (`>=`), while the daily exceedance plots use strict `>` as requested.
The script checks every xclim count against a direct count.

## Is a 2-year annual level a fair daily warning threshold?

It answers a rare-rainfall question, but cannot alone define a warning.
Part A has 12/27 Khartoum annual maxima (44.4%) and 13/27 Kassala maxima (48.1%)
above the respective 2-year levels. That agrees approximately with the fitted
50% probability of at least one annual exceedance. It is not 50% on each day.
Under an illustrative independent, identical daily model, the daily probability
would be `1 - 0.5**(1/365) = 0.190%`. Seasonality and dependence invalidate using
that number as a locally calibrated daily probability.

In this forecast, the 2-year level produces zero exceedances in both towns,
whereas the fixed level captures five Kassala member-days. This demonstrates
different sensitivity, not which threshold has better warning skill. Choosing a
warning also requires observed impacts, verification of false alarms and misses,
and an explicit ensemble probability rule. The members are correlated predictions.

## Coordinates and quality control

Forecast latitude descends; CMORPH latitude ascends. Point selections use
`method='nearest'`; rectangular slices would require `slice(north, south)` for
forecast latitude and `slice(south, north)` for CMORPH. The script verifies the
actual coordinate order and town inclusion in both source domains before a
fresh rainfall extraction. It also matches the CMORPH pixels to Part A's table.
Coordinate metadata are read before the precipitation `.compute()` call.

The legacy cached extraction does not contain both stores' coordinate bounds
or ordering. Offline cached results explicitly report those checks as not
recorded, rather than inventing coordinates or claiming fresh validation.
Run with `--use-cache --refresh-domain-checks` while connected to verify both
domains without downloading rainfall again. A fresh run checks them by default.

Thirteen tiny negative daily differences were clipped to zero; the largest was
0.030518 mm. Repeated increments suggest encoding noise, but its cause is
unverified. The tolerance is 0.05 mm; larger decreases stop execution. These
negative amounts are far below the smallest 20 mm threshold. The recorded QC
and explicit correction make this assumption reviewable.

The forecast and CMORPH pixels have different resolutions and footprints;
nearest-pixel matching is not area-conservative regridding or a rain-gauge record.
