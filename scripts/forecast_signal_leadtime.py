"""Part C: how early did the ECMWF forecasts warn of 2-year rainfall?

For each town, this reads a configurable window of daily forecast starts and
counts how many of the 51 ensemble members exceed that town's nearest-pixel
CMORPH 24-hour 2-year level on each forecast day.  It adapts the ensemble-plume
layout of E2 and the daily-total/exceedance logic of E5 and E6.  Only the
whole-day lead times (24, 48, ..., 240 hours) are read; the 3-hourly steps are
never loaded.

The outputs are:

* one start-date x forecast-day heatmap per town,
* a rainfall plume and exceedance-count figure for the most alarming start,
* a summary CSV with the earliest and most consistent town signals, and
* a long-form CSV with every heatmap cell.

Run:  uv run python -m scripts.forecast_signal_leadtime --config grid.json
"""

import argparse
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from scripts.common import (
    ROOT,
    ConfigError,
    box_inside,
    inside,
    load_config,
    slugify,
    validate_common,
)
from scripts.data_access import domain, open_store, town_indexers
from scripts.validation import check_town_coverage, units_report

DEFAULT_WINDOW_START = "2025-07-01"
DEFAULT_WINDOW_END = "2025-07-21"
DURATION = "24hr"
RETURN_PERIOD = 2
OUTPUT_DIRECTORY = ROOT / "out" / "forecast_leadtime"
TP_TO_MM = 1000.0
READ_WORKERS = 8
STRICT_OPERATOR = ">"


