# task_D: Where is the risk?

Final Task D includes its own **grid.json**, which supplies **all five towns**
and defines the region (bounding box of the town extents, plus a one-degree
margin). Towns: Khartoum, Kassala, Gedaref, El Obeid and Nyala.

References: workshop **08_exceedance_probability_map.py** (E8) and
**03_pan_vs_pencil.py** (E3).

The four starts are **10 June, 1 July, 22 July and 12 August 2025**, each with
days **1–5**: **20 sampled daily forecast intervals** across JJA. This is not a
complete-season frequency. The default probability decision is **>=20%**.

## Run

From the repository, use the existing environment:

```sh
../part_a_extremes/.venv312/bin/python -u task_D/analyze.py
```

No new cloud download or packages are needed. Saved actual probabilities and
their original source metadata are retained under `inputs/`. The script
validates source/grid signatures, the five-town domains, coordinate ordering
and probability values, then redraws figures and recalculates frequencies.
It does not recompute probabilities from raw rainfall, which is not retained
in these regional caches. Use `--probability 0.1` to inspect another decision
level without downloading data; this overwrites current figures and reports.

## Open these outputs

- **`results.md`**: regional hotspots versus town results, units, denominator,
  original read times and E3 explanation.
- Four **`probabilities_YYYY-MM-DD.png`** figures, one panel per daily lead,
  with every grid.json town marked. All panels share a stated color scale
  chosen to reveal low probabilities; blue contours mark the decision level.
- **`sampled_season_frequency.png`**: count, available-interval percentage
  and available-interval denominator, with town markers.
- **`town_frequency.csv`**: town coordinates, selected forecast pixels,
  counts, availability, percentage fractions and peak probabilities.
- **`regional_hotspots.csv`**: actual pixel coordinates and member counts for
  every sampled interval reaching the probability decision.
- `probability_summary.csv`: per-start/day maxima and decision-passing pixels.
- **`read_timings.csv`**: original cloud read records and separately labeled
  current local-cache timings, source chunk counts and original QC corrections.
- `regional_probability_results.npz`: probability, frequency, availability,
  coordinates, forecast starts and days for reproducibility.
- `run_metadata.json`: script/grid/input hashes, Git revision, source signature
  and retained connected domain-verification evidence.

## Interpretation and checks

Each forecast grid point uses its nearest CMORPH pixel's **local 2-year 24 h
threshold**, not one rainfall threshold for the whole region. Threshold units
are **mm accumulated in 24 h**. Probability is the fraction of **51 members**
with daily rainfall **strictly above** the threshold. The decision uses **>=**:
>=20% requires at least **11/51 members (21.57%)**; 10/51 is only 19.61%.

Frequency counts sampled forecast intervals, not unique events or all JJA
days. Its percentage denominator is the available intervals at each pixel.
Missing members/thresholds are masked, not silently counted as zero. Gray maps
indicate missing data. Forecast latitude descends; CMORPH latitude ascends.
The current offline run validates previous source-domain evidence rather
than claiming a new cloud query. All five towns and full regional bounds are
checked against both recorded domains.

Town results refer to nearest **forecast** pixels. That pixel's nearest
CMORPH cell can differ from the direct town-coordinate CMORPH selection in
Tasks A–C. Different resolution and footprints limit a direct point comparison.

The original read timings and chunk shapes explain why maps are efficient:
one forecast chunk contains one start/lead, all 51 members and a broad map.
Six cumulative endpoints give five daily maps per start. Do not confuse the
new millisecond local-cache reads with original cloud performance.

Outputs describe forecast rainfall hazard. Without observed 2025 rainfall or
impacts, they are not verified event forecasts or calibrated impact-risk maps.
All figures come from this committed script; data and figures stay local.
