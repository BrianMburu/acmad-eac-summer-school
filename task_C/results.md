# Task C: Did the forecast see it coming?

All five towns in **grid.json**. Forecast starts **2025-07-06–2025-07-26**, inclusive; days 1–10; 51 members.
The rainfall threshold is each town’s published Task A **2-year, 24 h level**. Counts use strict rainfall > threshold.
Default exploratory signal: at least one member (1/51 = 1.96%). This is not an operational warning rule.

## Main results

| Town | Threshold (mm in 24 h) | Peak members | Strongest start | Starts with any signal |
|---|---:|---:|---|---:|
| Khartoum | 23.82 | 3/51 | 2025-07-21 | 19/21 |
| Kassala | 37.95 | 2/51 | 2025-07-23 | 10/21 |
| Gedaref | 52.98 | 1/51 | 2025-07-20 | 2/21 |
| El Obeid | 37.18 | 4/51 | 2025-07-07 | 12/21 |
| Nyala | 32.32 | 4/51 | 2025-07-07 | 20/21 |

The strongest start maximizes its largest daily count, breaking ties by summed member-day counts, then earliest start. Plumes show daily rainfall, not cumulative totals.

## Earliest signal: identify the target interval

Earliest means greatest lead time before one valid 24-hour interval. Ties select the earliest target ending date; this is an illustrative target, not the only tied target.

| Town | Maximum lead (days) | Issued on | Target interval ends |
|---|---:|---|---|
| Khartoum | 10 | 2025-07-18 | 2025-07-28 00:00:00 |
| Kassala | 10 | 2025-07-06 | 2025-07-16 00:00:00 |
| Gedaref | 8 | 2025-07-20 | 2025-07-28 00:00:00 |
| El Obeid | 10 | 2025-07-12 | 2025-07-22 00:00:00 |
| Nyala | 10 | 2025-07-07 | 2025-07-17 00:00:00 |

A 10-day lead equals the available forecast horizon. Towns tied there cannot be ranked uniquely as earliest, and different towns may be signaling different valid days.

## Consistency: repeated forecasts for the SAME interval

| Town | Consecutive starts | First start | Last start | Target interval ends |
|---|---:|---|---|---|
| Khartoum | 3 | 2025-07-07 | 2025-07-09 | 2025-07-16 00:00:00 |
| Kassala | 2 | 2025-07-24 | 2025-07-25 | 2025-07-28 00:00:00 |
| Gedaref | 1 | 2025-07-20 | 2025-07-20 | 2025-07-28 00:00:00 |
| El Obeid | 2 | 2025-07-06 | 2025-07-07 | 2025-07-12 00:00:00 |
| Nyala | 5 | 2025-07-07 | 2025-07-11 | 2025-07-17 00:00:00 |

Target interval starts exactly 24 hours before its ending timestamp. Boundary targets have fewer available starts; `same_valid_day_signals.csv` records denominators and all target dates.

## Sensitivity to requiring more members

| Town | Required members | Signal starts | Longest target-day streak |
|---|---:|---:|---:|
| Khartoum | 1/51 (1.96%) | 19 | 3 |
| Kassala | 1/51 (1.96%) | 10 | 2 |
| Gedaref | 1/51 (1.96%) | 2 | 1 |
| El Obeid | 1/51 (1.96%) | 12 | 2 |
| Nyala | 1/51 (1.96%) | 20 | 5 |
| Khartoum | 3/51 (5.88%) | 1 | 1 |
| Kassala | 3/51 (5.88%) | 0 | 0 |
| Gedaref | 3/51 (5.88%) | 0 | 0 |
| El Obeid | 3/51 (5.88%) | 1 | 1 |
| Nyala | 3/51 (5.88%) | 2 | 1 |
| Khartoum | 5/51 (9.80%) | 0 | 0 |
| Kassala | 5/51 (9.80%) | 0 | 0 |
| Gedaref | 5/51 (9.80%) | 0 | 0 |
| El Obeid | 5/51 (9.80%) | 0 | 0 |
| Nyala | 5/51 (9.80%) | 0 | 0 |

Earliest-lead tie: **Khartoum, Kassala, El Obeid, Nyala**, 10 days.
Most persistent: **Nyala**, 5 consecutive starts for one target interval.

## Why do signals differ, and did the forecast get it right?

Signals depend jointly on the local rainfall threshold, predicted daily amounts and ensemble spread. For example, Nyala’s threshold is lower than Gedaref’s, but thresholds alone cannot explain differences: Khartoum has the lowest threshold and is not automatically the most persistent.
The default one-member criterion is weak; the stronger-criterion table shows how conclusions change. Signal frequency across starts is distinct from persistence for one target interval.
**Observed 2025 rainfall and impact data are not provided.** These are forecast signals, not verified hits, misses or warning skill. Annual maxima ending in 2024 cannot verify July 2025 events.

## Units and validation

- Daily rainfall = difference of consecutive cumulative tp endpoints ×1000, converting m to mm in 24 h. Count units are members, of 51.
- grid.json determines all five towns and their order. Every cache’s source/town fingerprint is checked.
- Task A thresholds and selected CMORPH pixels match recorded source-domain evidence.
- Earlier connected checks established both domains, descending forecast latitude and ascending CMORPH latitude. This offline run rechecks retained evidence, not fresh cloud metadata.
- A town/day requires all 51 member endpoints; missing data are gray, not zero. The QC table records missing cells and small-negative corrections.
- 148 tiny negative increments were clipped to zero. Tolerance is 0.05 mm; larger decreases stop execution.
- Forecast and CMORPH pixels have different areas; nearest-point matching is not a rain-gauge comparison.
