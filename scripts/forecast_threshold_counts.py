"""Count forecast ensemble members above town rainfall thresholds.

For every town in the shared settings, this adapts workshop exercises E5 (xclim
heavy-rain days from cumulative forecast totals) and E6 (members above a local
CMORPH return level).  It compares ten 24-hour forecast totals with:

* a fixed 20 mm/day threshold,
* the town's CMORPH 24-hour 2-year level, and
* the town's CMORPH 24-hour 10-year level.

The default initializations are the three 16th-of-month starts in common.py.  One CSV summary and one three-panel figure per town are
written, plus a combined five-row figure for all towns.

Run:  uv run python -m scripts.forecast_threshold_counts --config grid.json
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
import xclim

from scripts.common import (
    ROOT,
    forecast_settings,
    ConfigError,
    box_inside,
    inside,
    load_config,
    slugify,
    validate_common,
    validate_thresholds,
)
from scripts.data_access import domain, open_store, town_indexers
from scripts.forecast_rainfall import (daily_step_indices, daily_totals, forecast_unit_report,
                                       validate_starts, validate_ensemble, warn_source_size, write_manifest)
from scripts.validation import check_town_coverage, units_report

DURATION = "24hr"
OUTPUT_DIRECTORY = ROOT / "out" / "forecast_thresholds"
THRESHOLD_COLOURS = {
    "cmorph_2yr": "darkorange",
    "cmorph_10yr": "crimson",
}
FIXED_COLOUR = "steelblue"


def fixed_key(fixed_mm):
    """A stable threshold identifier for the configurable fixed threshold."""
    return f"fixed_{fixed_mm:g}".replace(".", "_") + "mm"


def threshold_label(key, fixed_mm):
    if key == fixed_key(fixed_mm):
        return f"fixed {fixed_mm:g} mm/day"
    return {"cmorph_2yr": "CMORPH 2-year", "cmorph_10yr": "CMORPH 10-year"}[key]


def threshold_colour(key):
    return THRESHOLD_COLOURS.get(key, FIXED_COLOUR)


def forecast_time_index(forecast, init):
    """Return the forecast time index for an ISO initialization date."""
    if "time" not in forecast.coords:
        raise ValueError("forecast store has no time coordinate")
    times = pd.to_datetime(forecast["time"].values)
    target = pd.Timestamp(init)
    matches = np.flatnonzero(times == target)
    if len(matches) != 1:
        raise ValueError(
            f"forecast initialization {target.date()} not found; "
            f"available {times[0].date()} to {times[-1].date()}"
        )
    return int(matches[0]), target


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


def read_thresholds(observed, config):
    """Read the paired CMORPH 24-hour 2- and 10-year levels for every town."""
    ref = config["cmorph_reference"]
    variable = ref["variable"]
    if variable not in observed:
        raise ValueError(f"missing CMORPH variable: {variable}")
    if "duration" not in observed.coords or DURATION not in observed["duration"].values:
        raise ValueError(f"CMORPH duration {DURATION} is not available")
    available = observed["return_period"].values.tolist()
    missing = {2, 10} - {int(value) for value in available}
    if missing:
        raise ValueError(f"CMORPH return periods are missing {sorted(missing)}")
    units = units_report(observed[variable], config["thresholds"].get("units_if_missing"))
    if not units["accepted_as_mm_depth"]:
        raise ValueError(f"unsupported rainfall-depth units for {variable}: {units}")
    check_town_coverage(observed, config)
    levels = (
        observed[variable]
        .sel(duration=DURATION, return_period=[2, 10])
        .sel(**town_indexers(config), method="nearest")
        .compute()
        .transpose("return_period", "town")
    )
    values = levels.values
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("CMORPH return levels contain missing, nonfinite or negative values")
    if bool((levels.sel(return_period=10) < levels.sel(return_period=2)).any()):
        raise ValueError("CMORPH return levels decrease between 2 and 10 years")
    return levels, units


def forecast_daily_totals(forecast, config, time_index):
    """Validate and difference whole-day cumulative rainfall, respecting its units."""
    variable = config["forecast"]["variable"]
    if variable not in forecast:
        raise ValueError(f"missing forecast variable: {variable}")
    validate_ensemble(forecast[variable])
    forecast_unit_report(forecast[variable], config)
    _, day_indices = daily_step_indices(forecast["step"].values)
    init = pd.Timestamp(forecast.time.values[time_index])
    validate_starts([init], config)
    warn_source_size(forecast[variable], [init], day_indices)
    cumulative = (forecast[variable].isel(time=time_index, step=day_indices)
                  .sel(**town_indexers(config, "latitude", "longitude"), method="nearest"))
    daily = daily_totals(cumulative.compute(num_workers=config["execution"]["workers"]), config)
    if daily is not None:
        daily = daily.transpose("number", "step", "town")
    return daily, init


def threshold_grid(levels, config, fixed_mm):
    """Build the threshold × town grid used for all exceedance counts."""
    names = [town["name"] for town in config["towns"]]
    if not set(names) <= set(levels["town"].values.tolist()):
        raise ValueError("CMORPH thresholds do not cover every configured town")
    levels = levels.sel(town=names)
    values = np.vstack([
        np.full(len(names), float(fixed_mm)),
        levels.sel(return_period=2).values,
        levels.sel(return_period=10).values,
    ])
    keys = [fixed_key(fixed_mm), "cmorph_2yr", "cmorph_10yr"]
    grid = xr.DataArray(
        values,
        dims=("threshold", "town"),
        coords={"threshold": keys, "town": names},
        name="threshold_mm",
    )
    if not np.isfinite(grid.values).all() or (grid.values <= 0).any():
        raise ValueError("rainfall thresholds must be finite and positive")
    if bool((grid.sel(threshold="cmorph_10yr") < grid.sel(threshold="cmorph_2yr")).any()):
        raise ValueError("CMORPH 10-year levels must not be below the 2-year levels")
    return grid


def count_members(daily, levels):
    """Count members above each threshold per day and overall."""
    if not set(levels["town"].values.tolist()) <= set(daily["town"].values.tolist()):
        raise ValueError("daily totals do not cover every threshold town")
    above = daily > levels
    per_day = above.sum("number").transpose("threshold", "step", "town")
    members_any = above.any("step").sum("number").transpose("threshold", "town")
    member_days = above.sum(("number", "step")).transpose("threshold", "town")
    max_per_day = per_day.max("step")
    days_any = (per_day > 0).sum("step")
    if int(per_day.max()) > daily.sizes["number"]:
        raise ValueError("member count exceeds the ensemble size")
    return {
        "above": above,
        "per_day": per_day,
        "members_any": members_any,
        "member_days": member_days,
        "max_per_day": max_per_day,
        "days_any": days_any,
    }


def xclim_heavy_days(daily_town, threshold_mm):
    """xclim ``wetdays`` count per member over the forecast days.

    The daily series is labelled as mm/day and ``op='>'`` matches the strict
    exceedance used by exercise E6.  Annual grouping is summed so a forecast
    crossing a calendar-year boundary still reports one total per member.
    """
    if "valid_time" not in daily_town.coords:
        raise ValueError("daily totals need a valid_time coordinate for xclim")
    values = daily_town.transpose("number", "step")
    pr = xr.DataArray(
        values.values,
        dims=("number", "time"),
        coords={"number": values["number"].values, "time": values["valid_time"].values},
        attrs={"units": "mm/day", "standard_name": "precipitation_flux"},
        name="pr",
    )
    wet = xclim.indices.wetdays(
        pr, thresh=f"{float(threshold_mm)} mm/day", freq="YS", op=">"
    )
    if "time" in wet.dims:
        wet = wet.sum("time")
    if wet.dims != ("number",):
        raise ValueError(f"unexpected xclim wetdays dimensions: {wet.dims}")
    return wet


def build_table(daily, levels, counts, config, init, fixed_mm):
    """A short per-town, per-threshold summary, including the xclim count."""
    rows = []
    for town in config["towns"]:
        name = town["name"]
        for key in levels["threshold"].values.tolist():
            threshold = float(levels.sel(threshold=key, town=name))
            wet = xclim_heavy_days(daily.sel(town=name), threshold)
            xclim_total = int(wet.sum())
            member_days = int(counts["member_days"].sel(threshold=key, town=name))
            if xclim_total != member_days:
                raise ValueError(
                    f"xclim and direct counts disagree for {name}, {key}: "
                    f"{xclim_total} != {member_days}"
                )
            rows.append({
                "forecast_init": init.strftime("%Y-%m-%d"),
                "town": name,
                "threshold": key,
                "threshold_label": threshold_label(key, fixed_mm),
                "threshold_mm": threshold,
                "members_above_any_day": int(counts["members_any"].sel(threshold=key, town=name)),
                "max_members_above_in_day": int(counts["max_per_day"].sel(threshold=key, town=name)),
                "member_days_above": member_days,
                "days_with_any_member": int(counts["days_any"].sel(threshold=key, town=name)),
                "xclim_heavy_days_total": xclim_total,
                "xclim_members_with_heavy_day": int((wet.values >= 1).sum()),
                "xclim_max_heavy_days_per_member": int(wet.max()),
            })
    return pd.DataFrame(rows)


def plot_town(counts, levels, config, init, fixed_mm, town_name, out):
    """Save one three-panel threshold figure for a town."""
    names = levels["threshold"].values.tolist()
    days = counts["per_day"]["forecast_day"].values.astype(int)
    dates = pd.to_datetime(counts["per_day"]["valid_time"].values)
    n_members = counts["above"].sizes["number"]
    fig, axes = plt.subplots(1, len(names), figsize=(4.8 * len(names), 4.3), sharey=True)
    for ax, key in zip(axes, names):
        values = counts["per_day"].sel(town=town_name, threshold=key).values
        threshold = float(levels.sel(threshold=key, town=town_name))
        label = threshold_label(key, fixed_mm)
        ax.bar(days, values, color=threshold_colour(key), width=0.8)
        if key == fixed_key(fixed_mm):
            title = label
        else:
            title = f"{label} ({threshold:.1f} mm)"
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("forecast day")
        ax.set_xticks(days)
        ax.set_xticklabels([f"{day}\n{date:%d %b}" for day, date in zip(days, dates)], fontsize=8)
        ax.set_ylim(0, n_members)
        ax.grid(axis="y", alpha=0.25)
        if values.max() == 0:
            ax.text(0.5, 0.55, "no member\nexceeds", transform=ax.transAxes,
                    ha="center", va="center", color="0.35", fontsize=9)
    axes[0].set_ylabel(f"members above threshold\n(of {n_members})")
    fig.suptitle(f"{town_name}: ECMWF ensemble members above rainfall thresholds\n"
                 f"init {init:%Y-%m-%d}, 24-hour totals, strict >")
    fig.tight_layout()
    path = out / f"07_forecast_threshold_members_{slugify(town_name)}.png"
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_overview(counts, levels, config, init, fixed_mm, out):
    """Save one town × threshold overview figure."""
    names = levels["threshold"].values.tolist()
    towns = [town["name"] for town in config["towns"]]
    days = counts["per_day"]["forecast_day"].values.astype(int)
    n_members = counts["above"].sizes["number"]
    fig, axes = plt.subplots(
        len(towns), len(names),
        figsize=(4.4 * len(names), 2.7 * len(towns)),
        sharex=True, sharey=True, squeeze=False,
    )
    for row, town in enumerate(towns):
        for col, key in enumerate(names):
            ax = axes[row, col]
            values = counts["per_day"].sel(town=town, threshold=key).values
            threshold = float(levels.sel(threshold=key, town=town))
            ax.bar(days, values, color=threshold_colour(key), width=0.8)
            ax.set_ylim(0, n_members)
            ax.set_xticks(days)
            ax.grid(axis="y", alpha=0.25)
            if row == 0:
                ax.set_title(threshold_label(key, fixed_mm), fontsize=10)
            if col == 0:
                ax.set_ylabel(town, fontsize=9)
            ax.text(0.98, 0.92, f"{threshold:.1f} mm", transform=ax.transAxes,
                    ha="right", va="top", fontsize=7, color="0.3")
            if row == len(towns) - 1:
                ax.set_xlabel("forecast day", fontsize=9)
    fig.suptitle(
        f"ECMWF ensemble members above rainfall thresholds per forecast day\n"
        f"init {init:%Y-%m-%d}, 24-hour totals, strict >, {n_members} members"
    )
    fig.supylabel("members above threshold")
    fig.tight_layout()
    path = out / "07_forecast_threshold_members.png"
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


def write_table(table, out):
    path = out / "07_forecast_threshold_counts.csv"
    table.to_csv(path, index=False, float_format="%.4f")
    return path


def run(config, out, init=None, fixed_mm=None):
    """Compare all shared starts, or an explicit single-start override."""
    settings = forecast_settings(config)
    fixed_mm = settings["fixed_threshold_mm"] if fixed_mm is None else fixed_mm
    if not np.isfinite(fixed_mm) or fixed_mm <= 0:
        raise ValueError("fixed threshold must be a finite number greater than zero")
    validate_common(config, require_forecast_dates=init is None)
    starts = validate_starts([init] if init is not None else config["forecast"]["start_dates"], config)
    out = Path(out)
    tables, town_paths, overview_paths, kept, skipped, rainfall = [], [], [], [], [], []
    forecast, forecast_snapshot = open_store(config["forecast"])
    try:
        check_forecast_coverage(forecast, config)
        _, daily_indices = daily_step_indices(forecast.step.values)
        warn_source_size(forecast[config["forecast"]["variable"]], starts, daily_indices)
        observed, observed_snapshot = open_store(config["cmorph_reference"])
        try:
            levels, units = read_thresholds(observed, config)
        finally:
            observed.close()
        levels = threshold_grid(levels, config, fixed_mm)
        for start in starts:
            time_index, init_time = forecast_time_index(forecast, start)
            daily, _ = forecast_daily_totals(forecast, config, time_index)
            if daily is None:
                skipped.append(start)
                continue
            kept.append(start)
            rainfall.append(daily)
            counts = count_members(daily, levels)
            tables.append(build_table(daily, levels, counts, config, init_time, fixed_mm))
            target = out / start.strftime("%Y%m%d") if len(starts) > 1 else out
            target.mkdir(parents=True, exist_ok=True)
            town_paths.extend(plot_town(counts, levels, config, init_time, fixed_mm, town["name"], target)
                              for town in config["towns"])
            overview_paths.append(plot_overview(counts, levels, config, init_time, fixed_mm, target))
    finally:
        forecast.close()
    if not tables:
        raise ValueError("all selected forecast starts are missing (all NaN)")
    table = pd.concat(tables, ignore_index=True)
    table_path = write_table(table, out)
    manifest_path = write_manifest(out, config, forecast_snapshot, observed_snapshot,
                                   starts, kept, skipped, rainfall, {"fixed_threshold_mm": fixed_mm})
    return {"forecast_snapshot": forecast_snapshot, "observed_snapshot": observed_snapshot,
            "init": kept[-1], "time_index": time_index, "starts": kept, "skipped_starts": skipped,
            "units": units, "table": table, "table_path": table_path,
            "town_paths": town_paths, "overview_path": overview_paths[-1],
            "overview_paths": overview_paths, "manifest_path": manifest_path}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", "--grid", dest="config", type=Path,
                        help="JSON settings override or grid.json export; defaults to scripts/common.py")
    parser.add_argument("--init", help="single-start override; default: all shared forecast.start_dates")
    parser.add_argument("--fixed-threshold-mm", type=float, default=None,
                        help="fixed daily threshold in mm/day; default: common.py fixed_threshold_mm")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIRECTORY,
                        help=f"output directory (default: {OUTPUT_DIRECTORY})")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        validate_common(config)
        validate_thresholds(config)
    except ConfigError as exc:
        parser.error(str(exc))

    try:
        started = time.time()
        result = run(config, args.out, init=args.init, fixed_mm=args.fixed_threshold_mm)
    except (ConfigError, ValueError) as exc:
        parser.error(str(exc))

    print(f"forecast snapshot {result['forecast_snapshot']}; "
          f"CMORPH snapshot {result['observed_snapshot']}")
    print(f"starts {[str(pd.Timestamp(s).date()) for s in result['starts']]}; "
          f"{result['table']['town'].nunique()} towns; "
          f"xclim {xclim.__version__}; {time.time() - started:.1f}s")
    print(f"CMORPH {DURATION} units: {result['units']['effective_units']}")
    print(result["table"][[
        "town", "threshold_label", "threshold_mm",
        "members_above_any_day", "max_members_above_in_day",
        "member_days_above", "xclim_heavy_days_total",
    ]].to_string(index=False))
    print("saved", result["table_path"])
    for path in [*result["town_paths"], result["overview_path"]]:
        print("saved", path)


if __name__ == "__main__":
    main()
