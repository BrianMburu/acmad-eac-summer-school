"""Part C: forecast-start versus lead-day signals, adapted from E2/E5/E6.

Inspect the read cost, extract in Colab/Kaggle, then plot offline. Preview reads
only existing point caches and labels every output as incomplete.
"""

import argparse
import json
import math
import os
import tempfile
import time
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.common import (ROOT, ConfigError, config_hash, lead_time_windows, load_config,
                            slugify, validate_lead_time)
from scripts.data_access import open_store
from scripts.forecast_rainfall import daily_rainfall, select_town_forecasts
from scripts.rainfall_thresholds import (file_sha256, provenance, require_complete_run,
                                        write_json, write_status)
from scripts.threshold_choice import load_handoff, read_start


def effective_config(config):
    """Expand C's starts while retaining B's anchors and shared processing rules."""
    validate_lead_time(config)
    result = deepcopy(config)
    result["forecast"]["start_dates"] = sorted(
        day for window in lead_time_windows(config) for day in window["start_dates"])
    result["threshold_choice"]["towns"] = [town["name"] for town in config["towns"]]
    return result


def scheduled_counts(config, thresholds, lead_hours):
    """Include scheduled but unwritten starts; missing values are never dry days."""
    rows = []
    last_end = pd.Timestamp(config["end_date"]) + pd.Timedelta(days=1)
    for window in lead_time_windows(config):
        for date in window["start_dates"]:
            for hours in lead_hours:
                if hours <= 0:
                    continue
                valid = pd.Timestamp(date) + pd.Timedelta(hours=hours)
                if valid > last_end:
                    continue
                for threshold in thresholds.itertuples():
                    rows.append({"window_anchor": window["anchor"], "initialization": date,
                        "town": threshold.town, "forecast_day": hours // 24,
                        "valid_end": valid.isoformat(), "threshold_mm": threshold.threshold_mm,
                        "operator": ">", "members_total": 51})
    return pd.DataFrame(rows)


def member_counts(daily, thresholds, date):
    rows = []
    for threshold in thresholds.itertuples():
        rainfall = daily.sel(town=threshold.town)
        counts = (rainfall > threshold.threshold_mm).sum("number")
        for day, count in zip(rainfall.forecast_day.values, counts.values):
            rows.append({"initialization": date, "town": threshold.town,
                         "forecast_day": int(day), "members_above": int(count)})
    return pd.DataFrame(rows)


def diagnose_lead_time(counts, config):
    """Compare successive starts for one valid date, with explicit coverage.

    Earliest signal means the first *available, sampled forecast* with at least
    one member (or the configured probability); it does not establish skill.
    """
    minimum = math.ceil(51 * config["lead_time"]["signal_probability"])
    events = []
    for (town, window, valid), group in counts.groupby(["town", "window_anchor", "valid_end"], sort=True):
        available = group[group.members_above.notna()].sort_values("initialization")
        for criterion, required in [("any_member", 1), ("configured_probability", minimum)]:
            signals = available[available.members_above >= required]
            first = signals.initialization.iloc[0] if len(signals) else None
            events.append({"town": town, "window_anchor": window, "valid_end": valid,
                "criterion": criterion, "minimum_members": required, "scheduled_starts": len(group),
                "available_starts": len(available), "signaling_starts": len(signals),
                "consistency_percent": 100 * len(signals) / len(available) if len(available) else None,
                "first_signal_start": first,
                "earliest_lead_days": (pd.Timestamp(valid) - pd.Timestamp(first)).days if first else None,
                "peak_members_above": int(available.members_above.max()) if len(available) else None})
    events = pd.DataFrame(events)
    summaries = []
    for (town, window), group in events.groupby(["town", "window_anchor"], sort=True):
        candidates = group[group.criterion == "any_member"].sort_values(
            ["peak_members_above", "available_starts", "valid_end"], ascending=[False, False, True])
        chosen = candidates.iloc[0]
        for row in group[group.valid_end == chosen.valid_end].to_dict("records"):
            row["status"] = ("no_available_starts" if not row["available_starts"] else
                             "signal" if row["signaling_starts"] else "no_signal")
            summaries.append(row)
    usable = counts.dropna(subset=["members_above"])
    starts = usable.groupby(["town", "window_anchor", "initialization"], as_index=False).agg(
        peak_members_above=("members_above", "max"), member_days_above=("members_above", "sum"))
    starts = starts.sort_values(["town", "peak_members_above", "member_days_above", "initialization"],
                                ascending=[True, False, False, True])
    alarming = starts.groupby("town", sort=False).head(1).copy()
    alarming["status"] = np.where(alarming.peak_members_above > 0, "signal", "no_signal")
    return events, pd.DataFrame(summaries), alarming


