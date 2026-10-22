# task_C: Did the forecast see it coming?

Final Task C uses **all five towns from this folder's `grid.json`**:
Khartoum, Kassala, Gedaref, El Obeid and Nyala. It covers the 21 forecast starts
from **6–26 July 2025**, days **1–10**, and **51 members**. Rainfall thresholds
are the published **2-year 24 h levels from completed task_A**.

Reference: workshop `06_forecast_vs_local_extremes.py`.

## Run

From the repository, using the existing environment:

```sh
../part_a_extremes/.venv312/bin/python -u task_C/analyze.py
```

No cloud download is required. `inputs/cache/` contains the original Task C
daily-endpoint forecast extractions, and `inputs/thresholds.csv` retains the
completed Task A table. The original extraction selected initialization, steps
0,24,...,240 h, and all five town points before compute; its source/town
fingerprint and connected domain evidence are checked again here.
Optional `--start` and `--end` must select an inclusive 14–21-day window for
which retained caches exist. Dependencies are listed in `requirements.txt`.

## Outputs

- **`results.md`**: main results, explicit target dates for earliest and most
  persistent signals, stronger-criterion comparison, units and limitations.
- **`five_town_heatmap_comparison.png`**: all towns on the same integer color scale.
- Five **`*_heatmap.png`** figures: start date × forecast day, colored by
  members strictly above the local threshold. Pale cells = zero; gray = unavailable.
- Five **`*_strongest_start_plume.png`** figures: 51 daily-rainfall member traces,
  ensemble mean, threshold, and daily exceedance counts for the strongest start.
- **`town_signal_summary.csv`**: strongest start, earliest target and same-target
  persistence for the default one-member criterion.
- **`signal_criterion_sensitivity.csv`**: comparable metrics for >=1, >=3 and
  >=5 members (1.96%, 5.88%, 9.80% of the ensemble).
- **`same_valid_day_signals.csv`**: all target intervals and their available
  forecasts, earliest lead, and longest consecutive run at each member criterion.
- `daily_member_counts.csv`: 1,050 town/start/day counts for the default window.
- `quality_control.csv`: missing-cell and tiny-negative correction counts.
- `run_metadata.json`: grid/source/input/script hashes, Git revision and
  recorded domain checks.

## Definitions

Rainfall is **mm in 24 h**, differenced from cumulative metres then multiplied
by 1000. Counts are **members**, of 51. Daily rainfall uses strict `>` against
each town's threshold. Missing member endpoints invalidate a town/day cell;
missing data are not counted as zeros. Small negative differences up to 0.05 mm
are set to zero and counted; larger decreases stop the run.

Strongest start maximizes peak member count, then summed counts, then earliest
start. Earliest means greatest forecast lead for a specific valid 24 h interval;
target dates and issuing starts are reported. Consistency is the longest run
of consecutive initialization dates signaling **that same valid interval**.
Equal earliest leads are shown as ties; ten days is also the forecast horizon.
The summary uses deterministic example targets for ties; the full target table
preserves the other tied dates and the available-forecast denominators.

The one-member criterion is exploratory, not a warning recommendation. Stronger
criteria show sensitivity. No observed 2025 rainfall or impacts are supplied,
so these results cannot verify whether the forecast got an event right.
Town differences reflect thresholds, rainfall forecasts and ensemble spread;
the counts alone cannot establish a causal explanation.

All five towns and threshold pixels are checked against recorded source domains.
Forecast latitude descends; CMORPH latitude ascends. This offline run rechecks
previously verified source evidence and does not claim a fresh cloud check.
Figures come from the committed script; cached data and outputs remain local.
