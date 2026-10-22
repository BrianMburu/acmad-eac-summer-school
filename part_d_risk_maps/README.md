# Part D: Where is the risk?

References: workshop `08_exceedance_probability_map.py` (E8) and
`03_pan_vs_pencil.py` (E3). The region is the bounding box of all five town
extents in `grid.json`, with one degree of margin on every side.

Default starts are **10 June, 1 July, 22 July and 12 August 2025**, each with
forecast days **1–5**. These are 20 nonoverlapping valid daily intervals sampled
across JJA. They do not represent all days or forecast starts in the season.

Run using the existing environment (no additional dependencies beyond Part A):

```sh
cd /Users/mac/Group1/acmad-eac-summer-school
../part_a_extremes/.venv312/bin/python -u part_d_risk_maps/analyze.py
```

Options include `--probability 0.2`, `--days 5`, and `--starts` followed by three
or four dates. All valid intervals must stay in the configured season. Completed
regional probabilities are cached per start; rerun to resume. Use `--offline`
after all caches exist to redraw figures without accessing cloud data.

## Outputs in this folder

- Four `probabilities_YYYY-MM-DD.png` figures, with one panel per forecast day.
  Color shows the fraction of 51 members above the **local** 2-year 24 h CMORPH
  level; the shared color scale is 0–100%. Blue contours identify the chosen
  probability decision level wherever it crosses the field. All towns are marked.
- `sampled_season_frequency.png`: one figure with the number of sampled forecast
  intervals reaching the probability decision level, percentage of available
  intervals, and available-interval count. The denominator is normally 20, but
  may vary spatially with missing forecasts or thresholds.
- `town_frequency.csv`: frequency at the nearest forecast pixel for each town.
- `probability_summary.csv`: per-start/day maximum probabilities and counts of
  grid points meeting the probability criterion.
- `read_timings.csv`: measured reads, original read records for reused caches,
  and estimates of source storage chunks touched (not HTTP request counts).
- `regional_probability_results.npz`: arrays of probabilities, counts, available
  intervals, fractions, dates, leads, and coordinates.
- `results.txt` and `run_metadata.json`: explanation, source coordinates and
  chunk shapes, timing records, script hash and commit revision.

## Units, denominator and missing data

Each 24 h rainfall depth is the difference of cumulative `tp` endpoints in
metres, multiplied by 1000. Rainfall threshold units are **mm in 24 h**.
At each forecast pixel, the threshold is matched to the nearest CMORPH pixel;
it is not a single constant threshold for the region. Probability is the
fraction of members with rainfall **strictly greater than** that threshold.
The frequency criterion is probability **greater than or equal to** 20%.
With 51 members this requires 11/51 = **21.57%**: 10/51 = 19.61% does not pass.

Every pixel/day requires all 51 members' endpoints and a finite threshold.
Missing data are masked, never counted as zero rainfall. Counts exclude missing
intervals; percentages use the number available at each pixel. Gray probability
cells are missing; a zero probability is a valid forecast with no exceedances.
Tiny negative differences up to 0.05 mm are clipped to zero and counted in the
read records. Larger decreases stop execution rather than hiding a data problem.

Metadata checks require descending forecast latitude, ascending CMORPH latitude,
all towns inside both domains, and the full region inside both domains. Forecast
and CMORPH resolutions differ; nearest matching is not conservative regridding.
No observed impact or 2025 rainfall verification is supplied, so these are
rainfall-hazard probabilities rather than calibrated impact-risk estimates.

## Why maps can be cheap with these chunks

E3 contrasts pan and pencil layouts. A pan chunk covers a broad spatial map
for a particular initialization and lead, often containing all 51 members.
A map uses many values already in the same chunk; a point read may need to
retrieve that same map-sized chunk. A multi-lead series touches many time/lead
chunks. A pencil layout instead puts many times for a small spatial patch into
one chunk, helping point series but making maps touch many spatial chunks.

The script records actual source chunk shapes and computes the unique chunk
indices intersecting the selected dates, steps, members and region. Therefore
its estimates do not assume exactly one chunk per map when the stored encoding
differs. Daily differencing needs two cumulative endpoints; adjacent daily maps
reuse endpoints, so six selected endpoints produce five daily maps per start.
For a one-date/one-lead pan layout this is about 24 forecast chunks for four
starts, plus the threshold chunks and metadata. The actual count is reported.
No non-daily lead times are read. Timings include transfer, decoding and compute;
they depend on cache, connection and compression and are not pure bandwidth tests.

Initial validation: syntax and synthetic checks for probabilities, missing-data
masking, negative-rainfall rejection and storage-chunk counts. Scientific outputs
remain pending the first connected extraction; no timings or probabilities have
been fabricated.
