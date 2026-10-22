# Part B: Which threshold should trigger a warning?

Two towns: Khartoum and Kassala. Default forecast initialization: 16 July 2025,
matching workshop exercise 06. This is one forecast's daily lead intervals,
not an analysis of every JJA initialization. Source thresholds are the completed
Part A 24 h results; no CMORPH rainfall is downloaded again.

From this folder, use the existing Part A Python environment:

```sh
../part_a_extremes/.venv312/bin/python -m pip install -r requirements.txt &&
../part_a_extremes/.venv312/bin/python -u analyze.py
```

Options: `--init 2025-07-16 --towns Khartoum Kassala`.
After a point extraction has been saved, `--use-cache` reuses it without a
rainfall download. It must match the requested initialization and towns.
Older diagnostic caches lack grid coordinates; those metadata fields are null.
Use names present in Part A. The chosen date and valid intervals must be in JJA 2025.

Outputs, all alongside the script:

- `*_threshold_counts.png`: members exceeding 20 mm, local 2-year, local 10-year depths per day.
- `daily_member_counts.csv`: exact counts, fractions and valid end times.
- `summary_counts.csv`: short comparison table.
- `daily_counts_short.csv`: one row per town/day with all three threshold counts.
- `xclim_heavy_days.csv`: number of days >= each threshold per member in the forecast window.
- `daily_rainfall.csv`: extracted daily values for reproducibility.
- `results.txt`: counts and quantitative discussion of annual versus daily thresholds.
- `run_metadata.json`: source, initialization, thresholds, grid cells and package versions.

All daily comparison counts use strict `>`; xclim wetdays uses `>=`.
Its counts are cross-checked against direct NumPy counts. Warning thresholds
here are a classroom comparison; no operational trigger is inferred without
impact and verification data. Fifty-one ensemble predictions are not 51 independent observations.

QC clips negative daily differences up to 0.05 mm in magnitude to zero; larger
decreases stop execution. The observed largest decrease was 0.030518 mm, with
repeated small increments consistent with encoding noise (cause unverified).
The minimum, tolerance and number clipped are recorded in results and metadata.
The completed run's xclim counts matched direct NumPy counts.

See `OUTPUT_GUIDE.md` for the units, exact numerical results, and interpretation.
Fresh runs check both source domains and their latitude order using coordinate
metadata only, then select time, whole-day steps, and two town points before
computing rainfall. To refresh only coordinate checks with cached rainfall:

```sh
../part_a_extremes/.venv312/bin/python -u analyze.py --use-cache --refresh-domain-checks
```

Legacy cached results explicitly report source domain verification as not
recorded until this connected check is completed. Run metadata includes the
script SHA-256 hash and Git revision to identify figure provenance.
