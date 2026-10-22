"""Part D: regional forecast probabilities, inspired by workshop E8 and E3.

Maps depict rainfall-threshold exceedance, not observed impacts or calibrated risk.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import socket
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent


def touched_chunks(shape, chunks, indices):
    """Count unique storage chunks intersecting a Cartesian selection (not HTTP requests)."""
    import numpy as np
    return int(np.prod([len(np.unique(np.asarray(index, dtype=int)//chunk))
                        for size, chunk, index in zip(shape, chunks, indices)]))


def probability_from_cumulative(cumulative, threshold):
    """Input: step × member × latitude × longitude in m; output probabilities."""
    import numpy as np
    raw = np.diff(cumulative, axis=0)*1000
    if np.isinf(raw).any() or np.any(raw < -.05):
        raise ValueError('Infinite rainfall or cumulative decrease larger than 0.05 mm; inspect source data')
    valid = np.isfinite(cumulative[:-1]).all(axis=1) & np.isfinite(cumulative[1:]).all(axis=1)
    valid &= np.isfinite(threshold)[None, ...]
    counts = (np.maximum(raw, 0) > threshold[None, None, ...]).sum(axis=1)
    prob = counts/cumulative.shape[1]
    return np.where(valid, prob, np.nan), int((raw < 0).sum())


# %% Configuration and public data metadata
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--starts', nargs='+', default=['2025-06-10', '2025-07-01', '2025-07-22', '2025-08-12'])
    parser.add_argument('--days', type=int, default=5, help='Consecutive daily leads starting at day 1')
    parser.add_argument('--probability', type=float, default=.2, help='Grid-point probability decision level')
    parser.add_argument('--offline', action='store_true', help='Require existing regional probability caches')
    args = parser.parse_args()
    if not 3 <= len(set(args.starts)) == len(args.starts) <= 4:
        raise ValueError('Choose 3 or 4 distinct forecast starts')
    if not 1 <= args.days <= 10 or not 0 < args.probability <= 1:
        raise ValueError('Require 1–10 forecast days and probability in (0,1]')
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'.matplotlib'))
    for key in list(os.environ):
        if key.startswith('AWS_'):
            os.environ.pop(key)
    print('Loading libraries...', flush=True)
    import icechunk
    import numpy as np
    import pandas as pd
    import xarray as xr
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm
    from matplotlib.ticker import PercentFormatter
    sys.path.insert(0, str(ROOT.parent/'part_b_warnings'))
    from analyze import validate_domain

    config = json.loads((ROOT.parent/'part_a_extremes/grid.json').read_text())
    towns = config['towns']
    starts = sorted(pd.Timestamp(s) for s in args.starts)
    if any(s < pd.Timestamp(config['start_date']) or s+pd.Timedelta(days=args.days) >=
           pd.Timestamp(config['end_date'])+pd.Timedelta(days=1) for s in starts):
        raise ValueError('All forecast intervals must lie in configured JJA season')
    box = dict(west=min(t['extent']['west'] for t in towns)-1,
               east=max(t['extent']['east'] for t in towns)+1,
               south=min(t['extent']['south'] for t in towns)-1,
               north=max(t['extent']['north'] for t in towns)+1)
    signature = hashlib.sha256(json.dumps(dict(box=box, forecast=config['forecast'],
        cmorph=config['cmorph_reference'], days=args.days, towns=towns), sort_keys=True).encode()).hexdigest()
    cache_dir = ROOT/'cache'
    cache_dir.mkdir(exist_ok=True)
    metadata_path = cache_dir/f'metadata_{signature[:16]}.json'
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else None
    ds = None
    threshold = None
    latitude = longitude = None
    timings, probabilities, summary_rows = [], [], []

    def open_source(source):
        storage = icechunk.s3_storage(bucket=source['bucket'], prefix=source['prefix'],
            endpoint_url=source['endpoint'], region='us-east-1', anonymous=True,
            from_env=False, force_path_style=True)
        repo = icechunk.Repository.open(storage, config=icechunk.RepositoryConfig.default())
        return xr.open_zarr(repo.readonly_session('main').store, zarr_format=3,
                            consolidated=False, chunks={}, decode_timedelta=True)

    # %% Select source initialization, daily endpoints and region BEFORE compute
    for init in starts:
        path = cache_dir/f'{init:%Y-%m-%d}_{signature[:16]}.npz'
        print(f'{init:%Y-%m-%d}: ', end='', flush=True)
        if path.exists():
            t0 = time.perf_counter()
            with np.load(path, allow_pickle=False) as cache:
                probability = cache['probability']
                latitude, longitude = cache['latitude'], cache['longitude']
                read_info = json.loads(str(cache['read_info']))
            timings.append(dict(kind='local_probability_cache', initialization=str(init.date()),
                seconds=time.perf_counter()-t0, estimated_storage_chunks=0, negative_totals_clipped=0))
            timings.append(dict(read_info, kind='original_forecast_read_record'))
            print('using local regional probability cache', flush=True)
        else:
            if args.offline:
                raise ValueError(f'Cache unavailable for {init.date()}; run online first')
            if ds is None:
                try:
                    socket.getaddrinfo(urlparse(config['forecast']['endpoint']).hostname, 443)
                except OSError as error:
                    raise RuntimeError('Cannot resolve the cloud data host. Run this command from your connected Mac Terminal; '
                                       'completed starts remain cached for resuming.') from error
                t0 = time.perf_counter()
                print('opening both source stores...', flush=True)
                ds, obs = open_source(config['forecast']), open_source(config['cmorph_reference'])
                domains = dict(forecast=validate_domain(ds, 'forecast', 'latitude', 'longitude', False, towns),
                    cmorph=validate_domain(obs, 'CMORPH', 'lat', 'lon', True, towns))
                for source in domains.values():
                    bounds = source['bounds']
                    if not (bounds['west'] <= box['west'] < box['east'] <= bounds['east'] and
                            bounds['south'] <= box['south'] < box['north'] <= bounds['north']):
                        raise ValueError(f"Requested region exceeds {source['source']} domain")
                metadata_seconds = time.perf_counter()-t0
                region = ds.sel(latitude=slice(box['north'], box['south']),
                                longitude=slice(box['west'], box['east']))
                latitude, longitude = region.latitude.values, region.longitude.values
                t0 = time.perf_counter()
                native = obs['return_period_precip'].sel(duration='24hr', return_period=2)
                # Each forecast point gets its nearest CMORPH threshold, not a town-wide constant.
                matched = native.sel(lat=region.latitude, lon=region.longitude, method='nearest')
                threshold = matched.compute().transpose('latitude', 'longitude').values
                threshold_seconds = time.perf_counter()-t0
                if np.any(np.isfinite(threshold) & (threshold < 0)) or not np.isfinite(threshold).any():
                    raise ValueError('Regional thresholds are invalid')
                tp_chunks = ds.tp.encoding.get('chunks')
                rp_chunks = obs.return_period_precip.encoding.get('chunks')
                metadata = dict(domains=domains, box=box, forecast_dims=list(ds.tp.dims),
                    forecast_shape=list(ds.tp.shape), forecast_chunks=list(tp_chunks) if tp_chunks else None,
                    threshold_dims=list(obs.return_period_precip.dims),
                    threshold_chunks=list(rp_chunks) if rp_chunks else None,
                    metadata_open_seconds=metadata_seconds, threshold_read_seconds=threshold_seconds,
                    threshold_units='mm in 24 h', threshold_matching='nearest CMORPH pixel per forecast pixel')
                # Chunk count uses source-grid indices, including the selected duration and return period.
                if rp_chunks:
                    selections = []
                    for dim in obs.return_period_precip.dims:
                        if dim == 'duration':
                            indices = np.flatnonzero(obs.duration.values == '24hr')
                        elif dim == 'return_period':
                            indices = np.flatnonzero(obs.return_period.values == 2)
                        elif dim == 'lat':
                            indices = obs.indexes['lat'].get_indexer(latitude, method='nearest')
                        elif dim == 'lon':
                            indices = obs.indexes['lon'].get_indexer(longitude, method='nearest')
                        else:
                            indices = np.arange(obs.sizes[dim])
                        selections.append(indices)
                    metadata['threshold_estimated_storage_chunks'] = touched_chunks(
                        obs.return_period_precip.shape, rp_chunks, selections)
                metadata_path.write_text(json.dumps(metadata, indent=2)+'\n')
                timings.append(dict(kind='cmorph_threshold_read', initialization='', seconds=threshold_seconds,
                    estimated_storage_chunks=metadata.get('threshold_estimated_storage_chunks'), negative_totals_clipped=0))
            if init not in pd.DatetimeIndex(ds.time.values):
                raise ValueError(f'Unavailable initialization: {init}')
            desired = pd.to_timedelta(np.arange(args.days+1)*24, unit='h')
            steps = ds.indexes['step'].get_indexer(desired)
            if np.any(steps < 0):
                raise ValueError('Required daily lead endpoint missing')
            print(f'reading {args.days+1} cumulative maps, then calculating probabilities...', flush=True)
            t0 = time.perf_counter()
            point = ds.tp.sel(time=init).isel(step=steps).sel(
                latitude=slice(box['north'], box['south']), longitude=slice(box['west'], box['east'])).compute()
            elapsed = time.perf_counter()-t0
            point = point.transpose('step', 'number', 'latitude', 'longitude')
            units = str(point.attrs.get('units', '')).lower().strip()
            if units and units not in ['m', 'metre', 'meter', 'metres', 'meters']:
                raise ValueError(f'Unexpected rainfall units {units!r}')
            if not units and config['forecast']['prefix'] != 'forecasts/ecmwf-ifs-ea-swio-realized-v3/49r1-jja2025':
                raise ValueError('Missing units for unknown store')
            if point.sizes['number'] != 51:
                raise ValueError('Expected 51 forecast members')
            probability, negative_count = probability_from_cumulative(point.values, threshold)
            chunk_count = None
            chunks = ds.tp.encoding.get('chunks')
            if chunks:
                selections = []
                for dim in ds.tp.dims:
                    if dim == 'time':
                        indices = [ds.indexes['time'].get_loc(init)]
                    elif dim == 'step':
                        indices = steps
                    elif dim == 'latitude':
                        indices = np.flatnonzero((ds.latitude.values >= box['south']) & (ds.latitude.values <= box['north']))
                    elif dim == 'longitude':
                        indices = np.flatnonzero((ds.longitude.values >= box['west']) & (ds.longitude.values <= box['east']))
                    else:
                        indices = np.arange(ds.sizes[dim])
                    selections.append(indices)
                chunk_count = touched_chunks(ds.tp.shape, chunks, selections)
            read_info = dict(kind='forecast_read', initialization=str(init.date()), seconds=elapsed,
                             estimated_storage_chunks=chunk_count, negative_totals_clipped=negative_count)
            timings.append(read_info)
            temporary = cache_dir/'writing.npz'
            np.savez_compressed(temporary, probability=probability, latitude=latitude,
                longitude=longitude, read_info=json.dumps(read_info))
            temporary.replace(path)
        probabilities.append(probability)
        for day, field in enumerate(probability, start=1):
            summary_rows.append(dict(initialization=str(init.date()), forecast_day=day,
                valid_start=str(init+pd.Timedelta(days=day-1)), valid_end=str(init+pd.Timedelta(days=day)),
                available_grid_points=int(np.isfinite(field).sum()), grid_points_ge_probability=int((field >= args.probability).sum()),
                maximum_probability=float(np.nanmax(field)) if np.isfinite(field).any() else np.nan))

    if metadata is None:
        raise ValueError('Cached source metadata is missing; rerun online to validate sources')
    # %% Probability maps with fixed 0–100% scale and all town locations
    def mark_towns(ax):
        for town in towns:
            ax.plot(town['longitude'], town['latitude'], '^', color='black', markerfacecolor='white', ms=5)
            ax.annotate(town['name'], (town['longitude'], town['latitude']), xytext=(3, 4),
                        textcoords='offset points', fontsize=7, color='black')
        ax.set(xlabel='Longitude', ylabel='Latitude', aspect='equal')

    cmap = plt.get_cmap('YlOrRd').copy()
    cmap.set_bad('#bdbdbd')
    for init, probability in zip(starts, probabilities):
        ncols = min(3, args.days)
        nrows = int(np.ceil(args.days/ncols))
        fig, axes = plt.subplots(nrows, ncols, figsize=(5*ncols, 4*nrows), squeeze=False, layout='constrained')
        for day, (ax, field) in enumerate(zip(axes.flat, probability), start=1):
            pm = ax.pcolormesh(longitude, latitude, np.ma.masked_invalid(field), cmap=cmap, vmin=0, vmax=1, shading='auto')
            if np.isfinite(field).any() and np.nanmin(field) < args.probability < np.nanmax(field):
                ax.contour(longitude, latitude, field, levels=[args.probability], colors='#174c87', linewidths=.8)
            mark_towns(ax)
            ax.set_title(f'Day {day} | ending {init+pd.Timedelta(days=day):%d %b}\n'
                         f'{int((field >= args.probability).sum())} grid points ≥{args.probability:.0%}')
        for ax in list(axes.flat)[args.days:]:
            ax.set_visible(False)
        colorbar = fig.colorbar(pm, ax=list(axes.flat)[:args.days], shrink=.8, label='Ensemble fraction above local 2-year 24 h level')
        colorbar.ax.yaxis.set_major_formatter(PercentFormatter(1))
        fig.suptitle(f'Forecast initialized {init:%Y-%m-%d} | 51 members\n'
                     'Rainfall threshold: mm in 24 h. Blue contour: probability decision level; gray: missing.', fontsize=13)
        fig.savefig(ROOT/f'probabilities_{init:%Y-%m-%d}.png', dpi=160)
        plt.close(fig)
    # %% Frequency denominator counts only available sampled forecast intervals
    cube = np.stack(probabilities)
    available = np.isfinite(cube).sum(axis=(0, 1))
    frequency = (cube >= args.probability).sum(axis=(0, 1))
    fraction = np.divide(frequency, available, out=np.full(available.shape, np.nan), where=available > 0)
    total = len(starts)*args.days
    count_masked = np.where(available > 0, frequency, np.nan)
    fig, axes = plt.subplots(1, 3, figsize=(18, 6), layout='constrained')
    norm = BoundaryNorm(np.arange(-.5, total+1.5), 256)
    for ax, values, title, fractional in zip(axes, [count_masked, fraction, available],
        [f'Count with probability ≥{args.probability:.0%}', 'Fraction of available intervals', 'Available forecast intervals'], [False, True, False]):
        pm = ax.pcolormesh(longitude, latitude, np.ma.masked_invalid(values), cmap=cmap,
            shading='auto', **({'vmin': 0, 'vmax': 1} if fractional else {'norm': norm}))
        mark_towns(ax)
        ax.set_title(title)
        cb = fig.colorbar(pm, ax=ax, shrink=.75, label='Fraction' if fractional else f'Intervals (maximum {total})')
        if fractional:
            cb.ax.yaxis.set_major_formatter(PercentFormatter(1))
    fig.suptitle(f'JJA 2025 sampled forecast frequency | {len(starts)} starts × {args.days} daily leads\n'
                 'Sampled intervals only; not a complete-season frequency or observed impact map.', fontsize=14)
    fig.savefig(ROOT/'sampled_season_frequency.png', dpi=160)
    plt.close(fig)
    np.savez_compressed(ROOT/'regional_probability_results.npz', probability=cube,
        starts=np.array([str(s) for s in starts]), forecast_days=np.arange(1, args.days+1),
        latitude=latitude, longitude=longitude, frequency=frequency, available=available, fraction= fraction)
    pd.DataFrame(summary_rows).to_csv(ROOT/'probability_summary.csv', index=False)
    pd.DataFrame(timings).to_csv(ROOT/'read_timings.csv', index=False)
    town_rows = []
    for town in towns:
        yi, xi = int(np.argmin(abs(latitude-town['latitude']))), int(np.argmin(abs(longitude-town['longitude'])))
        town_rows.append(dict(town=town['name'], grid_latitude=latitude[yi], grid_longitude=longitude[xi],
            exceedance_intervals=int(frequency[yi, xi]), available_intervals=int(available[yi, xi]),
            fraction=fraction[yi, xi]))
    pd.DataFrame(town_rows).to_csv(ROOT/'town_frequency.csv', index=False)
    minimum_members = int(np.ceil(args.probability*51))
    notes = [f'Sampled starts: {", ".join(s.strftime("%Y-%m-%d") for s in starts)}; days 1–{args.days}.',
        f'Probability = members with rainfall > local 2-year 24 h threshold / 51.',
        f'Frequency decision is probability >= {args.probability:.0%}: at least {minimum_members}/51 members ({minimum_members/51:.2%}).',
        f'Frequency counts {total} sampled start/day intervals, not all days or starts in JJA.',
        'Missing thresholds or incomplete member data are masked; frequency fractions use available intervals at each pixel.',
        'Dates with overlapping leads, if supplied, count separate forecast intervals rather than unique observed days.',
        f'Forecast chunk dimensions: {metadata["forecast_dims"]}; shapes: {metadata["forecast_chunks"]}.',
        f'CMORPH threshold chunk dimensions: {metadata["threshold_dims"]}; shapes: {metadata["threshold_chunks"]}.',
        'A pan chunk covers a broad spatial map for one initialization/lead, often all ensemble members.',
        'A regional map uses spatial values already in those chunks. A single point may fetch the same large chunks.',
        'Daily rainfall requires two cumulative endpoints; selecting six endpoints yields five daily maps and reuses shared endpoints.',
        'A pencil layout favors time series at a point, but a map must span many small spatial chunks.',
        'read_timings.csv records measured read+decode+compute seconds and source chunk estimates, not exact HTTP request counts.',
        'Warm caches, network conditions, metadata reads and compression affect timing; local cached reads are labeled separately.',
        'Missing cumulative tp units use the documented metres convention only for the known workshop store.',
        'Forecast latitude descends, CMORPH ascends; town and full-region domains are verified.',
        'Thresholds use nearest CMORPH pixels, not conservative regridding; this is a rainfall-hazard indicator, not verified impact risk.']
    notes.extend(['', 'Town frequency at nearest forecast pixels:', pd.DataFrame(town_rows).to_string(index=False),
                  '', 'Measured read records:', pd.DataFrame(timings).to_string(index=False)])
    (ROOT/'results.txt').write_text('\n'.join(notes)+'\n')
    revision = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    (ROOT/'run_metadata.json').write_text(json.dumps(dict(source_metadata=metadata, probability_decision=args.probability,
        starts=[str(s) for s in starts], forecast_days=args.days, total_sample_intervals=total,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        git_commit=revision.stdout.strip() if revision.returncode == 0 else None), indent=2)+'\n')
    print('\n'.join(notes), flush=True)
    print(f'All Task D outputs saved in {ROOT}', flush=True)


if __name__ == '__main__':
    main()