def inspect_selection(ds, config, out, snapshot):
    effective = effective_config(config)
    selected, report = select_town_forecasts(ds, effective)
    cached = []
    for date in effective["forecast"]["start_dates"]:
        try:
            read_start(selected, date, effective, out, snapshot, report,
                       cache_directory=ROOT / config["lead_time"]["cache_directory"], cache_only=True)
            cached.append(date)
        except FileNotFoundError:
            pass
    report.update(forecast_snapshot=snapshot, windows=lead_time_windows(config),
                  cached_starts=cached, config_sha256=config_hash(config))
    per_start = report["decoded_source_mib"] / selected.sizes["time"]
    report["uncached_source_mib"] = per_start * (selected.sizes["time"] - len(cached))
    print(f"{selected.sizes['time']} scheduled starts, {len(cached)} cached; "
          f"source footprint {report['decoded_source_mib']:.1f} MiB, "
          f"uncached estimate {report['uncached_source_mib']:.1f} MiB. "
          "Decoded source estimates are not compressed transfer or peak RAM.", flush=True)
    if report["uncached_source_mib"] > 1024:
        print("SIZE WARNING: more than 1 GiB of uncached source chunks. "
              "Use the cloud notebook for the full run; preview fetches no rainfall.", flush=True)
    return effective, selected, report


