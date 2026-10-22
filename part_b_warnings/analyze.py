"""Part B: compare warning thresholds at two Sudan towns.

Inspired by python-workshop exercises 05 and 06. Outputs stay beside this file.
The default is one initialization (2025-07-16), not the whole JJA season.
"""
from pathlib import Path
import argparse
import json
import os
import hashlib
import subprocess

# %% Configuration and metadata-only validation

ROOT = Path(__file__).resolve().parent
PART_A = ROOT.parent / 'part_a_extremes'


def validate_domain(dataset, name, lat_name, lon_name, ascending, towns):
    """Only coordinate vectors are read, never precipitation arrays."""
    import numpy as np
    lat, lon = dataset[lat_name].values, dataset[lon_name].values
    differences = np.diff(lat)
    if not np.all(differences > 0 if ascending else differences < 0):
        raise ValueError(f'{name} latitude is not strictly {"ascending" if ascending else "descending"}')
    bounds = dict(south=float(lat.min()), north=float(lat.max()),
                  west=float(lon.min()), east=float(lon.max()))
    checks = []
    for town in towns:
        inside = (bounds['south'] <= town['latitude'] <= bounds['north'] and
                  bounds['west'] <= town['longitude'] <= bounds['east'])
        if not inside:
            raise ValueError(f"{town['name']} outside {name} domain")
        point = dataset.sel({lat_name: town['latitude'], lon_name: town['longitude']}, method='nearest')
        checks.append(dict(town=town['name'], inside=True,
                           selected_latitude=float(point[lat_name]), selected_longitude=float(point[lon_name])))
    return dict(source=name, latitude_order='ascending' if ascending else 'descending',
                bounds=bounds, towns=checks, status='verified from source coordinates')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--init', default='2025-07-16')
    parser.add_argument('--towns', nargs=2, default=['Khartoum', 'Kassala'])
    parser.add_argument('--use-cache', action='store_true', help='Reuse the saved two-town point extraction')
    parser.add_argument('--refresh-domain-checks', action='store_true',
                        help='Read both stores coordinate metadata even when using cached rainfall')
    args = parser.parse_args()
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.matplotlib'))
    for key in list(os.environ):
        if key.startswith('AWS_'):
            os.environ.pop(key)
    print('Loading libraries (including xclim)...', flush=True)
    import icechunk
    import numpy as np
    import pandas as pd
    import xarray as xr
    import xclim
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    config = json.loads((PART_A / 'grid.json').read_text())
    lookup = {t['name']: t for t in config['towns']}
    towns = [lookup[name] for name in args.towns]
    thresholds = pd.read_csv(PART_A / 'thresholds.csv')
    annual = pd.read_csv(PART_A / 'annual_maxima.csv')
    # Validate all required thresholds before any remote reads.
    threshold_sets = {}
    for town in towns:
        rows = thresholds[(thresholds.town == town['name']) & (thresholds.duration == '24hr')]
        labels = {'20mm': 20.0}
        for period in [2, 10]:
            match = rows[rows.return_period_years == period]
            if len(match) != 1:
                raise ValueError(f"Missing or duplicate Part A threshold: {town['name']} {period}-year")
            labels[f'{period}yr'] = float(match.iloc[0].threshold_mm)
        if not all(np.isfinite(list(labels.values()))):
            raise ValueError('Nonfinite thresholds')
        threshold_sets[town['name']] = labels
    forecast = config['forecast']
    domains = {'status': 'not recorded in legacy point cache; rerun with --refresh-domain-checks'}
    def open_source(source):
        storage = icechunk.s3_storage(bucket=source['bucket'], prefix=source['prefix'],
            endpoint_url=source['endpoint'], region='us-east-1', anonymous=True,
            from_env=False, force_path_style=True)
        repo = icechunk.Repository.open(storage, config=icechunk.RepositoryConfig.default())
        return xr.open_zarr(repo.readonly_session('main').store, zarr_format=3,
                            consolidated=False, chunks={}, decode_timedelta=True)

    # %% Open source metadata; check both domains and their opposite latitude orders
    if not args.use_cache or args.refresh_domain_checks:
        print('Checking coordinate metadata in forecast and CMORPH stores...', flush=True)
        ds = open_source(forecast)
        obs = open_source(config['cmorph_reference'])
        domains = dict(status='verified', forecast=validate_domain(
            ds, 'forecast', 'latitude', 'longitude', False, towns),
            cmorph=validate_domain(obs, 'CMORPH', 'lat', 'lon', True, towns))
        (ROOT/'domain_validation.json').write_text(json.dumps(domains, indent=2)+'\n')
        print('Both towns inside both domains. Forecast latitude descends; CMORPH latitude ascends.', flush=True)
        # Confirm Part A used the same nearest CMORPH grid cells.
        for point in domains['cmorph']['towns']:
            row = thresholds[(thresholds.town == point['town']) & (thresholds.duration == '24hr')].iloc[0]
            if not (np.isclose(row.grid_latitude, point['selected_latitude']) and
                    np.isclose(row.grid_longitude, point['selected_longitude'])):
                raise ValueError('Part A CMORPH pixel does not match current store')
    print(f"Preparing forecast initialized {args.init}...", flush=True)
    init = pd.Timestamp(args.init)
    if args.use_cache:
        cache = np.load(ROOT / 'forecast_point_diagnostics.npz', allow_pickle=False)
        if str(cache['initialization']) != str(init) or cache['towns'].tolist() != args.towns:
            raise ValueError('Cached initialization/towns do not match requested analysis')
        whole_hours = cache['lead_hours']
        if whole_hours[0] != 0 or not np.all(np.diff(whole_hours) == 24):
            raise ValueError('Invalid cached lead intervals')
        cumulative = xr.DataArray(cache['cumulative_m'], dims=('town', 'number', 'step'),
            coords={'number': cache['members'], 'step': pd.to_timedelta(whole_hours, unit='h')})
        if 'domains_json' in cache and not args.refresh_domain_checks:
            domains = json.loads(str(cache['domains_json']))
        if domains.get('status') != 'verified':
            print('DOMAIN CHECK STATUS: '+domains['status'], flush=True)
        print('Using saved forecast point extraction; no rainfall download needed.', flush=True)
    else:
        init = pd.Timestamp(args.init)
        if init not in pd.DatetimeIndex(ds.time.values):
            raise ValueError(f'Initialization {init} unavailable')
        for town in towns:
            if not (float(ds.latitude.min()) <= town['latitude'] <= float(ds.latitude.max())
                    and float(ds.longitude.min()) <= town['longitude'] <= float(ds.longitude.max())):
                raise ValueError(f"{town['name']} outside forecast domain")
        hours = np.asarray(pd.to_timedelta(ds.step.values) / pd.Timedelta(hours=1), dtype=float)
        selected = np.flatnonzero(np.isclose(hours % 24, 0))
        whole_hours = hours[selected]
        if len(selected) < 2 or whole_hours[0] != 0 or not np.all(np.diff(whole_hours) == 24):
            raise ValueError('Require step 0 and consecutive 24-hour endpoints')
        print('Reading two town points and whole-day cumulative rainfall...', flush=True)
        cumulative = ds[forecast['variable']].sel(time=init).isel(step=selected).sel(
            latitude=xr.DataArray([t['latitude'] for t in towns], dims='town'),
            longitude=xr.DataArray([t['longitude'] for t in towns], dims='town'),
            method='nearest').compute().transpose('town', 'number', 'step')
    # %% Convert cumulative metres to mm in consecutive 24-hour intervals
    if len(set(args.towns)) != 2:
        raise ValueError('Choose two distinct towns')
    if not np.isfinite(cumulative.values).all():
        raise ValueError('Missing forecast values; choose another initialization')
    units = str(cumulative.attrs.get('units', '')).lower().strip()
    if not units:
        # This specific workshop store is documented as cumulative tp in metres.
        # Do not extend the fallback to an unknown source.
        if forecast['prefix'] != 'forecasts/ecmwf-ifs-ea-swio-realized-v3/49r1-jja2025':
            raise ValueError('Missing precipitation units in an unrecognized forecast store')
        units = 'm'
        print('No units attribute: using documented cumulative tp units (metres) for this workshop store.', flush=True)
    if units not in ('m', 'metre', 'meter', 'metres', 'meters'):
        raise ValueError(f'Expected cumulative precipitation in metres, found {units!r}')
    daily = cumulative.diff('step') * 1000
    # Preserve the tiny point extraction so a failed validation is inspectable.
    np.savez_compressed(ROOT / 'forecast_point_diagnostics.npz',
        cumulative_m=cumulative.values, lead_hours=whole_hours,
        members=cumulative.number.values, towns=np.array(args.towns), initialization=str(init),
        domains_json=json.dumps(domains))
    negative_tolerance_mm = 0.05
    negative_count = int((daily.values < 0).sum())
    minimum_daily_mm = float(daily.min())
    if minimum_daily_mm < -negative_tolerance_mm:
        bad = []
        for ti, mi, si in np.argwhere(daily.values < -negative_tolerance_mm):
            bad.append(dict(town=towns[ti]['name'], member=int(cumulative.number.values[mi]),
                start_hour=float(whole_hours[si]), end_hour=float(whole_hours[si+1]),
                cumulative_start_mm=float(cumulative.values[ti, mi, si]*1000),
                cumulative_end_mm=float(cumulative.values[ti, mi, si+1]*1000),
                difference_mm=float(daily.values[ti, mi, si])))
        pd.DataFrame(bad).to_csv(ROOT/'negative_rainfall_diagnostics.csv', index=False)
        print(pd.DataFrame(bad).sort_values('difference_mm').head(10).to_string(index=False), flush=True)
        raise ValueError(f'Cumulative rainfall decreases: minimum {float(daily.min()):.8g} mm; '
            f'{len(bad)} intervals below -{negative_tolerance_mm} mm. Saved negative_rainfall_diagnostics.csv '
            'and forecast_point_diagnostics.npz. Do not interpret negative totals as rain.')
    if negative_count:
        print(f'QC: treating {negative_count} tiny negative totals as zero; '
              f'minimum {minimum_daily_mm:.6f} mm, tolerance {negative_tolerance_mm} mm.', flush=True)
    daily = daily.clip(min=0)
    days = (whole_hours[1:] / 24).astype(int)
    valid = init + pd.to_timedelta(days, unit='D')
    if (init < pd.Timestamp(config['start_date']) or valid[-1] >= pd.Timestamp(config['end_date']) + pd.Timedelta(days=1)):
        raise ValueError('Forecast intervals must lie within configured JJA period')
    # %% Count strict exceedances and xclim heavy-rain days; plot per town
    n = daily.sizes['number']
    if n != 51:
        raise ValueError(f'Expected 51 members in workshop forecast; found {n}')
    count_rows, member_rows, summary_rows, daily_rows, notes = [], [], [], [], []
    for i, town in enumerate(towns):
        name = town['name']
        print(f'Counting exceedances and xclim heavy-rain days: {name}...', flush=True)
        values = daily.isel(town=i).values
        pr = xr.DataArray(values, dims=('number', 'time'),
            coords={'number': daily.number.values, 'time': valid}, name='pr',
            attrs={'units': 'mm/day', 'standard_name': 'precipitation_flux'})
        fig, ax = plt.subplots(figsize=(10, 5))
        for label, threshold in threshold_sets[name].items():
            exceed = (values > threshold).sum(axis=0)
            # xclim wetdays convention includes equality; report it separately.
            heavy = xclim.indices.wetdays(pr, thresh=f'{threshold:.15g} mm/day', freq='YS').sum('time')
            direct = (values >= threshold).sum(axis=1)
            np.testing.assert_array_equal(heavy.values, direct)
            for d, date, count in zip(days, valid, exceed):
                count_rows.append(dict(town=name, initialization=str(init.date()), forecast_day=int(d),
                    valid_start=str(date-pd.Timedelta(days=1)), valid_end=str(date),
                    rainfall_units='mm in 24 h', threshold=label, threshold_mm=threshold,
                    members_above=int(count), members=n, fraction_above=float(count/n)))
            for member, heavy_count in zip(daily.number.values, heavy.values):
                member_rows.append(dict(town=name, member=int(member), threshold=label,
                    threshold_mm=threshold, heavy_days_ge=int(heavy_count), forecast_days=len(days)))
            summary_rows.append(dict(town=name, threshold=label, threshold_mm=threshold,
                member_days_above=int(exceed.sum()), total_member_days=int(values.size),
                fraction_above=float(exceed.sum()/values.size), max_members_above=int(exceed.max()),
                members_with_heavy_day_ge=int((heavy.values >= 1).sum()),
                mean_heavy_days_ge=float(heavy.mean())))
            style = {'20mm': ('o', '-'), '2yr': ('s', '--'), '10yr': ('x', ':')}[label]
            ax.plot(days, exceed, marker=style[0], linestyle=style[1],
                    label=f'{label}: > {threshold:.1f} mm in 24 h')
            for day, count in zip(days, exceed):
                if count:
                    ax.annotate(str(count), (day, count), xytext=(0, 5), textcoords='offset points', ha='center')
        for m, member in enumerate(daily.number.values):
            for j, date in enumerate(valid):
                daily_rows.append(dict(town=name, member=int(member), forecast_day=int(days[j]),
                    valid_end=str(date), rainfall_mm=float(values[m, j])))
        max_count = max(int(row['max_members_above']) for row in summary_rows if row['town'] == name)
        ax.set(title=f'{name}: ensemble from {init:%Y-%m-%d} (51 members)', xlabel='Forecast day (24 h intervals)',
               ylabel=f'Number of members exceeding threshold (of {n})',
               ylim=(-.15, min(n, max(3, max_count+1))), xticks=days)
        ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        if max_count == 0:
            ax.text(.5, .5, 'No members exceed any threshold on any forecast day',
                    transform=ax.transAxes, ha='center', fontsize=10)
        ax.text(0, -.21, 'Rainfall depths: mm in 24 h. Counts use >; xclim heavy-day totals use ≥.',
                transform=ax.transAxes, fontsize=8)
        ax.grid(alpha=.25)
        ax.legend()
        fig.tight_layout()
        fig.savefig(ROOT / f'{name.lower().replace(" ", "_")}_threshold_counts.png', dpi=160)
        plt.close(fig)
        obs = annual[(annual.town == name) & (annual.duration == '24hr')]
        t2 = threshold_sets[name]['2yr']
        observed_count = int((obs.annual_maximum_mm > t2).sum())
        notes.append(f'{name}: observed annual maxima above the {t2:.2f} mm 2-year level: '
                     f'{observed_count}/{len(obs)} years ({observed_count/len(obs):.1%}).')
    # %% Save counts, explanation and provenance
    counts = pd.DataFrame(count_rows)
    summary = pd.DataFrame(summary_rows)
    counts.to_csv(ROOT/'daily_member_counts.csv', index=False)
    summary.to_csv(ROOT/'summary_counts.csv', index=False)
    pd.DataFrame(member_rows).to_csv(ROOT/'xclim_heavy_days.csv', index=False)
    pd.DataFrame(daily_rows).to_csv(ROOT/'daily_rainfall.csv', index=False)
    short_table = counts.pivot(index=['town', 'forecast_day', 'valid_end'],
                              columns='threshold', values='members_above').reset_index()
    short_table.to_csv(ROOT/'daily_counts_short.csv', index=False)
    notes.insert(0, 'Units: rainfall depth in mm accumulated over each 24-hour interval. Member counts have no rainfall unit.')
    notes.insert(1, 'Domain checks: '+domains['status'])
    notes += ['', summary.to_string(index=False), '',
        'A 2-year annual-maximum threshold has a fitted 50% chance of being exceeded at least once in a year.',
        'That is not a 50% daily exceedance probability. Under an illustrative independent, identically distributed',
        f'daily model, p = 1 - 0.5**(1/365) = {1-0.5**(1/365):.3%} per day.',
        'Real rainfall is seasonal and serially dependent, so that daily number is illustrative, not a calibrated forecast.',
        'The table quantifies how often the three thresholds are exceeded in this forecast; ensemble member-days',
        'are correlated predictions and cannot estimate an observed climatological return period.',
        'The annual threshold is useful for rare-event screening but may miss impactful, more frequent rain.',
        'Selecting an operational warning requires impact records, forecast verification, and a probability decision rule.',
        'Daily member counts use strict >; xclim heavy-day counts use >= and describe only the forecast window.',
        f'QC: {negative_count} negative daily totals clipped to zero; minimum raw total {minimum_daily_mm:.6f} mm; tolerance {negative_tolerance_mm} mm.',
        'Nearest forecast and CMORPH grid cells differ in resolution and area; these are not station measurements.']
    (ROOT/'results.txt').write_text('\n'.join(notes)+'\n')
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    git_state = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    metadata = dict(initialization=str(init), towns=towns, forecast=forecast, members=n,
        domain_validation=domains, script_sha256=script_hash,
        git_commit=git_state.stdout.strip() if git_state.returncode == 0 else None,
        rainfall_units='mm in 24 h', count_units='members',
        cumulative_precipitation_units=units,
        negative_tolerance_mm=negative_tolerance_mm, negative_totals_clipped=negative_count,
        minimum_raw_daily_mm=minimum_daily_mm,
        units_source='variable attribute' if cumulative.attrs.get('units') else 'documented workshop store convention',
        days=days.tolist(), thresholds_mm=threshold_sets,
        forecast_grid_latitudes=cumulative.latitude.values.tolist() if 'latitude' in cumulative.coords else None,
        forecast_grid_longitudes=cumulative.longitude.values.tolist() if 'longitude' in cumulative.coords else None,
        reused_point_cache=args.use_cache,
        versions={k: v for k, v in [('xclim', xclim.__version__), ('xarray', xr.__version__)]})
    (ROOT/'run_metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print('\n'.join(notes), flush=True)
    print(f'All outputs saved in {ROOT}', flush=True)


if __name__ == '__main__':
    main()