def window_starts(start, end):
    """Return the inclusive daily forecast-start dates in the requested window."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start > end:
        raise ValueError("window start must not be after window end")
    starts = pd.date_range(start, end, freq="D")
    if len(starts) < 2:
        raise ValueError("window must contain at least two daily forecast starts")
    return starts


def forecast_start_indices(forecast, starts):
    """Return the forecast time indices for the requested start dates."""
    if "time" not in forecast.coords:
        raise ValueError("forecast store has no time coordinate")
    times = pd.to_datetime(forecast["time"].values)
    indices = []
    missing = []
    for start in starts:
        matches = np.flatnonzero(times == start)
        if len(matches) != 1:
            missing.append(pd.Timestamp(start).strftime("%Y-%m-%d"))
        else:
            indices.append(int(matches[0]))
    if missing:
        raise ValueError(
            "forecast starts not found: "
            + ", ".join(missing)
            + f"; available {times[0].date()} to {times[-1].date()}"
        )
    return np.asarray(indices, dtype=int)


def check_forecast_coverage(forecast, config):
    """Fail if a town or its configured extent is outside the forecast grid."""
    box = domain(
        forecast,
        "latitude",
        "longitude",
        ascending=config["forecast"]["latitude_order"] == "ascending",
    )
    problems = []
    for town in config["towns"]:
        if not inside(box, town["latitude"], town["longitude"]):
            problems.append(f"{town['name']} centre is outside the forecast domain")
        if "extent" in town and not box_inside(box, town["extent"]):
            problems.append(f"{town['name']} extent is outside the forecast domain")
    if problems:
        raise ValueError("; ".join(problems))
    return box


def daily_step_indices(forecast):
    """Return cumulative and daily whole-day step indices, without reading data."""
    if "step" not in forecast.coords:
        raise ValueError("forecast store has no step coordinate")
    lead_h = (pd.to_timedelta(forecast["step"].values) / pd.Timedelta("1h")).astype(int)
    day_indices = [i for i, hours in enumerate(lead_h) if hours % 24 == 0]
    if not day_indices or day_indices[0] != 0 or len(day_indices) < 3:
        raise ValueError("forecast store needs a 0-hour step and at least two whole-day steps")
    return lead_h, day_indices


def read_two_year(observed, config):
    """Read each town's nearest-pixel CMORPH 24-hour 2-year level in mm."""
    ref = config["cmorph_reference"]
    variable = ref["variable"]
    if variable not in observed:
        raise ValueError(f"missing CMORPH variable: {variable}")
    if "duration" not in observed.coords or DURATION not in observed["duration"].values:
        raise ValueError(f"CMORPH duration {DURATION} is not available")
    if "return_period" not in observed.coords:
        raise ValueError("CMORPH store has no return_period coordinate")
    available = {int(value) for value in observed["return_period"].values}
    if RETURN_PERIOD not in available:
        raise ValueError(f"CMORPH return period {RETURN_PERIOD} years is not available")
    units = units_report(
        observed[variable], config.get("thresholds", {}).get("units_if_missing")
    )
    if not units["accepted_as_mm_depth"]:
        raise ValueError(f"unsupported rainfall-depth units for {variable}: {units}")
    check_town_coverage(observed, config)

    levels = (
        observed[variable]
        .sel(duration=DURATION, return_period=RETURN_PERIOD)
        .sel(**town_indexers(config), method="nearest")
        .compute()
        .transpose("town")
    )
    values = np.asarray(levels.values, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("CMORPH 2-year levels contain missing, nonfinite or negative values")
    thresholds = xr.DataArray(
        values,
        dims="town",
        coords={"town": levels["town"].values},
        name="threshold_mm",
        attrs={"units": "mm/day", "duration": DURATION, "return_period": RETURN_PERIOD},
    )
    return thresholds, units


def read_window_daily_totals(forecast, config, starts):
    """Read only whole-day leads for every start, then difference cumulative tp.

    The forecast ``tp`` field is cumulative from each initialization.  Selecting
    all daily lead times before point selection lets Dask fetch only the chunks
    needed for the five towns.  Starts whose entire field is NaN are skipped and
    reported, matching the project brief's warning about unwritten forecast starts.
    """
    variable = config["forecast"]["variable"]
    if variable not in forecast:
        raise ValueError(f"missing forecast variable: {variable}")
    starts = pd.DatetimeIndex(starts)
    time_indices = forecast_start_indices(forecast, starts)
    lead_h, day_indices = daily_step_indices(forecast)
    indexers = town_indexers(config, "latitude", "longitude")

    cumulative = (
        forecast[variable]
        .isel(time=time_indices, step=day_indices)
        .sel(**indexers, method="nearest")
        .transpose("time", "step", "number", "town")
        * TP_TO_MM
    )
    import dask

    cumulative, = dask.compute(
        cumulative, scheduler="threads", num_workers=READ_WORKERS
    )

    values = cumulative.values
    per_start_all_finite = np.isfinite(values).all(axis=(1, 2, 3))
    per_start_any_finite = np.isfinite(values).any(axis=(1, 2, 3))
    partial = per_start_any_finite & ~per_start_all_finite
    if partial.any():
        bad = [str(s.date()) for s in starts[partial]]
        raise ValueError("forecast starts contain partial missing data: " + ", ".join(bad))
    if not per_start_all_finite.any():
        raise ValueError("all selected forecast starts are missing (all NaN)")

    skipped = starts[~per_start_all_finite]
    if len(skipped):
        cumulative = cumulative.isel(time=np.flatnonzero(per_start_all_finite))
        starts = starts[per_start_all_finite]

    if (cumulative.values < -1e-6).any():
        raise ValueError("forecast cumulative totals contain negative values")

    daily = cumulative.diff("step", label="upper").transpose(
        "time", "number", "step", "town"
    )
    if not np.isfinite(daily.values).all():
        raise ValueError("forecast daily totals contain missing or nonfinite values")
    # Float32 cumulative storage can create a few hundredths of a millimetre of
    # apparent decrease.  Reject substantive decreases, clip tiny artefacts.
    if float(daily.min()) < -0.1:
        raise ValueError("forecast daily totals decrease; cumulative tp is not monotonic")
    if float(daily.min()) < 0:
        daily = daily.clip(min=0.0)

    days = (lead_h[day_indices][1:] // 24).astype(int)
    if (days <= 0).any():
        raise ValueError("forecast daily lead times must be positive whole days")
    valid_values = np.asarray([
        [start + pd.Timedelta(hours=int(hours)) for hours in lead_h[day_indices][1:]]
        for start in starts
    ], dtype="datetime64[ns]")
    daily = daily.assign_coords(
        forecast_day=("step", days),
        valid_time=(("time", "step"), valid_values),
    )
    daily.name = "daily_precipitation"
    daily.attrs["units"] = "mm/day"
    daily.attrs["exceedance_operator"] = STRICT_OPERATOR
    return daily, starts, skipped


def count_members(daily, thresholds):
    """Count members strictly above the 2-year level for every start and day."""
    if not set(thresholds["town"].values.tolist()) <= set(daily["town"].values.tolist()):
        raise ValueError("daily totals do not cover every threshold town")
    above = daily > thresholds
    counts = above.sum("number").transpose("time", "step", "town").astype(int)
    counts.name = "members_above"
    counts.attrs["threshold"] = "CMORPH 24-hour 2-year level"
    counts.attrs["operator"] = STRICT_OPERATOR
    counts.attrs["ensemble_size"] = int(daily.sizes["number"])
    if int(counts.max()) > daily.sizes["number"]:
        raise ValueError("member count exceeds the ensemble size")
    if not (counts.values >= 0).all():
        raise ValueError("member counts must be non-negative")
    return counts


def most_alarming_start(counts):
    """Pick the town/start with the most member-days, then peak, then earliest."""
    totals = counts.sum("step").transpose("time", "town")
    peaks = counts.max("step").transpose("time", "town")
    times = pd.to_datetime(totals["time"].values)
    towns = totals["town"].values.tolist()
    best = None
    for time_i, start in enumerate(times):
        for town_i, town in enumerate(towns):
            total = int(totals.values[time_i, town_i])
            peak = int(peaks.values[time_i, town_i])
            key = (total, peak, -time_i, -town_i)
            if best is None or key > best[0]:
                best = (key, start, town, total, peak)
    if best is None:
        raise ValueError("no forecast starts available")
    _, start, town, total, peak = best
    selected = counts.sel(time=start, town=town).transpose("step")
    peak_day = int(selected["forecast_day"].values[int(selected.argmax("step"))])
    return {
        "town": town,
        "start": pd.Timestamp(start),
        "total_member_days": total,
        "peak_members": peak,
        "peak_forecast_day": peak_day,
    }


def summarize_signals(counts, daily, thresholds, config):
    """Per-town earliest and consistency metrics for the selected window."""
    times = pd.to_datetime(counts["time"].values)
    days = counts["forecast_day"].values.astype(int)
    valid = np.asarray(daily["valid_time"].values, dtype="datetime64[ns]")
    rows = []
    for town in config["towns"]:
        name = town["name"]
        town_counts = counts.sel(town=name).transpose("time", "step")
        values = town_counts.values.astype(int)
        signal = values > 0
        if signal.any():
            first_start_i = int(np.flatnonzero(signal.any(axis=1))[0])
            first_start = times[first_start_i]
            first_start_lead = int(days[np.flatnonzero(signal[first_start_i])[0]])
            earliest_lead = int(np.min(days[signal.any(axis=0)]))
            earliest_valid = pd.Timestamp(valid[signal].min())
            starts_with_signal = int(signal.any(axis=1).sum())
            total_member_days = int(values.sum())
            peak_members = int(values.max())
            peak_time_i, peak_day_i = np.unravel_index(values.argmax(), values.shape)
            peak_start = times[peak_time_i]
            peak_day = int(days[peak_day_i])
            run = longest = 0
            for has_signal in signal.any(axis=1):
                if has_signal:
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
        else:
            first_start = None
            first_start_lead = None
            earliest_lead = None
            earliest_valid = None
            starts_with_signal = 0
            total_member_days = 0
            peak_members = 0
            peak_start = None
            peak_day = None
            longest = 0

        rows.append({
            "town": name,
            "threshold_mm": float(thresholds.sel(town=name)),
            "window_start": times[0].strftime("%Y-%m-%d"),
            "window_end": times[-1].strftime("%Y-%m-%d"),
            "window_starts": len(times),
            "earliest_signal_start": (
                first_start.strftime("%Y-%m-%d") if first_start is not None else ""
            ),
            "earliest_signal_start_lead_day": (
                first_start_lead if first_start_lead is not None else ""
            ),
            "earliest_signal_lead_day": (
                earliest_lead if earliest_lead is not None else ""
            ),
            "earliest_signal_valid_date": (
                earliest_valid.strftime("%Y-%m-%d") if earliest_valid is not None else ""
            ),
            "starts_with_signal": starts_with_signal,
            "fraction_starts_with_signal": (
                starts_with_signal / len(times) if len(times) else 0.0
            ),
            "total_member_days_above": total_member_days,
            "max_members_above_in_day": peak_members,
            "peak_start": peak_start.strftime("%Y-%m-%d") if peak_start is not None else "",
            "peak_lead_day": peak_day if peak_day is not None else "",
            "longest_consecutive_start_run": longest,
        })
    return pd.DataFrame(rows)


def _save(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_heatmap(counts, thresholds, town_name, out, vmax=None):
    """Save one start-date x forecast-day member-count heatmap for a town."""
    town_counts = counts.sel(town=town_name).transpose("time", "step")
    values = town_counts.values.astype(int)
    starts = pd.to_datetime(town_counts["time"].values)
    days = town_counts["forecast_day"].values.astype(int)
    if vmax is None:
        vmax = max(1, int(counts.max()))
    fig, ax = plt.subplots(
        figsize=(7.8, max(4.6, 0.27 * len(starts) + 2.2))
    )
    image = ax.imshow(
        values, aspect="auto", cmap="YlOrRd", vmin=0, vmax=vmax,
        interpolation="nearest",
    )
    ax.set_xticks(np.arange(len(days)), [str(day) for day in days])
    ax.set_yticks(np.arange(len(starts)), [f"{start:%d %b}" for start in starts])
    ax.set_xlabel("forecast day (whole-day lead)")
    ax.set_ylabel("forecast start date")
    for time_i in range(values.shape[0]):
        for day_i in range(values.shape[1]):
            value = int(values[time_i, day_i])
            if value:
                colour = "white" if value > 0.6 * vmax else "black"
                ax.text(day_i, time_i, str(value), ha="center", va="center",
                        fontsize=7, color=colour)
    threshold = float(thresholds.sel(town=town_name))
    colourbar = fig.colorbar(image, ax=ax, pad=0.02)
    n_members = counts.attrs.get("ensemble_size", int(values.max()) if values.size else 0)
    colourbar.set_label(f"members above threshold (of {n_members})")
    ax.set_title(
        f"{town_name}: ECMWF members above the CMORPH 2-year level\n"
        f"{starts[0]:%d %b %Y} to {starts[-1]:%d %b %Y}; "
        f"threshold {threshold:.1f} mm/day; strict {STRICT_OPERATOR}"
    )
    if not values.any():
        ax.text(0.5, 0.5, "no member above threshold", transform=ax.transAxes,
                ha="center", va="center", color="0.35", fontsize=10)
    fig.tight_layout()
    path = out / f"08_forecast_leadtime_heatmap_{slugify(town_name)}.png"
    return _save(fig, path)


def plot_plume(daily, counts, thresholds, best, out):
    """Save the ensemble plume plus exceedance bars for the most alarming start."""
    town = best["town"]
    start = pd.Timestamp(best["start"])
    selected = daily.sel(time=start, town=town).transpose("number", "step")
    values = selected.values.astype(float)
    days = selected["forecast_day"].values.astype(int)
    dates = pd.to_datetime(selected["valid_time"].values)
    day_counts = counts.sel(time=start, town=town).transpose("step").values.astype(int)
    threshold = float(thresholds.sel(town=town))
    n_members = selected.sizes["number"]

    fig, axes = plt.subplots(
        1, 2, figsize=(14, 5.0), gridspec_kw={"width_ratios": [2.2, 1.0]}
    )
    ax = axes[0]
    for member in range(n_members):
        ax.plot(days, values[member], color="steelblue", alpha=0.24, linewidth=0.8)
    ax.plot(days, values.mean(axis=0), color="black", linewidth=2.0,
            label="ensemble mean")
    ax.axhline(threshold, color="crimson", linestyle="--", linewidth=1.5,
               label=f"CMORPH 2-year level ({threshold:.1f} mm)")
    ax.set_xticks(days)
    ax.set_xticklabels([f"{day}\n{date:%d/%m}" for day, date in zip(days, dates)],
                       fontsize=8)
    ax.set_xlabel("forecast day")
    ax.set_ylabel("24-hour rainfall (mm)")
    ax.set_ylim(bottom=0)
    ax.set_title("Daily rainfall plume")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", fontsize=8)

    ax = axes[1]
    ax.bar(days, day_counts, color="darkorange", width=0.8)
    for day, value in zip(days, day_counts):
        if value:
            ax.text(day, value + 0.05, str(value), ha="center", va="bottom",
                    fontsize=8)
    ax.set_xticks(days)
    ax.set_xticklabels([f"{day}\n{date:%d/%m}" for day, date in zip(days, dates)],
                       fontsize=8)
    ax.set_ylim(0, max(1, int(day_counts.max())) + 0.4)
    ax.set_xlabel("forecast day")
    ax.set_ylabel(f"members above threshold (of {n_members})")
    ax.set_title("Members above the 2-year level")
    ax.grid(axis="y", alpha=0.25)

    if best["total_member_days"]:
        detail = (
            f"{best['total_member_days']} member-days above threshold; "
            f"peak {best['peak_members']} members on day {best['peak_forecast_day']}"
        )
    else:
        detail = "no member above the threshold in this start"
    fig.suptitle(
        f"Most alarming forecast start: {town}, initialized {start:%Y-%m-%d}\n"
        f"{detail}; threshold {threshold:.1f} mm/day; strict {STRICT_OPERATOR}"
    )
    fig.tight_layout()
    path = out / (
        f"08_forecast_leadtime_plume_{slugify(town)}_{start:%Y%m%d}.png"
    )
    return _save(fig, path)


def write_summary(summary, out):
    path = out / "08_forecast_leadtime_summary.csv"
    summary.to_csv(path, index=False, float_format="%.4f")
    return path


def write_counts(counts, out):
    """Write every heatmap cell as a long-form table for inspection."""
    times = pd.to_datetime(counts["time"].values)
    days = counts["forecast_day"].values.astype(int)
    valid = np.asarray(counts["valid_time"].values, dtype="datetime64[ns]")
    towns = counts["town"].values.tolist()
    rows = []
    for time_i, start in enumerate(times):
        for day_i, day in enumerate(days):
            for town_i, town in enumerate(towns):
                rows.append({
                    "forecast_start": start.strftime("%Y-%m-%d"),
                    "valid_date": pd.Timestamp(valid[time_i, day_i]).strftime("%Y-%m-%d"),
                    "forecast_day": int(day),
                    "town": town,
                    "members_above": int(counts.values[time_i, day_i, town_i]),
                })
    path = out / "08_forecast_leadtime_counts.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def run(config, out, window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END):
    """Read both stores, count exceedances, and write all Part C outputs."""
    starts = window_starts(window_start, window_end)
    out = Path(out)
    forecast, forecast_snapshot = open_store(config["forecast"])
    try:
        check_forecast_coverage(forecast, config)
        observed, observed_snapshot = open_store(config["cmorph_reference"])
        try:
            thresholds, units = read_two_year(observed, config)
        finally:
            observed.close()
        daily, kept_starts, skipped = read_window_daily_totals(forecast, config, starts)
    finally:
        forecast.close()

    counts = count_members(daily, thresholds)
    summary = summarize_signals(counts, daily, thresholds, config)
    best = most_alarming_start(counts)

    out.mkdir(parents=True, exist_ok=True)
    summary_path = write_summary(summary, out)
    counts_path = write_counts(counts, out)
    vmax = max(1, int(counts.max()))
    heatmap_paths = [
        plot_heatmap(counts, thresholds, town["name"], out, vmax=vmax)
        for town in config["towns"]
    ]
    plume_path = plot_plume(daily, counts, thresholds, best, out)
    return {
        "forecast_snapshot": forecast_snapshot,
        "observed_snapshot": observed_snapshot,
        "window_start": kept_starts[0],
        "window_end": kept_starts[-1],
        "requested_starts": len(starts),
        "starts": kept_starts,
        "skipped_starts": skipped,
        "units": units,
        "daily": daily,
        "thresholds": thresholds,
        "counts": counts,
        "summary": summary,
        "best": best,
        "summary_path": summary_path,
        "counts_path": counts_path,
        "heatmap_paths": heatmap_paths,
        "plume_path": plume_path,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", "--grid", dest="config", type=Path,
                        help="JSON settings override or grid.json export; defaults to scripts/common.py")
    parser.add_argument("--window-start", default=DEFAULT_WINDOW_START,
                        help=f"first forecast start date (default: {DEFAULT_WINDOW_START})")
    parser.add_argument("--window-end", default=DEFAULT_WINDOW_END,
                        help=f"last forecast start date (default: {DEFAULT_WINDOW_END})")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIRECTORY,
                        help=f"output directory (default: {OUTPUT_DIRECTORY})")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        validate_common(config)
    except ConfigError as exc:
        parser.error(str(exc))

    try:
        started = time.time()
        result = run(
            config, args.out,
            window_start=args.window_start, window_end=args.window_end,
        )
    except (ConfigError, ValueError) as exc:
        parser.error(str(exc))

    print(f"forecast snapshot {result['forecast_snapshot']}; "
          f"CMORPH snapshot {result['observed_snapshot']}")
    print(
        f"window {result['window_start']:%Y-%m-%d} to {result['window_end']:%Y-%m-%d}: "
        f"{len(result['starts'])} of {result['requested_starts']} starts; "
        f"{result['daily'].sizes['number']} members; "
        f"{time.time() - started:.1f}s"
    )
    if len(result["skipped_starts"]):
        print("skipped all-NaN starts: " +
              ", ".join(str(s.date()) for s in result["skipped_starts"]))
    print(f"CMORPH {DURATION} units: {result['units']['effective_units']}")
    print(result["summary"][[
        "town", "threshold_mm", "earliest_signal_start",
        "earliest_signal_lead_day", "earliest_signal_valid_date",
        "starts_with_signal", "window_starts", "total_member_days_above",
        "max_members_above_in_day", "peak_start",
    ]].to_string(index=False))
    print(f"most alarming start: {result['best']['town']} "
          f"{result['best']['start']:%Y-%m-%d} "
          f"({result['best']['total_member_days']} member-days)")
    print("saved", result["summary_path"])
    print("saved", result["counts_path"])
    for path in [*result["heatmap_paths"], result["plume_path"]]:
        print("saved", path)


if __name__ == "__main__":
    main()
