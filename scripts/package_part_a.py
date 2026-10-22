"""Package only project source for upload to Colab or a Kaggle dataset."""

import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.common import ROOT


def package(destination=None):
    destination = Path(destination or ROOT / "dist" / "part_a_source.zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / name for name in ["grid.json", "pyproject.toml", "uv.lock", "README.md"]]
    sources += sorted((ROOT / "scripts").glob("*.py"))
    sources += sorted((ROOT / "tests").glob("*.py"))
    sources += sorted((ROOT / "notebooks").glob("*.ipynb"))
    revision = {}
    for key, args in [("git_commit", ["rev-parse", "HEAD"]), ("git_status", ["status", "--short"])]:
        try:
            revision[key] = subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                                     stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            revision[key] = "unavailable"
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for path in sources:
            archive.write(path, path.relative_to(ROOT))
        archive.writestr("source_revision.json", json.dumps(revision, indent=2) + "\n")
    print(destination)
    return destination


if __name__ == "__main__":
    package()
