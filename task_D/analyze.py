"""Final Task D: regional hazard maps with all five grid.json towns.

Inspired by workshop 08_exceedance_probability_map.py and 03_pan_vs_pencil.py.
Regenerate maps and frequency from actual retained probabilities, without downloads.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import subprocess
import time

ROOT = Path(__file__).resolve().parent


# %% Configuration, source signatures and recorded five-town domain checks
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probability',type=float,default=.2,help='Probability decision level; default 20%%')
    args=parser.parse_args()
    if not 0<args.probability<=1:
        raise ValueError('Probability decision must be in (0,1]')
    os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.matplotlib'))
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm
    from matplotlib.ticker import PercentFormatter,MaxNLocator
    from matplotlib.lines import Line2D

    config=json.loads((ROOT/'grid.json').read_text())
    source=json.loads((ROOT/'inputs/source_run_metadata.json').read_text())
    towns=config['towns']
    if len(towns)!=5 or len({t['name'] for t in towns})!=5:
        raise ValueError('Require five unique towns from grid.json')
    starts=pd.DatetimeIndex(source['starts'])
    n_days=int(source['forecast_days'])
    if len(starts)!=4 or len(set(starts))!=4 or n_days!=5:
        raise ValueError('Expected four seasonal starts and five daily leads')
    box=dict(west=min(t['extent']['west'] for t in towns)-1,
        east=max(t['extent']['east'] for t in towns)+1,
        south=min(t['extent']['south'] for t in towns)-1,
        north=max(t['extent']['north'] for t in towns)+1)
    metadata=source['source_metadata']
    if box!=metadata['box'] or metadata['threshold_units']!='mm in 24 h':
        raise ValueError('Cached region or threshold units differ from grid.json')
    signature=hashlib.sha256(json.dumps(dict(box=box,forecast=config['forecast'],
        cmorph=config['cmorph_reference'],days=n_days,towns=towns),sort_keys=True).encode()).hexdigest()
    metadata_path=ROOT/'inputs/cache'/f'metadata_{signature[:16]}.json'
    if json.loads(metadata_path.read_text())!=metadata:
        raise ValueError('Retained source signature/metadata does not match source run')
    for key,order in [('forecast','descending'),('cmorph','ascending')]:
        evidence=metadata['domains'][key]
        if evidence['latitude_order']!=order or evidence['status']!='verified from source coordinates':
            raise ValueError('Missing source-domain or latitude-order verification')
        bounds=evidence['bounds']
        if not (bounds['south']<=box['south']<box['north']<=bounds['north'] and
                bounds['west']<=box['west']<box['east']<=bounds['east']):
            raise ValueError('Region outside recorded source domain')
        for town in towns:
            if not (bounds['south']<=town['latitude']<=bounds['north'] and
                    bounds['west']<=town['longitude']<=bounds['east']):
                raise ValueError('Town outside recorded source domain')
            point=next(p for p in evidence['towns'] if p['town']==town['name'])
            if not point['inside']:
                raise ValueError('Town outside original extraction')

    # %% Saved probabilities: validate shape, coordinates and 51-member quantization
    input_hashes={}
    probabilities,timings=[],[]
    latitude=longitude=None
    for init in starts:
        path=ROOT/'inputs/cache'/f'{init:%Y-%m-%d}_{signature[:16]}.npz'
        t0=time.perf_counter()
        with np.load(path,allow_pickle=False) as cache:
            probability=cache['probability']
            lat,lon=cache['latitude'],cache['longitude']
            record=json.loads(str(cache['read_info']))
        seconds=time.perf_counter()-t0
        if probability.shape!=(5,len(lat),len(lon)) or not np.all(np.diff(lat)<0) or not np.all(np.diff(lon)>0):
            raise ValueError('Invalid cached regional shape or coordinate order')
        finite=np.isfinite(probability)
        if np.isinf(probability).any() or np.any(probability[finite]<0) or np.any(probability[finite]>1):
            raise ValueError('Invalid probabilities')
        if not np.allclose(probability[finite]*51,np.round(probability[finite]*51)):
            raise ValueError('Probabilities are not fractions of 51 members')
        if latitude is None:
            latitude,longitude=lat,lon
        elif not np.array_equal(latitude,lat) or not np.array_equal(longitude,lon):
            raise ValueError('Grid coordinates changed between starts')
        if pd.Timestamp(record['initialization'])!=init or record['estimated_storage_chunks']!=6:
            raise ValueError('Read record does not match original six-endpoint extraction')
        probabilities.append(probability)
        timings.append(dict(record,kind='original_cloud_forecast_read'))
        timings.append(dict(kind='current_local_probability_cache',initialization=str(init.date()),
            seconds=seconds,estimated_storage_chunks=0,negative_totals_clipped=0))
        input_hashes[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        print(f'Loaded {init:%Y-%m-%d}: five probability maps, {int(finite.sum())} available cells.',flush=True)
    if any(init<pd.Timestamp(config['start_date']) or init+pd.Timedelta(days=n_days)>
           pd.Timestamp(config['end_date'])+pd.Timedelta(days=1) for init in starts):
        raise ValueError('Valid intervals outside configured JJA season')
    cube=np.stack(probabilities)
    total=len(starts)*n_days
    available=np.isfinite(cube).sum(axis=(0,1))
    frequency=(cube>=args.probability).sum(axis=(0,1))
    fraction=np.divide(frequency,available,out=np.full(available.shape,np.nan),where=available>0)
    max_probability=float(np.nanmax(cube))
    color_max=min(1,max(args.probability,np.ceil(max_probability*20)/20))
    summary_rows,hotspots,town_rows=[],[],[]
    for si,init in enumerate(starts):
        for di in range(n_days):
            field=cube[si,di]
            summary_rows.append(dict(initialization=str(init.date()),forecast_day=di+1,
                valid_start=str(init+pd.Timedelta(days=di)),valid_end=str(init+pd.Timedelta(days=di+1)),
                available_grid_points=int(np.isfinite(field).sum()),grid_points_ge_probability=int((field>=args.probability).sum()),
                maximum_probability=float(np.nanmax(field)) if np.isfinite(field).any() else np.nan))
            for yi,xi in np.argwhere(field>=args.probability):
                hotspots.append(dict(initialization=str(init.date()),forecast_day=di+1,
                    valid_start=str(init+pd.Timedelta(days=di)),valid_end=str(init+pd.Timedelta(days=di+1)),
                    latitude=float(latitude[yi]),longitude=float(longitude[xi]),probability=float(field[yi,xi]),
                    members_above=int(round(field[yi,xi]*51))))
    for town in towns:
        yi,xi=int(np.argmin(abs(latitude-town['latitude']))),int(np.argmin(abs(longitude-town['longitude'])))
        point=next(p for p in metadata['domains']['forecast']['towns'] if p['town']==town['name'])
        if not (np.isclose(latitude[yi],point['selected_latitude']) and np.isclose(longitude[xi],point['selected_longitude'])):
            raise ValueError('Town forecast pixel differs from verified extraction')
        town_rows.append(dict(town=town['name'],town_latitude=town['latitude'],town_longitude=town['longitude'],
            grid_latitude=float(latitude[yi]),grid_longitude=float(longitude[xi]),
            exceedance_intervals=int(frequency[yi,xi]),available_intervals=int(available[yi,xi]),
            frequency_fraction=float(fraction[yi,xi]),maximum_probability=float(np.nanmax(cube[:,:,yi,xi]))))
    # %% Town-marked probability maps, with a shared data-sensitive scale
    cmap=plt.get_cmap('YlOrRd').copy(); cmap.set_bad('#bdbdbd')
    def mark(ax):
        for town in towns:
            ax.plot(town['longitude'],town['latitude'],'^',ms=6,color='black',markerfacecolor='white',zorder=4)
            ax.annotate(town['name'],(town['longitude'],town['latitude']),xytext=(4,4),textcoords='offset points',fontsize=8,zorder=5,
                bbox=dict(facecolor='white',edgecolor='none',alpha=.75,pad=1))
        ax.set(xlabel='Longitude',ylabel='Latitude',aspect='equal',xlim=(box['west'],box['east']),ylim=(box['south'],box['north']))
    for init,probability in zip(starts,probabilities):
        fig,axes=plt.subplots(2,3,figsize=(18,9),layout='constrained')
        for day,(ax,field) in enumerate(zip(axes.flat,probability),start=1):
            pm=ax.pcolormesh(longitude,latitude,np.ma.masked_invalid(field),cmap=cmap,vmin=0,vmax=color_max,shading='auto')
            if np.isfinite(field).any() and np.nanmin(field)<args.probability<np.nanmax(field):
                ax.contour(longitude,latitude,field,levels=[args.probability],colors='#174c87',linewidths=1.2)
            mark(ax)
            maximum=float(np.nanmax(field)) if np.isfinite(field).any() else np.nan
            ax.set_title(f'Day {day} | ending {init+pd.Timedelta(days=day):%d %b}\n'
                f'Maximum {maximum:.1%}; {int((field>=args.probability).sum())} pixels ≥{args.probability:.0%}')
        axes[1,2].axis('off')
        axes[1,2].legend(handles=[Line2D([0],[0],color='#174c87',label=f'{args.probability:.0%} probability contour'),
            Line2D([0],[0],marker='^',color='black',markerfacecolor='white',linestyle='',label='grid.json town')],loc='center',frameon=False,fontsize=12)
        cb=fig.colorbar(pm,ax=list(axes.flat)[:5],shrink=.8,label='Ensemble probability above local 2-year 24 h level')
        cb.ax.yaxis.set_major_formatter(PercentFormatter(1))
        fig.suptitle(f'Task D | forecast initialized {init:%Y-%m-%d} | 51 members\n'
            f'Shared probability scale 0–{color_max:.0%}; pale = zero, gray = missing. Rainfall thresholds: mm in 24 h.',fontsize=14)
        fig.savefig(ROOT/f'probabilities_{init:%Y-%m-%d}.png',dpi=170); plt.close(fig)
    # %% Frequency: sampled count, percentage and spatial denominator
    count_values=np.where(available>0,frequency,np.nan)
    count_max=max(1,int(frequency.max()))
    percent_max=max(.05,float(np.nanmax(fraction))) if np.isfinite(fraction).any() else 1
    norm=BoundaryNorm(np.arange(-.5,count_max+1.5),256)
    fig,axes=plt.subplots(1,3,figsize=(19,5),layout='constrained')
    for ax,field,title,opts,label in zip(axes,[count_values,fraction,available],
        [f'Count of intervals with probability ≥{args.probability:.0%}','Percentage of available sampled intervals','Available sampled intervals'],
        [{'norm':norm},{'vmin':0,'vmax':percent_max},{'vmin':0,'vmax':total}],
        ['Intervals','Percentage of available intervals','Available intervals']):
        pm=ax.pcolormesh(longitude,latitude,np.ma.masked_invalid(field),
            cmap=plt.get_cmap('Blues') if ax is axes[2] else cmap,shading='auto',**opts)
        mark(ax); ax.set_title(title)
        cb=fig.colorbar(pm,ax=ax,shrink=.75,label=label)
        if ax is axes[0]: cb.set_ticks(range(count_max+1))
        elif ax is axes[1]: cb.ax.yaxis.set_major_formatter(PercentFormatter(1))
        else: cb.ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    fig.suptitle(f'Task D | JJA 2025 sampled forecast frequency: {len(starts)} starts × {n_days} daily leads = {total} intervals\n'
        'This is seasonal sampling, not a full-season observed frequency or impact-risk map.',fontsize=14)
    fig.savefig(ROOT/'sampled_season_frequency.png',dpi=170); plt.close(fig)
    # %% Tables, timing interpretation and final provenance
    summary=pd.DataFrame(summary_rows); town_table=pd.DataFrame(town_rows)
    summary.to_csv(ROOT/'probability_summary.csv',index=False)
    town_table.to_csv(ROOT/'town_frequency.csv',index=False)
    pd.DataFrame(hotspots,columns=['initialization','forecast_day','valid_start','valid_end','latitude','longitude','probability','members_above']).to_csv(ROOT/'regional_hotspots.csv',index=False)
    timings.append(dict(kind='original_cmorph_threshold_read',initialization='',seconds=metadata['threshold_read_seconds'],
        estimated_storage_chunks=metadata['threshold_estimated_storage_chunks'],negative_totals_clipped=0))
    timings.append(dict(kind='original_source_metadata_open',initialization='',seconds=metadata['metadata_open_seconds'],
        estimated_storage_chunks=np.nan,negative_totals_clipped=0))
    pd.DataFrame(timings).to_csv(ROOT/'read_timings.csv',index=False)
    np.savez_compressed(ROOT/'regional_probability_results.npz',probability=cube,starts=np.asarray(starts.astype(str),dtype=str),
        latitude=latitude,longitude=longitude,forecast_days=np.arange(1,n_days+1),frequency=frequency,available=available,fraction=fraction)
    minimum_members=int(np.ceil(args.probability*51))
    hot_pixels=int((frequency>0).sum())
    report=['# Task D: Where is the risk?','',
        'All five town markers and the regional bounds come from this folder’s **grid.json**.',
        f'Starts: **{", ".join(d.strftime("%d %B %Y") for d in starts)}**, days 1–5: **{total} sampled forecast intervals**.',
        f'Probability decision: **≥{args.probability:.0%}**, requiring **≥{minimum_members}/51 members** ({minimum_members/51:.2%}).','',
        '## Regional results','',
        f'- **{hot_pixels} regional grid points** reach the decision level at least once.',
        f'- Maximum regional probability: **{max_probability:.2%}**, equivalent to **{round(max_probability*51)}/51 members**.',
        f'- Maximum frequency: **{int(frequency.max())} of {total} sampled intervals**; largest available-interval percentage **{np.nanmax(fraction):.1%}**.','',
        'Intervals containing any grid point above the probability decision:', '',
        '| Start | Lead day | Interval ends | Grid points meeting criterion | Maximum probability |', '|---|---:|---|---:|---:|']
    for row in summary[summary.grid_points_ge_probability>0].itertuples():
        report.append(f'| {row.initialization} | {row.forecast_day} | {row.valid_end} | {row.grid_points_ge_probability} | {row.maximum_probability:.2%} |')
    if not (summary.grid_points_ge_probability>0).any(): report.append('| None | — | — | 0 | — |')
    report+=['','The exact hotspot coordinates, probabilities and member counts are listed in `regional_hotspots.csv`.','',
        '## Five-town results','',
        '| Town | Intervals meeting criterion | Available intervals | Frequency | Highest probability |', '|---|---:|---:|---:|---:|']
    for row in town_table.itertuples():
        report.append(f'| {row.town} | {row.exceedance_intervals} | {row.available_intervals} | {row.frequency_fraction:.1%} | {row.maximum_probability:.2%} |')
    report+=['','A town’s zero count does not imply the entire region is zero. Each town is evaluated at its nearest forecast pixel. The regional threshold at each forecast pixel is the nearest CMORPH pixel’s local 2-year level, not one threshold applied to every location.',
        'That matching can select a different CMORPH cell from the direct town-coordinate selection used in Tasks A–C. Grid resolution and footprints differ; this is not area-conservative regridding.','',
        '## Units and denominator','',
        '- Rainfall threshold: **mm accumulated in 24 h**. Original daily rainfall is the difference of consecutive cumulative tp endpoints in metres, multiplied by 1000.',
        '- Probability: fraction of 51 members with rainfall **strictly >** the local 2-year 24 h threshold.',
        f'- Decision: probability **≥{args.probability:.0%}**; for a 20% decision, 10/51=19.61% fails while 11/51=21.57% passes.',
        '- Frequency count: sampled forecast intervals meeting that probability decision. Percentage denominator: available intervals at each grid point.',
        '- Missing thresholds or any missing member endpoint mask a cell. Missing data are not interpreted as zero probability.',
        '- The default dates yield nonoverlapping daily intervals. These 20 samples are not the full June–August season and do not estimate observed seasonal occurrence rates.',
        '- Previous extraction recorded and clipped small negative differences up to 0.05 mm; its correction counts are retained in read timings. Cached probabilities do not permit an independent reconstruction of the original raw rainfall.','',
        '## E3 extension: measured reads and chunk layout','',
        '| Original forecast start | Read + decode + compute (s) | Storage chunks |', '|---|---:|---:|']
    original=[r for r in timings if r['kind']=='original_cloud_forecast_read']
    for row in original:
        report.append(f'| {row["initialization"]} | {row["seconds"]:.2f} | {row["estimated_storage_chunks"]} |')
    report+=['',f'CMORPH threshold read: **{metadata["threshold_read_seconds"]:.2f} s**, **{metadata["threshold_estimated_storage_chunks"]} storage chunk**. Initial metadata open: **{metadata["metadata_open_seconds"]:.2f} s**.',
        f'Forecast dimensions: `{metadata["forecast_dims"]}`; chunk shape: `{metadata["forecast_chunks"]}`.',
        f'CMORPH threshold dimensions: `{metadata["threshold_dims"]}`; chunk shape: `{metadata["threshold_chunks"]}`.',
        'The forecast pan chunk contains one initialization, one lead time, all 51 members and the whole 321×261 spatial map. A regional map therefore reuses many values in one chunk; a point can require fetching that same chunk.',
        'Five daily maps need six cumulative endpoints (0,24,...,120 h), hence six chunks per start and 24 across four starts, plus threshold and metadata reads. Only daily endpoints were selected before original compute.',
        'A pencil layout concentrates time for a small spatial patch: efficient for point time series, but a regional map touches many spatial chunks.',
        'Times depend on connection, compression and cache. Stored chunk counts are not exact HTTP request counts. `read_timings.csv` distinguishes original cloud records from this run’s local cache timings.','',
        '## Validation and interpretation limits','',
        '- All five grid.json towns and the entire requested region lie inside both recorded source domains.',
        '- Forecast latitude descends; CMORPH latitude ascends. Current cached coordinates and source-domain evidence are rechecked offline, not freshly queried.',
        '- Source/grid signatures match; all cached probabilities are in [0,1] and quantized to fractions of 51 members.',
        '- Frequency and availability were recomputed from the saved probabilities. Source rainfall was not downloaded or recomputed.',
        '- Probabilities represent a rainfall-hazard indicator. No observed impacts or 2025 rainfall verification are supplied, so this is not a calibrated impact-risk or forecast-skill assessment.']
    (ROOT/'results.md').write_text('\n'.join(report)+'\n')
    input_hashes['inputs/source_run_metadata.json']=hashlib.sha256((ROOT/'inputs/source_run_metadata.json').read_bytes()).hexdigest()
    input_hashes[str(metadata_path.relative_to(ROOT))]=hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    revision=subprocess.run(['git','-C',str(ROOT),'rev-parse','HEAD'],capture_output=True,text=True)
    (ROOT/'run_metadata.json').write_text(json.dumps(dict(run_utc=datetime.now(timezone.utc).isoformat(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        grid_json_sha256=hashlib.sha256((ROOT/'grid.json').read_bytes()).hexdigest(),
        git_commit=revision.stdout.strip() if revision.returncode==0 else None,input_hashes=input_hashes,
        source_metadata=metadata,towns=towns,source_signature=signature,starts=starts.astype(str).tolist(),
        forecast_days=n_days,total_sample_intervals=total,probability_decision=args.probability,
        minimum_members=minimum_members,probability_plot_scale_max=color_max,
        rainfall_threshold_units='mm in 24 h',fresh_cloud_domain_check=False,execution='offline regeneration from retained actual probabilities',
        versions=dict(numpy=np.__version__,pandas=pd.__version__,matplotlib=matplotlib.__version__)),indent=2)+'\n')
    print(town_table.to_string(index=False),flush=True)
    print(f'Regional pixels meeting {args.probability:.0%}: {hot_pixels}; peak probability {max_probability:.2%}.',flush=True)
    print(f'Task D complete. Figures, tables and results.md saved in {ROOT}',flush=True)


if __name__=='__main__':
    main()