def run_remote(config, thresholds_dir, out, *, inspection_only=False, cache_only=False):
    effective = effective_config(config)
    levels, handoff = load_handoff(thresholds_dir, effective)
    thresholds = levels[levels.threshold == "local_2yr"].copy()
    out.mkdir(parents=True, exist_ok=True)
    status_file = "inspection_status.json" if inspection_only else "run_status.json"
    write_status(out, "running", filename=status_file, stage="inspect")
    started = time.perf_counter()
    try:
        ds, snapshot = open_store(config["forecast"])
        with closing(ds):
            effective, selected, report = inspect_selection(ds, config, out, snapshot)
            write_json(out / "inspection.json", report)
            if not cache_only and report["uncached_source_mib"] > config["lead_time"]["max_source_mib"]:
                raise ValueError("Uncached source estimate exceeds lead_time.max_source_mib; reduce the windows or raise the explicit budget")
            if inspection_only:
                write_status(out, "ok", filename=status_file, stage="inspect")
                print("Inspection complete; no forecast rainfall fetched.")
                return
            grid = scheduled_counts(config, thresholds, report["daily_lead_hours"])
            all_counts, all_rain, starts = [], [], []
            for date in effective["forecast"]["start_dates"]:
                print(f"Processing {date} at all {selected.sizes['town']} towns ...", flush=True)
                try:
                    cumulative = read_start(selected, date, effective, out, snapshot, report,
                        cache_directory=ROOT / config["lead_time"]["cache_directory"], cache_only=cache_only)
                except FileNotFoundError:
                    if not cache_only:
                        raise
                    starts.append({"initialization": date, "status": "not_cached"})
                    continue
                daily = daily_rainfall(cumulative, report["units"]["mm_factor"],
                                       effective["threshold_choice"]["trace_rainfall_mm"])
                if daily is None:
                    starts.append({"initialization": date, "status": "skipped_all_nan"})
                    continue
                daily = daily.sel(time=slice(config["start_date"], pd.Timestamp(config["end_date"]) + pd.Timedelta(days=1)))
                if not daily.sizes["time"]:
                    starts.append({"initialization": date, "status": "skipped_outside_season"})
                    continue
                all_counts.append(member_counts(daily, thresholds, date))
                frame = daily.to_dataframe().reset_index().rename(columns={"time": "valid_end"})
                frame["initialization"] = date
                all_rain.append(frame)
                starts.append({"initialization": date, "status": "ok", "forecast_days": daily.sizes["time"],
                    **{key: daily.attrs[key] for key in ["tiny_negative_totals_clipped",
                       "positive_trace_totals_zeroed", "minimum_uncorrected_daily_mm", "trace_rainfall_mm"]}})
            if not all_counts:
                write_json(out / "forecast_starts.json", starts)
                raise ValueError("No usable forecasts; choose written starts or populate the point cache first")
            counts = grid.merge(pd.concat(all_counts, ignore_index=True),
                on=["initialization", "town", "forecast_day"], how="left", validate="one_to_one")
            counts["start_status"] = counts.initialization.map({s["initialization"]: s["status"] for s in starts})
            counts["percent_above"] = 100 * counts.members_above / counts.members_total
            events, summary, alarming = diagnose_lead_time(counts, config)
            with tempfile.TemporaryDirectory(prefix=".extract-", dir=out) as temporary:
                staging = Path(temporary)
                for name, frame in {"daily_member_counts.csv": counts,
                    "daily_rainfall.csv": pd.concat(all_rain, ignore_index=True),
                    "thresholds_used.csv": thresholds, "event_signals.csv": events,
                    "lead_time_summary.csv": summary, "most_alarming_starts.csv": alarming}.items():
                    frame.to_csv(staging / name, index=False)
                write_json(staging / "settings_used.json", config)
                write_json(staging / "forecast_starts.json", starts)
                manifest = provenance(config, {"cmorph": handoff["cmorph_snapshot"], "forecast": snapshot})
                manifest.update(mode="cache_preview" if cache_only else "complete", handoff=handoff,
                    windows=lead_time_windows(config), inspection=report, forecast_starts=starts,
                    elapsed_seconds=time.perf_counter() - started,
                    adapted_from=["E2: ensemble plumes", "E5: daily totals", "E6: local 2-year member counts"],
                    interpretation="Forecast signals, not verified 2025 events. Lead times and consistency refer to the same valid day and sampled available starts.")
                manifest["output_sha256"] = {path.name: file_sha256(path) for path in staging.iterdir()}
                write_json(staging / "manifest.json", manifest)
                for path in sorted(staging.iterdir(), key=lambda p: p.name == "manifest.json"):
                    os.replace(path, out / path.name)
            write_status(out, "ok", filename=status_file, stage="cache_preview" if cache_only else "complete")
            print(f"Saved {'CACHE PREVIEW' if cache_only else 'complete Part C run'} in {out}")
    except (Exception, KeyboardInterrupt) as exc:
        write_status(out, "failed", filename=status_file, error=str(exc) or "Interrupted")
        raise


