# Review of Tasks A–D

Reviewed against the requested approaches and outputs, using the existing local
tables, cached data, script versions and metadata. No new cloud downloads were
needed. This review does not replace visual inspection of every figure or
verification against independently observed 2025 event rainfall.

## A: How extreme is extreme?

Present: five town return-level figures, regional 10-year 24 h map, annual
maxima, 2/10/50-year threshold table for 24 h and 6 h, largest-year sensitivity.
Checked: 270 annual maxima = 5 towns × 2 durations × 27 years, all 1998–2024;
30 threshold rows; every stored exceedance count agrees with the saved maxima.

Needs clearer interpretation: a short per-town account of where the observed
maxima depart from the stored fitted levels, naming the relevant years. The
current figures annotate large years and the table lists threshold crossings,
but neither justifies calling a particular year a failure of the Gumbel model.
Use a transparent descriptive discrepancy criterion, without declaring an
observation an outlier merely because it exceeds a return level.

The removal extension consistently compares two MLE fits. Published store
thresholds can differ from the MLE refit; keep the estimators distinguished.
Example: Khartoum 24 h MLE 50-year depth changes from 68.23 to 62.05 mm
(-9.05%) when 2017 is removed; the published 50-year level is 76.05 mm.
Add run metadata for A: it currently lacks the script hash and Git revision
recorded for C and D. Some README validation notes still describe an unrun script.

## B: Which threshold should trigger a warning?

Present: per-town and combined plots, daily short table, exact daily counts,
xclim heavy-day counts, annual-versus-daily numerical discussion. Checked all
60 town/day/threshold counts against saved rainfall (51 members per cell).

Results: Khartoum has no exceedances. Kassala exceeds 20 mm in 24 h with two
members on day 1, two on day 6, and one on day 9. Neither exceeds its local
2-year or 10-year threshold. Forecast and CMORPH source domains are now verified.

Needs cleanup: the analysis run metadata script hash predates the plotting
integration. Refresh it by a cached run from the current committed script;
the separate renderer also writes its own figure provenance. Documentation
that still calls domain validation pending must be updated to reflect the
successful connected metadata refresh. Keep strict > daily counts separate
from xclim >= heavy-day counts. No new forecast extraction is required.

## C: Did the forecast see it coming?

Present: all five heatmaps and strongest-start plumes, member-count tables,
same-valid-day persistence table, and earliest/consistency summary. Checked:
1,050 available cells = 21 starts × 5 towns × 10 leads; peak and signal-start
counts agree with the summary. Current analysis hash matches run metadata.

Results: peak counts are Khartoum 3/51, Kassala 2/51, Gedaref 1/51, El Obeid
4/51, Nyala 4/51. Nyala has the longest persistence: five consecutive starts
signaling the same valid interval. Four towns tie at a maximum lead of 10 days;
Gedaref's maximum lead is eight days. Ten days is also the forecast horizon,
so the tie does not identify one uniquely earliest town.

Needs clearer explanation: show the target valid date(s) alongside each town's
earliest lead and longest streak, so users can trace the ranking. The default
criterion is only one member (1.96%), so these are weak exploratory signals.
A sensitivity comparison at a stronger member criterion would strengthen the
discussion and can use cached data. Counts alone cannot establish why towns
differ causally. Observed 2025 rainfall is absent: actual forecast hits/misses
and warning skill cannot be assessed from the available annual maxima.

## D: Where is the risk?

Present: four probability figure sets with towns, one sampled-frequency figure,
town table, read times, source chunk shapes and explanatory text. Checked:
frequency and availability arrays exactly equal recomputation from the saved
four-start × five-day probability cube; current script hash matches metadata.

Results: none of the five town pixels reaches 20%. However, 12 regional grid
points reach it once each, on day 4 of the 12 August initialization (24 h ending
16 August). Peak regional probability is 16/51 = 31.37%. Thus the regional map
is not all zero. Maximum sampled frequency is 1/20 = 5%.

Keep the scope explicit: the frequency covers 20 sampled forecast intervals,
not the full set of JJA days or initialization dates. The default four starts
meet the exercise's requested seasonal sampling; a full-season analysis would
be additional work. At 51 members, >=20% requires >=11 members, not ten.
Original forecast reads take about 19–37 seconds per start and touch six pan
chunks each. One chunk covers all 51 members and the spatial map for one
date/lead. Cached local timing must not be described as cloud read speed.

## Shared cleanup and suggested order

1. A: add the concise observed-versus-fit interpretation and run provenance.
2. B: refresh cached run metadata and remove obsolete pending-domain wording.
3. C: identify target dates for earliest/persistence metrics and explain weak signals.
4. D: emphasize the 12 regional exceedance pixels versus zero town exceedances,
   plus the sampled denominator and measured timing interpretation.
5. Keep one authoritative output location: this repository. Older sibling
   folders under Group1 contain earlier copies and may confuse readers.

Scripts are committed locally and the working tree was clean before this review.
The local `final` tag still points to the earlier A/B commit 49bf14b, not the
latest C/D state. If a new final snapshot is wanted, create a new descriptive
tag after updates; do not silently move the existing tag. No push is requested.
