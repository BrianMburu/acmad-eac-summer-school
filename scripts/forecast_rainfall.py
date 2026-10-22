"""Daily ensemble rainfall helpers adapted from workshop E2/E5/E6.

Select starts, whole-day leads and paired town points before computing. Forecast
tp is cumulative from initialization; daily totals are differences in mm.
"""

import math

import numpy as np
import pandas as pd
import xarray as xr

from scripts.common import box_inside, inside
from scripts.data_access import domain


def daily_step_indices(steps):
    values = np.asarray(steps)
    if not np.issubdtype(values.dtype, np.timedelta64) or np.isnat(values).any():
        raise ValueError("Forecast step must contain finite timedeltas")
    hours = values / np.timedelta64(1, "h")
    if (hours < 0).any() or (np.diff(hours) <= 0).any():
        raise ValueError("Forecast steps must be nonnegative and strictly increasing")
    indices = np.flatnonzero(hours % 24 == 0)
    daily_hours = hours[indices]
    if (not len(indices) or daily_hours[0] not in (0, 24)
            or daily_hours[-1] < 24 or (np.diff(daily_hours) != 24).any()):
        raise ValueError("Forecast needs consecutive daily leads starting at 0 or 24 h")
    return indices


def forecast_unit_report(array, fallback):
    source = array.attrs.get("units")
    effective = str(source or fallback).strip().lower()
    if effective in {"m", "metre", "meter", "metres", "meters"}:
        factor = 1000.0
    elif effective in {"mm", "millimetre", "millimeter", "kg m-2", "kg/m2"}:
        factor = 1.0
    else:
        raise ValueError(f"Unsupported cumulative forecast rainfall units: {source!r}; fallback {fallback!r}")
    return {"source_units": source, "effective_units": effective, "mm_factor": factor,
            "used_workshop_fallback": not bool(source), "accumulation": "since initialization (E5/E6)"}


def select_town_forecasts(ds, config):
    """Validate metadata/coverage and return a lazy, paired point selection."""
    settings = config["forecast"]
    array = ds[settings["variable"]]
    expected = {"time", "step", "number", "latitude", "longitude"}
    if set(array.dims) != expected:
        raise ValueError(f"Unexpected forecast dimensions: {array.dims}")
    if ds.sizes["number"] != 51 or len(np.unique(ds.number.values)) != 51:
        raise ValueError("Forecast analysis requires the complete 51-member ensemble")
    extent = domain(ds, "latitude", "longitude", settings["latitude_order"] == "ascending")
    if not box_inside(extent, config["region_extent"]):
        raise ValueError("Study region is outside the forecast domain")
    names = config["threshold_choice"]["towns"]
    towns = [next(t for t in config["towns"] if t["name"] == name) for name in names]
    for town in towns:
        if not inside(extent, town["latitude"], town["longitude"]):
            raise ValueError(f"{town['name']} is outside the forecast domain")
    starts = pd.DatetimeIndex(settings["start_dates"])
    available = pd.DatetimeIndex(ds.time.values)
    if available.has_duplicates or available.hasnans:
        raise ValueError("Forecast initialization coordinates must be unique and finite")
    missing = starts.difference(available)
    if len(missing):
        raise ValueError(f"Forecast start dates absent from store: {missing.strftime('%Y-%m-%d').tolist()}")
    indices = daily_step_indices(ds.step.values)
    indexers = {axis: xr.DataArray([town[key] for town in towns], dims="town", coords={"town": names})
                for axis, key in [("latitude", "latitude"), ("longitude", "longitude")]}
    selected = array.sel(time=starts).isel(step=indices).sel(**indexers, method="nearest")
    units = forecast_unit_report(array, config["threshold_choice"]["forecast_units_if_missing"])
    report = {"domain": extent, "units": units, "sizes": dict(array.sizes),
              "source_chunks": list(array.encoding.get("chunks", array.shape)),
              "daily_lead_hours": (ds.step.values[indices] / np.timedelta64(1, "h")).astype(int).tolist(),
              "towns": [{"town": name, "latitude": float(selected.latitude.sel(town=name)),
                         "longitude": float(selected.longitude.sel(town=name))} for name in names]}
    report.update(source_read_estimate(array, available.get_indexer(starts), indices, selected))
    return selected, report


def source_read_estimate(array, time_indices, step_indices, selected):
    """Count unique source chunks, including shared map chunks across towns.

    This is decoded source volume, not compressed network bytes or peak RAM.
    """
    chunks = array.encoding.get("chunks", array.shape)
    count, chunk_elements = 1, 1
    for dim, width in zip(array.dims, chunks):
        if dim == "time":
            positions = time_indices
        elif dim == "step":
            positions = step_indices
        elif dim in ("latitude", "longitude"):
            positions = pd.Index(array[dim].values).get_indexer(selected[dim].values)
        else:
            positions = np.arange(array.sizes[dim])
        count *= len(set((np.asarray(positions) // width).tolist()))
        chunk_elements *= int(width)
    chunk_bytes = chunk_elements * array.dtype.itemsize
    return {"source_chunks_touched": count, "source_chunk_mib": chunk_bytes / 2**20,
            "decoded_source_mib": count * chunk_bytes / 2**20,
            "selected_point_mib": math.prod(selected.shape) * array.dtype.itemsize / 2**20}


def daily_rainfall(cumulative, factor, trace_rainfall_mm=0.04):
    """Convert one computed start to finite 24-hour depths with valid end times.

    An entirely unwritten start returns None. Partial missingness and materially
    decreasing accumulations fail, rather than being counted as dry members.
    """
    values = np.asarray(cumulative.values)
    if np.isnan(values).all():
        return None
    if not np.isfinite(values).all():
        raise ValueError("Partially missing or infinite forecast; refusing a biased member count")
    mm = cumulative.astype("float64") * factor
    leads = mm.step.values / np.timedelta64(1, "h")
    if leads[0] == 0:
        if np.max(np.abs(mm.isel(step=0).values)) > 0.01:
            raise ValueError("Forecast step 0 must have zero cumulative rainfall")
        daily = mm.diff("step", label="upper")
    else:
        # A 24 h first lead is the first day's accumulation from initialization.
        daily = xr.concat([mm.isel(step=slice(0, 1)), mm.diff("step", label="upper")], dim="step")
    minimum = float(daily.min())
    if minimum < -trace_rainfall_mm:
        raise ValueError(f"Cumulative precipitation decreases: minimum daily total {minimum:.4f} mm")
    clipped = int((daily < 0).sum())
    positive_traces = int(((daily > 0) & (daily < trace_rainfall_mm)).sum())
    daily = daily.where(daily >= trace_rainfall_mm, 0).clip(min=0)
    init = pd.Timestamp(cumulative.time.item())
    valid = init + pd.to_timedelta(daily.step.values)
    days = (daily.step.values / np.timedelta64(24, "h")).astype(int)
    daily = daily.drop_vars("time").rename(step="time").assign_coords(
        time=valid, forecast_day=("time", days))
    daily.name = "rainfall_mm"
    daily.attrs = {"units": "mm/day", "standard_name": "precipitation_flux",
                   "tiny_negative_totals_clipped": clipped, "positive_trace_totals_zeroed": positive_traces,
                   "minimum_uncorrected_daily_mm": minimum, "trace_rainfall_mm": trace_rainfall_mm,
                   "initialization": init.isoformat()}
    return daily.transpose("town", "number", "time")
