"""Final Task C: five grid.json towns, 21 starts, daily exceedance signals.

Inspired by workshop 06_forecast_vs_local_extremes.py. Uses retained actual
CMORPH thresholds and daily-endpoint forecast extractions; no cloud download.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parent


def streak_details(group, minimum):
    """Return the longest consecutive initialization run for ONE target interval."""
    import pandas as pd
    best, current = (0, '', ''), []
    for row in group.sort_values('initialization').itertuples():
        date = pd.Timestamp(row.initialization)
        if row.members_above >= minimum:
            if current and date-current[-1] != pd.Timedelta(days=1):
                current = []
            current.append(date)
            if len(current) > best[0]:
                best = (len(current), str(current[0].date()), str(current[-1].date()))
        else:
            current = []
    return best


def event_metrics(counts, minimum):
    """Keep valid dates explicit; do not combine signals for different target days."""
    rows = []
    for (name, end), group in counts.groupby(['town', 'valid_end'], sort=False):
        hits = group[group.members_above >= minimum]
        length, first, last = streak_details(group, minimum)
        earliest = hits.sort_values(['forecast_day', 'initialization'], ascending=[False, True]).iloc[0] if len(hits) else None
        rows.append(dict(town=name, minimum_members=minimum, valid_start=group.valid_start.iloc[0], valid_end=end,
            available_starts=int(group.available.sum()), signal_starts=len(hits),
            earliest_lead_days=int(earliest.forecast_day) if earliest is not None else 0,
            first_start_for_earliest_lead=earliest.initialization if earliest is not None else '',
            longest_consecutive_signal_starts=length, streak_first_start=first, streak_last_start=last))
    return rows


# %% Load five towns and validate saved forecast/source fingerprints
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2025-07-06')
    parser.add_argument('--end', default='2025-07-26')
    args = parser.parse_args()
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'.matplotlib'))
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm

    config = json.loads((ROOT/'grid.json').read_text())
    towns = config['towns']
    names = [t['name'] for t in towns]
    if len(names) != 5 or len(set(names)) != 5:
        raise ValueError('Require five unique towns from grid.json')
    dates = pd.date_range(args.start, args.end, freq='D')
    if not 14 <= len(dates) <= 21:
        raise ValueError('Choose an inclusive window of 14–21 starts')
    thresholds_table = pd.read_csv(ROOT/'inputs/thresholds.csv')
    thresholds = []
    for town in towns:
        rows = thresholds_table[(thresholds_table.town == town['name']) &
            (thresholds_table.duration == '24hr') & (thresholds_table.return_period_years == 2)]
        if len(rows) != 1:
            raise ValueError('Missing or duplicate Task A threshold')
        row = rows.iloc[0]
        if row.units != 'mm in 24 h' or not np.isfinite(row.threshold_mm) or row.threshold_mm <= 0:
            raise ValueError('Invalid threshold units or depth')
        if not (np.isclose(row.latitude, town['latitude']) and np.isclose(row.longitude, town['longitude'])):
            raise ValueError('Threshold town coordinates do not match grid.json')
        thresholds.append(float(row.threshold_mm))
    expected = hashlib.sha256(json.dumps(dict(towns=towns, forecast=config['forecast']), sort_keys=True).encode()).hexdigest()
    cubes, daily_values, qc, input_hashes, domain_records = [], [], [], {}, []
    days = np.arange(1,11)
    member_ids = None
    if config['forecast']['prefix'] != 'forecasts/ecmwf-ifs-ea-swio-realized-v3/49r1-jja2025':
        raise ValueError('Cumulative-metre convention is documented only for this workshop store')
    # %% Cached files contain only steps 0,24,...,240 h, selected before original compute
    for index, init in enumerate(dates):
        path = ROOT/'inputs/cache'/f'{init:%Y-%m-%d}.npz'
        print(f'[{index+1}/{len(dates)}] Reading saved daily endpoints: {init:%Y-%m-%d}', flush=True)
        with np.load(path, allow_pickle=False) as cache:
            if str(cache['fingerprint']) != expected:
                raise ValueError('Cached forecast source or ordered town list differs from grid.json')
            cumulative = cache['cumulative_m']
            hours, ids = cache['lead_hours'], cache['members']
            domains = json.loads(str(cache['domains_json']))
        if cumulative.shape != (5,51,11) or len(np.unique(ids)) != 51 or not np.array_equal(hours,np.arange(11)*24):
            raise ValueError('Expected five towns, 51 unique members and daily cumulative endpoints')
        if member_ids is None:
            member_ids = ids
        elif not np.array_equal(member_ids,ids):
            raise ValueError('Member coordinates changed between starts')
        if domains.get('status') != 'verified':
            raise ValueError('Source-domain evidence must be verified')
        for key, order in [('forecast','descending'),('cmorph','ascending')]:
            evidence = domains[key]
            if evidence['latitude_order'] != order:
                raise ValueError('Unexpected source latitude order')
            bounds = evidence['bounds']
            for town in towns:
                if not (bounds['south'] <= town['latitude'] <= bounds['north'] and
                        bounds['west'] <= town['longitude'] <= bounds['east']):
                    raise ValueError('Town outside recorded source domain')
                point = next(p for p in evidence['towns'] if p['town'] == town['name'])
                if not point['inside']:
                    raise ValueError('Town outside recorded source domain')
                if key == 'cmorph':
                    row = thresholds_table[(thresholds_table.town==town['name']) &
                        (thresholds_table.duration=='24hr') & (thresholds_table.return_period_years==2)].iloc[0]
                    if not (np.isclose(row.grid_latitude,point['selected_latitude']) and
                            np.isclose(row.grid_longitude,point['selected_longitude'])):
                        raise ValueError('Task A and forecast extraction use different CMORPH reference pixels')
        raw = np.diff(cumulative,axis=-1)*1000
        if np.isinf(cumulative).any() or np.any(raw < -.05):
            raise ValueError('Infinite rainfall or cumulative decrease larger than 0.05 mm')
        valid = np.isfinite(cumulative[...,:-1]).all(axis=1) & np.isfinite(cumulative[...,1:]).all(axis=1)
        ends = init+pd.to_timedelta(days,unit='D')
        valid &= np.asarray((ends <= pd.Timestamp(config['end_date'])+pd.Timedelta(days=1)) &
            (init >= pd.Timestamp(config['start_date'])))[None,:]
        daily = np.where(valid[:,None,:],np.maximum(raw,0),np.nan)
        counts = (daily > np.asarray(thresholds)[:,None,None]).sum(axis=1).astype(float)
        counts[~valid]=np.nan
        cubes.append(counts)
        daily_values.append(daily)
        qc.append(dict(initialization=str(init.date()),negative_totals_clipped=int((raw<0).sum()),
            minimum_raw_daily_mm=float(np.nanmin(raw)) if np.isfinite(raw).any() else np.nan,
            missing_town_day_cells=int((~valid).sum())))
        input_hashes[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        domain_records.append(domains)
    if dates[0] < pd.Timestamp(config['start_date']) or dates[-1] > pd.Timestamp(config['end_date']):
        raise ValueError('Initialization dates outside configured season')
    cube, rainfall = np.stack(cubes), np.stack(daily_values)
    rows=[]
    for si, init in enumerate(dates):
        for ti,name in enumerate(names):
            for di,day in enumerate(days):
                value=cube[si,ti,di]
                rows.append(dict(town=name,initialization=str(init.date()),forecast_day=int(day),
                    valid_start=str(init+pd.Timedelta(days=int(day)-1)),valid_end=str(init+pd.Timedelta(days=int(day))),
                    threshold_mm=thresholds[ti],rainfall_units='mm in 24 h',members_above=value,
                    members=51,fraction_above=value/51,available=bool(np.isfinite(value))))
    counts=pd.DataFrame(rows)
    counts.to_csv(ROOT/'daily_member_counts.csv',index=False)
    pd.DataFrame(qc).to_csv(ROOT/'quality_control.csv',index=False)
    # %% Target-day metrics and stronger-criterion sensitivity; all ties deterministic
    summaries,event_rows=[],[]
    for minimum in [1,3,5]:
        events=pd.DataFrame(event_metrics(counts,minimum))
        event_rows.extend(events.to_dict('records'))
        for ti,name in enumerate(names):
            group=counts[counts.town==name]
            signals=group[group.members_above>=minimum]
            target=events[events.town==name]
            earliest=target.sort_values(['earliest_lead_days','valid_end'],ascending=[False,True]).iloc[0]
            consistent=target.sort_values(['longest_consecutive_signal_starts','signal_starts','valid_end'],ascending=[False,False,True]).iloc[0]
            finite=np.isfinite(cube[:,ti]).any(axis=1)
            candidates=[(-float(np.nanmax(cube[si,ti])),-float(np.nansum(cube[si,ti])),si)
                for si in range(len(dates)) if finite[si]]
            best=min(candidates)[2] if candidates else None
            summaries.append(dict(town=name,minimum_members=minimum,criterion_fraction=minimum/51,
                threshold_mm=thresholds[ti],peak_members_above=int(np.nanmax(cube[:,ti])) if finite.any() else np.nan,
                strongest_start=str(dates[best].date()) if best is not None else '',
                available_starts=int(finite.sum()),signal_starts=int(signals.initialization.nunique()),
                first_signal_start=signals.initialization.min() if len(signals) else '',
                earliest_lead_days=int(earliest.earliest_lead_days),
                earliest_target_end=earliest.valid_end if len(signals) else '',
                earliest_target_first_start=earliest.first_start_for_earliest_lead if len(signals) else '',
                longest_consecutive_signal_starts=int(consistent.longest_consecutive_signal_starts),
                consistent_target_end=consistent.valid_end if len(signals) else '',
                streak_first_start=consistent.streak_first_start if len(signals) else '',
                streak_last_start=consistent.streak_last_start if len(signals) else ''))
    summary=pd.DataFrame(summaries)
    baseline=summary[summary.minimum_members==1]
    baseline.to_csv(ROOT/'town_signal_summary.csv',index=False)
    summary.to_csv(ROOT/'signal_criterion_sensitivity.csv',index=False)
    pd.DataFrame(event_rows).to_csv(ROOT/'same_valid_day_signals.csv',index=False)
    # %% Plots with a common integer count scale, explicit targets and daily-rainfall units
    peak=max(1,int(np.nanmax(cube))) if np.isfinite(cube).any() else 1
    cmap=plt.get_cmap('YlOrRd').copy(); cmap.set_bad('#bdbdbd')
    norm=BoundaryNorm(np.arange(-.5,peak+1.5),256)
    def heatmap(ax,ti,all_dates=True):
        image=ax.imshow(np.ma.masked_invalid(cube[:,ti]),aspect='auto',cmap=cmap,norm=norm)
        ax.set(xticks=range(10),xticklabels=days,yticks=range(len(dates)),
            yticklabels=[d.strftime('%d %b') for d in dates],xlabel='Forecast day (24-hour intervals)',
            ylabel='Initialization date',title=f'{names[ti]} | > {thresholds[ti]:.2f} mm in 24 h')
        for si,di in np.argwhere(cube[:,ti]>0):
            value=cube[si,ti,di]
            ax.text(di,si,str(int(value)),ha='center',va='center',fontsize=8,
                color='white' if value>peak*.55 else 'black')
        return image
    for ti,name in enumerate(names):
        slug=name.lower().replace(' ','_')
        fig,ax=plt.subplots(figsize=(10,8),layout='constrained')
        image=heatmap(ax,ti)
        fig.colorbar(image,ax=ax,ticks=range(peak+1),label='Members above local 2-year level (of 51)')
        fig.suptitle(f'Task C | {dates[0]:%Y-%m-%d} to {dates[-1]:%Y-%m-%d}\nPale unlabelled cells = zero; gray = unavailable',fontsize=13)
        fig.savefig(ROOT/f'{slug}_heatmap.png',dpi=170); plt.close(fig)
        row=baseline[baseline.town==name].iloc[0]
        if not row.strongest_start:
            continue
        si=int(dates.get_loc(pd.Timestamp(row.strongest_start)))
        fig,(ax,ax2)=plt.subplots(2,1,figsize=(11,8),sharex=True,layout='constrained',gridspec_kw={'height_ratios':[3,1]})
        for mi in range(51):
            ax.plot(days,rainfall[si,ti,mi],color='#347eae',alpha=.2,lw=.8)
        ax.plot(days,np.nanmean(rainfall[si,ti],axis=0),color='black',lw=2,label='Ensemble mean')
        ax.axhline(thresholds[ti],color='#b32632',ls='--',label=f'2-year level: {thresholds[ti]:.2f} mm in 24 h')
        ax.set(ylabel='Daily rainfall (mm in 24 h)',title=f'{name} | strongest start {dates[si]:%Y-%m-%d} | 51 members')
        ax.legend(); ax.grid(alpha=.2)
        ax2.bar(days,cube[si,ti],color='#ba5638')
        for di,day in enumerate(days):
            if np.isfinite(cube[si,ti,di]):
                ax2.text(day,cube[si,ti,di]+.12,str(int(cube[si,ti,di])),ha='center',fontsize=9)
        ax2.set(xticks=days,xticklabels=[f'{d}\n{dates[si]+pd.Timedelta(days=int(d)):%d %b}' for d in days],
            xlabel='Forecast day / interval ending date',ylabel='Members > level',ylim=(0,peak+1.2))
        ax2.yaxis.set_major_locator(plt.MaxNLocator(integer=True)); ax2.grid(axis='y',alpha=.2)
        fig.savefig(ROOT/f'{slug}_strongest_start_plume.png',dpi=170); plt.close(fig)
    fig,axes=plt.subplots(2,3,figsize=(18,14),layout='constrained')
    for ti,ax in enumerate(axes.flat):
        if ti<5: image=heatmap(ax,ti)
        else: ax.set_visible(False)
    fig.colorbar(image,ax=list(axes.flat)[:5],ticks=range(peak+1),shrink=.7,label='Members (of 51) above local 2-year 24 h level')
    fig.suptitle(f'All five grid.json towns | starts {dates[0]:%d %b}–{dates[-1]:%d %b %Y}\nShared scale; pale = zero, gray = unavailable',fontsize=16)
    fig.savefig(ROOT/'five_town_heatmap_comparison.png',dpi=160); plt.close(fig)
    # %% Human-readable numerical interpretation and current-script provenance
    report=['# Task C: Did the forecast see it coming?','',
        f'All five towns in **grid.json**. Forecast starts **{dates[0]:%Y-%m-%d}–{dates[-1]:%Y-%m-%d}**, inclusive; days 1–10; 51 members.',
        'The rainfall threshold is each town’s published Task A **2-year, 24 h level**. Counts use strict rainfall > threshold.',
        'Default exploratory signal: at least one member (1/51 = 1.96%). This is not an operational warning rule.','',
        '## Main results','',
        '| Town | Threshold (mm in 24 h) | Peak members | Strongest start | Starts with any signal |',
        '|---|---:|---:|---|---:|']
    for row in baseline.itertuples():
        report.append(f'| {row.town} | {row.threshold_mm:.2f} | {row.peak_members_above}/51 | {row.strongest_start} | {row.signal_starts}/{row.available_starts} |')
    report+=['','The strongest start maximizes its largest daily count, breaking ties by summed member-day counts, then earliest start. Plumes show daily rainfall, not cumulative totals.','',
        '## Earliest signal: identify the target interval','',
        'Earliest means greatest lead time before one valid 24-hour interval. Ties select the earliest target ending date; this is an illustrative target, not the only tied target.','',
        '| Town | Maximum lead (days) | Issued on | Target interval ends |', '|---|---:|---|---|']
    for row in baseline.itertuples():
        report.append(f'| {row.town} | {row.earliest_lead_days} | {row.earliest_target_first_start} | {row.earliest_target_end} |')
    report+=['','A 10-day lead equals the available forecast horizon. Towns tied there cannot be ranked uniquely as earliest, and different towns may be signaling different valid days.','',
        '## Consistency: repeated forecasts for the SAME interval','',
        '| Town | Consecutive starts | First start | Last start | Target interval ends |', '|---|---:|---|---|---|']
    for row in baseline.itertuples():
        report.append(f'| {row.town} | {row.longest_consecutive_signal_starts} | {row.streak_first_start} | {row.streak_last_start} | {row.consistent_target_end} |')
    report+=['','Target interval starts exactly 24 hours before its ending timestamp. Boundary targets have fewer available starts; `same_valid_day_signals.csv` records denominators and all target dates.','',
        '## Sensitivity to requiring more members','',
        '| Town | Required members | Signal starts | Longest target-day streak |', '|---|---:|---:|---:|']
    for row in summary.itertuples():
        report.append(f'| {row.town} | {row.minimum_members}/51 ({row.criterion_fraction:.2%}) | {row.signal_starts} | {row.longest_consecutive_signal_starts} |')
    active=baseline[baseline.signal_starts>0]
    if len(active):
        lead=active.earliest_lead_days.max(); streak=active.longest_consecutive_signal_starts.max()
        report+=['',f'Earliest-lead tie: **{", ".join(active.loc[active.earliest_lead_days==lead,"town"])}**, {int(lead)} days.',
            f'Most persistent: **{", ".join(active.loc[active.longest_consecutive_signal_starts==streak,"town"])}**, {int(streak)} consecutive starts for one target interval.']
    report+=['','## Why do signals differ, and did the forecast get it right?','',
        'Signals depend jointly on the local rainfall threshold, predicted daily amounts and ensemble spread. For example, Nyala’s threshold is lower than Gedaref’s, but thresholds alone cannot explain differences: Khartoum has the lowest threshold and is not automatically the most persistent.',
        'The default one-member criterion is weak; the stronger-criterion table shows how conclusions change. Signal frequency across starts is distinct from persistence for one target interval.',
        '**Observed 2025 rainfall and impact data are not provided.** These are forecast signals, not verified hits, misses or warning skill. Annual maxima ending in 2024 cannot verify July 2025 events.','',
        '## Units and validation','',
        '- Daily rainfall = difference of consecutive cumulative tp endpoints ×1000, converting m to mm in 24 h. Count units are members, of 51.',
        '- grid.json determines all five towns and their order. Every cache’s source/town fingerprint is checked.',
        '- Task A thresholds and selected CMORPH pixels match recorded source-domain evidence.',
        '- Earlier connected checks established both domains, descending forecast latitude and ascending CMORPH latitude. This offline run rechecks retained evidence, not fresh cloud metadata.',
        '- A town/day requires all 51 member endpoints; missing data are gray, not zero. The QC table records missing cells and small-negative corrections.',
        f'- {sum(q["negative_totals_clipped"] for q in qc)} tiny negative increments were clipped to zero. Tolerance is 0.05 mm; larger decreases stop execution.',
        '- Forecast and CMORPH pixels have different areas; nearest-point matching is not a rain-gauge comparison.']
    (ROOT/'results.md').write_text('\n'.join(report)+'\n')
    input_hashes['inputs/thresholds.csv']=hashlib.sha256((ROOT/'inputs/thresholds.csv').read_bytes()).hexdigest()
    revision=subprocess.run(['git','-C',str(ROOT),'rev-parse','HEAD'],capture_output=True,text=True)
    (ROOT/'run_metadata.json').write_text(json.dumps(dict(run_utc=datetime.now(timezone.utc).isoformat(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        grid_json_sha256=hashlib.sha256((ROOT/'grid.json').read_bytes()).hexdigest(),
        git_commit=revision.stdout.strip() if revision.returncode==0 else None,input_hashes=input_hashes,
        start=args.start,end=args.end,towns=towns,forecast=config['forecast'],domain_validation=domain_records[0],
        all_cached_domains_verified=True,fresh_cloud_domain_check=False,rainfall_units='mm in 24 h',
        member_criteria=[1,3,5],negative_tolerance_mm=.05,available_cells=int(counts.available.sum()),
        total_cells=len(counts),versions=dict(numpy=np.__version__,pandas=pd.__version__,matplotlib=matplotlib.__version__)),indent=2)+'\n')
    print(baseline.to_string(index=False),flush=True)
    print(f'Task C complete. Figures, tables and results.md saved in {ROOT}',flush=True)


if __name__=='__main__':
    main()
