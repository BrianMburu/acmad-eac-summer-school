"""Part D: where did the JJA 2025 forecasts show the highest risk?

This adapts E8 (local CMORPH return-level probability maps) and the map-read
lesson from E3 (pan chunks): select the region, start date and whole-day lead
steps before touching the remote data, then compute only those maps.

For each configured forecast start, the script maps the share of the 51
ensemble members above the nearest-pixel CMORPH 24-hour 2-year level for
forecast days 1-10.  It then counts, at every forecast grid point, how many
start/day cases reach a chosen probability (20% by default).  The final
frequency map describes the selected start/day cases. All probability and
frequency maps carry the five Part C town markers.

Run:
    uv run python -m scripts.region_risk_maps --config grid.json

Dates, days and probability default to the shared settings in common.py.
Pass ``--start-dates`` to override the configured selection.
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
    forecast_settings,
    ConfigError,
    box_inside,
    load_config,
    validate_common,
)
from scripts.data_access import domain, open_store
from scripts.forecast_rainfall import (daily_step_indices as validated_daily_indices, daily_totals,
                                       forecast_unit_report, validate_starts, validate_ensemble,
                                       warn_source_size, write_manifest)
from scripts.validation import units_report

OUTPUT_DIRECTORY = ROOT / "out" / "region_risk"
DEFAULT_N_STARTS = 4
DEFAULT_SEED = 42
RETURN_PERIOD = 2
DURATION = "24hr"
LABEL_OFFSETS = {
    "Khartoum": (4, 4),
    "Kassala": (4, 4),
    "Gedaref": (4, -10),
    "El Obeid": (4, 4),
    "Nyala": (4, 4),
}


def region_slices(config, lat_name, lon_name, ascending):
    """Return coordinate slices for the configured region box."""
    region = config["region_extent"]
    lat_slice = (
        slice(region["south"], region["north"])
        if ascending
        else slice(region["north"], region["south"])
    )
    return {lat_name: lat_slice, lon_name: slice(region["west"], region["east"])}


def check_domain(ds, config, lat_name, lon_name, ascending):
    """Fail if the selected region is not fully inside a store domain."""
    bounds = domain(ds, lat_name, lon_name, ascending)
    if not box_inside(bounds, config["region_extent"]):
        raise ValueError(
            f"region {config['region_extent']} is not inside the store domain {bounds}"
        )
    return bounds


def select_region(ds, config, lat_name, lon_name, ascending):
    """Select the configured region before any remote data are computed."""
    region = ds.sel(**region_slices(config, lat_name, lon_name, ascending))
    if region.sizes.get(lat_name, 0) < 2 or region.sizes.get(lon_name, 0) < 2:
        raise ValueError("region selection contains fewer than two grid points per axis")
    return region


def season_starts(forecast, config):
    """Return forecast initialization dates inside the configured season."""
    if "time" not in forecast.coords:
        raise ValueError("forecast store has no time coordinate")
    times = pd.DatetimeIndex(pd.to_datetime(forecast["time"].values)).sort_values()
    start = pd.Timestamp(config["start_date"])
    end = pd.Timestamp(config["end_date"])
    selected = times[(times >= start) & (times <= end)]
    if len(selected) < 3:
        raise ValueError(
            f"forecast season has only {len(selected)} starts between "
            f"{start:%Y-%m-%d} and {end:%Y-%m-%d}"
        )
    return selected


def choose_random_starts(times, n_starts=DEFAULT_N_STARTS, seed=DEFAULT_SEED):
    """Choose one random start from each of ``n_starts`` season blocks.

    Stratifying by time makes the 3-4 samples cover the whole season instead of
    accidentally clustering in one month, while the seed keeps the selection
    reproducible.
    """
    times = pd.DatetimeIndex(times)
    if not 3 <= n_starts <= min(4, len(times)):
        raise ValueError("n_starts must be 3 or 4 and no larger than available starts")
    rng = np.random.default_rng(seed)
    blocks = np.array_split(np.arange(len(times)), n_starts)
    chosen = [times[int(block[rng.integers(len(block))])] for block in blocks if len(block)]
    return pd.DatetimeIndex(sorted(chosen))


def parse_start_dates(values):
    """Parse explicit dates from whitespace- or comma-separated CLI values."""
    if not values:
        return None
    tokens = []
    for value in values:
        tokens.extend(part for part in str(value).split(",") if part)
    dates = pd.DatetimeIndex(pd.to_datetime(tokens)).sort_values()
    if len(dates) < 3 or len(dates) > 4:
        raise ValueError("specify 3 or 4 explicit start dates")
    if len(set(dates)) != len(dates):
        raise ValueError("start dates must be unique")
    return dates


def forecast_start_indices(forecast, starts):
    """Return time indices for the requested initialization dates."""
    times = pd.DatetimeIndex(pd.to_datetime(forecast["time"].values))
    indices = []
    missing = []
    for start in starts:
        matches = np.flatnonzero(times == pd.Timestamp(start))
        if len(matches) != 1:
            missing.append(pd.Timestamp(start).strftime("%Y-%m-%d"))
        else:
            indices.append(int(matches[0]))
    if missing:
        raise ValueError("forecast starts not found: " + ", ".join(missing))
    return np.asarray(indices, dtype=int)


def daily_step_indices(forecast):
    """Return all whole-day lead indices; 3-hourly steps are excluded."""
    if "step" not in forecast.coords:
        raise ValueError("forecast store has no step coordinate")
    return validated_daily_indices(forecast.step.values)


def cumulative_indices(forecast, days):
    """Indices for 0 h plus every whole day needed to form the requested totals."""
    lead_h, day_indices = daily_step_indices(forecast)
    day_to_index = {int(lead_h[index] // 24): index for index in day_indices}
    days = tuple(sorted(int(day) for day in days))
    if not days or any(day < 1 for day in days):
        raise ValueError("forecast days must be positive integers")
    if max(days) not in day_to_index:
        raise ValueError(f"forecast day {max(days)} is not available")
    needed = [0, *range(1, max(days) + 1)]
    missing = [day for day in needed if day not in day_to_index]
    if missing:
        raise ValueError(f"missing whole-day steps: {missing}")
    return [day_to_index[day] for day in needed], days


def parse_days(value):
    """Parse a comma-separated list of forecast days."""
    try:
        days = tuple(sorted({int(part) for part in str(value).split(",") if part.strip()}))
    except ValueError as exc:
        raise ValueError("--days must be a comma-separated list of whole-day integers") from exc
    if not days or days[0] < 1:
        raise ValueError("--days must contain positive whole-day integers")
    return days


def read_threshold_map(observed, forecast_region, config):
    """Read the local CMORPH 24-hour 2-year threshold on the forecast grid."""
    ref = config["cmorph_reference"]
    variable = ref["variable"]
    if variable not in observed:
        raise ValueError(f"missing CMORPH variable: {variable}")
    if DURATION not in observed["duration"].values:
        raise ValueError(f"CMORPH duration {DURATION} is not available")
    if RETURN_PERIOD not in {int(value) for value in observed["return_period"].values}:
        raise ValueError(f"CMORPH return period {RETURN_PERIOD} years is not available")
    units = units_report(
        observed[variable], config.get("thresholds", {}).get("units_if_missing")
    )
    if not units["accepted_as_mm_depth"]:
        raise ValueError(f"unsupported rainfall-depth units for {variable}: {units}")

    # One CMORPH return-level map is a pan chunk.  Take the 2-year field once,
    # then match every forecast grid point to its nearest CMORPH pixel.
    levels = (
        observed[variable]
        .sel(duration=DURATION, return_period=RETURN_PERIOD)
        .compute()
    )
    threshold = levels.sel(
        lat=forecast_region["latitude"],
        lon=forecast_region["longitude"],
        method="nearest",
    )
    for coordinate in ("lat", "lon"):
        if coordinate in threshold.coords and coordinate not in threshold.dims:
            threshold = threshold.drop_vars(coordinate)
    threshold = threshold.transpose("latitude", "longitude")
    if not np.isfinite(threshold).any():
        raise ValueError("CMORPH threshold map has no finite values over the region")
    threshold.name = "threshold_mm"
    threshold.attrs.update({"units": "mm/day", "duration": DURATION,
                            "return_period": RETURN_PERIOD})
    return threshold, units


def read_probability_for_start(forecast_region, config, start, threshold_map, days):
    """Read one start and return its probability maps for the requested days."""
    variable = config["forecast"]["variable"]
    starts = pd.DatetimeIndex([pd.Timestamp(start)])
    start_indices = forecast_start_indices(forecast_region, starts)
    step_indices, days = cumulative_indices(forecast_region, days)
    validate_starts(starts, config)
    validate_ensemble(forecast_region[variable])
    forecast_unit_report(forecast_region[variable], config)
    warn_source_size(forecast_region[variable], starts, step_indices)
    started = time.perf_counter()
    cumulative = forecast_region[variable].isel(time=int(start_indices[0]), step=step_indices)
    daily = daily_totals(cumulative.compute(num_workers=config["execution"]["workers"]), config)
    elapsed = time.perf_counter() - started
    if daily is None:
        return None, elapsed
    selected = daily.isel(step=[int(day) - 1 for day in days])
    probability = (selected > threshold_map).mean("number").where(
        np.isfinite(threshold_map)
    )
    probability = probability.drop_vars("time").expand_dims(time=[pd.Timestamp(start)])
    probability = probability.assign_coords(forecast_day=("step", list(days)))
    probability.name = "exceedance_probability"
    probability.attrs.update(daily.attrs)
    probability.attrs.update({
        "units": "1",
        "probability_threshold": "fraction of ensemble members above threshold",
        "threshold": f"CMORPH {DURATION} {RETURN_PERIOD}-year level",
    })
    return probability, elapsed


def read_probabilities(forecast_region, config, starts, threshold_map, days):
    """Read all selected starts, skipping starts that are entirely unwritten."""
    arrays, kept, skipped, timings = [], [], [], []
    for start in starts:
        probability, elapsed = read_probability_for_start(
            forecast_region, config, start, threshold_map, days
        )
        if probability is None:
            skipped.append(pd.Timestamp(start))
            print(f"skipping all-NaN start {start:%Y-%m-%d}")
            continue
        arrays.append(probability)
        kept.append(pd.Timestamp(start))
        timings.append(elapsed)
    if not arrays:
        raise ValueError("no selected forecast starts contain finite data")
    probabilities = xr.concat(arrays, dim="time", coords="different", compat="equals")
    probabilities.attrs["per_start_validation"] = [dict(array.attrs) for array in arrays]
    return probabilities, pd.DatetimeIndex(kept), pd.DatetimeIndex(skipped), timings


def frequency_map(probabilities, probability_threshold):
    """Count start/day cases at or above the chosen probability at each point."""
    if not 0 < probability_threshold < 1:
        raise ValueError("probability threshold must be strictly between 0 and 1")
    valid = probabilities.notnull().any(dim=("time", "step"))
    frequency = (
        (probabilities >= probability_threshold)
        .sum(dim=("time", "step"))
        .where(valid)
    )
    frequency.name = "frequency"
    frequency.attrs.update({
        "probability_threshold": float(probability_threshold),
        "cases": int(probabilities.sizes["time"] * probabilities.sizes["step"]),
    })
    return frequency


def _max_location(array):
    """Return the dimension and coordinate values of a finite maximum."""
    values = np.asarray(array.values, dtype=float)
    if not np.isfinite(values).any():
        return {}
    index = np.unravel_index(int(np.nanargmax(values)), values.shape)
    return {
        dim: array[dim].values[position]
        for dim, position in zip(array.dims, index)
    }


def summarize_starts(probabilities, kept, skipped, timings, probability_threshold):
    """Tabulate probability and read-time diagnostics for each selected start."""
    rows = []
    for start, elapsed in zip(kept, timings):
        selected = probabilities.sel(time=start)
        location = _max_location(selected)
        day = int(selected["forecast_day"].sel(step=location["step"]))
        rows.append({
            "start_date": start.strftime("%Y-%m-%d"),
            "max_probability": float(selected.max()),
            "max_probability_latitude": float(location["latitude"]),
            "max_probability_longitude": float(location["longitude"]),
            "max_probability_forecast_day": day,
            "cells_at_or_above_threshold": int(
                (selected >= probability_threshold).any(dim="step").sum()
            ),
            "read_seconds": float(elapsed),
        })
    season_location = _max_location(probabilities)
    season_day = int(
        probabilities["forecast_day"].sel(step=season_location["step"])
    )
    rows.append({
        "start_date": "season",
        "max_probability": float(probabilities.max()),
        "max_probability_latitude": float(season_location["latitude"]),
        "max_probability_longitude": float(season_location["longitude"]),
        "max_probability_forecast_day": season_day,
        "cells_at_or_above_threshold": int(
            (probabilities >= probability_threshold).any(dim=("time", "step")).sum()
        ),
        "read_seconds": float(sum(timings)),
    })
    frame = pd.DataFrame(rows)
    frame.attrs["skipped_starts"] = [str(start.date()) for start in skipped]
    return frame


def top_hotspots(frequency, maximum_probability=None, n=15):
    """Return the highest-frequency grid points, breaking ties by peak probability."""
    values = np.asarray(frequency.values, dtype=float)
    valid = np.isfinite(values)
    if not valid.any():
        return pd.DataFrame(
            columns=["rank", "latitude", "longitude", "frequency",
                     "max_probability"]
        )
    if maximum_probability is None:
        peak = np.zeros_like(values)
    else:
        peak = np.asarray(maximum_probability.transpose(
            *frequency.dims
        ).values, dtype=float)
        peak = np.where(np.isfinite(peak), peak, 0.0)
    order = np.lexsort((
        np.where(valid, peak, -np.inf).ravel(),
        np.where(valid, values, -np.inf).ravel(),
    ))[::-1]
    rows = []
    for index in order[:n]:
        flat = np.unravel_index(int(index), values.shape)
        if not np.isfinite(values[flat]):
            continue
        rows.append({
            "rank": len(rows) + 1,
            "latitude": float(frequency["latitude"].values[flat[0]]),
            "longitude": float(frequency["longitude"].values[flat[1]]),
            "frequency": int(values[flat]),
            "max_probability": float(peak[flat]),
        })
    return pd.DataFrame(rows)


def mark_towns(ax, config, fontsize=6.5):
    """Mark all Part C towns on a map with compact labels."""
    for town in config["towns"]:
        lon, lat = town["longitude"], town["latitude"]
        ax.plot(lon, lat, marker="o", markersize=4.2, markerfacecolor="black",
                markeredgecolor="white", markeredgewidth=0.7, linestyle="none", zorder=5)
        offset = LABEL_OFFSETS.get(town["name"], (4, 4))
        ax.annotate(
            town["name"], (lon, lat), xytext=offset, textcoords="offset points",
            fontsize=fontsize, color="black", zorder=6,
            bbox={"boxstyle": "round,pad=0.15", "facecolor": "white",
                  "edgecolor": "none", "alpha": 0.72},
        )


def _map_axes(ax, config):
    region = config["region_extent"]
    ax.set_xlim(region["west"], region["east"])
    ax.set_ylim(region["south"], region["north"])
    ax.set_aspect("equal")
    ax.set_xlabel("longitude")
    ax.grid(alpha=0.25, linewidth=0.4)


def plot_probability_maps(probabilities, config, out, probability_threshold):
    """Save one multi-panel probability figure per selected start."""
    paths = []
    days = probabilities["forecast_day"].values.astype(int)
    tag = f"p{round(probability_threshold * 100):02d}"
    for start in pd.to_datetime(probabilities["time"].values):
        selected = probabilities.sel(time=start).transpose("step", "latitude", "longitude")
        columns = min(5, len(days))
        rows = (len(days) + columns - 1) // columns
        fig, axes = plt.subplots(rows, columns, figsize=(3.3 * columns, 3.8 * rows),
                                 sharey=True, constrained_layout=True, squeeze=False)
        axes = axes.ravel()
        for unused in axes[len(days):]:
            unused.set_visible(False)
        mesh = None
        for ax, day in zip(axes, days):
            field = selected.sel(forecast_day=day)
            mesh = ax.pcolormesh(
                field["longitude"], field["latitude"], field,
                cmap="Reds", vmin=0, vmax=1, shading="auto",
            )
            valid_date = start + pd.Timedelta(days=int(day))
            ax.set_title(f"day {day} ({valid_date:%d %b})")
            _map_axes(ax, config)
            mark_towns(ax, config)
            if np.nanmax(field.values) >= probability_threshold:
                ax.contour(
                    field["longitude"], field["latitude"], field,
                    levels=[probability_threshold], colors="black", linewidths=0.7,
                )
        axes[0].set_ylabel("latitude")
        fig.colorbar(mesh, ax=axes.tolist(), shrink=0.8,
                     label=f"probability above local {RETURN_PERIOD}-year level")
        fig.suptitle(
            f"ECMWF exceedance probability: start {start:%Y-%m-%d}\n"
            f"local CMORPH 24 h {RETURN_PERIOD}-year level; black contour "
            f"{probability_threshold:.0%}",
            fontsize=11,
        )
        path = out / f"09_probability_map_{start:%Y%m%d}_{tag}.png"
        fig.savefig(path, dpi=140, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)
    return paths


def plot_frequency_map(frequency, config, out, probability_threshold, n_cases):
    """Save the one season frequency map, including all Part C towns."""
    values = np.asarray(frequency.values, dtype=float)
    actual_max = int(np.nanmax(values)) if np.isfinite(values).any() else 0
    fig, ax = plt.subplots(figsize=(12.5, 4.6))
    mesh = ax.pcolormesh(
        frequency["longitude"], frequency["latitude"], frequency,
        cmap="YlOrRd", vmin=0, vmax=max(1, actual_max), shading="auto",
    )
    _map_axes(ax, config)
    mark_towns(ax, config, fontsize=7)
    ax.set_ylabel("latitude")
    fig.colorbar(
        mesh, ax=ax, shrink=0.9,
        label=f"cases at or above {probability_threshold:.0%} probability "
              f"(of {n_cases}; maximum shown = {actual_max})",
    )
    tag = f"p{round(probability_threshold * 100):02d}"
    ax.set_title(
        f"Season risk frequency: {n_cases} selected start/day cases\n"
        f"number of cases with probability ≥ {probability_threshold:.0%} "
        f"(maximum {actual_max})"
    )
    path = out / f"09_frequency_map_{tag}.png"
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return path


def run(
    config,
    out,
    start_dates=None,
    days=None,
    probability_threshold=None,
):
    """Read the selected starts, build probabilities and write Part D maps."""
    out = Path(out)
    settings = forecast_settings(config)
    days = settings["risk_forecast_days"] if days is None else days
    probability_threshold = settings["probability_threshold"] if probability_threshold is None else probability_threshold
    days = tuple(sorted(int(day) for day in days))
    if not 0 < probability_threshold < 1:
        raise ValueError("probability threshold must be strictly between 0 and 1")
    forecast, forecast_snapshot = open_store(config["forecast"])
    try:
        times = season_starts(forecast, config)
        starts = (
            pd.DatetimeIndex(start_dates)
            if start_dates is not None
            else pd.DatetimeIndex(settings["risk_start_dates"])
        )
        starts = validate_starts(starts, config)
        if len(starts) < 3 or len(starts) > 4:
            raise ValueError("select 3 or 4 forecast starts")
        if not set(starts).issubset(set(times)):
            missing = sorted(set(starts) - set(times))
            raise ValueError("start dates not available: " + ", ".join(
                str(date.date()) for date in missing
            ))

        check_domain(forecast, config, "latitude", "longitude", ascending=False)
        forecast_region = select_region(
            forecast, config, "latitude", "longitude", ascending=False
        )
        observed, observed_snapshot = open_store(config["cmorph_reference"])
        try:
            check_domain(observed, config, "lat", "lon", ascending=True)
            threshold_map, units = read_threshold_map(
                observed, forecast_region, config
            )
        finally:
            observed.close()
        indices, _ = cumulative_indices(forecast_region, days)
        warn_source_size(forecast_region[config["forecast"]["variable"]], starts, indices)
        probabilities, kept, skipped, timings = read_probabilities(
            forecast_region, config, starts, threshold_map, days
        )
    finally:
        forecast.close()

    frequency = frequency_map(probabilities, probability_threshold)
    n_cases = int(probabilities.sizes["time"] * probabilities.sizes["step"])
    summary = summarize_starts(
        probabilities, kept, skipped, timings, probability_threshold
    )
    hotspots = top_hotspots(frequency, probabilities.max(dim=("time", "step")))
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "09_region_risk_summary.csv"
    hotspot_path = out / "09_region_risk_hotspots.csv"
    summary.to_csv(summary_path, index=False, float_format="%.4f")
    hotspots.to_csv(hotspot_path, index=False)
    probability_paths = plot_probability_maps(
        probabilities, config, out, probability_threshold
    )
    frequency_path = plot_frequency_map(
        frequency, config, out, probability_threshold, n_cases
    )
    manifest_path = write_manifest(out, config, forecast_snapshot, observed_snapshot,
                                   starts, kept, skipped, [probabilities], {"forecast_days": list(days),
                                   "probability_threshold": probability_threshold,
                                   "frequency_denominator": "available selected initialization/forecast-day pairs"})
    return {
        "manifest_path": manifest_path,
        "forecast_snapshot": forecast_snapshot,
        "observed_snapshot": observed_snapshot,
        "units": units,
        "starts": kept,
        "skipped_starts": skipped,
        "days": days,
        "probability_threshold": probability_threshold,
        "n_cases": n_cases,
        "threshold_map": threshold_map,
        "probabilities": probabilities,
        "frequency": frequency,
        "summary": summary,
        "hotspots": hotspots,
        "summary_path": summary_path,
        "hotspot_path": hotspot_path,
        "probability_paths": probability_paths,
        "frequency_path": frequency_path,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", "--grid", dest="config", type=Path,
                        help="JSON settings override or grid.json export; defaults to scripts/common.py")
    parser.add_argument("--start-dates", nargs="+",
                        help="explicit 3-4 ISO start dates; default: common.py risk_start_dates")
    parser.add_argument("--days", help="comma-separated whole-day leads; default: common.py risk_forecast_days")
    parser.add_argument("--probability", type=float,
                        help="probability fraction; default: common.py probability_threshold")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIRECTORY,
                        help=f"output directory (default: {OUTPUT_DIRECTORY})")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        validate_common(config)
        starts = parse_start_dates(args.start_dates)
        days = parse_days(args.days) if args.days is not None else None
    except (ConfigError, ValueError) as exc:
        parser.error(str(exc))

    try:
        started = time.time()
        result = run(
            config, args.out, start_dates=starts, days=days, probability_threshold=args.probability,
        )
    except (ConfigError, ValueError, OSError) as exc:
        parser.error(str(exc))

    print(f"forecast snapshot {result['forecast_snapshot']}; "
          f"CMORPH snapshot {result['observed_snapshot']}")
    print("selected starts: " + ", ".join(
        start.strftime("%Y-%m-%d") for start in result["starts"]
    ))
    if len(result["skipped_starts"]):
        print("skipped all-NaN starts: " + ", ".join(
            start.strftime("%Y-%m-%d") for start in result["skipped_starts"]
        ))
    print(f"region: {config['region_extent']}; days {result['days']}; "
          f"{result['n_cases']} cases")
    print(f"threshold units: {result['units']['effective_units']}; "
          f"threshold range {float(result['threshold_map'].min()):.1f}-"
          f"{float(result['threshold_map'].max()):.1f} mm/day")
    print(result["summary"].to_string(index=False))
    print("\ntop frequency grid points:")
    print(result["hotspots"].head(10).to_string(index=False))
    print(f"elapsed {time.time() - started:.1f}s")
    print("saved", result["summary_path"])
    print("saved", result["hotspot_path"])
    for path in [*result["probability_paths"], result["frequency_path"]]:
        print("saved", path)


if __name__ == "__main__":
    main()
