"""Generate the thin cloud runner; all scientific code lives in scripts/."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    cells = []

    def markdown(source):
        cells.append({"cell_type": "markdown", "metadata": {}, "source": source.strip() + "\n"})

    def code(source):
        cells.append({"cell_type": "code", "metadata": {}, "execution_count": None,
                      "outputs": [], "source": source.strip() + "\n"})

    markdown("""
# Part A — Sudan CMORPH rainfall thresholds

Run this notebook on **Colab or Kaggle, using a CPU session with Internet enabled**.
No GPU or cloud credentials are needed. The code adapts workshop E4 and E6.

1. Upload `dist/part_a_source.zip` using Colab's Files panel, or attach it as a
   Kaggle dataset. Upload/open this notebook separately.
2. Run **Setup**, then **Inspect**. Inspect stops with a report if coverage,
   units, years or the configured 48-hour duration are unsuitable. Send that
   report back before changing the agreed settings.
3. If inspection passes, run **Extract**, **Plot**, **Review**, and **Download**.

The analysis runs in its own Python 3.12 environment via uv, independent of the
notebook kernel. Initial setup needs package downloads. Expect remote I/O;
no forecast rainfall arrays are downloaded by Part A.

Thresholds describe **annual maxima from 1998–2024**, for 24 and 48 hours and
2-, 10-, 50-year return periods. They are not observed June–August 2025 rain.
""")
    markdown("## 1. Setup — locate the uploaded source and prepare the environment")
    code('''
from pathlib import Path
import csv
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

# Set this only if automatic discovery cannot find your upload.
SOURCE_ZIP = ""
search_roots = [Path.cwd(), Path("/content"), Path("/kaggle/input")]
archives = sorted({p.resolve() for root in search_roots if root.exists()
                   for p in root.rglob("part_a_source.zip")})
if SOURCE_ZIP:
    archive = Path(SOURCE_ZIP)
elif len(archives) == 1:
    archive = archives[0]
else:
    raise RuntimeError(f"Found {len(archives)} source ZIPs. Upload part_a_source.zip, "
                       "or set SOURCE_ZIP above to the intended file's full path.")
work = Path("/kaggle/working") if Path("/kaggle/working").exists() else Path.cwd()
PROJECT_ROOT = (work / "acmad-part-a").resolve()
PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive) as bundle:
    for entry in bundle.infolist():
        target = (PROJECT_ROOT / entry.filename).resolve()
        if not target.is_relative_to(PROJECT_ROOT):
            raise ValueError("Source archive contains an unsafe path")
    bundle.extractall(PROJECT_ROOT)
subprocess.run([sys.executable, "-m", "pip", "install", "uv"], check=True)
UV = [sys.executable, "-m", "uv"]
subprocess.run(UV + ["sync", "--project", str(PROJECT_ROOT), "--python", "3.12", "--locked"], check=True)
OUT = PROJECT_ROOT / "out" / ("part_a_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))

def run_stage(stage):
    subprocess.run(UV + ["run", "--project", str(PROJECT_ROOT), "--python", "3.12",
                        "--locked", "python", "-m", "scripts.part_a_thresholds", stage,
                        "--out", str(OUT)], cwd=PROJECT_ROOT, check=True)

print("Project:", PROJECT_ROOT)
print("Results:", OUT)
print((PROJECT_ROOT / "grid.json").read_text())
''')
    markdown("""
## 2. Inspect — run this before any data extraction

Checks metadata and coordinate coverage in both stores. Confirm all town centres,
town extents and the regional extent are covered. Missing unit metadata uses E4's
explicit mm assumption and is logged; conflicting units stop execution.

If this fails, **stop here** and return `inspection.json` and `coverage.csv`.
Do not continue with partially suitable locations or silently snap to a boundary.
""")
    code('''
try:
    run_stage("inspect")
finally:
    for filename in ["inspection.json", "coverage.csv"]:
        path = OUT / filename
        if path.exists():
            print("\\n" + filename + "\\n" + path.read_text())
''')
    markdown("""
## 3. Extract — remote reads and the optional sensitivity calculation

Reads 27 annual maxima per town and duration, 30 thresholds, and the regional
10-year 24-hour map. Reads for towns share source chunks. A chunk may contain a
whole map even when only town pixels are requested.

The extension refits a Gumbel distribution with and without one largest year.
Compare both refits to isolate the removal effect; the stored fit may use a
different estimator. A successful run writes a manifest and quality checks.
""")
    code('''
run_stage("extract")
manifest = json.loads((OUT / "manifest.json").read_text())
print(json.dumps(manifest["quality_checks"], indent=2))
''')
    markdown("## 4. Plot — uses the exported cache without further remote reads")
    code('''
run_stage("plots")
from IPython.display import Image, display
for figure in sorted((OUT / "figures").glob("*.png")):
    print(figure.name)
    display(Image(filename=str(figure)))
''')
    markdown("""
## 5. Review before sharing

- Expect **30 thresholds**, **270 annual maxima**, five town figures and one map.
- Confirm the selected pixels, units and reference years; examine the top-three
  labelled years at each town. `fit_departures.csv` describes departures, not a
  formal rejection test or proof that those observations are wrong.
- Examine the 50-year sensitivity, including the full-refit versus stored difference.
- The second duration has its own accumulation period. B/C use **24hr** rows only.
- Discuss the short record, extrapolation, satellite measurement uncertainty,
  nearest-pixel sampling and the lack of observed 2025 rainfall.
""")
    code('''
for filename in ["coverage.csv", "thresholds.csv", "fit_departures.csv", "sensitivity_50yr.csv"]:
    print("\\n" + filename)
    rows = list(csv.DictReader((OUT / filename).open()))
    print("Rows:", len(rows))
    for row in rows:
        print(row)
assert len(list(csv.DictReader((OUT / "thresholds.csv").open()))) == 30
assert len(list(csv.DictReader((OUT / "annual_maxima.csv").open()))) == 270
''')
    markdown("""
## 6. Download the result bundle

Download the ZIP using the link below (on Kaggle, also available in notebook
outputs). Send it back for review and integration. It contains the tables, figures,
map cache, settings, provenance, and source ZIP. Keep generated results out of Git;
the group should share the reviewed thresholds as an artifact with the source revision.
""")
    code('''
result_zip = work / "part_a_results.zip"
with zipfile.ZipFile(result_zip, "w", zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted(OUT.rglob("*")):
        if path.is_file():
            bundle.write(path, Path("results") / path.relative_to(OUT))
    bundle.write(archive, "part_a_source.zip")
try:
    from google.colab import files
except ImportError:
    from IPython.display import FileLink, display
    display(FileLink(str(result_zip)))
else:
    files.download(str(result_zip))
print("Download:", result_zip)
''')
    notebook = {"cells": cells, "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"}}, "nbformat": 4, "nbformat_minor": 5}
    for i, cell in enumerate(cells):
        cell["id"] = f"part-a-{i:02d}"
    target = ROOT / "notebooks" / "part_a_thresholds.ipynb"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(notebook, indent=2) + "\n")
    print(target)


if __name__ == "__main__":
    build()
