"""Create a concise 15-slide edition, retaining all 28 final scientific figures."""
from pathlib import Path
import json, csv

HERE=Path(__file__).resolve().parent
source=(HERE/'build_deck.py').read_text()
exec(compile(source[:source.index('towns=json.loads')],str(HERE/'build_deck.py'),'exec'))
BUILD=ROOT/'presentation/.build15'

def multi(title,subtitle,files,caption,cols=3):
    add(title,subtitle,notes='Source figures: '+', '.join(files)+'\nGenerating scripts and reports: task_A through task_D. Original PNGs retain full resolution. Grouped slides provide overview; zoom into individual figures for detailed labels.')
    slide=slides[-1];slide['images']=[]
    top=1.55;bottom=6.65;gap=.18;nrows=(len(files)+cols-1)//cols
    cw=(12.4-gap*(cols-1))/cols;ch=(bottom-top-gap*(nrows-1))/nrows
    for j,file in enumerate(files):
        p=ROOT/file; row,col=divmod(j,cols)
        # Center the last partial row, keeping all original panels uncropped.
        count=min(cols,len(files)-row*cols);offset=(cols-count)*(cw+gap)/2
        slide['objects']+=picture(100+j,p,.45+col*(cw+gap)+offset,top+row*(ch+gap),cw,ch).replace('rIdImage',f'rIdImage{j}')
        slide['images'].append(p)
    slide['objects']+=textbox(200,caption,.6,6.88,12.05,.3,14,GRAY)

towns=json.loads((ROOT/'task_A/grid.json').read_text())['towns'];names=[t['name'] for t in towns]
thresholds=readcsv('task_A/thresholds.csv');sensitivity=readcsv('task_A/sensitivity.csv')
b=readcsv('task_B/summary_counts.csv');c=readcsv('task_C/town_signal_summary.csv')
timing=readcsv('task_D/read_timings.csv')

add('Sudan rainfall extremes','Observed thresholds and ensemble forecast signals',dark=True,
    body=['Five towns from grid.json','Tasks A–D','CMORPH: 1998–2024\nECMWF ensemble: June–August 2025'],
    notes='All content comes from final task_A through task_D outputs. The 15-slide deck retains all 28 output PNGs.')
slides[-1]['objects']=slides[-1]['objects'].replace('sz="3000"','sz="4200"',1)

add('Five towns and the observed rainfall reference','Task A regional 10-year level, in mm accumulated over 24 h',
    image='task_A/regional_10yr_24hr.png',insights=[
        'CMORPH annual maxima: 1998–2024, 27 years. Five town coordinates from grid.json.'],
    notes='Source: task_A/grid.json, regional_10yr_24hr.png and results.md. The forecast latitude descends and CMORPH latitude ascends. Both domains cover the towns.')

multi('A: observed extremes at every town','Annual maxima and fitted return levels for 24 h and 6 h',
    [f'task_A/{name.lower().replace(" ","_")}_return_levels.png' for name in names],
    'The plots distinguish published Gumbel levels from an independent MLE refit. Large departures are descriptive evidence.',3)

rows=[['Town','2-year','10-year','50-year']]
for name in names:rows.append([name]+[f(row_for(thresholds,town=name,duration='24hr',return_period_years=t)['threshold_mm']) for t in [2,10,50]])
add('A: local return levels and largest-year sensitivity','Published 24 h rainfall depths in mm',table=rows,
    tableopts=dict(y=1.6,row_h=.55,col_widths=[3.2,2.9,2.9,2.9]),
    body='Removing Khartoum’s 2017 maximum lowers its MLE 50-year level from 68.23 to 62.05 mm (−9.05%). Both sensitivity fits use MLE. Fifty-year levels extrapolate beyond 27 observed years.',
    notes='Sources: task_A/thresholds.csv and sensitivity.csv. Original 6 h comparisons appear in the previous slide’s five source figures. The published estimator is unspecified; sensitivity compares consistent MLE fits.')

add('B: three thresholds across five towns','16 July 2025 start, ten daily intervals, 51 members',image='task_B/five_town_threshold_comparison.png',
    insights=['Fixed threshold: 20 mm in 24 h','Local 2-year and 10-year levels come from Task A.','El Obeid and Nyala alone have 2-year exceedances. No town exceeds a 10-year level.'],
    notes='Source: task_B/five_town_threshold_comparison.png and summary_counts.csv. Counts use strict >.')

multi('B: daily member counts at each town','Each figure separates the fixed 20 mm, 2-year and 10-year thresholds',
    [f'task_B/{name.lower().replace(" ","_")}_threshold_counts.png' for name in names],
    'Daily counts are out of 51 members. Rainfall thresholds are mm in 24 h. Exact zero labels distinguish no exceedance.',3)

rows=[['Town','20 mm','2-year','10-year','≥1 heavy day']]
for name in names:
    r=row_for(b,town=name,threshold='20mm')
    rows.append([name,r['member_days_above'],row_for(b,town=name,threshold='2yr')['member_days_above'],row_for(b,town=name,threshold='10yr')['member_days_above'],r['members_with_heavy_day_ge']+'/51'])
add('B: threshold sensitivity and xclim counts','First three columns count member-days out of 510 per town. Last column: distinct members at ≥20 mm.',table=rows,
    tableopts=dict(col_widths=[2.7,2.1,2.2,2.2,2.7],font=18),
    body='xclim uses ≥, plots use >. A 2-year annual level implies 50% annual exceedance. The illustrative 0.190% daily probability assumes independent, identical days.',
    notes='Sources: task_B/summary_counts.csv and results.md. All 765 xclim counts match direct counts. Member-days are correlated predictions; they do not estimate observed climatological frequency.')

