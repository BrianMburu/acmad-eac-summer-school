"""Part D: regional probabilities and sampled forecast frequency (workshop E3/E8).

Run inspect, extract, then plots. Inspection fetches no remote rainfall;
extraction caches each regional start; plotting is offline. Shared settings
are in scripts/common.py. Frequency is over sampled start/day forecasts,
not observed events or all days of the season.
"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import tempfile
import time

import numpy as np
import pandas as pd
import xarray as xr

from scripts.common import (ROOT, ConfigError, config_hash, load_config,
                            risk_map_dates, validate_risk_map)
from scripts.data_access import open_store, town_indexers
from scripts.forecast_rainfall import (daily_rainfall, select_town_forecasts,
                                      source_read_estimate)
from scripts.rainfall_thresholds import (file_sha256, inspect_stores, provenance,
                                        require_complete_run, write_json, write_status)


def select_region(obs, forecast, config):
    """Validate both domains and select daily leads and the region lazily."""
    validate_risk_map(config)
    report, coverage = inspect_stores(obs, forecast, config)
    if report['problems']:
        raise ValueError('; '.join(report['problems']))
    effective = deepcopy(config)
    dates = risk_map_dates(config)
    effective['forecast']['start_dates'] = dates
    effective['threshold_choice']['towns'] = [town['name'] for town in config['towns']]
    _, point_report = select_town_forecasts(forecast, effective)
    hours = point_report['daily_lead_hours']
    maximum = 24 * max(config['risk_map']['forecast_days'])
    if max(hours) < maximum:
        raise ValueError('Forecast horizon is shorter than risk_map.forecast_days')
    leads = [hour for hour in hours if hour <= maximum]
    box = config['region_extent']
    bounds = ((box['north'], box['south']) if config['forecast']['latitude_order'] == 'descending'
              else (box['south'], box['north']))
    source = forecast[config['forecast']['variable']]
    selected = source.sel(time=pd.DatetimeIndex(dates),
        step=pd.to_timedelta(leads, unit='h'), latitude=slice(*bounds),
        longitude=slice(box['west'], box['east']))
    if min(selected.sizes['latitude'], selected.sizes['longitude']) < 2:
        raise ValueError('Selected region must contain at least two forecast pixels per axis')
    raw = obs[config['cmorph_reference']['variable']].sel(duration='24hr', return_period=2)
    if set(raw.dims) != {'lat', 'lon'}:
        raise ValueError(f'Unexpected CMORPH threshold dimensions: {raw.dims}')
    threshold = raw.sel(
        lat=xr.DataArray(selected.latitude.values, dims='latitude',
                         coords={'latitude': selected.latitude.values}),
        lon=xr.DataArray(selected.longitude.values, dims='longitude',
                         coords={'longitude': selected.longitude.values}), method='nearest')
    matched_lat, matched_lon = threshold.lat.values, threshold.lon.values
    threshold = threshold.drop_vars(['lat', 'lon', 'duration', 'return_period'], errors='ignore')
    threshold = threshold.assign_coords(cmorph_latitude=('latitude', matched_lat),
        cmorph_longitude=('longitude', matched_lon)).rename('threshold_mm')
    threshold.attrs = {'units': 'mm', 'duration': '24hr', 'return_period_years': 2}
    all_times = pd.DatetimeIndex(forecast.time.values).get_indexer(pd.DatetimeIndex(dates))
    all_steps = pd.Index(forecast.step.values).get_indexer(selected.step.values)
    forecast_cost = source_read_estimate(source, all_times, all_steps, selected)
    forecast_cost['selected_region_mib'] = forecast_cost.pop('selected_point_mib')
    report.update(start_dates=dates, forecast_days=config['risk_map']['forecast_days'],
        daily_lead_hours=leads, forecast_units=point_report['units'],
        forecast_read=forecast_cost, threshold_read=threshold_read_estimate(obs, threshold, config),
        regional_shape={key: selected.sizes[key] for key in ['latitude', 'longitude']},
        selected_region_extent={'west': float(selected.longitude.min()),
            'east': float(selected.longitude.max()), 'south': float(selected.latitude.min()),
            'north': float(selected.latitude.max())},
        all_leads_source_mib=source_read_estimate(source, all_times,
            np.arange(source.sizes['step']), selected)['decoded_source_mib'],
        config_sha256=config_hash(config))
    return selected, threshold, report, coverage


def threshold_read_estimate(obs, threshold, config):
    array = obs[config['cmorph_reference']['variable']]
    if set(array.dims) != {'duration', 'return_period', 'lat', 'lon'}:
        raise ValueError(f'Unexpected stored CMORPH dimensions: {array.dims}')
    positions = {'duration': [pd.Index(obs.duration.values).get_loc('24hr')],
        'return_period': [pd.Index(obs.return_period.values).get_loc(2)],
        'lat': pd.Index(obs.lat.values).get_indexer(threshold.cmorph_latitude.values),
        'lon': pd.Index(obs.lon.values).get_indexer(threshold.cmorph_longitude.values)}
    chunks = array.encoding.get('chunks', array.shape)
    count = math.prod(len(set((np.asarray(positions[dim]) // width).tolist()))
                     for dim, width in zip(array.dims, chunks))
    size = math.prod(chunks) * array.dtype.itemsize / 2**20
    return {'source_chunks': list(chunks), 'source_chunks_touched': count,
            'source_chunk_mib': size, 'decoded_source_mib': count * size}


def cached_field(name, inputs, cache, loader=None):
    """Cache only the selected field, with input and file hashes and atomic writes."""
    cache.mkdir(parents=True, exist_ok=True)
    digest = config_hash(inputs)
    path = cache / f'{name}-{digest[:16]}.nc'
    metadata = path.with_suffix('.json')
    started = time.perf_counter()
    if metadata.exists():
        saved = json.loads(metadata.read_text())
        if (saved['input_sha256'] != digest or not path.exists()
                or saved['file_sha256'] != file_sha256(path)):
            raise ValueError(f'Invalid regional cache {path}; remove that entry before retrying')
        with xr.open_dataarray(path, engine='scipy', decode_timedelta=True) as field:
            result = field.load()
        return result, True, time.perf_counter() - started
    if loader is None:
        raise FileNotFoundError(path)
    result = loader()
    copy = result.copy(deep=False)
    copy.encoding = {}
    for coord in copy.coords:
        copy[coord].encoding = {}
    with tempfile.TemporaryDirectory(prefix='.field-', dir=cache) as temporary:
        staged = Path(temporary) / 'field.nc'
        copy.to_netcdf(staged, engine='scipy')
        os.replace(staged, path)
    write_json(metadata, {'input_sha256': digest, 'file_sha256': file_sha256(path), 'inputs': inputs})
    return result, False, time.perf_counter() - started


def cache_inputs(selected, config, snapshots):
    grid = {axis: selected[axis].values.tolist() for axis in ['latitude', 'longitude']}
    forecast = {'store': {k: v for k, v in config['forecast'].items() if k != 'start_dates'},
        'snapshot': snapshots['forecast'], 'grid': grid,
        'daily_lead_hours': (selected.step.values / np.timedelta64(1, 'h')).astype(int).tolist()}
    threshold = {'store': config['cmorph_reference'], 'snapshot': snapshots['cmorph'],
        'grid': grid, 'duration': '24hr', 'return_period_years': 2,
        'units_if_missing': config['thresholds']['units_if_missing']}
    return forecast, threshold


def inspect_cache(selected, config, report, snapshots, out):
    forecast_input, threshold_input = cache_inputs(selected, config, snapshots)
    cache = out / 'cache'
    cached = []
    for date in report['start_dates']:
        try:
            cached_field(date, {**forecast_input, 'date': date}, cache)
            cached.append(date)
        except FileNotFoundError:
            pass
    try:
        cached_field('threshold', threshold_input, cache)
        threshold_cached = True
    except FileNotFoundError:
        threshold_cached = False
    source = report['forecast_read']['decoded_source_mib']
    uncached = source * (1 - len(cached) / len(report['start_dates']))
    uncached += 0 if threshold_cached else report['threshold_read']['decoded_source_mib']
    report.update(cached_starts=cached, threshold_cached=threshold_cached,
        uncached_source_mib=uncached, store_snapshots=snapshots)
    print(f"{len(report['start_dates'])} starts, {len(cached)} cached; "
        f"forecast {source:.1f} MiB decoded; threshold "
        f"{report['threshold_read']['decoded_source_mib']:.1f} MiB; "
        f"uncached estimate {uncached:.1f} MiB.", flush=True)
    if uncached > 256:
        print('SIZE WARNING: source chunks exceed 256 MiB despite the small regional output. '
              'Decoded estimates are not compressed transfer or peak RAM.', flush=True)
    return forecast_input, threshold_input


def validate_threshold_map(threshold):
    values = threshold.values
    finite = np.isfinite(values)
    if (not finite.any() or np.isinf(values).any() or (values[finite] < 0).any()):
        raise ValueError('Invalid regional 2-year rainfall thresholds')
    return {'valid_pixels': int(finite.sum()), 'missing_pixels': int((~finite).sum()),
            'minimum_mm': float(values[finite].min()), 'maximum_mm': float(values[finite].max())}


def probability_for_start(daily, threshold, date):
    """Strict rainfall exceedance; missing thresholds stay missing, never dry."""
    if daily.sizes['number'] != 51 or not np.isfinite(daily.values).all():
        raise ValueError('Probability requires 51 finite members at every forecast pixel')
    for axis in ['latitude', 'longitude']:
        if not np.array_equal(daily[axis].values, threshold[axis].values):
            raise ValueError(f'Threshold and forecast {axis} coordinates differ')
    count = (daily > threshold).sum('number').where(np.isfinite(threshold))
    count = count.swap_dims({'time': 'forecast_day'}).drop_vars('time')
    count = count.expand_dims(initialization=[date]).rename('members_above')
    return xr.Dataset({'members_above': count, 'probability': count / 51})


def combine_maps(pieces, threshold, config):
    dates, days = risk_map_dates(config), config['risk_map']['forecast_days']
    maps = xr.concat(pieces, dim='initialization', join='outer', combine_attrs='drop_conflicts').reindex(
        initialization=dates, forecast_day=days)
    maps = maps.assign_coords(valid_end=(('initialization', 'forecast_day'), np.array([
        [np.datetime64(date, 'ns') + np.timedelta64(day, 'D') for day in days] for date in dates])))
    valid = np.isfinite(maps.probability)
    maps['available_forecasts'] = valid.sum(['initialization', 'forecast_day'])
    maps['risk_hits'] = ((maps.probability >= config['risk_map']['signal_probability']) & valid).sum(
        ['initialization', 'forecast_day'])
    maps['frequency_fraction'] = (maps.risk_hits / maps.available_forecasts.where(maps.available_forecasts > 0))
    maps['threshold_mm'] = threshold
    maps.probability.attrs = {'units': '1', 'members_total': 51, 'rainfall_operator': '>'}
    maps.frequency_fraction.attrs = {'units': '1', 'probability_operator': '>=',
        'signal_probability': config['risk_map']['signal_probability'],
        'denominator': 'available sampled initialization/forecast-day opportunities, not observed events'}
    return maps


def output_tables(maps, config):
    spatial = []
    for date in risk_map_dates(config):
        for day in config['risk_map']['forecast_days']:
            field = maps.probability.sel(initialization=date, forecast_day=day)
            values = field.values
            finite = np.isfinite(values)
            peak = np.unravel_index(np.nanargmax(values), values.shape) if finite.any() else None
            spatial.append({'initialization': date, 'forecast_day': day,
                'valid_end': (pd.Timestamp(date) + pd.Timedelta(days=day)).isoformat(),
                'valid_pixels': int(finite.sum()),
                'pixels_at_probability': int((values >= config['risk_map']['signal_probability']).sum()),
                'maximum_probability': float(values[finite].max()) if finite.any() else None,
                'peak_latitude': float(field.latitude.values[peak[0]]) if peak else None,
                'peak_longitude': float(field.longitude.values[peak[1]]) if peak else None})
    requested = pd.DataFrame(config['towns'])[['name', 'latitude', 'longitude']].rename(
        columns={'name': 'town', 'latitude': 'requested_latitude', 'longitude': 'requested_longitude'})
    paired = town_indexers(config)
    indexers = {'latitude': paired['lat'], 'longitude': paired['lon']}
    points = maps[['members_above', 'probability', 'threshold_mm']].sel(**indexers, method='nearest')
    points = points.to_dataframe().reset_index().rename(
        columns={'latitude': 'forecast_latitude', 'longitude': 'forecast_longitude'})
    points = points.merge(requested, on='town', validate='many_to_one')
    points['probability_percent'] = 100 * points.probability
    summary = xr.Dataset({key: maps[key] for key in
        ['risk_hits', 'available_forecasts', 'frequency_fraction', 'threshold_mm']}).sel(**indexers, method='nearest')
    summary = summary.to_dataframe().reset_index().rename(
        columns={'latitude': 'forecast_latitude', 'longitude': 'forecast_longitude'})
    summary = summary.merge(requested, on='town', validate='one_to_one')
    summary['frequency_percent'] = 100 * summary.frequency_fraction
    summary = summary.merge(points.groupby('town', as_index=False).probability.max().rename(
        columns={'probability': 'peak_probability'}), on='town', validate='one_to_one')
    frequency = xr.Dataset({key: maps[key] for key in
        ['risk_hits', 'available_forecasts', 'frequency_fraction']}).to_dataframe().reset_index()
    return {'spatial_summary.csv': pd.DataFrame(spatial), 'town_probabilities.csv': points,
            'town_risk_summary.csv': summary, 'frequency.csv': frequency}


def run_remote(config, out, inspection_only=False):
    validate_risk_map(config)
    out.mkdir(parents=True, exist_ok=True)
    status = 'inspection_status.json' if inspection_only else 'run_status.json'
    write_status(out, 'running', filename=status, stage='inspect')
    started = time.perf_counter()
    try:
        with ExitStack() as resources:
            obs, obs_snapshot = open_store(config['cmorph_reference'])
            resources.callback(obs.close)
            forecast, fc_snapshot = open_store(config['forecast'])
            resources.callback(forecast.close)
            snapshots = {'cmorph': obs_snapshot, 'forecast': fc_snapshot}
            selected, threshold, report, coverage = select_region(obs, forecast, config)
            fc_inputs, threshold_inputs = inspect_cache(selected, config, report, snapshots, out)
            write_json(out / 'inspection.json', report)
            coverage.to_csv(out / 'inspection_coverage.csv', index=False)
            if inspection_only:
                write_status(out, 'ok', filename=status, stage='inspect')
                print('Inspection complete; no remote rainfall fetched.')
                return
            if report['uncached_source_mib'] > config['risk_map']['max_source_mib']:
                raise ValueError('Uncached source estimate exceeds risk_map.max_source_mib; reduce the selection or raise the explicit budget')
            cache = out / 'cache'
            print('Reading the local 2-year threshold field ...', flush=True)
            threshold, hit, seconds = cached_field('threshold', threshold_inputs, cache,
                lambda: threshold.compute(scheduler='threads', num_workers=config['execution']['workers']))
            checks = validate_threshold_map(threshold)
            timings = [{'source': 'cmorph_threshold', 'initialization': None,
                        'cached': hit, 'read_seconds': seconds}]
            pieces, starts = [], []
            for date in report['start_dates']:
                print(f'Processing regional forecast {date} ...', flush=True)
                cumulative, hit, seconds = cached_field(date, {**fc_inputs, 'date': date}, cache,
                    lambda date=date: selected.sel(time=date).compute(scheduler='threads',
                        num_workers=config['execution']['workers']))
                timings.append({'source': 'forecast', 'initialization': date,
                                'cached': hit, 'read_seconds': seconds})
                daily = daily_rainfall(cumulative, report['forecast_units']['mm_factor'],
                                       config['threshold_choice']['trace_rainfall_mm'])
                if daily is None:
                    starts.append({'initialization': date, 'status': 'skipped_all_nan'})
                else:
                    daily = daily.sel(time=slice(config['start_date'],
                        pd.Timestamp(config['end_date']) + pd.Timedelta(days=1)))
                    if daily.sizes['time']:
                        pieces.append(probability_for_start(daily, threshold, date))
                        starts.append({**daily.attrs, 'initialization': date, 'status': 'ok',
                                       'forecast_days': daily.sizes['time']})
                    else:
                        starts.append({'initialization': date, 'status': 'skipped_outside_season'})
                write_status(out, 'running', stage='extract', completed_starts=len(starts),
                             scheduled_starts=len(report['start_dates']))
            if not pieces:
                raise ValueError('No usable regional forecasts in the requested season')
            maps = combine_maps(pieces, threshold, config)
            tables = output_tables(maps, config)
            with tempfile.TemporaryDirectory(prefix='.extract-', dir=out) as temporary:
                staging = Path(temporary)
                maps.to_netcdf(staging / 'risk_maps.nc', engine='scipy')
                for name, table in tables.items():
                    table.to_csv(staging / name, index=False)
                coverage.to_csv(staging / 'coverage.csv', index=False)
                pd.DataFrame(timings).to_csv(staging / 'read_timings.csv', index=False)
                write_json(staging / 'settings_used.json', config)
                write_json(staging / 'forecast_starts.json', starts)
                manifest = provenance(config, snapshots)
                manifest.update(mode='complete', inspection=report, threshold_checks=checks,
                    forecast_starts=starts, read_timings=timings,
                    elapsed_seconds=time.perf_counter() - started,
                    adapted_from=['E3: pan chunks and timed reads', 'E8: local 2-year probability maps',
                                  'E5/E6: shared daily rainfall and strict member counts'],
                    interpretation='Sampled forecast probabilities and start/day frequency, not observed 2025 events or a complete seasonal frequency.',
                    matching_note='CMORPH is matched to forecast pixels; town markers use shared coordinates. Part C instead matches CMORPH directly to town centres, so town thresholds can differ.')
                manifest['output_sha256'] = {path.name: file_sha256(path) for path in staging.iterdir()}
                write_json(staging / 'manifest.json', manifest)
                for path in sorted(staging.iterdir(), key=lambda p: p.name == 'manifest.json'):
                    os.replace(path, out / path.name)
            write_status(out, 'ok', stage='complete')
            print(f'Saved complete Part D run in {out}', flush=True)
    except (Exception, KeyboardInterrupt) as exc:
        write_status(out, 'failed', filename=status, error=str(exc) or 'Interrupted')
        raise


def mark_towns(ax, config, fontsize=7):
    for town in config['towns']:
        ax.plot(town['longitude'], town['latitude'], 'o', color='black', ms=3,
                markeredgecolor='white', markeredgewidth=.5)
        ax.annotate(town['name'], (town['longitude'], town['latitude']),
                    xytext=(3, 3), textcoords='offset points', fontsize=fontsize)
    box = config['region_extent']
    ax.set(xlim=(box['west'], box['east']), ylim=(box['south'], box['north']),
           xlabel='Longitude (°E)', ylabel='Latitude (°N)')
    ax.set_aspect('equal')


def plot_outputs(out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    require_complete_run(out)
    manifest = json.loads((out / 'manifest.json').read_text())
    for name, digest in manifest['output_sha256'].items():
        if file_sha256(out / name) != digest:
            raise ValueError(f'Cached {name} differs from its manifest; re-extract before plotting')
    config = load_config(out / 'settings_used.json')
    validate_risk_map(config)
    if config_hash(config) != manifest['config_sha256']:
        raise ValueError('Saved Part D settings differ from the manifest')
    with xr.open_dataset(out / 'risk_maps.nc', engine='scipy') as source:
        maps = source.load()
    figures = out / 'figures'
    figures.mkdir(exist_ok=True)
    cmap = plt.get_cmap('YlOrRd').with_extremes(bad='lightgrey')
    days = config['risk_map']['forecast_days']
    available = sum(row['status'] == 'ok' for row in manifest['forecast_starts'])
    for date in risk_map_dates(config):
        columns = min(5, len(days))
        fig, axes = plt.subplots(math.ceil(len(days) / columns), columns,
            figsize=(4.1 * columns, 3.3 * math.ceil(len(days) / columns)),
            squeeze=False, layout='constrained')
        for ax, day in zip(axes.flat, days):
            field = maps.probability.sel(initialization=date, forecast_day=day)
            mesh = ax.pcolormesh(field.longitude, field.latitude,
                np.ma.masked_invalid(field.values), cmap=cmap, vmin=0, vmax=1, shading='auto')
            valid = pd.Timestamp(date) + pd.Timedelta(days=day)
            ax.set_title(f'Day {day}: 24 h ending {valid:%d %b}', fontsize=9)
            mark_towns(ax, config)
        for ax in list(axes.flat)[len(days):]:
            ax.set_visible(False)
        colorbar = fig.colorbar(mesh, ax=list(axes.flat), shrink=.85)
        colorbar.ax.yaxis.set_major_formatter(PercentFormatter(1))
        colorbar.set_label('Members above local 2-year / 24 h level (of 51)')
        fig.suptitle(f'ECMWF start {date}: rainfall exceedance probability\nGrey = unavailable; towns from Part C; same probability scale for every start')
        fig.savefig(figures / f'probability_{date}.png', dpi=150)
        plt.close(fig)
    field = maps.frequency_fraction
    maximum = max(.1, float(field.max(skipna=True)))
    fig, ax = plt.subplots(figsize=(12, 5.5), layout='constrained')
    mesh = ax.pcolormesh(field.longitude, field.latitude, np.ma.masked_invalid(field.values),
                        cmap=cmap, vmin=0, vmax=maximum, shading='auto')
    mark_towns(ax, config, fontsize=9)
    colorbar = fig.colorbar(mesh, ax=ax, shrink=.85)
    colorbar.ax.yaxis.set_major_formatter(PercentFormatter(1))
    cutoff = config['risk_map']['signal_probability']
    colorbar.set_label(f'Available sampled start/day forecasts with probability ≥{cutoff:.0%}')
    ax.set_title(f'Sampled June–August 2025 forecast risk frequency\n'
        f'{available}/{len(risk_map_dates(config))} starts available; days {days[0]}–{days[-1]}; '
        'grey = no valid threshold/forecast')
    fig.savefig(figures / 'sampled_risk_frequency.png', dpi=160)
    plt.close(fig)
    print(f'Saved {len(risk_map_dates(config))} probability figures and one frequency map in {figures}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['inspect', 'extract', 'plots'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        out = args.out or ROOT / config['risk_map']['output_directory']
        if args.stage == 'plots':
            plot_outputs(out)
        else:
            run_remote(config, out, inspection_only=args.stage == 'inspect')
    except (ConfigError, ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'ERROR: {exc}\n')


if __name__ == '__main__':
    main()
