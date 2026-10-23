"""Shared E5/E6 cumulative rainfall validation for the B/C/D analyses."""

import hashlib
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.common import config_hash, forecast_settings


def daily_step_indices(steps):
    values = np.asarray(steps)
    if not np.issubdtype(values.dtype, np.timedelta64) or np.isnat(values).any():
        raise ValueError("forecast steps must be finite timedeltas")
    hours = values / np.timedelta64(1, "h")
    if (hours < 0).any() or (np.diff(hours) <= 0).any():
        raise ValueError("forecast steps must be nonnegative and strictly increasing")
    indices = np.flatnonzero(hours % 24 == 0)
    days = hours[indices]
    if (len(days) < 2 or days[0] != 0 or (np.diff(days) != 24).any()):
        raise ValueError("forecast requires a 0-hour step and consecutive whole-day steps")
    return hours, indices.tolist()


def forecast_unit_report(array, config):
    source = array.attrs.get("units")
    fallback = forecast_settings(config)["units_if_missing"]
    effective = str(source if source is not None else fallback).strip().lower()
    if effective in {"m", "metre", "meter", "metres", "meters"}:
        factor = 1000.0
    elif effective in {"mm", "millimetre", "millimeter", "millimetres", "millimeters",
                       "kg m-2", "kg m^-2", "kg/m2", "kg m**-2"}:
        factor = 1.0
    else:
        raise ValueError(f"unsupported cumulative forecast rainfall units: {source!r}")
    return {"source_units": source, "effective_units": effective, "mm_factor": factor,
            "used_workshop_fallback": source is None, "accumulation": "since initialization"}


def validate_ensemble(array):
    if "number" not in array.dims or array.sizes["number"] != 51:
        raise ValueError("forecast requires the complete 51-member ensemble")
    if len(np.unique(array.number.values)) != 51 or bool(array.number.isnull().any()):
        raise ValueError("forecast requires 51 unique finite member identifiers")


def validate_starts(starts, config):
    starts = pd.DatetimeIndex(starts)
    if starts.empty or starts.hasnans or starts.has_duplicates or not starts.equals(starts.normalize()):
        raise ValueError("forecast starts must be unique finite midnight dates")
    if not ((starts >= pd.Timestamp(config['start_date']))
            & (starts <= pd.Timestamp(config['end_date']))).all():
        raise ValueError("forecast starts must lie inside the configured season")
    return starts.sort_values()


def daily_totals(cumulative, config):
    """Return daily mm with the original step axis, or None for an all-NaN start.

    Only a completely unwritten start can be skipped. A partial ensemble, missing
    values, a nonzero baseline or a material decrease invalidates the analysis.
    Both positive and negative packing traces are zeroed using the explicit
    ECMWF tolerance, which is much smaller than the warning thresholds.
    """
    validate_ensemble(cumulative)
    report = forecast_unit_report(cumulative, config)
    _, indices = daily_step_indices(cumulative.step.values)
    if indices != list(range(cumulative.sizes['step'])):
        raise ValueError("select only whole-day endpoints before daily conversion")
    values = np.asarray(cumulative.values)
    if np.isnan(values).all():
        return None
    if not np.isfinite(values).all():
        raise ValueError("forecast contains partial missing data or nonfinite values")
    mm = cumulative.astype('float64') * report['mm_factor']
    if bool((mm < -1e-6).any()):
        raise ValueError("forecast has negative cumulative totals")
    if float(abs(mm.isel(step=0)).max()) > 0.01:
        raise ValueError("forecast step 0 must have zero cumulative rainfall")
    daily = mm.diff('step', label='upper')
    tolerance = forecast_settings(config)['trace_rainfall_mm']
    minimum = float(daily.min())
    if minimum < -tolerance:
        raise ValueError(f"cumulative rainfall decreases: minimum daily total {minimum:.6f} mm")
    negative_traces = int((daily < 0).sum())
    positive_traces = int(((daily > 0) & (daily < tolerance)).sum())
    daily = daily.where(daily >= tolerance, 0).clip(min=0)
    init = pd.Timestamp(cumulative.time.values)
    valid = init + pd.to_timedelta(daily.step.values)
    if (valid > pd.Timestamp(config['end_date']) + pd.Timedelta(days=1)).any():
        raise ValueError("forecast valid rainfall periods extend beyond the configured season")
    daily = daily.assign_coords(forecast_day=('step', (daily.step.values / np.timedelta64(24, 'h')).astype(int)),
                                valid_time=('step', valid))
    daily.name = 'daily_precipitation'
    daily.attrs = {**report, 'units': 'mm/day', 'trace_rainfall_mm': tolerance,
                   'minimum_uncorrected_daily_mm': minimum,
                   'negative_traces_zeroed': negative_traces, 'positive_traces_zeroed': positive_traces}
    return daily


def warn_source_size(array, starts, step_indices):
    """Warn about decoded map-chunk volume before fetching point selections."""
    chunks = array.encoding.get('chunks')
    if chunks is None:
        return
    # These workshop stores use one start and one step per pan chunk. Estimate
    # full spatial chunks conservatively; this is decoded I/O, not network bytes.
    volume = len(starts) * len(step_indices) * np.prod(chunks) * array.dtype.itemsize / 2**20
    if volume > 256:
        warnings.warn(f"Selected forecasts may decode about {volume:.0f} MiB of source map chunks; "
                      "point output is much smaller. Reduce starts or reuse cached reads if needed.",
                      UserWarning, stacklevel=2)


def write_manifest(out, config, forecast_snapshot, observed_snapshot, requested, kept, skipped, rainfall, parameters=None):
    """Record effective settings and the forecast conversion used for this run."""
    attributes = [{k: v for k, v in array.attrs.items()} for array in rainfall]
    payload = {'config_sha256': config_hash(config), 'settings': config,
               'forecast_snapshot': forecast_snapshot, 'cmorph_snapshot': observed_snapshot,
               'requested_starts': [str(pd.Timestamp(d).date()) for d in requested],
               'kept_starts': [str(pd.Timestamp(d).date()) for d in kept],
               'skipped_all_nan_starts': [str(pd.Timestamp(d).date()) for d in skipped],
               'rainfall_validation': attributes, 'analysis_parameters': parameters or {},
               'source_sha256': {str(p.relative_to(Path(__file__).parent.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(Path(__file__).parent.glob('*.py'))}}
    path = Path(out) / 'forecast_manifest.json'
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + '\n')
    return path