add('C: forecast signals across 21 starts','6–26 July 2025, ten daily leads at every town',image='task_C/five_town_heatmap_comparison.png',
    insights=['Signal: at least one member above the local 2-year 24 h level.','Nyala: signals in 20/21 starts\nGedaref: signals in 2/21 starts','A one-member signal is only 1.96% of the ensemble.'],
    notes='Source: task_C/five_town_heatmap_comparison.png and town_signal_summary.csv. Shared integer scale. Pale is zero and gray unavailable.')

multi('C: complete daily signal histories','Rows are initialization dates, columns are forecast days',
    [f'task_C/{name.lower().replace(" ","_")}_heatmap.png' for name in names],
    'Shared member-count scale across towns. Local rainfall thresholds differ. All 1,050 town/start/day cells are available.',3)

multi('C: the strongest start at each town','Daily rainfall plumes, ensemble mean, local threshold and member counts',
    [f'task_C/{name.lower().replace(" ","_")}_strongest_start_plume.png' for name in names],
    'Strongest start maximizes peak count, then summed member-day counts, then earliest date. Plume rainfall units: mm in 24 h.',3)

rows=[['Town','Peak','Lead days','Signal streak','Streak target']]
for name in names:
    r=row_for(c,town=name);rows.append([name,r['peak_members_above']+'/51',r['earliest_lead_days'],r['longest_consecutive_signal_starts']+(' start' if r['longest_consecutive_signal_starts']=='1' else ' starts'),r['consistent_target_end'][:10]])
add('C: Nyala has the most persistent weak signal','Streaks require consecutive starts signaling the same target interval',table=rows,
    tableopts=dict(col_widths=[2.7,1.7,2,2.5,3],font=18),
    body='Nyala’s starts on 7–11 July target the interval ending 17 July. Four towns tie at the ten-day horizon, targeting different dates. No town reaches five members above the threshold.',
    notes='Sources: task_C/town_signal_summary.csv and signal_criterion_sensitivity.csv. The Target ends column refers to the longest signal streak; Lead days refers to the earliest-lead example, which may target a different interval. No observed 2025 rainfall is available for event verification.')

multi('D: probability maps for the early seasonal samples','Local 2-year 24 h thresholds and all five grid.json towns',
    ['task_D/probabilities_2025-06-10.png','task_D/probabilities_2025-07-01.png'],
    'June 10 peak: 1.96%. July 1 peak: 9.80%. No sampled pixel reaches 20% for these two starts.',2)

multi('D: the August sample contains the regional hotspot','Probability decision: ≥20%, requiring at least 11 of 51 members',
    ['task_D/probabilities_2025-07-22.png','task_D/probabilities_2025-08-12.png'],
    'August 12, day 4: 12 pixels reach 20%, with a peak of 16/51 = 31.37%. The target interval ends 16 August.',2)

add('D: sampled frequency and town results','Four starts × five daily leads = 20 sampled forecast intervals',image='task_D/sampled_season_frequency.png',
    insights=['Twelve regional pixels reach 20% once each. Maximum frequency: 1/20 = 5%. All five town pixels remain below 20%.'],
    notes='Sources: task_D/sampled_season_frequency.png, town_frequency.csv and regional_hotspots.csv. These samples do not cover every JJA day. A forecast pixel uses its nearest CMORPH threshold pixel, which can differ from direct town-coordinate selection in A–C.')

rows=[['Start','Cloud read','Chunks']]
for date in ['2025-06-10','2025-07-01','2025-07-22','2025-08-12']:
    r=next(r for r in timing if r['kind']=='original_cloud_forecast_read' and r['initialization']==date)
    rows.append([date,f(r['seconds'])+' s',str(int(float(r['estimated_storage_chunks'])))])
add('Conclusions and the cost of map reads','Pan chunks contain a broad map, all 51 members, and one start/lead',table=rows,
    tableopts=dict(y=1.65,row_h=.52,col_widths=[4,4,3.9]),
    body='Six cumulative endpoints give five daily maps. Threshold read: 10.84 s, one chunk. Local thresholds shape weak signals. Observed 2025 rainfall and impacts are needed to assess warning skill.',
    notes='Sources: task_D/read_timings.csv, results.md and task_A through task_C reports. Forecast chunk shape [1,1,51,321,261]. Measurements include transfer, decode and compute. Data: data.source.coop/e4drr-project. Examples: github.com/icpac-igad/python-workshop. All 28 final scientific PNGs appear in this deck.')

assert len(slides)==15
for s in slides:
    if 'images' not in s:s['images']=[s['image']] if s['image'] else []
package=source[source.index('# Native OOXML package'):]
old="""    if slide['image']:
        media=f'image{index}.png';parts['ppt/media/'+media]=slide['image'].read_bytes();links.append(('rIdImage',REL+'image','../media/'+media))"""
new="""    for j,p in enumerate(slide['images']):
        media=f'image{index}_{j}.png';parts['ppt/media/'+media]=p.read_bytes()
        links.append(('rIdImage' if slide['image'] else f'rIdImage{j}',REL+'image','../media/'+media))"""
assert old in package;package=package.replace(old,new)
package=package.replace("included=[s['image'].resolve() for s in slides if s['image']]","included=[p.resolve() for s in slides for p in s['images']]")
package=package.replace("figure=str(s['image'].relative_to(ROOT)) if s['image'] else None","figures=[str(p.relative_to(ROOT)) for p in s['images']]")
exec(compile(package,str(HERE/'build_deck.py'),'exec'))
