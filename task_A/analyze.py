"""Task A: observed rainfall extremes from actual saved CMORPH extractions.

Inspired by python-workshop/exercises/04_cmorph_return_periods.py.
No cloud access is required. Inputs are retained under task_A/inputs.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parent


# %% Validate the saved observations and published return levels
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, default=ROOT/'inputs')
    args = parser.parse_args()
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'.matplotlib'))
    import numpy as np
    import pandas as pd
    import xarray as xr
    from scipy.stats import gumbel_r
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    config = json.loads((ROOT/'grid.json').read_text())
    towns = config['towns']
    durations, periods = ['24hr', '6hr'], np.array([2, 10, 50])
    annual = pd.read_csv(args.inputs/'annual_maxima.csv')
    published = pd.read_csv(args.inputs/'thresholds.csv')
    if annual.duplicated(['town', 'duration', 'year']).any():
        raise ValueError('Duplicate annual maxima')
    if published.duplicated(['town', 'duration', 'return_period_years']).any():
        raise ValueError('Duplicate return levels')
    if len(annual) != 270 or len(published) != 30:
        raise ValueError('Expected 270 maxima and 30 thresholds')
    threshold_rows, diagnostic_rows, summary_rows, sensitivity_rows, parameter_rows = [], [], [], [], []
    colors = ['#777777', '#df8b16', '#ba3141']
    for town in towns:
        name = town['name']
        print(f'Analyzing and plotting {name}...', flush=True)
        fig, axes = plt.subplots(2, 2, figsize=(13, 9), layout='constrained')
        for j, duration in enumerate(durations):
            obs = annual[(annual.town == name) & (annual.duration == duration)].sort_values('year')
            levels = published[(published.town == name) & (published.duration == duration)].sort_values('return_period_years')
            if len(obs) != 27 or set(obs.year) != set(range(1998, 2025)):
                raise ValueError(f'{name} {duration}: require each year 1998–2024 exactly once')
            if not np.array_equal(levels.return_period_years.values, periods):
                raise ValueError('Missing return periods')
            values, years = obs.annual_maximum_mm.values, obs.year.values
            stored = levels.threshold_mm.values
            if not np.isfinite(values).all() or not np.isfinite(stored).all() or (values < 0).any() or (np.diff(stored) <= 0).any():
                raise ValueError(f'Invalid observations or thresholds for {name} {duration}')
            if not (np.allclose(levels.latitude, town['latitude']) and np.allclose(levels.longitude, town['longitude'])):
                raise ValueError('Town coordinates differ from extraction')
            # Published Gumbel z(T) = location + scale * reduced_variate(T).
            # Recover its curve from the supplied levels; this does not infer its fitting estimator.
            reduced_variate = -np.log(-np.log(1-1/periods))
            stored_scale, stored_loc = np.polyfit(reduced_variate, stored, 1)
            reconstruction_error = float(abs(stored_loc+stored_scale*reduced_variate-stored).max())
            if stored_scale <= 0 or reconstruction_error > .001:
                raise ValueError('Published levels do not define a consistent Gumbel curve')
            mle_loc, mle_scale = gumbel_r.fit(values)
            if mle_scale <= 0:
                raise ValueError('Degenerate annual maxima')
            parameter_rows.append(dict(town=name, duration=duration, published_location_mm=stored_loc,
                published_scale_mm=stored_scale, reconstruction_max_error_mm=reconstruction_error,
                mle_location_mm=mle_loc, mle_scale_mm=mle_scale))
            rank = np.argsort(-values, kind='stable')
            empirical_t = 28/np.arange(1, 28)
            fitted_at_rank = gumbel_r.ppf(1-1/empirical_t, loc=stored_loc, scale=stored_scale)
            residual = values[rank]-fitted_at_rank
            tail = np.flatnonzero(empirical_t >= 5)
            worst = int(tail[np.argmax(abs(residual[tail]))])
            largest = int(rank[0])
            for k, source_index in enumerate(rank):
                diagnostic_rows.append(dict(town=name, duration=duration, year=int(years[source_index]),
                    rank_descending=k+1, observed_mm=float(values[source_index]), empirical_return_period_years=float(empirical_t[k]),
                    published_curve_at_plotting_position_mm=float(fitted_at_rank[k]),
                    observed_minus_published_mm=float(residual[k]), upper_tail=bool(empirical_t[k] >= 5),
                    largest_absolute_upper_tail_departure=bool(k == worst)))
            summary_rows.append(dict(town=name, duration=duration, largest_year=int(years[largest]),
                largest_mm=float(values[largest]), largest_minus_published_50yr_mm=float(values[largest]-stored[2]),
                tail_departure_year=int(years[rank[worst]]), tail_observed_mm=float(values[rank[worst]]),
                tail_curve_mm=float(fitted_at_rank[worst]), tail_residual_mm=float(residual[worst]),
                tail_empirical_return_period_years=float(empirical_t[worst])))
            for period, depth in zip(periods, stored):
                hit_years = years[values > depth]
                source_row = levels[levels.return_period_years == period].iloc[0]
                threshold_rows.append(dict(town=name, latitude=town['latitude'], longitude=town['longitude'],
                    grid_latitude=float(source_row.grid_latitude), grid_longitude=float(source_row.grid_longitude),
                    duration=duration, units=f'mm in {duration.replace("hr", " h")}', return_period_years=int(period),
                    threshold_mm=float(depth), exceedance_count=len(hit_years), exceedance_years=';'.join(map(str, hit_years))))
            without_loc, without_scale = gumbel_r.fit(np.delete(values, largest))
            full50 = float(gumbel_r.ppf(.98, loc=mle_loc, scale=mle_scale))
            without50 = float(gumbel_r.ppf(.98, loc=without_loc, scale=without_scale))
            sensitivity_rows.append(dict(town=name, duration=duration, removed_year=int(years[largest]),
                removed_maximum_mm=float(values[largest]), published_50yr_mm=float(stored[2]),
                mle_full_50yr_mm=full50, mle_without_largest_50yr_mm=without50,
                change_mm=without50-full50, change_percent=100*(without50/full50-1)))
            # %% Town plots: annual series and published Gumbel versus observed plotting positions
            label = duration.replace('hr', ' h')
            ax = axes[j, 0]
            ax.bar(years, values, color='#4b86ac')
            for period, depth, color in zip(periods, stored, colors):
                ax.axhline(depth, color=color, ls='--', label=f'{period}-year: {depth:.1f} mm')
            ax.annotate(f'{years[largest]}: {values[largest]:.1f} mm', (years[largest], values[largest]),
                xytext=(0, 6), textcoords='offset points', ha='center', fontsize=8)
            ax.set(title=f'{label} annual maxima', xlabel='Year', ylabel=f'Rainfall depth (mm in {label})')
            ax.margins(y=.2)
            ax.legend(fontsize=8)
            ax.grid(axis='y', alpha=.2)
            ax = axes[j, 1]
            curve_t = np.geomspace(1.05, 100, 300)
            ax.axvspan(27, 100, color='#cccccc', alpha=.22, label='Beyond 27-year record')
            ax.semilogx(curve_t, gumbel_r.ppf(1-1/curve_t, loc=stored_loc, scale=stored_scale),
                        color='#ba3141', label='Published Gumbel curve')
            ax.semilogx(periods, stored, 's', color='#ba3141', ms=5)
            ax.semilogx(curve_t, gumbel_r.ppf(1-1/curve_t, loc=mle_loc, scale=mle_scale),
                        '--', color='#df8b16', label='Independent MLE refit')
            ax.semilogx(empirical_t, values[rank], 'o', color='#1b3445', ms=4, label='Observed (Weibull positions)')
            for k in sorted(set([0, worst])):
                ax.annotate(str(years[rank[k]]), (empirical_t[k], values[rank[k]]), xytext=(4, 5),
                            textcoords='offset points', fontsize=8)
            ax.set(xlabel='Return period (years, logarithmic scale)', ylabel=f'Rainfall depth (mm in {label})',
                   title=f'{label}: observed versus fitted return levels', xlim=(1.05, 100))
            ax.grid(alpha=.2, which='both')
            ax.legend(fontsize=7, loc='upper left')
        fig.suptitle(f'{name} | CMORPH annual maxima, 1998–2024\n27 years; published thresholds and separate MLE refit', fontsize=14)
        fig.savefig(ROOT/f'{name.lower().replace(" ", "_")}_return_levels.png', dpi=170)
        plt.close(fig)

    # %% Regional 10-year 24 h map, using actual cached CMORPH values
    with xr.open_dataarray(args.inputs/'regional_10yr_24hr.nc') as data:
        region = data.load()
    if not np.all(np.diff(region.lat.values) > 0) or not np.isfinite(region.values).any():
        raise ValueError('Invalid cached map or nonascending latitude')
    for town in towns:
        if not (float(region.lat.min()) <= town['latitude'] <= float(region.lat.max()) and
                float(region.lon.min()) <= town['longitude'] <= float(region.lon.max())):
            raise ValueError('Town outside cached CMORPH region')
        row = published[(published.town == town['name']) & (published.duration == '24hr') & (published.return_period_years == 10)].iloc[0]
        map_depth = float(region.sel(lat=row.grid_latitude, lon=row.grid_longitude, method='nearest'))
        if not np.isclose(map_depth, row.threshold_mm, rtol=1e-5):
            raise ValueError('Regional map and town 10-year threshold disagree')
    fig, ax = plt.subplots(figsize=(11, 6), layout='constrained')
    cmap = plt.get_cmap('YlGnBu').copy()
    cmap.set_bad('#cccccc')
    pm = ax.pcolormesh(region.lon, region.lat, region, shading='auto', cmap=cmap)
    fig.colorbar(pm, ax=ax, label='10-year rainfall depth (mm in 24 h)')
    for town in towns:
        ax.plot(town['longitude'], town['latitude'], '^', color='black', markerfacecolor='white', ms=7)
        ax.annotate(town['name'], (town['longitude'], town['latitude']), xytext=(5, 6), textcoords='offset points')
    ax.set(title='Task A | CMORPH 10-year 24 h Gumbel level\nReference period: 1998–2024',
           xlabel='Longitude', ylabel='Latitude', aspect='equal')
    fig.savefig(ROOT/'regional_10yr_24hr.png', dpi=170)
    plt.close(fig)
    region.to_netcdf(ROOT/'regional_10yr_24hr.nc')

    # %% Tables, numerical interpretation and provenance
    thresholds_out = pd.DataFrame(threshold_rows)
    diagnostics = pd.DataFrame(diagnostic_rows)
    summary = pd.DataFrame(summary_rows)
    sensitivity = pd.DataFrame(sensitivity_rows)
    annual.to_csv(ROOT/'annual_maxima.csv', index=False)
    thresholds_out.to_csv(ROOT/'thresholds.csv', index=False)
    diagnostics.to_csv(ROOT/'fit_diagnostics.csv', index=False)
    summary.to_csv(ROOT/'observed_vs_fit_summary.csv', index=False)
    sensitivity.to_csv(ROOT/'sensitivity.csv', index=False)
    pd.DataFrame(parameter_rows).to_csv(ROOT/'gumbel_parameters.csv', index=False)
    compact = thresholds_out.pivot(index=['town', 'duration'], columns='return_period_years', values='threshold_mm').reset_index()
    compact.columns = ['town', 'duration', '2_year_mm', '10_year_mm', '50_year_mm']
    compact.to_csv(ROOT/'thresholds_short.csv', index=False)
    report = ['# Task A: How extreme is extreme?', '',
        'Five Sudan towns; CMORPH annual maxima for 1998–2024 (27 years), at 24 h and 6 h.',
        'All results use saved observations, not simulated data. Rainfall depths are mm accumulated over the stated duration.', '',
        '## Published thresholds', '', '| Town | Duration | 2-year (mm) | 10-year (mm) | 50-year (mm) |', '|---|---|---:|---:|---:|']
    for row in compact.itertuples(index=False, name=None):
        report.append(f'| {row[0]} | {row[1]} | {row[2]:.2f} | {row[3]:.2f} | {row[4]:.2f} |')
    report += ['', '## Observed maxima versus the published fit', '',
        'For each ranked observation, the empirical return period is (27+1)/rank. We compare its depth with the published Gumbel curve at that plotting position.',
        'The highlighted upper-tail departure is the largest absolute depth difference among empirical return periods >=5 years. This is a descriptive comparison, not an outlier or goodness-of-fit test.',
        'The published curve is reconstructed from the 2-, 10-, and 50-year levels; all three must agree to within 0.001 mm. Its original fitting estimator is not inferred.', '']
    for row in summary.itertuples():
        level = thresholds_out[(thresholds_out.town == row.town) & (thresholds_out.duration == row.duration) & (thresholds_out.return_period_years == 50)].iloc[0]
        report.append(f'- **{row.town}, {row.duration}:** maximum {row.largest_mm:.2f} mm in {row.largest_year}; '
            f'published 50-year level {level.threshold_mm:.2f} mm. Largest absolute upper-tail departure: '
            f'{row.tail_departure_year}, observed {row.tail_observed_mm:.2f} mm versus curve {row.tail_curve_mm:.2f} mm '
            f'at empirical T={row.tail_empirical_return_period_years:.2f} years (observed minus curve {row.tail_residual_mm:+.2f} mm).')
    report += ['', '## Years exceeding published thresholds', '',
        'Exceedance uses strict >. A threshold crossing is expected occasionally and does not itself mean that a model fails.', '']
    for row in thresholds_out.itertuples():
        report.append(f'- {row.town} {row.duration}, {row.return_period_years}-year level: {row.exceedance_count}/27 years; {row.exceedance_years or "none"}.')
    report += ['', '## Remove the single largest year', '',
        'Both samples are independently fitted with SciPy Gumbel maximum likelihood. Changes compare full-sample MLE with reduced-sample MLE, not published thresholds with an unrelated estimator.', '',
        '| Town | Duration | Removed year | Full MLE 50-year (mm) | Without largest (mm) | Change |', '|---|---|---:|---:|---:|---:|']
    for row in sensitivity.itertuples():
        report.append(f'| {row.town} | {row.duration} | {row.removed_year} | {row.mle_full_50yr_mm:.2f} | {row.mle_without_largest_50yr_mm:.2f} | {row.change_percent:+.2f}% |')
    report += ['', '## Limits and checks', '',
        '- Each town/duration has exactly one finite, nonnegative maximum for every year 1998–2024.',
        '- Regional-map 10-year values agree with the town threshold table at the selected CMORPH pixels.',
        '- Latitude ascends in the cached CMORPH map. The town coordinates lie within its bounds.',
        '- These are annual extremes, not June–August totals or observed 2025 events.',
        '- The 50-year level extrapolates beyond a 27-year sample; no confidence interval is estimated here.',
        '- Nearest satellite grid pixels represent areas, not town rain gauges.',
        '- Observed plotting positions are uncertain; the departure ranking does not prove that particular years break the fit.',
        '- The removal extension isolates sensitivity to one large observation; it is not a complete uncertainty assessment.']
    (ROOT/'results.md').write_text('\n'.join(report)+'\n')
    revision = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    input_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.inputs.iterdir() if p.is_file()}
    domain_evidence = ROOT.parent/'part_c_forecast_signals/run_metadata.json'
    historical_domain = None
    if domain_evidence.exists():
        historical_domain = json.loads(domain_evidence.read_text()).get('domain_validation', {}).get('cmorph')
    metadata = dict(script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        grid_json_sha256=hashlib.sha256((ROOT/'grid.json').read_bytes()).hexdigest(),
        git_commit=revision.stdout.strip() if revision.returncode == 0 else None,
        inputs=input_hashes, source=config['cmorph_reference'], execution='offline from saved actual CMORPH extraction',
        historical_source_domain_evidence=historical_domain, fresh_cloud_domain_check=False,
        cached_map_latitude_order='ascending', historical_domain_evidence_file=str(domain_evidence) if historical_domain else None,
        tail_diagnostic='largest absolute published-curve residual among empirical return periods >=5 years',
        years=list(range(1998,2025)), durations=durations, versions=dict(numpy=np.__version__, pandas=pd.__version__, xarray=xr.__version__))
    (ROOT/'run_metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(compact.round(2).to_string(index=False), flush=True)
    print('Validated 270 maxima, 30 thresholds and five map-point comparisons.', flush=True)
    print(f'Task A complete. Figures, tables and results.md saved in {ROOT}', flush=True)


if __name__ == '__main__':
    main()