def plot_outputs(out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    require_complete_run(out)
    manifest = json.loads((out / "manifest.json").read_text())
    for name, digest in manifest["output_sha256"].items():
        if file_sha256(out / name) != digest:
            raise ValueError(f"Cached {name} differs from its manifest; re-extract before plotting")
    config = load_config(out / "settings_used.json")
    validate_lead_time(config)
    counts = pd.read_csv(out / "daily_member_counts.csv")
    rain = pd.read_csv(out / "daily_rainfall.csv")
    alarming = pd.read_csv(out / "most_alarming_starts.csv")
    levels = pd.read_csv(out / "thresholds_used.csv").set_index("town").threshold_mm
    windows = lead_time_windows(config)
    starts = manifest["forecast_starts"]
    available = sum(row["status"] == "ok" for row in starts)
    preview = manifest["mode"] == "cache_preview"
    label = f"CACHE PREVIEW: {available}/{len(starts)} starts" if preview else f"{available}/{len(starts)} starts available"
    figures = out / "figures"
    figures.mkdir(exist_ok=True)
    cmap = plt.get_cmap("YlOrRd").copy()
    cmap.set_bad("lightgrey")
    for town in [t["name"] for t in config["towns"]]:
        data = counts[counts.town == town]
        days = sorted(data.forecast_day.unique())
        fig, axes = plt.subplots(1, len(windows), figsize=(6 * len(windows), 8), squeeze=False, layout="constrained")
        for ax, window in zip(axes[0], windows):
            matrix = data[data.window_anchor == window["anchor"]].pivot(
                index="initialization", columns="forecast_day", values="members_above").reindex(index=window["start_dates"], columns=days)
            mesh = ax.imshow(np.ma.masked_invalid(matrix.to_numpy()), cmap=cmap, vmin=0, vmax=51, aspect="auto")
            ax.set(title=f"Window around {window['anchor']}", xlabel="Forecast day (24 h ending at this lead)",
                ylabel="Forecast start", xticks=np.arange(len(days)), xticklabels=days,
                yticks=np.arange(len(matrix)), yticklabels=matrix.index)
        fig.colorbar(mesh, ax=axes.ravel().tolist(), label="Members above local 2-year level (of 51)")
        fig.suptitle(f"{town}: > {levels[town]:.1f} mm / 24 h\n{label}; grey = unavailable")
        fig.savefig(figures / f"{slugify(town)}_lead_time_heatmap.png", dpi=130)
        plt.close(fig)
        best = alarming[alarming.town == town].iloc[0]
        daily = rain[(rain.town == town) & (rain.initialization == best.initialization)]
        plume = daily.pivot(index="forecast_day", columns="number", values="rainfall_mm").sort_index()
        fig, (ax, bars) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]}, layout="constrained")
        ax.plot(plume.index, plume.values, color="steelblue", alpha=.23, lw=.8)
        ax.plot(plume.index, plume.mean(axis=1), color="black", lw=2, label="Ensemble mean")
        ax.axhline(levels[town], color="crimson", ls="--", label=f"2-year: {levels[town]:.1f} mm / 24 h")
        ax.set(ylabel="Rainfall (mm in 24 h)")
        ax.legend()
        ax.grid(alpha=.3)
        selected = data[data.initialization == best.initialization].sort_values("forecast_day")
        bars.bar(selected.forecast_day, selected.members_above, color="crimson")
        labels = [f"{row.forecast_day}\n{pd.Timestamp(row.valid_end):%d %b}" for row in selected.itertuples()]
        bars.set(xlabel="Forecast day and valid end date", ylabel="Members\n(of 51)", ylim=(0, 51),
                 xticks=selected.forecast_day, xticklabels=labels)
        state = "No members above the level" if best.status == "no_signal" else f"Peak: {int(best.peak_members_above)}/51 members"
        fig.suptitle(f"{town}: strongest sampled start {best.initialization}\n{state}; {label}")
        fig.savefig(figures / f"{slugify(town)}_most_alarming_plume.png", dpi=140)
        plt.close(fig)
    print(f"Saved five heatmaps and five plumes in {figures}; {label}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["inspect", "extract", "preview", "plots"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--thresholds", type=Path, help="verified Part A result directory")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        suffix = "_preview" if args.stage == "preview" else ""
        out = args.out or Path(str(ROOT / config["lead_time"]["output_directory"]) + suffix)
        if args.stage == "plots":
            plot_outputs(out)
        else:
            run_remote(config, args.thresholds or ROOT / config["execution"]["output_directory"], out,
                       inspection_only=args.stage == "inspect", cache_only=args.stage == "preview")
    except (ConfigError, ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
