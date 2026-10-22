# Task D: Where is the risk?

All five town markers and the regional bounds come from this folder’s **grid.json**.
Starts: **10 June 2025, 01 July 2025, 22 July 2025, 12 August 2025**, days 1–5: **20 sampled forecast intervals**.
Probability decision: **≥20%**, requiring **≥11/51 members** (21.57%).

## Regional results

- **12 regional grid points** reach the decision level at least once.
- Maximum regional probability: **31.37%**, equivalent to **16/51 members**.
- Maximum frequency: **1 of 20 sampled intervals**; largest available-interval percentage **5.0%**.

Intervals containing any grid point above the probability decision:

| Start | Lead day | Interval ends | Grid points meeting criterion | Maximum probability |
|---|---:|---|---:|---:|
| 2025-08-12 | 4 | 2025-08-16 00:00:00 | 12 | 31.37% |

The exact hotspot coordinates, probabilities and member counts are listed in `regional_hotspots.csv`.

## Five-town results

| Town | Intervals meeting criterion | Available intervals | Frequency | Highest probability |
|---|---:|---:|---:|---:|
| Khartoum | 0 | 20 | 0.0% | 1.96% |
| Kassala | 0 | 20 | 0.0% | 0.00% |
| Gedaref | 0 | 20 | 0.0% | 0.00% |
| El Obeid | 0 | 20 | 0.0% | 0.00% |
| Nyala | 0 | 20 | 0.0% | 1.96% |

A town’s zero count does not imply the entire region is zero. Each town is evaluated at its nearest forecast pixel. The regional threshold at each forecast pixel is the nearest CMORPH pixel’s local 2-year level, not one threshold applied to every location.
That matching can select a different CMORPH cell from the direct town-coordinate selection used in Tasks A–C. Grid resolution and footprints differ; this is not area-conservative regridding.

## Units and denominator

- Rainfall threshold: **mm accumulated in 24 h**. Original daily rainfall is the difference of consecutive cumulative tp endpoints in metres, multiplied by 1000.
- Probability: fraction of 51 members with rainfall **strictly >** the local 2-year 24 h threshold.
- Decision: probability **≥20%**; for a 20% decision, 10/51=19.61% fails while 11/51=21.57% passes.
- Frequency count: sampled forecast intervals meeting that probability decision. Percentage denominator: available intervals at each grid point.
- Missing thresholds or any missing member endpoint mask a cell. Missing data are not interpreted as zero probability.
- The default dates yield nonoverlapping daily intervals. These 20 samples are not the full June–August season and do not estimate observed seasonal occurrence rates.
- Previous extraction recorded and clipped small negative differences up to 0.05 mm; its correction counts are retained in read timings. Cached probabilities do not permit an independent reconstruction of the original raw rainfall.

## E3 extension: measured reads and chunk layout

| Original forecast start | Read + decode + compute (s) | Storage chunks |
|---|---:|---:|
| 2025-06-10 | 37.43 | 6 |
| 2025-07-01 | 19.49 | 6 |
| 2025-07-22 | 21.14 | 6 |
| 2025-08-12 | 34.88 | 6 |

CMORPH threshold read: **10.84 s**, **1 storage chunk**. Initial metadata open: **16.34 s**.
Forecast dimensions: `['time', 'step', 'number', 'latitude', 'longitude']`; chunk shape: `[1, 1, 51, 321, 261]`.
CMORPH threshold dimensions: `['duration', 'return_period', 'lat', 'lon']`; chunk shape: `[1, 6, 550, 474]`.
The forecast pan chunk contains one initialization, one lead time, all 51 members and the whole 321×261 spatial map. A regional map therefore reuses many values in one chunk; a point can require fetching that same chunk.
Five daily maps need six cumulative endpoints (0,24,...,120 h), hence six chunks per start and 24 across four starts, plus threshold and metadata reads. Only daily endpoints were selected before original compute.
A pencil layout concentrates time for a small spatial patch: efficient for point time series, but a regional map touches many spatial chunks.
Times depend on connection, compression and cache. Stored chunk counts are not exact HTTP request counts. `read_timings.csv` distinguishes original cloud records from this run’s local cache timings.

## Validation and interpretation limits

- All five grid.json towns and the entire requested region lie inside both recorded source domains.
- Forecast latitude descends; CMORPH latitude ascends. Current cached coordinates and source-domain evidence are rechecked offline, not freshly queried.
- Source/grid signatures match; all cached probabilities are in [0,1] and quantized to fractions of 51 members.
- Frequency and availability were recomputed from the saved probabilities. Source rainfall was not downloaded or recomputed.
- Probabilities represent a rainfall-hazard indicator. No observed impacts or 2025 rainfall verification are supplied, so this is not a calibrated impact-risk or forecast-skill assessment.
