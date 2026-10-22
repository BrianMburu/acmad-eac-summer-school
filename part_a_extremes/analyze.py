"""Part A: observed CMORPH extremes, adapted from workshop exercise 04.

Run with Python >=3.12: python analyze.py [--other-duration 6hr]
All artifacts are written next to this script. No synthetic data are used.
"""
from pathlib import Path
import argparse
import json
import os

ROOT = Path(__file__).resolve().parent


# %% Open public CMORPH data and select only needed durations and points
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--other-duration', default='6hr')
    args = parser.parse_args()
    # Public anonymous store: avoid inherited AWS settings, as in exercise 04.
    for key in list(os.environ):
        if key.startswith('AWS_'):
            os.environ.pop(key)
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.matplotlib'))
    print('Loading scientific libraries and initializing Matplotlib...', flush=True)
    import icechunk
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import xarray as xr
    from scipy.stats import gumbel_r

    config = json.loads((ROOT / 'grid.json').read_text())
    ref = config['cmorph_reference']
    durations = ['24hr', args.other_duration]
    if len(set(durations)) != 2:
        raise ValueError('Choose a second duration different from 24hr')
    storage = icechunk.s3_storage(
        bucket=ref['bucket'], prefix=ref['prefix'], endpoint_url=ref['endpoint'],
        region='us-east-1', anonymous=True, from_env=False, force_path_style=True)
    print('Opening the public CMORPH cloud store...', flush=True)
    repo = icechunk.Repository.open(storage, config=icechunk.RepositoryConfig.default())
    ds = xr.open_zarr(repo.readonly_session('main').store, zarr_format=3,
                      consolidated=False, chunks={})
    if not np.all(np.diff(ds.lat.values) > 0):
        raise ValueError('Expected strictly ascending CMORPH latitude')
    for duration in durations:
        if duration not in ds.duration.values:
            raise ValueError(f'{duration} unavailable; choose from {ds.duration.values.tolist()}')
    periods = [2, 10, 50]
    towns = config['towns']
    for town in towns:
        for coord, field in [('lat', 'latitude'), ('lon', 'longitude')]:
            if not float(ds[coord].min()) <= town[field] <= float(ds[coord].max()):
                raise ValueError(f"{town['name']} outside CMORPH {coord} domain")
    # Vectorized point selection reads only the two durations and five locations.
    points = ds.sel(
        lat=xr.DataArray([t['latitude'] for t in towns], dims='town'),
        lon=xr.DataArray([t['longitude'] for t in towns], dims='town'), method='nearest')
    print('Downloading annual maxima for five towns (27 years, two durations)...', flush=True)
    maxima = points[ref['annual_maxima_variable']].sel(duration=durations).compute()
    print('Downloading stored return levels...', flush=True)
    levels = points[ref['variable']].sel(duration=durations, return_period=periods).compute()
    years = maxima.year.values.astype(int)
    if set(years) != set(range(1998, 2025)) or len(years) != 27:
        raise ValueError(f'Expected 27 annual maxima for 1998–2024; got {years}')
    annual_rows, threshold_rows, sensitivity_rows, notes = [], [], [], []
    for i, town in enumerate(towns):
        print(f"Creating plots for {town['name']}...", flush=True)
        fig, axes = plt.subplots(2, 2, figsize=(12, 9), squeeze=False)
        for j, duration in enumerate(durations):
            values = maxima.isel(town=i).sel(duration=duration).transpose('year').values
            stored = levels.isel(town=i).sel(duration=duration).transpose('return_period').values
            if not np.isfinite(values).all() or not np.isfinite(stored).all():
                raise ValueError(f"Missing data: {town['name']} {duration}")
            if (values < 0).any() or (np.diff(stored) < 0).any():
                raise ValueError('Negative rainfall or nonmonotonic return levels')
            loc, scale = gumbel_r.fit(values)
            if scale <= 0:
                raise ValueError('Degenerate annual maxima cannot support a Gumbel fit')
            largest = int(np.argmax(values))
            reduced = np.delete(values, largest)
            loc_minus, scale_minus = gumbel_r.fit(reduced)
            full50 = float(gumbel_r.ppf(.98, loc=loc, scale=scale))
            minus50 = float(gumbel_r.ppf(.98, loc=loc_minus, scale=scale_minus))
            sensitivity_rows.append(dict(town=town['name'], duration=duration,
                removed_year=int(years[largest]), removed_maximum_mm=float(values[largest]),
                stored_50yr_mm=float(stored[2]), mle_full_50yr_mm=full50,
                mle_without_largest_50yr_mm=minus50, change_mm=minus50-full50,
                change_percent=100*(minus50/full50-1)))
            for year, value in zip(years, values):
                annual_rows.append(dict(town=town['name'], duration=duration,
                    year=int(year), annual_maximum_mm=float(value)))
            for period, level in zip(periods, stored):
                exceeded = years[values > level].tolist()
                threshold_rows.append(dict(town=town['name'], latitude=town['latitude'],
                    longitude=town['longitude'], grid_latitude=float(points.lat[i]),
                    grid_longitude=float(points.lon[i]), duration=duration,
                    return_period_years=period, threshold_mm=float(level),
                    exceedance_count=len(exceeded), exceedance_years=';'.join(map(str, exceeded))))
            ax = axes[j, 0]
            ax.bar(years, values, color='steelblue')
            for period, level in zip(periods, stored):
                ax.axhline(level, ls='--', label=f'{period}-year: {level:.1f} mm')
            ax.set(title=f'{duration}: annual maxima', xlabel='Year', ylabel='Rainfall depth (mm)')
            ax.legend(fontsize=8)
            ax = axes[j, 1]
            rank = np.argsort(values)[::-1]
            empirical = (len(values)+1)/np.arange(1, len(values)+1)
            curve_t = np.geomspace(1.01, 100, 300)
            ax.semilogx(curve_t, gumbel_r.ppf(1-1/curve_t, loc=loc, scale=scale), label='Refit Gumbel (MLE)')
            ax.semilogx(periods, stored, 's--', label='Stored Gumbel levels')
            ax.semilogx(empirical, values[rank], 'k.', label='Observed (Weibull positions)')
            for index in rank[:3]:
                pos = int(np.where(rank == index)[0][0])
                ax.annotate(str(years[index]), (empirical[pos], values[index]), fontsize=8)
            ax.set(title=f'{duration}: return levels', xlabel='Return period (years)', ylabel='Rainfall depth (mm)')
            ax.legend(fontsize=8)
            ax.grid(alpha=.25, which='both')
            notes.append(f"{town['name']} {duration}: largest {values[largest]:.1f} mm in {years[largest]}; "
                         f"50-year MLE changes {full50:.1f} → {minus50:.1f} mm without that year.")
        fig.suptitle(f"{town['name']} — CMORPH annual maxima, 1998–2024")
        fig.tight_layout()
        fig.savefig(ROOT / (town['name'].lower().replace(' ', '_')+'_return_levels.png'), dpi=160)
        plt.close(fig)
    pd.DataFrame(annual_rows).to_csv(ROOT/'annual_maxima.csv', index=False)
    pd.DataFrame(threshold_rows).to_csv(ROOT/'thresholds.csv', index=False)
    pd.DataFrame(sensitivity_rows).to_csv(ROOT/'sensitivity.csv', index=False)
    # Regional bounds cover all town extents, plus a one-degree margin.
    west = min(t['extent']['west'] for t in towns)-1
    east = max(t['extent']['east'] for t in towns)+1
    south = min(t['extent']['south'] for t in towns)-1
    north = max(t['extent']['north'] for t in towns)+1
    print('Downloading the regional 10-year 24 h map...', flush=True)
    rp = ds[ref['variable']].sel(duration='24hr', return_period=10).sortby('lat').sortby('lon')
    rp = rp.sel(lat=slice(south, north), lon=slice(west, east)).compute()
    if not np.isfinite(rp.values).any():
        raise ValueError('Regional map contains no finite values')
    rp.to_netcdf(ROOT/'regional_10yr_24hr.nc')
    fig, ax = plt.subplots(figsize=(10, 6))
    image = ax.pcolormesh(rp.lon, rp.lat, rp, shading='auto', cmap='YlGnBu')
    fig.colorbar(image, ax=ax, label='24 h rainfall depth (mm)')
    for town in towns:
        ax.plot(town['longitude'], town['latitude'], 'r^')
        ax.annotate(town['name'], (town['longitude'], town['latitude']), xytext=(5, 5), textcoords='offset points')
    ax.set(title='CMORPH 10-year 24 h Gumbel level (1998–2024)', xlabel='Longitude', ylabel='Latitude', aspect='equal')
    fig.tight_layout()
    fig.savefig(ROOT/'regional_10yr_24hr.png', dpi=160)
    plt.close(fig)
    notes.extend(['', 'Thresholds use the published store; sensitivity refits both samples with scipy Gumbel maximum likelihood.',
        'The original store fitting estimator is not assumed to be MLE. Compare the two MLE fits for removal sensitivity.',
        'Exceedance years use strict >. Crossing a return level is not by itself evidence that a fit fails.',
        'The three largest years are annotated for visual diagnosis; no formal outlier claim is made.',
        'A 50-year return level extrapolates beyond the 27-year sample and is uncertain.',
        'These are annual maxima, not June–August 2025 totals. Nearest CMORPH pixels represent grid cells, not gauges.'])
    (ROOT/'results.txt').write_text('\n'.join(notes)+'\n')
    print('\n'.join(notes))


if __name__ == '__main__':
    main()
