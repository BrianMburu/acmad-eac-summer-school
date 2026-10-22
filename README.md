# Sudan rainfall extremes and warning thresholds

Part A extracts 1998–2024 CMORPH annual maxima and Gumbel thresholds at five
Sudan towns. Part B compares 20 mm, 2-year and 10-year rainfall thresholds at
Khartoum and Kassala using the ECMWF ensemble initialized 16 July 2025.

Original workshop references (read-only):
`icpac-igad/python-workshop/exercises/04_cmorph_return_periods.py`,
`05_xclim_heavy_rain.py`, and `06_forecast_vs_local_extremes.py`.

Use Python 3.12+ with the packages in `part_b_warnings/requirements.txt`.
Run Part A first to generate its threshold table, then Part B:

```sh
python part_a_extremes/analyze.py
python part_b_warnings/analyze.py
```

Each folder contains detailed run instructions. `part_b_warnings/OUTPUT_GUIDE.md`
explains units, member counts, xclim counts and annual versus daily thresholds.
Figures and data stay local and are ignored by Git; their generating scripts
are committed. Part B run metadata records its script hash and commit revision.

The historical cached Part B run passed finite-value and xclim checks, but its
cache did not preserve both stores' coordinate metadata. Fresh runs now require
verified domains and latitude orders. To verify coordinates without rereading
cached rainfall, run Part B with `--use-cache --refresh-domain-checks` while online.
Offline legacy-cache outputs explicitly preserve this validation limitation.

For topic changes in an interactive workshop agent session, use `/clear` before
the next topic. It is a chat command, not a Python or shell command.
