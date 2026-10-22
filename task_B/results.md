# Task B: Which threshold should trigger a warning?

Forecast initialization: **2025-07-16**. All **5 grid.json towns**, **51 members**, **10 daily intervals**.
Day 1: 16 Jul–17 Jul; day 10: 25 Jul–26 Jul 2025.

## Units and thresholds

Rainfall is a depth in **mm accumulated in 24 h**. For a full 24-hour interval this is numerically equivalent to mm/day.
Daily depth = (cumulative tp at interval end − cumulative tp at interval start) × 1000, converting metres to millimetres.
Plot counts are numbers of members, not rainfall depths. Two members means 2/51 = 3.92%; one means 1/51 = 1.96%.

| Town | Fixed (mm in 24 h) | 2-year (mm in 24 h) | 10-year (mm in 24 h) |
|---|---:|---:|---:|
| Khartoum | 20.00 | 23.82 | 51.65 |
| Kassala | 20.00 | 37.95 | 60.56 |
| Gedaref | 20.00 | 52.98 | 72.84 |
| El Obeid | 20.00 | 37.18 | 61.68 |
| Nyala | 20.00 | 32.32 | 50.15 |

The 2-year and 10-year depths come from the completed **task_A** published CMORPH thresholds, not its separate MLE refit.

## Members strictly above the threshold each day

| Town | Threshold | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Khartoum | 20mm | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Khartoum | 2yr | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Khartoum | 10yr | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Kassala | 20mm | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 1 | 0 |
| Kassala | 2yr | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Kassala | 10yr | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Gedaref | 20mm | 0 | 1 | 2 | 4 | 3 | 7 | 2 | 2 | 1 | 2 |
| Gedaref | 2yr | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Gedaref | 10yr | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| El Obeid | 20mm | 3 | 0 | 0 | 2 | 1 | 1 | 2 | 0 | 0 | 0 |
| El Obeid | 2yr | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| El Obeid | 10yr | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Nyala | 20mm | 0 | 0 | 0 | 1 | 3 | 0 | 2 | 1 | 0 | 1 |
| Nyala | 2yr | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 |
| Nyala | 10yr | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Each row above reports exact counts out of 51 members; zero means no member exceeds that threshold on that forecast day.

## Xclim heavy-rain-day counts

`xclim.indices.wetdays` counts days **>=** the threshold for each member during the ten-day forecast window. The daily comparison plots count **>**; equality is deliberately distinguished.
All 765 xclim counts (5 towns × 3 thresholds × 51 members) were checked against a direct count.

| Town | Threshold | Members with >=1 heavy day | Mean heavy days/member |
|---|---|---:|---:|
| Khartoum | 20mm | 0/51 | 0.000 |
| Khartoum | 2yr | 0/51 | 0.000 |
| Khartoum | 10yr | 0/51 | 0.000 |
| Kassala | 20mm | 5/51 | 0.098 |
| Kassala | 2yr | 0/51 | 0.000 |
| Kassala | 10yr | 0/51 | 0.000 |
| Gedaref | 20mm | 22/51 | 0.471 |
| Gedaref | 2yr | 0/51 | 0.000 |
| Gedaref | 10yr | 0/51 | 0.000 |
| El Obeid | 20mm | 7/51 | 0.176 |
| El Obeid | 2yr | 1/51 | 0.020 |
| El Obeid | 10yr | 0/51 | 0.000 |
| Nyala | 20mm | 7/51 | 0.157 |
| Nyala | 2yr | 2/51 | 0.039 |
| Nyala | 10yr | 0/51 | 0.000 |

Heavy-day means describe the ten-day forecast window, not annual totals. Members with at least one heavy day are counted once, even if they have several heavy days.

## Extension: is an annual 2-year level fair for one daily warning?

It is useful for screening unusually large rain, but cannot alone determine an operational daily warning. A fitted 2-year annual level has a 50% chance of at least one exceedance in a year, not a 50% chance each day.
- Khartoum: 12/27 observed annual maxima exceed 23.82 mm (44.4%).
- Kassala: 13/27 observed annual maxima exceed 37.95 mm (48.1%).
- Gedaref: 18/27 observed annual maxima exceed 52.98 mm (66.7%).
- El Obeid: 15/27 observed annual maxima exceed 37.18 mm (55.6%).
- Nyala: 15/27 observed annual maxima exceed 32.32 mm (55.6%).

In this forecast, threshold sensitivity differs by town:
- Khartoum: fixed 20 mm gives **0/510** member-day exceedances (0.00%); 2-year gives **0/510** (0.00%); 10-year gives **0/510** (0.00%).
- Kassala: fixed 20 mm gives **5/510** member-day exceedances (0.98%); 2-year gives **0/510** (0.00%); 10-year gives **0/510** (0.00%).
- Gedaref: fixed 20 mm gives **24/510** member-day exceedances (4.71%); 2-year gives **0/510** (0.00%); 10-year gives **0/510** (0.00%).
- El Obeid: fixed 20 mm gives **9/510** member-day exceedances (1.76%); 2-year gives **1/510** (0.20%); 10-year gives **0/510** (0.00%).
- Nyala: fixed 20 mm gives **8/510** member-day exceedances (1.57%); 2-year gives **2/510** (0.39%); 10-year gives **0/510** (0.00%).
- Under an illustrative model with independent, identical days, daily p = 1 − 0.5^(1/365) = **0.190%**. Rainfall is seasonal and dependent, so this is not a calibrated local daily probability.
- These numbers show different sensitivity; ensemble member-days are correlated predictions and do not estimate observed climatological frequency.
- Choosing a warning needs impact records, forecast verification, false-alarm/miss tradeoffs and an explicit probability decision rule.

## Checks and limitations

- All five towns lie inside the recorded forecast and CMORPH source domains. Forecast latitude descends; CMORPH latitude ascends.
- Source-domain evidence was verified in the earlier connected extraction and retained in the cache. This final run validates that evidence without a fresh cloud query.
- Task A coordinates and selected CMORPH pixels match that source-domain evidence.
- All 51 members are finite at every cumulative endpoint; intervals are consecutive 24-hour periods.
- 19 tiny negative daily differences were set to zero. Minimum raw difference: -0.030518 mm; tolerance: 0.05 mm. Larger decreases stop the analysis.
- Repeated small increments are consistent with encoding noise, but that cause has not been independently established.
- Forecast and CMORPH nearest pixels have different sizes and footprints; these are grid-cell comparisons, not rain-gauge measurements.
- No observed 2025 event rainfall or impacts were supplied, so this exercise compares thresholds rather than proving warning skill.
