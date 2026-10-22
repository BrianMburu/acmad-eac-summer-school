"""Compare three warning thresholds at selected towns (group Part B, workshop E5/E6).

Run inspect, extract, then plots. Only extract reads forecast rainfall; plots is
offline. All settings are in scripts/common.py; --config loads a saved override.
"""

import argparse
import importlib.metadata
import json
import os
import tempfile
import time
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from scripts.common import (ROOT, ConfigError, config_hash, extraction_hash, load_config,
                            slugify, validate_threshold_choice)
from scripts.data_access import open_store
from scripts.forecast_rainfall import daily_rainfall, select_town_forecasts
from scripts.rainfall_thresholds import (file_sha256, provenance, require_complete_run,
                                        verify_saved_settings, write_json, write_status)


def load_handoff(directory, config):
    """Verify Part A's saved results, settings and snapshot before using its levels."""
    require_complete_run(directory)
    saved = load_config(directory / "settings_used.json")
    verify_saved_settings(saved, directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    snapshot = manifest["store_snapshots"]["cmorph"]
    expected = config["cmorph_reference"]["snapshot_id"]
    if expected and snapshot != expected:
        raise ValueError("Part A CMORPH snapshot differs from the configured snapshot")
    # Legacy exports followed main; their manifest still pins the actual snapshot.
    saved, current = deepcopy(saved), deepcopy(config)
    saved["cmorph_reference"]["snapshot_id"] = snapshot
    current["cmorph_reference"]["snapshot_id"] = snapshot
    if extraction_hash(saved) != extraction_hash(current):
        raise ValueError("Part A geography, reference years or threshold settings differ; re-extract Part A")
    levels = pd.read_csv(directory / "thresholds.csv")
    maxima = pd.read_csv(directory / "annual_maxima.csv")
    rows = []
    ref = config["cmorph_reference"]
    years = set(range(ref["reference_start_year"], ref["reference_end_year"] + 1))
    for town in config["threshold_choice"]["towns"]:
        for period, label in [(None, "fixed_20mm"), (2, "local_2yr"), (10, "local_10yr")]:
            threshold = config["threshold_choice"]["fixed_threshold_mm"]
            if period is not None:
                match = levels[(levels.town == town) & (levels.duration == "24hr")
                               & (levels.return_period_years == period)]
                if len(match) != 1 or match.iloc[0]["units"] != "mm":
                    raise ValueError(f"Need exactly one mm threshold for {town}, 24hr, {period} years")
                threshold = float(match.iloc[0].threshold_mm)
            if not np.isfinite(threshold) or threshold <= 0:
                raise ValueError(f"Invalid threshold for {town}: {threshold}")
            series = maxima[(maxima.town == town) & (maxima.duration == "24hr")]
            if (len(series) != len(years) or set(series.year) != years
                    or not np.isfinite(series.rainfall_mm).all() or not (series.units == "mm").all()):
                raise ValueError(f"Invalid Part A annual maxima for {town}")
            above = int((series.rainfall_mm > threshold).sum())
            rows.append({"town": town, "threshold": label, "threshold_mm": threshold,
                         "operator": ">", "annual_maxima_above": above,
                         "reference_years": len(years), "annual_maxima_above_percent": 100 * above / len(years)})
        town_levels = rows[-3:]
        if town_levels[1]["threshold_mm"] > town_levels[2]["threshold_mm"]:
            raise ValueError(f"Part A return levels decrease at {town}")
    return pd.DataFrame(rows), {"directory": str(directory.resolve()), "cmorph_snapshot": snapshot,
            "source_commit": manifest.get("git_commit"),
            "sha256": {name: file_sha256(directory / name) for name in
                       ["thresholds.csv", "annual_maxima.csv", "settings_used.json", "manifest.json"]}}


def count_thresholds(daily, thresholds, initialization):
    """Daily member counts and xclim per-member heavy-day counts, strict > throughout."""
    from xclim.indices import wetdays

    counts, heavy, summary = [], [], []
    for threshold in thresholds.itertuples():
        pr = daily.sel(town=threshold.town)
        above = pr > threshold.threshold_mm
        daily_count = above.sum("number")
        # Each call contains one forecast horizon, not a complete calendar year.
        # xclim/pandas need three timestamps to infer a daily frequency. NaN
        # padding supplies that cadence for short end-of-season horizons and
        # contributes no days to this low-level count; the direct check below
        # confirms that only the real forecast days are counted.
        xinput = pr if pr.sizes["time"] >= 3 else pr.reindex(
            time=pd.date_range(pr.time.values[0], periods=3, freq="D"))
        xcount = wetdays(xinput, thresh=f"{threshold.threshold_mm:.17g} mm/day", freq="YS", op=">").sum("time")
        manual = above.sum("time")
        if not np.array_equal(xcount.values, manual.values):
            raise ValueError("xclim heavy-day counts disagree with the direct strict > calculation")
        common = {"initialization": initialization, "town": threshold.town,
                  "threshold": threshold.threshold, "threshold_mm": threshold.threshold_mm,
                  "operator": ">", "members_total": pr.sizes["number"]}
        for i in range(pr.sizes["time"]):
            n = int(daily_count.isel(time=i))
            counts.append({**common, "forecast_day": int(pr.forecast_day.isel(time=i)),
                           "valid_end": pd.Timestamp(pr.time.values[i]).isoformat(),
                           "members_above": n, "percent_above": 100 * n / pr.sizes["number"]})
        for number, days in zip(pr.number.values, xcount.values):
            heavy.append({**common, "member": int(number), "heavy_days": int(days),
                          "forecast_days": pr.sizes["time"], "method": "xclim.indices.wetdays"})
        total = int(daily_count.sum())
        summary.append({**common, "forecast_days": pr.sizes["time"], "member_days_above": total,
                        "member_days_total": pr.sizes["time"] * pr.sizes["number"],
                        "member_days_above_percent": 100 * float(above.mean()),
                        "peak_members_above": int(daily_count.max()),
                        "forecast_days_with_signal": int((daily_count > 0).sum()),
                        "members_with_any_heavy_day": int((xcount > 0).sum()),
                        "mean_heavy_days_per_member": float(xcount.mean()),
                        "max_heavy_days_per_member": int(xcount.max())})
    return pd.DataFrame(counts), pd.DataFrame(heavy), pd.DataFrame(summary)


def check_read_budget(report, config):
    volume = report["decoded_source_mib"]
    print(f"Selected source chunks: {report['source_chunks_touched']}; decoded volume {volume:.1f} MiB; "
          f"town-point result {report['selected_point_mib']:.3f} MiB. "
          "Compressed transfer and peak RAM are not measured by this estimate.", flush=True)
    if volume > 256:
        print("SIZE WARNING: source chunks exceed 256 MiB despite the small point selection. "
              "Processing one start at a time with the configured worker limit.", flush=True)
    if volume > config["threshold_choice"]["max_source_mib"]:
        raise ValueError("Selected source volume exceeds threshold_choice.max_source_mib; reduce the "
                         "start dates or explicitly raise this budget before extracting")


def read_start(selected, date, config, out, snapshot, report, *, cache_directory=None, cache_only=False):
    """Cache the small raw point slice before scientific validation, for safe retries."""
    inputs = {"store": {k: v for k, v in config["forecast"].items() if k != "start_dates"},
              "snapshot": snapshot, "date": date, "towns": report["towns"],
              "daily_lead_hours": report["daily_lead_hours"]}
    digest = config_hash(inputs)
    cache_dir = Path(cache_directory) if cache_directory is not None else out / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{date}-{digest[:16]}.nc"
    metadata = path.with_suffix(".json")
    if metadata.exists():
        saved = json.loads(metadata.read_text())
        if saved["input_sha256"] != digest or not path.exists() or saved["file_sha256"] != file_sha256(path):
            raise ValueError(f"Invalid point cache {path}; remove that cache entry before retrying")
        print(f"Using cached cumulative town forecasts for {date}", flush=True)
        with xr.open_dataarray(path, engine="scipy", decode_timedelta=True) as cached:
            return cached.load()
    if cache_only:
        raise FileNotFoundError(f"No cached point forecast for {date}")
    cumulative = selected.sel(time=date).compute(scheduler="threads",
                                num_workers=config["execution"]["workers"])
    # NetCDF3 needs only SciPy and avoids installing another binary dependency.
    cached = cumulative.copy(deep=False)
    cached.encoding = {}
    for name in cached.coords:
        cached[name].encoding = {}
    with tempfile.TemporaryDirectory(prefix=".point-", dir=cache_dir) as temporary:
        temporary_path = Path(temporary) / "forecasts.nc"
        cached.to_netcdf(temporary_path, engine="scipy")
        os.replace(temporary_path, path)
    write_json(metadata, {"input_sha256": digest, "file_sha256": file_sha256(path), "inputs": inputs})
    return cumulative


def run_remote(config, thresholds_dir, out, inspection_only=False):
    validate_threshold_choice(config)
    thresholds, handoff = load_handoff(thresholds_dir, config)
    out.mkdir(parents=True, exist_ok=True)
    status_file = "inspection_status.json" if inspection_only else "run_status.json"
    write_status(out, "running", filename=status_file, stage="inspect")
    started = time.perf_counter()
    try:
        ds, snapshot = open_store(config["forecast"])
        with closing(ds):
            selected, report = select_town_forecasts(ds, config)
            report.update(forecast_snapshot=snapshot, handoff=handoff, config_sha256=config_hash(config))
            write_json(out / "inspection.json", report)
            check_read_budget(report, config)
            if inspection_only:
                write_status(out, "ok", filename=status_file, stage="inspect")
                print("Inspection passed; forecast rainfall was not read.")
                return
            all_counts, all_heavy, all_summary, all_daily, starts = [], [], [], [], []
            for date in config["forecast"]["start_dates"]:
                print(f"Reading daily leads at {selected.sizes['town']} towns for {date} ...", flush=True)
                cumulative = read_start(selected, date, config, out, snapshot, report)
                daily = daily_rainfall(cumulative, report["units"]["mm_factor"],
                                       config["threshold_choice"]["trace_rainfall_mm"])
                if daily is None:
                    starts.append({"initialization": date, "status": "skipped_all_nan"})
                    print(f"Skipped {date}: selected forecast is entirely NaN (unwritten start).", flush=True)
                    continue
                # Keep 24-hour intervals within the configured season. End time
                # 1 September 00 UTC is the end of the last August day.
                daily = daily.sel(time=slice(config["start_date"],
                    pd.Timestamp(config["end_date"]) + pd.Timedelta(days=1)))
                if not daily.sizes["time"]:
                    starts.append({"initialization": date, "status": "skipped_outside_season"})
                    continue
                counts, heavy, summary = count_thresholds(daily, thresholds, date)
                all_counts.append(counts)
                all_heavy.append(heavy)
                all_summary.append(summary)
                frame = daily.to_dataframe().reset_index()
                frame["initialization"] = date
                frame = frame.rename(columns={"time": "valid_end"})
                all_daily.append(frame)
                starts.append({"initialization": date, "status": "ok", "forecast_days": daily.sizes["time"],
                               **{key: daily.attrs[key] for key in ["tiny_negative_totals_clipped",
                                   "positive_trace_totals_zeroed", "minimum_uncorrected_daily_mm", "trace_rainfall_mm"]}})
                print(summary[["town", "threshold", "threshold_mm", "peak_members_above"]].to_string(index=False), flush=True)
            if not all_counts:
                write_json(out / "forecast_starts.json", starts)
                raise ValueError("No usable forecast starts; select written starts before continuing")
            with tempfile.TemporaryDirectory(prefix=".extract-", dir=out) as temp:
                staging = Path(temp)
                frames = {"daily_member_counts.csv": pd.concat(all_counts, ignore_index=True),
                          "heavy_rain_days.csv": pd.concat(all_heavy, ignore_index=True),
                          "summary_counts.csv": pd.concat(all_summary, ignore_index=True),
                          "daily_rainfall.csv": pd.concat(all_daily, ignore_index=True),
                          "thresholds_used.csv": thresholds}
                for name, frame in frames.items():
                    frame.to_csv(staging / name, index=False)
                write_json(staging / "forecast_starts.json", starts)
                write_json(staging / "settings_used.json", config)
                manifest = provenance(config, {"cmorph": handoff["cmorph_snapshot"], "forecast": snapshot})
                manifest.update(handoff=handoff, inspection=report, forecast_starts=starts,
                    elapsed_seconds=time.perf_counter() - started,
                    adapted_from=["workshop E5: daily totals and xclim heavy-day counts",
                                  "workshop E6: local threshold comparison and member counts"],
                    interpretation="Sampled forecast starts; forecasts of 24-hour rainfall, not observed 2025 events. "
                                   "Heavy-day counts describe each available horizon, not a whole season.")
                manifest["packages"]["xclim"] = importlib.metadata.version("xclim")
                manifest["output_sha256"] = {path.name: file_sha256(path) for path in staging.iterdir()}
                write_json(staging / "manifest.json", manifest)
                for path in sorted(staging.iterdir(), key=lambda p: p.name == "manifest.json"):
                    os.replace(path, out / path.name)
            write_status(out, "ok", filename=status_file, stage="complete")
            print(f"Saved Part B tables and daily point cache in {out}", flush=True)
    except Exception as exc:
        write_status(out, "failed", filename=status_file, error=str(exc))
        raise


def plot_outputs(out):
    """Plot the cached counts without opening a store or importing xclim."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    require_complete_run(out)
    manifest = json.loads((out / "manifest.json").read_text())
    for name, digest in manifest["output_sha256"].items():
        if file_sha256(out / name) != digest:
            raise ValueError(f"Cached {name} differs from its manifest; re-extract before plotting")
    config = load_config(out / "settings_used.json")
    validate_threshold_choice(config)
    counts = pd.read_csv(out / "daily_member_counts.csv")
    figures = out / "figures"
    figures.mkdir(exist_ok=True)
    labels = {"fixed_20mm": "Fixed 20 mm", "local_2yr": "Local 2-year", "local_10yr": "Local 10-year"}
    for town in config["threshold_choice"]["towns"]:
        town_data = counts[counts.town == town]
        dates = town_data.initialization.unique()
        fig, axes = plt.subplots(len(dates), 1, figsize=(10, 3.5 * len(dates)), squeeze=False)
        for ax, date in zip(axes[:, 0], dates):
            for threshold, data in town_data[town_data.initialization == date].groupby("threshold", sort=False):
                data = data.sort_values("forecast_day")
                ax.plot(data.forecast_day, data.members_above, marker="o", lw=1.5,
                        label=f"{labels[threshold]}: > {data.threshold_mm.iloc[0]:.1f} mm / 24 h")
            ax.set(title=f"Start {date}", xlabel="Forecast day (24 h ending at this lead)",
                   ylabel="Members above threshold (of 51)", ylim=(-0.5, 51.5),
                   xticks=sorted(town_data[town_data.initialization == date].forecast_day.unique()))
            ax.grid(alpha=.3)
            ax.legend(fontsize=8)
        fig.suptitle(f"{town}: sensitivity to the warning threshold\nECMWF IFS ensemble, JJA 2025 sampled starts")
        fig.tight_layout()
        fig.savefig(figures / f"{slugify(town)}_threshold_choice.png", dpi=150)
        plt.close(fig)
    print(f"Saved {len(config['threshold_choice']['towns'])} threshold-comparison figures in {figures}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["inspect", "extract", "plots"])
    parser.add_argument("--config", type=Path, help="JSON override; defaults to scripts/common.py")
    parser.add_argument("--thresholds", type=Path, help="verified Part A result directory")
    parser.add_argument("--out", type=Path, help="defaults to threshold_choice.output_directory")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        out = args.out or ROOT / config["threshold_choice"]["output_directory"]
        if args.stage == "plots":
            plot_outputs(out)
        else:
            thresholds_dir = args.thresholds or ROOT / config["execution"]["output_directory"]
            run_remote(config, thresholds_dir, out, args.stage == "inspect")
    except (ConfigError, ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
