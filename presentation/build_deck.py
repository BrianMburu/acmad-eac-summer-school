"""Package final Task A–D figures and editable summaries as a native OOXML PPTX.

Uses standard-library XML/ZIP packaging because the supplied artifact authoring
runtime is unavailable on this host. Original scientific PNGs remain unchanged.
"""
from pathlib import Path
import csv, hashlib, json, struct, zipfile
from xml.sax.saxutils import escape
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parent.parent
BUILD=ROOT/'presentation/.build'
OUT=ROOT/'presentation/output'
W,H=12192000,6858000
EMU=914400
NAVY='17334A'; TEAL='087F8C'; GRAY='506471'; WHITE='FFFFFF'
NS='xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
slides=[]
def E(v): return int(v*EMU)
def readcsv(path):
    with (ROOT/path).open() as f:return list(csv.DictReader(f))
def row_for(rows,**keys):return next(r for r in rows if all(r[k]==str(v) for k,v in keys.items()))
def f(v,d=2):return f'{float(v):.{d}f}'

def para(text,size=20,color=NAVY,bold=False,align='l'):
    return f'<a:p><a:pPr algn="{align}"/><a:r><a:rPr lang="en-US" sz="{int(size*100)}" b="{int(bold)}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:latin typeface="Arial"/></a:rPr><a:t xml:space="preserve">{escape(str(text))}</a:t></a:r><a:endParaRPr lang="en-US" sz="{int(size*100)}"/></a:p>'
