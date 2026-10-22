# Part A: How extreme is extreme?

Uses the five Sudan towns in `grid.json`, copied from the local checkout of
BrianMburu/acmad-eac-summer-school. Inspired by the read-only workshop example
`../python-workshop/exercises/04_cmorph_return_periods.py`.

## Run

Requires Python 3.12 or newer and internet access to the public CMORPH store.
From this folder, with uv installed:

```sh
uv run --with-requirements requirements.txt python analyze.py
```

Alternatively create a Python 3.12+ virtual environment, install
`requirements.txt`, and run `python analyze.py` in that environment.
The default second duration is `6hr`; change it with `--other-duration`.
The script reports available durations if the requested duration is unavailable.

## Outputs (all saved in this folder)

- Five `*_return_levels.png` figures: annual maxima and observed versus fitted
  return levels for 24 h and 6 h, with the three largest years annotated.
- `regional_10yr_24hr.png`: regional threshold map covering the five towns.
- `regional_10yr_24hr.nc`: the map values for reuse.
- `annual_maxima.csv`: 27 annual maxima per town and duration.
- `thresholds.csv`: 2-, 10-, and 50-year stored levels, selected pixel coordinates,
  counts and years exceeding each level; depths in mm.
- `sensitivity.csv`: 50-year MLE estimates with and without the largest year,
  including absolute and percentage change and the removed year.
- `results.txt`: numerical findings and interpretation caveats.

The map uses longitude/latitude axes without administrative boundaries.
Thresholds come from the published fitted store. The sensitivity comparison
uses a consistent Gumbel MLE refit on both samples; it does not assume the
published store used the same fitting estimator. An observation exceeding a
return level does not automatically invalidate the fit. The figures help
inspect discrepancies; they do not provide a formal goodness-of-fit test.

## Validation status

Python syntax was checked. Scientific execution is pending: this environment
has none of the required scientific packages and could not install icechunk.
No numerical outputs have been generated or validated. Run with internet
access to install dependencies and fetch the actual observations.
