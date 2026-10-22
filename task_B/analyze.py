"""Final Task B: warning-threshold comparison using actual saved forecasts.

Inspired by workshop 05_xclim_heavy_rain.py and 06_forecast_vs_local_extremes.py.
Uses Task A thresholds and saved cumulative rainfall; no cloud download.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parent


# %% Read and validate retained input data and historical domain evidence
def main():
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'.matplotlib'))
    import numpy as np
    import pandas as pd
    import xarray as xr
    import xclim
    from plot_results import render

    inputs = ROOT/'inputs'
    config = json.loads((ROOT/'grid.json').read_text())
    source = json.loads((inputs/'source_run_metadata.json').read_text())
    thresholds = pd.read_csv(inputs/'thresholds.csv')
    annual = pd.read_csv(inputs/'annual_maxima.csv')
    towns = [town['name'] for town in config['towns']]
    init = pd.Timestamp('2025-07-16')
    with np.load(inputs/f'{init:%Y-%m-%d}.npz', allow_pickle=False) as cache:
        cumulative = cache['cumulative_m']
        hours, members = cache['lead_hours'], cache['members']
        domains = json.loads(str(cache['domains_json']))
        expected = hashlib.sha256(json.dumps(dict(towns=config['towns'], forecast=config['forecast']), sort_keys=True).encode()).hexdigest()
        if str(cache['fingerprint']) != expected:
            raise ValueError('Cached forecast source or town coordinates differ from grid.json')
    if len(towns) != 5 or len(set(towns)) != 5 or cumulative.shape != (len(towns), 51, 11):
        raise ValueError('Expected five distinct grid.json towns, 51 members and 11 cumulative endpoints')
    if len(np.unique(members)) != 51 or not np.array_equal(hours, np.arange(11)*24):
        raise ValueError('Expected unique member IDs and steps 0,24,...,240 hours')
    if not np.isfinite(cumulative).all():
        raise ValueError('Missing forecast data')
    if not pd.Timestamp(source['start']) <= init <= pd.Timestamp(source['end']):
        raise ValueError('Initialization is outside the recorded Task C extraction window')
    if config['forecast']['prefix'] != 'forecasts/ecmwf-ifs-ea-swio-realized-v3/49r1-jja2025':
        raise ValueError('Cumulative-metre convention is only documented for the workshop forecast store')
    if domains.get('status') != 'verified':
        raise ValueError('Require verified source-domain evidence in saved extraction')
    lookup = {t['name']: t for t in config['towns']}
    for key, expected_order in [('forecast', 'descending'), ('cmorph', 'ascending')]:
        evidence = domains[key]
        bounds = evidence['bounds']
        if evidence['latitude_order'] != expected_order:
            raise ValueError('Unexpected source latitude order')
        for name in towns:
            town = lookup[name]
            if not (bounds['south'] <= town['latitude'] <= bounds['north'] and
                    bounds['west'] <= town['longitude'] <= bounds['east']):
                raise ValueError(f'{name} outside recorded {key} domain')
            point = next(p for p in evidence['towns'] if p['town'] == name)
            if not point['inside']:
                raise ValueError('Source extraction recorded a town outside its domain')
    # %% Convert cumulative metres into mm accumulated in each 24-hour interval
    raw = np.diff(cumulative, axis=-1)*1000
    minimum_raw = float(raw.min())
    if minimum_raw < -.05:
        raise ValueError(f'Cumulative rainfall decreases by more than 0.05 mm: {minimum_raw}')
    negative_count = int((raw < 0).sum())
    daily = np.maximum(raw, 0)
    days = np.arange(1, 11)
    dates = init+pd.to_timedelta(days, unit='D')
    count_rows, rainfall_rows, heavy_rows, summaries, observation_rows, threshold_rows = [], [], [], [], [], []
    for ti, name in enumerate(towns):
        print(f'Counting daily exceedances and xclim heavy days: {name}...', flush=True)
        table = thresholds[(thresholds.town == name) & (thresholds.duration == '24hr')]
        settings = [('20mm', 20.)]
        cmorph_point = next(p for p in domains['cmorph']['towns'] if p['town'] == name)
        for period in [2, 10]:
            rows = table[table.return_period_years == period]
            if len(rows) != 1:
                raise ValueError(f'Missing or duplicate {period}-year threshold for {name}')
            row = rows.iloc[0]
            if row.units != 'mm in 24 h' or not np.isfinite(row.threshold_mm) or row.threshold_mm <= 0:
                raise ValueError('Invalid rainfall threshold or units')
            if not (np.isclose(row.latitude, lookup[name]['latitude']) and
                    np.isclose(row.longitude, lookup[name]['longitude']) and
                    np.isclose(row.grid_latitude, cmorph_point['selected_latitude']) and
                    np.isclose(row.grid_longitude, cmorph_point['selected_longitude'])):
                raise ValueError('Task A town or CMORPH pixel differs from recorded source')
            settings.append((f'{period}yr', float(row.threshold_mm)))
        pr = xr.DataArray(daily[ti], dims=('number', 'time'), coords={'number': members, 'time': dates},
            name='pr', attrs={'units': 'mm/day', 'standard_name': 'precipitation_flux'})
        # %% Strict daily counts and inclusive xclim wetdays on the ten-day window
        for label, depth in settings:
            counts = (daily[ti] > depth).sum(axis=0)
            heavy = xclim.indices.wetdays(pr, thresh=f'{depth:.15g} mm/day', freq='YS').sum('time').values
            direct = (daily[ti] >= depth).sum(axis=1)
            np.testing.assert_array_equal(heavy, direct)
            threshold_rows.append(dict(town=name, threshold=label, threshold_mm=depth, units='mm in 24 h'))
            for di, day in enumerate(days):
                count_rows.append(dict(town=name, initialization=str(init.date()), forecast_day=int(day),
                    valid_start=str(dates[di]-pd.Timedelta(days=1)), valid_end=str(dates[di]),
                    threshold=label, threshold_mm=depth, rainfall_units='mm in 24 h', members_above=int(counts[di]),
                    members=51, fraction_above=float(counts[di]/51)))
            for member, count in zip(members, heavy):
                heavy_rows.append(dict(town=name, member=int(member), threshold=label, threshold_mm=depth,
                    heavy_days_ge=int(count), available_forecast_days=10))
            summaries.append(dict(town=name, threshold=label, threshold_mm=depth,
                member_days_above=int(counts.sum()), total_member_days=510, fraction_above=float(counts.sum()/510),
                peak_daily_members=int(counts.max()), members_with_heavy_day_ge=int((heavy >= 1).sum()),
                mean_heavy_days_ge=float(heavy.mean()), equality_member_days=int((daily[ti] == depth).sum())))
        for mi, member in enumerate(members):
            for di, day in enumerate(days):
                rainfall_rows.append(dict(town=name, member=int(member), forecast_day=int(day),
                    valid_start=str(dates[di]-pd.Timedelta(days=1)), valid_end=str(dates[di]), rainfall_mm=float(daily[ti, mi, di])))
        obs = annual[(annual.town == name) & (annual.duration == '24hr')]
        if len(obs) != 27 or set(obs.year) != set(range(1998,2025)) or not np.isfinite(obs.annual_maximum_mm).all():
            raise ValueError('Expected all 27 observed annual maxima')
        t2 = settings[1][1]
        observation_rows.append(dict(town=name, threshold_2yr_mm=t2, observed_years=27,
            observed_annual_exceedances=int((obs.annual_maximum_mm > t2).sum())))

    # %% Tables and plots: every daily count visible, including zero counts
    counts = pd.DataFrame(count_rows)
    summary = pd.DataFrame(summaries)
    counts.to_csv(ROOT/'daily_member_counts.csv', index=False)
    counts.pivot(index=['town', 'forecast_day', 'valid_start', 'valid_end'], columns='threshold',
        values='members_above').reset_index().to_csv(ROOT/'daily_counts_short.csv', index=False)
    summary.to_csv(ROOT/'summary_counts.csv', index=False)
    pd.DataFrame(heavy_rows).to_csv(ROOT/'xclim_heavy_days.csv', index=False)
    pd.DataFrame(rainfall_rows).to_csv(ROOT/'daily_rainfall.csv', index=False)
    pd.DataFrame(threshold_rows).to_csv(ROOT/'thresholds_used.csv', index=False)
    pd.DataFrame(observation_rows).to_csv(ROOT/'annual_vs_daily_comparison.csv', index=False)
    render(ROOT)

    # %% Numerical report and provenance from this committed script
    report = ['# Task B: Which threshold should trigger a warning?', '',
        f'Forecast initialization: **{init:%Y-%m-%d}**. All **{len(towns)} grid.json towns**, **51 members**, **10 daily intervals**.',
        f'Day 1: {init:%d %b}–{dates[0]:%d %b}; day 10: {dates[-1]-pd.Timedelta(days=1):%d %b}–{dates[-1]:%d %b %Y}.', '',
        '## Units and thresholds', '',
        'Rainfall is a depth in **mm accumulated in 24 h**. For a full 24-hour interval this is numerically equivalent to mm/day.',
        'Daily depth = (cumulative tp at interval end − cumulative tp at interval start) × 1000, converting metres to millimetres.',
        'Plot counts are numbers of members, not rainfall depths. Two members means 2/51 = 3.92%; one means 1/51 = 1.96%.', '',
        '| Town | Fixed (mm in 24 h) | 2-year (mm in 24 h) | 10-year (mm in 24 h) |', '|---|---:|---:|---:|']
    for name in towns:
        t = {r['threshold']:r['threshold_mm'] for r in threshold_rows if r['town']==name}
        report.append(f'| {name} | {t["20mm"]:.2f} | {t["2yr"]:.2f} | {t["10yr"]:.2f} |')
    report += ['', 'The 2-year and 10-year depths come from the completed **task_A** published CMORPH thresholds, not its separate MLE refit.', '',
        '## Members strictly above the threshold each day', '',
        '| Town | Threshold | '+ ' | '.join(f'D{i}' for i in days)+' |', '|---|---|'+ '|'.join(['---:']*10)+'|']
    for name in towns:
        for label in ['20mm','2yr','10yr']:
            subset=counts[(counts.town==name)&(counts.threshold==label)].sort_values('forecast_day')
            report.append(f'| {name} | {label} | '+' | '.join(map(str,subset.members_above))+' |')
    report += ['', 'Each row above reports exact counts out of 51 members; zero means no member exceeds that threshold on that forecast day.', '',
        '## Xclim heavy-rain-day counts', '',
        '`xclim.indices.wetdays` counts days **>=** the threshold for each member during the ten-day forecast window. The daily comparison plots count **>**; equality is deliberately distinguished.',
        f'All {len(towns)*3*51} xclim counts ({len(towns)} towns × 3 thresholds × 51 members) were checked against a direct count.', '',
        '| Town | Threshold | Members with >=1 heavy day | Mean heavy days/member |', '|---|---|---:|---:|']
    for row in summary.itertuples():
        report.append(f'| {row.town} | {row.threshold} | {row.members_with_heavy_day_ge}/51 | {row.mean_heavy_days_ge:.3f} |')
    report += ['', 'Heavy-day means describe the ten-day forecast window, not annual totals. Members with at least one heavy day are counted once, even if they have several heavy days.', '',
        '## Extension: is an annual 2-year level fair for one daily warning?', '',
        'It is useful for screening unusually large rain, but cannot alone determine an operational daily warning. A fitted 2-year annual level has a 50% chance of at least one exceedance in a year, not a 50% chance each day.']
    for row in observation_rows:
        report.append(f'- {row["town"]}: {row["observed_annual_exceedances"]}/27 observed annual maxima exceed {row["threshold_2yr_mm"]:.2f} mm ({row["observed_annual_exceedances"]/27:.1%}).')
    report += ['', 'In this forecast, threshold sensitivity differs by town:']
    for name in towns:
        local = summary[summary.town == name].set_index('threshold')
        report.append(f'- {name}: fixed 20 mm gives **{int(local.loc["20mm", "member_days_above"])}/510** member-day exceedances '
            f'({local.loc["20mm", "fraction_above"]:.2%}); 2-year gives **{int(local.loc["2yr", "member_days_above"])}/510** '
            f'({local.loc["2yr", "fraction_above"]:.2%}); 10-year gives **{int(local.loc["10yr", "member_days_above"])}/510** '
            f'({local.loc["10yr", "fraction_above"]:.2%}).')
    report += [f'- Under an illustrative model with independent, identical days, daily p = 1 − 0.5^(1/365) = **{1-.5**(1/365):.3%}**. Rainfall is seasonal and dependent, so this is not a calibrated local daily probability.',
        '- These numbers show different sensitivity; ensemble member-days are correlated predictions and do not estimate observed climatological frequency.',
        '- Choosing a warning needs impact records, forecast verification, false-alarm/miss tradeoffs and an explicit probability decision rule.', '',
        '## Checks and limitations', '',
        '- All five towns lie inside the recorded forecast and CMORPH source domains. Forecast latitude descends; CMORPH latitude ascends.',
        '- Source-domain evidence was verified in the earlier connected extraction and retained in the cache. This final run validates that evidence without a fresh cloud query.',
        '- Task A coordinates and selected CMORPH pixels match that source-domain evidence.',
        '- All 51 members are finite at every cumulative endpoint; intervals are consecutive 24-hour periods.',
        f'- {negative_count} tiny negative daily differences were set to zero. Minimum raw difference: {minimum_raw:.6f} mm; tolerance: 0.05 mm. Larger decreases stop the analysis.',
        '- Repeated small increments are consistent with encoding noise, but that cause has not been independently established.',
        '- Forecast and CMORPH nearest pixels have different sizes and footprints; these are grid-cell comparisons, not rain-gauge measurements.',
        '- No observed 2025 event rainfall or impacts were supplied, so this exercise compares thresholds rather than proving warning skill.']
    (ROOT/'results.md').write_text('\n'.join(report)+'\n')
    revision = subprocess.run(['git','-C',str(ROOT),'rev-parse','HEAD'],capture_output=True,text=True)
    metadata = dict(run_utc=datetime.now(timezone.utc).isoformat(), initialization=str(init),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        plot_script_sha256=hashlib.sha256((ROOT/'plot_results.py').read_bytes()).hexdigest(),
        grid_sha256=hashlib.sha256((ROOT/'grid.json').read_bytes()).hexdigest(),
        git_commit=revision.stdout.strip() if revision.returncode==0 else None,
        input_hashes={name:hashlib.sha256((inputs/name).read_bytes()).hexdigest() for name in
            [f'{init:%Y-%m-%d}.npz','source_run_metadata.json','thresholds.csv','annual_maxima.csv']},
        domain_validation=domains, fresh_cloud_domain_check=False, domain_evidence='recorded verified extraction metadata',
        forecast=config['forecast'], threshold_source='published CMORPH levels from completed task_A',
        rainfall_units='mm in 24 h', source_cumulative_units='m', count_units='members',
        daily_operator='>', xclim_operator='>=', negative_totals_clipped=negative_count,
        minimum_raw_daily_mm=minimum_raw, negative_tolerance_mm=.05,
        towns=towns, checked_daily_counts=len(counts), checked_xclim_member_counts=len(heavy_rows),
        versions=dict(numpy=np.__version__,pandas=pd.__version__,xarray=xr.__version__,xclim=xclim.__version__))
    (ROOT/'run_metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(summary.to_string(index=False),flush=True)
    print(f'All {len(counts)} daily counts and {len(heavy_rows)} xclim counts validated.',flush=True)
    print(f'Task B complete. Figures, tables and results.md saved in {ROOT}',flush=True)


if __name__=='__main__':
    main()