def textbox(i,text,x,y,w,h,size=20,color=NAVY,bold=False):
    paragraphs=''.join(para(t,size,color,bold) for t in str(text).split('\n'))
    return f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Text {i}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{E(x)}" y="{E(y)}"/><a:ext cx="{E(w)}" cy="{E(h)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0"/><a:lstStyle/>{paragraphs}</p:txBody></p:sp>'
def picture(i,path,x,y,w,h):
    width,height=struct.unpack('>II',path.read_bytes()[16:24])
    scale=min(w/width,h/height); fw,fh=width*scale,height*scale
    x+=(w-fw)/2;y+=(h-fh)/2
    return f'<p:pic><p:nvPicPr><p:cNvPr id="{i}" name="{escape(path.name)}" descr="Original scientific output: {escape(str(path.relative_to(ROOT)))}"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rIdImage"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="{E(x)}" y="{E(y)}"/><a:ext cx="{E(fw)}" cy="{E(fh)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
def native_table(i,rows,x=.7,y=1.65,w=11.9,row_h=.57,col_widths=None,font=19):
    n=len(rows[0]); col_widths=col_widths or [w/n]*n
    grid=''.join(f'<a:gridCol w="{E(c)}"/>' for c in col_widths)
    allrows=[]
    for ri,row in enumerate(rows):
        cells=[]
        for value in row:
            fill=NAVY if ri==0 else ('F0F5F7' if ri%2 else WHITE)
            color=WHITE if ri==0 else NAVY
            cells.append(f'<a:tc><a:txBody><a:bodyPr wrap="square" lIns="{E(.10)}" rIns="{E(.08)}" tIns="{E(.07)}" bIns="{E(.04)}"/><a:lstStyle/>{para(value,font,color,ri==0)}</a:txBody><a:tcPr><a:solidFill><a:srgbClr val="{fill}"/></a:solidFill></a:tcPr></a:tc>')
        allrows.append(f'<a:tr h="{E(row_h)}">'+''.join(cells)+'</a:tr>')
    return f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{i}" name="Editable results table"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="{E(x)}" y="{E(y)}"/><a:ext cx="{E(w)}" cy="{E(row_h*len(rows))}"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr firstRow="1" bandRow="1"/><a:tblGrid>{grid}</a:tblGrid>'+''.join(allrows)+'</a:tbl></a:graphicData></a:graphic></p:graphicFrame>'

def add(title,subtitle='',image=None,insights=None,table=None,tableopts=None,body=None,notes='',dark=False):
    idx=len(slides)+1; bg=NAVY if dark else WHITE; fg=WHITE if dark else NAVY
    objects=[textbox(2,title,.55,.3,12.2,.65,30,fg,True)]
    if subtitle:objects.append(textbox(3,subtitle,.57,1.05,12.15,.43,16,TEAL if not dark else 'B6E4E7'))
    if image:
        image=ROOT/image; width,height=struct.unpack('>II',image.read_bytes()[16:24]); aspect=width/height
        if aspect>=1.75:
            objects.append(picture(4,image,.4,1.6,12.5,5.1))
            if insights:objects.append(textbox(5,'  '.join(insights),.6,6.87,12.1,.34,15,GRAY))
        else:
            objects.append(picture(4,image,.3,1.55,8.65,5.55))
            for j,text in enumerate(insights or []):objects.append(textbox(5+j,text,9.3,1.9+j*1.5,3.35,1.3,20))
    if table:
        objects.append(native_table(20,table,**(tableopts or {})))
        if body:objects.append(textbox(21,body,.75,6.1,11.8,.75,18,GRAY))
    elif body and not image:
        for j,text in enumerate(body if isinstance(body,list) else [body]):
            objects.append(textbox(10+j,text,.75,1.85+j*1.1,11.8,.92,23,fg))
    objects.append(textbox(90,str(idx),12.3,7.13,.45,.23,11,GRAY if not dark else 'B6E4E7'))
    slides.append(dict(title=title,objects=''.join(objects),image=image,notes=notes or (str(image.relative_to(ROOT)) if image else ''),background=bg))

def fig(task,name,title,subtitle,insights,source):
    add(title,subtitle,image=f'task_{task}/{name}',insights=insights,
        notes=f'Source image: task_{task}/{name}\nGenerating committed script: task_{task}/analyze.py\nData and interpretation: {source}\nRetain original plot units and scales. Embedded PNG preserves the original resolution.')

towns=json.loads((ROOT/'task_A/grid.json').read_text())['towns']; names=[t['name'] for t in towns]
thresholds=readcsv('task_A/thresholds.csv'); fit=readcsv('task_A/observed_vs_fit_summary.csv'); sensitivity=readcsv('task_A/sensitivity.csv')
b=readcsv('task_B/summary_counts.csv'); c=readcsv('task_C/town_signal_summary.csv'); cs=readcsv('task_C/signal_criterion_sensitivity.csv')
ds=readcsv('task_D/probability_summary.csv'); dt=readcsv('task_D/town_frequency.csv'); timing=readcsv('task_D/read_timings.csv')

add('Rainfall extremes and forecast warning signals','Sudan towns, CMORPH observations and ECMWF ensemble forecasts',body=[
    'Tasks A–D', 'Khartoum, Kassala, Gedaref, El Obeid and Nyala',
    'Observed reference: 1998–2024\nForecast season: June–August 2025'],dark=True,notes='Sources: task_A/grid.json and results.md in task_A through task_D.')
add('Study design and units','Five towns from grid.json',body=[
    'A: 27 annual maxima at 24 h and 6 h, with 2-, 10- and 50-year return levels',
    'B: one forecast start, 16 July 2025, with 51 members and ten daily intervals',
    'C: 21 starts from 6–26 July 2025, with ten daily leads at every town',
    'D: four seasonal starts and five daily leads, giving 20 sampled intervals',
    'Rainfall depth: mm in 24 h. Member counts: out of 51. Probability: ensemble fraction.'],notes='Sources: task_A/results.md, task_B/results.md, task_C/results.md, task_D/results.md.')
for duration,label in [('24hr','24 h'),('6hr','6 h')]:
    rows=[['Town','2-year','10-year','50-year']]
    for name in names:rows.append([name]+[f(row_for(thresholds,town=name,duration=duration,return_period_years=p)['threshold_mm']) for p in [2,10,50]])
    add(f'A: published {label} return levels',f'CMORPH 1998–2024, rainfall depth in mm accumulated over {label}',table=rows,
        tableopts=dict(col_widths=[3.2,2.9,2.9,2.9]),body='Published CMORPH Gumbel levels supply the thresholds used in the later tasks.',notes='Source: task_A/thresholds.csv. All values in mm over the stated duration.')
for name in names:
    slug=name.lower().replace(' ','_'); r=row_for(fit,town=name,duration='24hr'); s=row_for(sensitivity,town=name,duration='24hr')
    fig('A',f'{slug}_return_levels.png',f'A: observed extremes at {name}','27 annual maxima, 1998–2024, at 24 h and 6 h',[
        f'24 h maximum\n{f(r["largest_mm"],1)} mm in {r["largest_year"]}',
        f'Largest upper-tail departure\n{r["tail_departure_year"]}: {float(r["tail_residual_mm"]):+.1f} mm versus published curve',
        f'Remove largest year\n50-year MLE changes {float(s["change_percent"]):+.2f}%'], 'task_A/observed_vs_fit_summary.csv and sensitivity.csv. Upper tail uses empirical T≥5 years. Descriptive departures do not establish fit failure.')
fig('A','regional_10yr_24hr.png','A: regional 10-year rainfall level','Published Gumbel depths from CMORPH 1998–2024',[
    'Each map value is a 24-hour rainfall depth in mm.',
    'Town thresholds vary with location. Gedaref has the highest 10-year town level: 72.84 mm.'], 'task_A/thresholds.csv and regional_10yr_24hr.nc')
for duration in ['24hr','6hr']:
    rows=[['Town','Removed','Full MLE','Without','Change']]
    for name in names:
        r=row_for(sensitivity,town=name,duration=duration)
        rows.append([name,r['removed_year'],f(r['mle_full_50yr_mm']),f(r['mle_without_largest_50yr_mm']),f(r['change_percent'])+'%'])
    add(f'A: largest-year sensitivity at {duration.replace("hr"," h")}',
        '50-year rainfall estimate in mm, refitted with Gumbel maximum likelihood',table=rows,
        tableopts=dict(col_widths=[2.7,1.7,2.5,2.5,2.5]),
        body='Both columns use MLE. Published thresholds can differ because their original fitting estimator is unspecified. A 50-year level extrapolates beyond 27 observed years.',
        notes='Source: task_A/sensitivity.csv. Confidence intervals are not estimated.')

rows=[['Town','Above 20 mm','Above 2-year','Above 10-year']]
for name in names:rows.append([name]+[row_for(b,town=name,threshold=t)['member_days_above'] for t in ['20mm','2yr','10yr']])
add('B: threshold choice changes the flagged member-days','16 July 2025 start, ten daily intervals, 510 member-days per town',table=rows,
    tableopts=dict(col_widths=[3.2,2.9,2.9,2.9]),body='Counts sum exceedances across members and days. They differ from the number of distinct members with at least one heavy day.',notes='Source: task_B/summary_counts.csv. Rainfall comparison uses strict >. Member-days are correlated predictions.')
for name in names:
    slug=name.lower().replace(' ','_');r=row_for(b,town=name,threshold='20mm');r2=row_for(b,town=name,threshold='2yr')
    fig('B',f'{slug}_threshold_counts.png',f'B: warning-threshold comparison at {name}','Forecast initialized 16 July 2025, daily counts out of 51 members',[
        f'Fixed 20 mm level\n{r["member_days_above"]} member-days above threshold',
        f'Local 2-year level\n{f(r2["threshold_mm"])} mm in 24 h\n{r2["member_days_above"]} member-days above it',
        'Each panel shows one threshold. Zero labels mean no member exceeds it.'], 'task_B/daily_member_counts.csv and summary_counts.csv')
fig('B','five_town_threshold_comparison.png','B: all five towns and all three thresholds','Overview of exact daily member counts for the 16 July 2025 start',[
    'Gedaref has 24 member-days above 20 mm, the largest fixed-threshold count.',
    'El Obeid has one and Nyala has two member-days above their 2-year levels.',
    'No town exceeds its 10-year level. Individual town slides show the detail.'], 'task_B/daily_counts_short.csv')
rows=[['Town','Members ≥1 day','Mean days/member']]
for name in names:
    r=row_for(b,town=name,threshold='20mm');rows.append([name,r['members_with_heavy_day_ge']+'/51',f(r['mean_heavy_days_ge'],3)])
add('B: xclim heavy-rain-day counts','Threshold ≥20 mm in 24 h, measured within the ten-day forecast window',table=rows,
    tableopts=dict(col_widths=[4,4,3.9]),body='xclim wetdays includes equality (≥). Daily exceedance plots use strict >. All 765 member-level xclim counts match direct counts.',notes='Source: task_B/xclim_heavy_days.csv and summary_counts.csv. Includes 5 towns × 3 thresholds × 51 members. This table shows the fixed 20 mm threshold.')
add('B: annual return levels and daily warning thresholds','Annual exceedance probability and daily probability answer different questions',body=[
    'A fitted 2-year annual level has a 50% chance of at least one exceedance in a year.',
    'Independent, identical days would imply a daily probability of 0.190%. Rainfall seasonality and dependence limit that illustration.',
    'In this forecast, 2-year exceedances total one member-day at El Obeid and two at Nyala.',
    'Impact records and forecast verification are needed to choose an operational warning threshold.'],notes='Sources: task_B/results.md and annual_vs_daily_comparison.csv. Illustrative p=1−0.5^(1/365). Ensemble member-days do not estimate observed climatological frequency.')

rows=[['Town','Peak members','Strongest start','Starts with signal']]
for name in names:
    r=row_for(c,town=name);rows.append([name,r['peak_members_above']+'/51',r['strongest_start'],r['signal_starts']+'/'+r['available_starts']])
add('C: forecast signals across 21 starts','6–26 July 2025, days 1–10, local 2-year 24 h levels',table=rows,
    tableopts=dict(col_widths=[2.8,2.5,3.4,3.2]),body='Default exploratory signal: at least one member above the rainfall level. One of 51 members is only 1.96%.',notes='Source: task_C/town_signal_summary.csv. Strongest start maximizes peak count, then total counts, then earliest date.')
for name in names:
    slug=name.lower().replace(' ','_');r=row_for(c,town=name)
    fig('C',f'{slug}_heatmap.png',f'C: signal history at {name}','Rows are initialization dates, columns are daily forecast leads',[
        f'{r["signal_starts"]} of 21 starts show at least one signal.',
        f'Peak daily count\n{r["peak_members_above"]}/51 members',
        'Shared color scale across towns. Pale cells are zero. Gray indicates unavailable forecasts.'], 'task_C/daily_member_counts.csv')
for name in names:
    slug=name.lower().replace(' ','_');r=row_for(c,town=name)
    fig('C',f'{slug}_strongest_start_plume.png',f'C: strongest forecast at {name}',f'Start {r["strongest_start"]}, daily rainfall and exceedance counts',[
        f'Peak count\n{r["peak_members_above"]}/51 members above the threshold',
        'Blue traces show member rainfall in mm in 24 h. Black shows the ensemble mean.',
        'The lower panel gives daily counts and the ending dates of the 24-hour intervals.'], 'task_C/town_signal_summary.csv and daily_member_counts.csv')
fig('C','five_town_heatmap_comparison.png','C: five-town signal overview','Shared count scale across the 21 initialization dates',[
    'Nyala shows a signal in 20 of 21 starts.',
    'Gedaref shows a signal in 2 of 21 starts.',
    'A signal in many starts differs from repeated signals for the same target day.'], 'task_C/town_signal_summary.csv')
rows=[['Town','Lead days','Issued on','Target ends']]
for name in names:
    r=row_for(c,town=name);rows.append([name,r['earliest_lead_days'],r['earliest_target_first_start'],r['earliest_target_end'][:10]])
add('C: earliest signals refer to specific target days','The 24-hour target interval ends on the date shown',table=rows,
    tableopts=dict(col_widths=[2.8,2,3.55,3.55]),body='Four towns tie at ten days, the forecast horizon. Different target days prevent a unique ranking of one common event.',notes='Source: task_C/town_signal_summary.csv. Ties use the earliest target ending date as a deterministic example. Other tied targets remain in same_valid_day_signals.csv.')
rows=[['Town','Consecutive starts','First start','Last start','Target ends']]
for name in names:
    r=row_for(c,town=name);rows.append([name,r['longest_consecutive_signal_starts'],r['streak_first_start'],r['streak_last_start'],r['consistent_target_end'][:10]])
add('C: Nyala has the longest same-target signal streak','A streak requires consecutive starts signaling the same valid 24-hour interval',table=rows,
    tableopts=dict(col_widths=[2.35,2.35,2.4,2.4,2.4],font=17),body='Nyala’s 7–11 July starts target the interval ending 17 July. Boundary targets have fewer available starts, which limits comparisons.',notes='Source: task_C/town_signal_summary.csv and same_valid_day_signals.csv. Counts alone cannot establish why towns differ causally.')
rows=[['Town','≥1 member','≥3 members','≥5 members']]
for name in names:rows.append([name]+[row_for(cs,town=name,minimum_members=m)['signal_starts']+'/21' for m in [1,3,5]])
add('C: stronger signal criteria reduce the number of flagged starts','Starts with at least one daily interval meeting the member criterion',table=rows,
    tableopts=dict(col_widths=[3.2,2.9,2.9,2.9]),body='No town reaches five members. Threshold depth, predicted rainfall and ensemble spread jointly affect these weak signals.',notes='Source: task_C/signal_criterion_sensitivity.csv. Criteria 1/51,3/51,5/51 correspond to 1.96%,5.88%,9.80%.')

for date in ['2025-06-10','2025-07-01','2025-07-22','2025-08-12']:
    records=[r for r in ds if r['initialization']==date]
    peak=max(float(r['maximum_probability']) for r in records);hits=sum(int(r['grid_points_ge_probability']) for r in records)
    fig('D',f'probabilities_{date}.png',f'D: regional probabilities for {date}','Five daily leads, local 2-year 24 h threshold at each forecast pixel',[
        f'Peak probability: {peak:.2%}. Pixel-intervals reaching 20%: {hits}. All five towns appear on every map.'], 'task_D/probability_summary.csv. Probability is the fraction of 51 members with rainfall > the local threshold. The 20% decision requires 11 members.')
fig('D','sampled_season_frequency.png','D: frequency across the sampled seasonal forecasts','Four starts and five daily leads give 20 sampled intervals',[
    'Twelve regional pixels reach 20% once each. Maximum sampled frequency is 1/20, or 5%.'], 'task_D/regional_hotspots.csv. All hotspots occur at day 4 of the 12 August start, ending 16 August. This is not full-season frequency.')
rows=[['Town','Intervals ≥20%','Available','Peak probability']]
for name in names:
    r=row_for(dt,town=name);rows.append([name,r['exceedance_intervals'],r['available_intervals'],f(float(r['maximum_probability'])*100)+'%'])
add('D: none of the five town pixels reaches 20%','Regional hotspots lie away from the selected town pixels',table=rows,
    tableopts=dict(col_widths=[3.1,3.1,2.5,3.2]),body='Regional peak probability reaches 16/51 = 31.37%. The sampled frequency map and the town table describe different spatial locations.',notes='Source: task_D/town_frequency.csv and regional_hotspots.csv. At each forecast pixel the rainfall threshold uses its nearest CMORPH pixel, which can differ from direct town-coordinate matching in Tasks A–C.')
rows=[['Start','Original cloud read','Storage chunks']]
for date in ['2025-06-10','2025-07-01','2025-07-22','2025-08-12']:
    r=next(r for r in timing if r['kind']=='original_cloud_forecast_read' and r['initialization']==date)
    rows.append([date,f(r['seconds'])+' s',r['estimated_storage_chunks']])
add('D: pan chunks make regional maps efficient','One forecast chunk contains one start and lead, all 51 members, and a broad spatial map',table=rows,
    tableopts=dict(col_widths=[4,4,3.9]),body='Six cumulative endpoints produce five daily maps. CMORPH threshold read: 10.84 s and one chunk. Local cache timings measure a different operation.',notes='Source: task_D/read_timings.csv and results.md. Forecast chunks [1,1,51,321,261] in time,step,number,latitude,longitude. Chunk estimates are not exact HTTP request counts. Network and cache conditions affect timing.')
add('Conclusions and limits','Observed extremes and forecast signals provide complementary evidence',body=[
    'A: local thresholds vary substantially, and removing one large year changes extrapolated return levels.',
    'B: 20 mm captures more member-day exceedances than the local annual return levels.',
    'C: Nyala has the most persistent weak signal for one target interval. No town reaches a five-member signal.',
    'D: twelve regional pixels reach 20% in one sampled interval, while all five town pixels remain below 20%.',
    'Observed 2025 rainfall and impacts are required to verify events and assess warning performance.'],notes='Sources: final task_A through task_D results.md files. No observed 2025 event verification is available.')
add('Data sources and reproducibility','All 28 final output figures appear in this deck',body=[
    'CMORPH annual maxima and Gumbel return levels, 1998–2024',
    'ECMWF ensemble forecast store, 49r1-jja2025, with 51 members',
    'Town coordinates and bounds: grid.json in each final task folder',
    'Generating scripts and reports: task_A, task_B, task_C and task_D',
    'Public store: data.source.coop/e4drr-project. Workshop examples: github.com/icpac-igad/python-workshop'],notes='Specific prefixes: observations/cmorph_rp_icechunk and forecasts/ecmwf-ifs-ea-swio-realized-v3/49r1-jja2025. Every figure slide names its source file in speaker notes. Input/script hashes and Git revisions are stored in each task run_metadata.json.')

# Native OOXML package with blank layout, explicit Arial theme and speaker notes
EMPTY='<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
def rels(items):return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="{i}" Type="{typ}" Target="{target}"/>' for i,typ,target in items)+'</Relationships>'
parts={}
def xml(name,text):parts[name]=('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'+text).encode()
xml('ppt/theme/theme1.xml','<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Sudan rainfall"><a:themeElements><a:clrScheme name="Rainfall">'+''.join(f'<a:{name}><a:srgbClr val="{color}"/></a:{name}>' for name,color in [('dk1','17334A'),('lt1','FFFFFF'),('dk2','506471'),('lt2','F0F5F7'),('accent1','087F8C'),('accent2','BA5638'),('accent3','347EAE'),('accent4','D48716'),('accent5','338363'),('accent6','B32632'),('hlink','0563C1'),('folHlink','954F72')])+'</a:clrScheme><a:fontScheme name="Arial"><a:majorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="Basic"><a:fillStyleLst>'+('<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'*3)+'</a:fillStyleLst><a:lnStyleLst>'+('<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'*3)+'</a:lnStyleLst><a:effectStyleLst>'+('<a:effectStyle><a:effectLst/></a:effectStyle>'*3)+'</a:effectStyleLst><a:bgFillStyleLst>'+('<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'*3)+'</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
clr='<p:clrMap accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" bg1="lt1" bg2="lt2" folHlink="folHlink" hlink="hlink" tx1="dk1" tx2="dk2"/>'
xml('ppt/slideMasters/slideMaster1.xml',f'<p:sldMaster {NS}><p:cSld><p:spTree>{EMPTY}</p:spTree></p:cSld>{clr}<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rIdLayout"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>')
parts['ppt/slideMasters/_rels/slideMaster1.xml.rels']=rels([('rIdLayout',REL+'slideLayout','../slideLayouts/slideLayout1.xml'),('rIdTheme',REL+'theme','../theme/theme1.xml')]).encode()
xml('ppt/slideLayouts/slideLayout1.xml',f'<p:sldLayout {NS} type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>{EMPTY}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
parts['ppt/slideLayouts/_rels/slideLayout1.xml.rels']=rels([('rIdMaster',REL+'slideMaster','../slideMasters/slideMaster1.xml')]).encode()
xml('ppt/notesMasters/notesMaster1.xml',f'<p:notesMaster {NS}><p:cSld><p:spTree>{EMPTY}</p:spTree></p:cSld>{clr}<p:notesStyle/></p:notesMaster>')
parts['ppt/notesMasters/_rels/notesMaster1.xml.rels']=rels([('rIdTheme',REL+'theme','../theme/theme1.xml')]).encode()
for index,slide in enumerate(slides,1):
    xml(f'ppt/slides/slide{index}.xml',f'<p:sld {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="{slide["background"]}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree>{EMPTY}{slide["objects"]}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')
    links=[('rIdLayout',REL+'slideLayout','../slideLayouts/slideLayout1.xml'),('rIdNotes',REL+'notesSlide',f'../notesSlides/notesSlide{index}.xml')]
    if slide['image']:
        media=f'image{index}.png';parts['ppt/media/'+media]=slide['image'].read_bytes();links.append(('rIdImage',REL+'image','../media/'+media))
    parts[f'ppt/slides/_rels/slide{index}.xml.rels']=rels(links).encode()
    xml(f'ppt/notesSlides/notesSlide{index}.xml',f'<p:notes {NS}><p:cSld><p:spTree>{EMPTY}<p:sp><p:nvSpPr><p:cNvPr id="2" name="Source notes"/><p:cNvSpPr/><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>'+''.join(para(x,12) for x in slide['notes'].split('\n'))+'</p:txBody></p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>')
    parts[f'ppt/notesSlides/_rels/notesSlide{index}.xml.rels']=rels([('rIdSlide',REL+'slide',f'../slides/slide{index}.xml'),('rIdMaster',REL+'notesMaster','../notesMasters/notesMaster1.xml')]).encode()
xml('ppt/presentation.xml',f'<p:presentation {NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rIdMaster"/></p:sldMasterIdLst><p:notesMasterIdLst><p:notesMasterId r:id="rIdNotesMaster"/></p:notesMasterIdLst><p:sldIdLst>'+''.join(f'<p:sldId id="{255+i}" r:id="rIdSlide{i}"/>' for i in range(1,len(slides)+1))+f'</p:sldIdLst><p:sldSz cx="{W}" cy="{H}" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle><a:defPPr><a:defRPr><a:latin typeface="Arial"/></a:defRPr></a:defPPr></p:defaultTextStyle></p:presentation>')
parts['ppt/_rels/presentation.xml.rels']=rels([('rIdMaster',REL+'slideMaster','slideMasters/slideMaster1.xml'),('rIdNotesMaster',REL+'notesMaster','notesMasters/notesMaster1.xml')]+[(f'rIdSlide{i}',REL+'slide',f'slides/slide{i}.xml') for i in range(1,len(slides)+1)]).encode()
parts['_rels/.rels']=rels([('rIdOffice',REL+'officeDocument','ppt/presentation.xml'),('rIdCore','http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties','docProps/core.xml'),('rIdApp',REL+'extended-properties','docProps/app.xml')]).encode()
xml('docProps/core.xml','<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>Sudan rainfall extremes and forecast warning signals</dc:title><dc:creator>Workshop analysis</dc:creator></cp:coreProperties>')
xml('docProps/app.xml',f'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Open XML presentation</Application><PresentationFormat>On-screen Show (16:9)</PresentationFormat><Slides>{len(slides)}</Slides></Properties>')
overrides=[('/ppt/presentation.xml','application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml'),('/ppt/theme/theme1.xml','application/vnd.openxmlformats-officedocument.theme+xml'),('/ppt/slideMasters/slideMaster1.xml','application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml'),('/ppt/slideLayouts/slideLayout1.xml','application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml'),('/ppt/notesMasters/notesMaster1.xml','application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml'),('/docProps/core.xml','application/vnd.openxmlformats-package.core-properties+xml'),('/docProps/app.xml','application/vnd.openxmlformats-officedocument.extended-properties+xml')]
for i in range(1,len(slides)+1):overrides.extend([(f'/ppt/slides/slide{i}.xml','application/vnd.openxmlformats-officedocument.presentationml.slide+xml'),(f'/ppt/notesSlides/notesSlide{i}.xml','application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml')])
xml('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'+''.join(f'<Override PartName="{p}" ContentType="{t}"/>' for p,t in overrides)+'</Types>')
BUILD.mkdir(parents=True,exist_ok=True);OUT.mkdir(exist_ok=True)
target=BUILD/'Sudan_Rainfall_Tasks_A_to_D_draft.pptx'
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
    for name,data in parts.items():archive.writestr(name,data)
expected={p.resolve() for task in 'ABCD' for p in (ROOT/f'task_{task}').glob('*.png')}
included=[s['image'].resolve() for s in slides if s['image']]
assert set(included)==expected and len(included)==len(expected)==28
manifest=dict(slides=[dict(number=i,title=s['title'],figure=str(s['image'].relative_to(ROOT)) if s['image'] else None) for i,s in enumerate(slides,1)],
    figure_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in expected},
    slide_count=len(slides),figure_count=len(expected),native_table_slides=[i for i,s in enumerate(slides,1) if '<a:tbl>' in s['objects']])
(BUILD/'slide_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(dict(draft=str(target),slides=len(slides),figures=len(included),native_table_slides=manifest['native_table_slides']),indent=2))
