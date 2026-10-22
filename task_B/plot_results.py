"""Redraw Part B from saved counts, without downloading rainfall."""
from pathlib import Path
import os
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parent


def render(root=ROOT):
    os.environ.setdefault('MPLCONFIGDIR', str(root / '.matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    import pandas as pd

    data = pd.read_csv(root / 'daily_member_counts.csv')
    towns = data.town.drop_duplicates().tolist()
    thresholds = [('20mm', 'Fixed threshold', '#2479ae'),
                  ('2yr', '2-year annual level', '#d48716'),
                  ('10yr', '10-year annual level', '#338363')]
    upper = max(3, int(data.members_above.max()) + 1)
    members = int(data.members.iloc[0])
    initialization = data.initialization.iloc[0]

    def panel(ax, town, threshold, label, color):
        rows = data[(data.town == town) & (data.threshold == threshold)].sort_values('forecast_day')
        days, counts = rows.forecast_day, rows.members_above
        depth = float(rows.threshold_mm.iloc[0])
        ax.bar(days, counts, color=color, width=.55, alpha=.85)
        ax.scatter(days, counts, color=color, s=28, zorder=3)
        for day, count in zip(days, counts):
            ax.annotate(str(count), (day, count), xytext=(0, 6), textcoords='offset points',
                        ha='center', color=color, weight='bold', fontsize=10)
        ax.set(title=f'{label}: > {depth:.2f} mm in 24 h', xticks=list(days),
               ylim=(-.12, upper), ylabel=f'Members (of {members})')
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(axis='y', alpha=.2)
        ax.set_axisbelow(True)
        ax.spines[['top', 'right']].set_visible(False)
        if not counts.any():
            ax.text(.5, .6, 'No exceedances', transform=ax.transAxes, ha='center', color='#666666')

    for town in towns:
        fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, layout='constrained')
        for ax, (threshold, label, color) in zip(axes, thresholds):
            panel(ax, town, threshold, label, color)
        axes[-1].set_xlabel('Forecast day — each interval is 24 hours')
        fig.suptitle(f'{town} | forecast initialized {initialization}\n'
                     f'{members} ensemble members • numbers above markers are exact counts', fontsize=14)
        fig.savefig(root / f'{town.lower().replace(" ", "_")}_threshold_counts.png', dpi=180)
        plt.close(fig)

    fig, axes = plt.subplots(3, len(towns), figsize=(7*len(towns), 9), squeeze=False,
                             sharex=True, sharey=True, layout='constrained')
    for col, town in enumerate(towns):
        for row, (threshold, label, color) in enumerate(thresholds):
            panel(axes[row, col], town, threshold, label, color)
            if row == 0:
                axes[row, col].set_title(town+'\n'+axes[row, col].get_title(), fontsize=13)
        axes[-1, col].set_xlabel('Forecast day (24-hour intervals)')
    fig.suptitle(f'Which threshold is exceeded? | Forecast initialized {initialization}\n'
                 f'Counts out of {members} members • rainfall thresholds in mm in 24 h • strict >', fontsize=15)
    target = root / 'two_town_threshold_comparison.png'
    fig.savefig(target, dpi=180)
    plt.close(fig)
    revision = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    (root / 'figure_provenance.json').write_text(json.dumps(dict(
        plotting_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        counts_sha256=hashlib.sha256((root/'daily_member_counts.csv').read_bytes()).hexdigest(),
        git_commit=revision.stdout.strip() if revision.returncode == 0 else None), indent=2)+'\n')
    print('Updated town plots and', target, flush=True)


if __name__ == '__main__':
    render()
