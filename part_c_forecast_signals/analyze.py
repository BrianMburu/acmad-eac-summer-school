"""Part C, inspired by workshop 06_forecast_vs_local_extremes.py.

Select initialization, daily endpoints, and five town points before compute.
Example: python -u analyze.py --start 2025-07-06 --end 2025-07-26
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PART_A = ROOT.parent / 'part_a_extremes'


def longest_streak(rows, minimum):
    """Consecutive calendar-day initializations signaling the SAME valid interval."""
    import pandas as pd
    longest = current = 0
    previous = None
    for row in rows.sort_values('initialization').itertuples():
        date = pd.Timestamp(row.initialization)
        if row.members_above >= minimum:
            current = current + 1 if previous is not None and date-previous == pd.Timedelta(days=1) else 1
            longest = max(longest, current)
            previous = date
        else:
            current, previous = 0, None
    return longest


# %% Configuration; reuse the metadata-only validation helper from Part B
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2025-07-06')
    parser.add_argument('--end', default='2025-07-26')
    parser.add_argument('--min-members', type=int, default=1,
                        help='Exploratory signal criterion, not an operational warning rule')
    parser.add_argument('--offline', action='store_true', help='Require all cached starts; never access cloud')
    args = parser.parse_args()
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
    sys.path.insert(0, str(ROOT.parent/'part_b_warnings'))
    from analyze import validate_domain

    dates = pd.date_range(args.start, args.end, freq='D')
    if not 14 <= len(dates) <= 21:
        raise ValueError('Choose an inclusive window of 14 to 21 initialization dates')
    if not 1 <= args.min_members <= 51:
        raise ValueError('--min-members must be between 1 and 51')
    config = json.loads((PART_A/'grid.json').read_text())
    towns = config['towns']
    if len(towns) != 5:
        raise ValueError('Expected five towns in grid.json')
    if dates[0] < pd.Timestamp(config['start_date']) or dates[-1] > pd.Timestamp(config['end_date']):
        raise ValueError('Initialization window outside configured JJA period')
    table = pd.read_csv(PART_A/'thresholds.csv')
    thresholds = []
    for town in towns:
        row = table[(table.town == town['name']) & (table.duration == '24hr') & (table.return_period_years == 2)]
        if len(row) != 1 or not np.isfinite(row.threshold_mm.iloc[0]):
            raise ValueError(f"Missing or invalid Part A threshold for {town['name']}")
        if not (np.isclose(row.latitude.iloc[0], town['latitude']) and
                np.isclose(row.longitude.iloc[0], town['longitude'])):
            raise ValueError('Part A town coordinates differ from grid.json')
        thresholds.append(float(row.threshold_mm.iloc[0]))
    cache_dir = ROOT/'cache'
    cache_dir.mkdir(exist_ok=True)
    fingerprint = hashlib.sha256(json.dumps(dict(towns=towns, forecast=config['forecast']), sort_keys=True).encode()).hexdigest()
    ds = None
    domains = None

    def open_source(source):
        storage = icechunk.s3_storage(bucket=source['bucket'], prefix=source['prefix'],
            endpoint_url=source['endpoint'], region='us-east-1', anonymous=True,
            from_env=False, force_path_style=True)
        repo = icechunk.Repository.open(storage, config=icechunk.RepositoryConfig.default())
        return xr.open_zarr(repo.readonly_session('main').store, zarr_format=3,
                            consolidated=False, chunks={}, decode_timedelta=True)

    all_daily, all_counts, qc_rows = [], [], []
    lead_hours = None
    members = None
    # %% Read one initialization at a time; cache only daily town-point extractions
    for index, init in enumerate(dates):
        cache_path = cache_dir/f'{init:%Y-%m-%d}.npz'
        print(f'[{index+1}/{len(dates)}] {init:%Y-%m-%d}: ', end='', flush=True)
        if cache_path.exists():
            with np.load(cache_path, allow_pickle=False) as cached:
                if str(cached['fingerprint']) != fingerprint:
                    raise ValueError(f'Cache source/towns changed: {cache_path}; move old cache aside')
                cumulative = cached['cumulative_m']
                hours = cached['lead_hours']
                ids = cached['members']
                domains = json.loads(str(cached['domains_json']))
                if domains.get('status') != 'verified':
                    raise ValueError('Cached source domains are not verified')
            print('using local point cache', flush=True)
        else:
            if args.offline:
                raise ValueError(f'No cache for {init:%Y-%m-%d}; run online first')
            if ds is None:
                print('opening source metadata...', flush=True)
                ds = open_source(config['forecast'])
                obs = open_source(config['cmorph_reference'])
                domains = dict(status='verified', forecast=validate_domain(
                    ds, 'forecast', 'latitude', 'longitude', False, towns),
                    cmorph=validate_domain(obs, 'CMORPH', 'lat', 'lon', True, towns))
                for point in domains['cmorph']['towns']:
                    row = table[(table.town == point['town']) & (table.duration == '24hr')].iloc[0]
                    if not (np.isclose(row.grid_latitude, point['selected_latitude']) and
                            np.isclose(row.grid_longitude, point['selected_longitude'])):
                        raise ValueError('Part A threshold grid cell differs from CMORPH source')
            if init not in pd.DatetimeIndex(ds.time.values):
                raise ValueError(f'Start date not available: {init}')
            hours_all = np.asarray(pd.to_timedelta(ds.step.values)/pd.Timedelta(hours=1), dtype=float)
            selected = np.flatnonzero(np.isclose(hours_all % 24, 0))
            hours = hours_all[selected]
            print(f'reading {len(selected)} daily endpoints for all five towns...', flush=True)
            point = ds[config['forecast']['variable']].sel(time=init).isel(step=selected).sel(
                latitude=xr.DataArray([t['latitude'] for t in towns], dims='town'),
                longitude=xr.DataArray([t['longitude'] for t in towns], dims='town'),
                method='nearest').compute().transpose('town', 'number', 'step')
            units = str(point.attrs.get('units', '')).strip().lower()
            if units and units not in ['m', 'metres', 'meters', 'metre', 'meter']:
                raise ValueError(f'Unexpected cumulative tp units {units!r}')
            if not units and config['forecast']['prefix'] != 'forecasts/ecmwf-ifs-ea-swio-realized-v3/49r1-jja2025':
                raise ValueError('Missing units in unknown store')
            cumulative, ids = point.values, point.number.values
            temporary = cache_dir/'writing.npz'
            np.savez_compressed(temporary, cumulative_m=cumulative, lead_hours=hours,
                members=ids, fingerprint=fingerprint, domains_json=json.dumps(domains))
            temporary.replace(cache_path)
        if len(hours) < 2 or hours[0] != 0 or not np.all(np.diff(hours) == 24) or len(ids) != 51:
            raise ValueError('Require 51 members, step zero and consecutive 24-hour endpoints')
        if lead_hours is None:
            lead_hours, members = hours, ids
        elif not np.array_equal(hours, lead_hours) or not np.array_equal(ids, members):
            raise ValueError('Forecast coordinates changed between starts')
        raw = np.diff(cumulative, axis=-1)*1000
        if np.isinf(raw).any():
            raise ValueError('Infinite forecast rainfall')
        if np.any(raw < -.05):
            raise ValueError(f'{init}: decrease exceeds 0.05 mm tolerance; minimum {np.nanmin(raw):.6f} mm')
        qc_rows.append(dict(initialization=str(init.date()), negative_totals_clipped=int((raw < 0).sum())))
        daily = np.maximum(raw, 0)
        valid = np.isfinite(cumulative[..., :-1]).all(axis=1) & np.isfinite(cumulative[..., 1:]).all(axis=1)
        ends = init + pd.to_timedelta(hours[1:], unit='h')
        valid &= np.asarray(ends < pd.Timestamp(config['end_date'])+pd.Timedelta(days=1))[None, :]
        counts = (daily > np.array(thresholds)[:, None, None]).sum(axis=1).astype(float)
        counts[~valid] = np.nan
        daily = np.where(valid[:, None, :], daily, np.nan)
        all_daily.append(daily)
        all_counts.append(counts)

    # %% Tables and comparable signal metrics, grouped by the same valid interval
    rainfall = np.stack(all_daily)   # initialization, town, member, forecast day
    cube = np.stack(all_counts)
    days = (lead_hours[1:]/24).astype(int)
    rows = []
    for si, init in enumerate(dates):
        for ti, town in enumerate(towns):
            for di, day in enumerate(days):
                rows.append(dict(town=town['name'], initialization=str(init.date()), forecast_day=int(day),
                    valid_start=str(init+pd.Timedelta(days=int(day)-1)),
                    valid_end=str(init+pd.Timedelta(days=int(day))), threshold_mm=thresholds[ti],
                    members_above=cube[si, ti, di], total_members=51,
                    fraction_above=cube[si, ti, di]/51, available=bool(np.isfinite(cube[si, ti, di]))))
    counts_table = pd.DataFrame(rows)
    counts_table.to_csv(ROOT/'daily_member_counts.csv', index=False)
    pd.DataFrame(qc_rows).to_csv(ROOT/'quality_control.csv', index=False)
    events, summaries = [], []
    max_scale = max(1, int(np.nanmax(cube))) if np.isfinite(cube).any() else 1
    cmap = plt.get_cmap('YlOrRd').copy()
    cmap.set_bad('#bdbdbd')
    for ti, town in enumerate(towns):
        name, slug = town['name'], town['name'].lower().replace(' ', '_')
        town_counts = counts_table[counts_table.town == name]
        event_rows = []
        for valid_end, group in town_counts.groupby('valid_end'):
            hits = group[group.members_above >= args.min_members]
            event = dict(town=name, valid_end=valid_end, available_starts=int(group.available.sum()),
                signal_starts=len(hits), first_signal_start=hits.initialization.min() if len(hits) else '',
                earliest_lead_days=int(hits.forecast_day.max()) if len(hits) else 0,
                longest_consecutive_signal_starts=longest_streak(group, args.min_members))
            event_rows.append(event)
        events.extend(event_rows)
        finite_starts = np.isfinite(cube[:, ti, :]).any(axis=1)
        if not finite_starts.any():
            summaries.append(dict(town=name, status='no available forecasts'))
            continue
        # Peak members first, then total member-days, then earliest initialization.
        scores = [(-float(np.nanmax(cube[si, ti])), -float(np.nansum(cube[si, ti])), si)
                  for si in range(len(dates)) if finite_starts[si]]
        best = min(scores)[2]
        town_hits = town_counts[town_counts.members_above >= args.min_members]
        available_starts = int(finite_starts.sum())
        signal_starts = int(town_hits.initialization.nunique())
        summaries.append(dict(town=name, status='signal' if len(town_hits) else 'no signal',
            threshold_mm=thresholds[ti], peak_members_above=int(np.nanmax(cube[:, ti])),
            strongest_start=str(dates[best].date()), available_starts=available_starts,
            signal_starts=signal_starts, fraction_starts_with_signal=signal_starts/available_starts,
            first_signal_start=town_hits.initialization.min() if len(town_hits) else '',
            earliest_lead_days=int(town_hits.forecast_day.max()) if len(town_hits) else 0,
            longest_consecutive_signal_starts=max(e['longest_consecutive_signal_starts'] for e in event_rows)))
        fig, ax = plt.subplots(figsize=(10, max(6, len(dates)*.29)), layout='constrained')
        image = ax.imshow(np.ma.masked_invalid(cube[:, ti]), aspect='auto', cmap=cmap, vmin=0, vmax=max_scale)
        ax.set(xticks=range(len(days)), xticklabels=days, yticks=range(len(dates)),
            yticklabels=[d.strftime('%d %b') for d in dates], xlabel='Forecast day (24 h intervals)',
            ylabel='Initialization date', title=f'{name}: members > {thresholds[ti]:.2f} mm in 24 h\n'
            f'CMORPH 2-year level | ensemble size 51 | {dates[0]:%Y-%m-%d} to {dates[-1]:%Y-%m-%d}')
        for si in range(len(dates)):
            for di in range(len(days)):
                value = cube[si, ti, di]
                if np.isfinite(value) and value > 0:
                    ax.text(di, si, str(int(value)), ha='center', va='center', fontsize=8,
                            color='white' if value > max_scale*.55 else 'black')
        fig.colorbar(image, ax=ax, label='Members above threshold (of 51)')
        ax.text(0, -.12, 'Unannotated pale cells = zero; gray = missing/incomplete forecast.', transform=ax.transAxes, fontsize=8)
        fig.savefig(ROOT/f'{slug}_heatmap.png', dpi=160)
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(10, 5), layout='constrained')
        for member in range(51):
            ax.plot(days, rainfall[best, ti, member], color='#327eab', alpha=.2, lw=.8)
        ax.plot(days, np.nanmean(rainfall[best, ti], axis=0), color='black', lw=2, label='Ensemble mean')
        ax.axhline(thresholds[ti], color='#b32632', ls='--', label=f'2-year level: {thresholds[ti]:.2f} mm in 24 h')
        ax.set(title=f'{name}: strongest start {dates[best]:%Y-%m-%d}\n'
            f'Peak exceedance: {int(np.nanmax(cube[best, ti]))}/51 members'+
            (' (no threshold signal)' if np.nanmax(cube[best, ti]) == 0 else ''),
            xlabel='Forecast day (24 h intervals)', ylabel='Daily rainfall (mm in 24 h)', xticks=days)
        ax.legend()
        ax.grid(alpha=.2)
        fig.savefig(ROOT/f'{slug}_strongest_start_plume.png', dpi=160)
        plt.close(fig)
    summary = pd.DataFrame(summaries)
    summary.to_csv(ROOT/'town_signal_summary.csv', index=False)
    pd.DataFrame(events).to_csv(ROOT/'same_valid_day_signals.csv', index=False)
    available_summary = summary[summary.status != 'no available forecasts']
    active = available_summary[available_summary.status == 'signal']
    notes = [f'Window: {dates[0]:%Y-%m-%d} to {dates[-1]:%Y-%m-%d}; signal criterion >= {args.min_members}/51 members above local 2-year level.',
        summary.to_string(index=False), '',
        'Earliest means greatest lead time before the SAME valid 24-hour interval; first issuance date is also reported.',
        'Consistency means the longest run of consecutive initialization dates signaling that SAME valid interval.',
        'Signal-start fractions additionally describe frequency, and do not prove persistence for the same event.',
        'Boundary valid dates have fewer available starts; inspect same_valid_day_signals.csv before comparing.',
        'Most alarming start maximizes peak member count, then summed member-day counts, then earliest initialization.',
        'If all counts are zero, the tied earliest start is displayed with an explicit no-signal label.',
        'Missing members invalidate a town-day cell; missing forecasts are gray, never silently counted as zero.',
        'Thresholds are mm in 24 h; count units are members. Latitude order and all five town domain checks verified.',
        'Tiny negative daily amounts up to 0.05 mm are clipped to zero and recorded; larger decreases stop execution.',
        'Differences between towns can reflect thresholds, rainfall regime and ensemble spread; these counts cannot isolate a causal explanation.',
        'Annual maxima end in 2024. No observed 2025 event rainfall is supplied, so these plots show forecast signals, not verified hits or skill.']
    if len(active):
        lead = active.earliest_lead_days.max()
        streak = active.longest_consecutive_signal_starts.max()
        notes += ['Earliest-lead town(s): '+', '.join(active.loc[active.earliest_lead_days == lead, 'town'])+f' ({int(lead)} days).',
            'Most persistent town(s): '+', '.join(active.loc[active.longest_consecutive_signal_starts == streak, 'town'])+f' ({int(streak)} consecutive starts for one valid interval).']
    else:
        notes.append('No town had a signal at the specified criterion; no earliest or most consistent signal can be ranked.')
    (ROOT/'results.txt').write_text('\n'.join(notes)+'\n')
    revision = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    (ROOT/'run_metadata.json').write_text(json.dumps(dict(start=args.start, end=args.end,
        min_members=args.min_members, domain_validation=domains, thresholds_mm=dict(zip([t['name'] for t in towns], thresholds)),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        git_commit=revision.stdout.strip() if revision.returncode == 0 else None,
        rainfall_units='mm in 24 h', negative_tolerance_mm=.05), indent=2)+'\n')
    print('\n'.join(notes), flush=True)
    print(f'All Task C outputs saved in {ROOT}', flush=True)


if __name__ == '__main__':
    main()
