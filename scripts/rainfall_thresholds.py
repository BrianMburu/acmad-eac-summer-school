"""Observed rainfall thresholds from CMORPH, adapted from workshop E4/E6.

Stages: inspect (metadata/coordinates), extract (remote data), plots (offline).
Run with: uv run python -m scripts.rainfall_thresholds --help
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import tempfile
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import gumbel_r

from scripts.common import (
    ROOT,
    ConfigError,
    box_inside,
    config_hash,
    extraction_hash,
    inside,
    load_config,
    migrate_legacy,
    slugify,
    validate_common,
    validate_thresholds,
)
from scripts.data_access import domain, open_store, town_indexers
from scripts.return_levels import (
    empirical_positions,
    gumbel_reduced_variate,
    gumbel_return_level,
)
from scripts.validation import units_report


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_status(out, status, *, filename="run_status.json", **extra):
    write_json(out / filename,
               {"status": status, "updated_utc": datetime.now(UTC).isoformat(), **extra})


def require_complete_run(out):
    """Refuse to plot a run that failed or never completed.

    Runs produced before this marker existed have no run_status.json and remain
    readable; the manifest checks still apply to them.
    """
    path = out / "run_status.json"
    if not path.exists():
        return
    status = json.loads(path.read_text()).get("status")
    if status != "ok":
        raise ValueError(f"Run status is {status!r}, not 'ok'; re-run extract before plotting ({path})")


def inspect_stores(obs, forecast, config):
    """Read coordinates/metadata only and collect the problems found.

    Invalid coordinate order raises immediately from ``domain``; other missing
    variables/levels/coverage are reported together in ``problems``.
    """
    cm_domain = domain(obs, "lat", "lon", ascending=config["cmorph_reference"]["latitude_order"] == "ascending")
    fc_domain = domain(forecast, "latitude", "longitude", ascending=config["forecast"]["latitude_order"] == "ascending")
    ref = config["cmorph_reference"]
    expected_years = list(range(ref["reference_start_year"], ref["reference_end_year"] + 1))
    durations = obs.duration.values.tolist()
    periods = obs.return_period.values.tolist()
    years = obs.year.values.tolist()
    problems = []
    if not set(config["thresholds"]["durations"]) <= set(durations):
        problems.append(f"Requested durations unavailable; available durations: {durations}")
    if not set(config["thresholds"]["return_periods_years"]) <= set(periods):
        problems.append(f"Requested return periods unavailable; available values: {periods}")
    if sorted(years) != expected_years:
        problems.append(f"Expected exactly the years {expected_years[0]}–{expected_years[-1]}; got {years}")
    units = {}
    for variable in [ref["variable"], ref["annual_maxima_variable"]]:
        if variable not in obs:
            problems.append(f"Missing CMORPH variable: {variable}")
            continue
        units[variable] = units_report(obs[variable], config["thresholds"].get("units_if_missing"))
        if not units[variable]["accepted_as_mm_depth"]:
            problems.append(f"Unsupported rainfall-depth units for {variable}: {units[variable]}")
    rows = []
    for town in config["towns"]:
        lat, lon = town["latitude"], town["longitude"]
        cm_ok, fc_ok = inside(cm_domain, lat, lon), inside(fc_domain, lat, lon)
        row = {"town": town["name"], "requested_latitude": lat, "requested_longitude": lon,
               "inside_cmorph": cm_ok, "inside_forecast": fc_ok,
               "extent_inside_cmorph": box_inside(cm_domain, town["extent"]),
               "extent_inside_forecast": box_inside(fc_domain, town["extent"])}
        # Do not silently snap an out-of-domain town to a boundary pixel (E6).
        if cm_ok:
            row.update(cmorph_latitude=float(obs.lat.sel(lat=lat, method="nearest")),
                       cmorph_longitude=float(obs.lon.sel(lon=lon, method="nearest")))
        if fc_ok:
            row.update(forecast_latitude=float(forecast.latitude.sel(latitude=lat, method="nearest")),
                       forecast_longitude=float(forecast.longitude.sel(longitude=lon, method="nearest")))
        if not all([cm_ok, fc_ok, row["extent_inside_cmorph"], row["extent_inside_forecast"]]):
            problems.append(f"{town['name']} or its extent is outside a dataset; review coverage.csv")
        rows.append(row)
    region_coverage = {"cmorph": box_inside(cm_domain, config["region_extent"]),
                       "forecast": box_inside(fc_domain, config["region_extent"])}
    if not all(region_coverage.values()):
        problems.append("Regional extent is outside a dataset; review region coverage before changing towns/box")
    report = {"cmorph_domain": cm_domain, "forecast_domain": fc_domain,
              "region_inside": region_coverage, "available_durations": durations,
              "available_return_periods": periods, "years": years, "units": units,
              "cmorph_sizes": dict(obs.sizes), "forecast_sizes": dict(forecast.sizes),
              "cmorph_chunks": {name: obs[name].encoding.get("chunks") for name in units},
              "forecast_data_read": False, "problems": problems}
    return report, pd.DataFrame(rows)


def extract_arrays(obs, config):
    ref, settings = config["cmorph_reference"], config["thresholds"]
    indexers = town_indexers(config)
    # Combine all town/duration reads in one graph, sharing map-chunk fetches.
    points = obs[[ref["variable"], ref["annual_maxima_variable"]]].sel(
        duration=settings["durations"], return_period=settings["return_periods_years"]
    ).sel(**indexers, method="nearest").sel(
        year=slice(ref["reference_start_year"], ref["reference_end_year"]))
    box = config["region_extent"]
    lat_bounds = ((box["south"], box["north"]) if ref["latitude_order"] == "ascending"
                  else (box["north"], box["south"]))
    regional = obs[ref["variable"]].sel(duration=settings["map_duration"],
                                       return_period=settings["map_return_period_years"]).sel(
        lat=slice(*lat_bounds), lon=slice(box["west"], box["east"]))
    # Include the map in the same compute: its source chunk can also serve town reads.
    import dask
    points, regional = dask.compute(points, regional, scheduler="threads",
                                    num_workers=config["execution"]["workers"])
    return points, regional


def validate_arrays(points, regional, config):
    ref = config["cmorph_reference"]
    for variable in [ref["variable"], ref["annual_maxima_variable"]]:
        if not np.isfinite(points[variable].values).all():
            raise ValueError(f"Missing/nonfinite town values in {variable}; no thresholds exported")
        if (points[variable].values < 0).any():
            raise ValueError(f"Negative rainfall in {variable}")
    thresholds = points[ref["variable"]].sortby("return_period")
    if (thresholds.diff("return_period").values < 0).any():
        raise ValueError("Return levels decrease with return period")
    if regional.sizes["lat"] < 2 or regional.sizes["lon"] < 2:
        raise ValueError("Regional map has fewer than two pixels on an axis")
    finite = np.isfinite(regional.values)
    if not finite.any() or np.isinf(regional.values).any() or (regional.values[finite] < 0).any():
        raise ValueError("Invalid regional threshold map")
    return {"town_values_finite": True, "nonnegative": True,
            "return_levels_nondecreasing": True,
            "regional_missing_pixels": int((~finite).sum()),
            "regional_total_pixels": int(finite.size)}


def tables(points, config):
    ref = config["cmorph_reference"]
    requested = pd.DataFrame(config["towns"])[["name", "latitude", "longitude"]].rename(
        columns={"name": "town", "latitude": "requested_latitude", "longitude": "requested_longitude"})

    def frame(variable, value_name):
        df = points[variable].to_dataframe(name=value_name).reset_index()
        df = df.rename(columns={"lat": "cmorph_latitude", "lon": "cmorph_longitude",
                                "return_period": "return_period_years"})
        return df.merge(requested, on="town", validate="many_to_one")

    thresholds = frame(ref["variable"], "threshold_mm")
    maxima = frame(ref["annual_maxima_variable"], "rainfall_mm")
    for df in [thresholds, maxima]:
        df["units"] = "mm"
        df["reference_start_year"] = ref["reference_start_year"]
        df["reference_end_year"] = ref["reference_end_year"]
    return thresholds, maxima


def diagnostics(thresholds, maxima):
    """Describe candidate departures; these are not formal fit-test rejections."""
    departures, sensitivity = [], []
    for (town, duration), group in maxima.groupby(["town", "duration"], sort=False):
        group = group.sort_values("year")
        values = group.rainfall_mm.to_numpy()
        levels = thresholds[(thresholds.town == town) & (thresholds.duration == duration)].sort_values(
            "return_period_years")
        order, periods = empirical_positions(values)
        # Gumbel levels are linear in the reduced variate. Top-three empirical
        # periods (28, 14, 9.33 years) lie within the stored 2–50-year range.
        for rank, idx in enumerate(order[:3]):
            expected = np.interp(gumbel_reduced_variate(periods[rank]),
                                 gumbel_reduced_variate(levels.return_period_years.to_numpy()),
                                 levels.threshold_mm)
            departures.append({"town": town, "duration": duration, "rank": rank + 1,
                               "year": int(group.iloc[idx].year), "rainfall_mm": float(values[idx]),
                               "empirical_return_period_years": float(periods[rank]),
                               "stored_curve_mm": float(expected),
                               "departure_mm": float(values[idx] - expected)})
        stored = float(levels.loc[levels.return_period_years == 50, "threshold_mm"].iloc[0])
        if np.ptp(values) == 0 or np.ptp(np.delete(values, order[0])) == 0:
            sensitivity.append({"town": town, "duration": duration, "status": "constant series; no Gumbel fit"})
            continue
        loc, scale = gumbel_r.fit(values)
        trim_loc, trim_scale = gumbel_r.fit(np.delete(values, order[0]))
        full = float(gumbel_return_level(loc, scale, 50))
        trimmed = float(gumbel_return_level(trim_loc, trim_scale, 50))
        sensitivity.append({"town": town, "duration": duration, "status": "ok",
                            "method": "scipy.stats.gumbel_r maximum likelihood",
                            "removed_year": int(group.iloc[order[0]].year),
                            "removed_rainfall_mm": float(values[order[0]]),
                            "stored_50yr_mm": stored, "refit_full_50yr_mm": full,
                            "refit_without_largest_50yr_mm": trimmed,
                            "refit_minus_stored_mm": full - stored,
                            "change_mm": trimmed - full,
                            "change_percent": 100 * (trimmed - full) / full if full else None})
    return pd.DataFrame(departures), pd.DataFrame(sensitivity)


def provenance(config, snapshots):
    def git(*args):
        try:
            return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                           stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return "unavailable (not a Git checkout)"
    return {"created_utc": datetime.now(UTC).isoformat(),
            "config_sha256": config_hash(config), "extraction_sha256": extraction_hash(config),
            "store_snapshots": snapshots,
            "git_commit": git("rev-parse", "HEAD"), "git_status": git("status", "--short"),
            "python": platform.python_version(),
            "packages": {p: importlib.metadata.version(p) for p in
                         ["icechunk", "zarr", "xarray", "dask", "numpy", "pandas", "scipy", "matplotlib"]},
            "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted((ROOT / "scripts").glob("*.py"))},
            "adapted_from": ["workshop E4: CMORPH extraction and return-level plots",
                             "workshop E6: explicit domain checks before nearest selection"],
            "interpretation": "Historical annual-maxima thresholds, not JJA-only thresholds or observed 2025 rainfall.",
            "sensitivity_note": "Leave-largest-out uses the same MLE method for both refits. Stored fit method may differ. Tied maxima: remove earliest year only."}


def regional_map_name(config, suffix):
    settings = config["thresholds"]
    return f"regional_{settings['map_return_period_years']}yr_{settings['map_duration']}.{suffix}"


RESULT_PATTERNS = ("thresholds.csv", "annual_maxima.csv", "fit_departures.csv",
                   "sensitivity_50yr.csv", "settings_used.json", "manifest.json",
                   "regional_*.npz")


def promote_results(staging, out):
    """Atomically replace a previous run's results with the staged files.

    The manifest is moved last. If anything fails, run_status.json stays
    non-ok, so plotting refuses the possibly mixed directory.
    """
    produced = {path.name for path in staging.iterdir()}
    for pattern in RESULT_PATTERNS:
        for old in out.glob(pattern):
            if old.name not in produced:
                old.unlink()
    for path in sorted(staging.iterdir(), key=lambda p: p.name == "manifest.json"):
        os.replace(path, out / path.name)


def run_remote(config, out, inspection_only=False):
    validate_common(config)
    validate_thresholds(config)
    out.mkdir(parents=True, exist_ok=True)
    # A metadata inspection has its own status and cannot invalidate an extraction.
    status_file = "inspection_status.json" if inspection_only else "run_status.json"
    write_status(out, "running", filename=status_file, stage="inspect")
    stage = "inspect"
    try:
        with ExitStack() as resources:
            obs, obs_snapshot = open_store(config["cmorph_reference"])
            resources.callback(obs.close)
            forecast, fc_snapshot = open_store(config["forecast"])
            resources.callback(forecast.close)
            report, coverage = inspect_stores(obs, forecast, config)
            report["config_sha256"] = config_hash(config)
            report["extraction_sha256"] = extraction_hash(config)
            report["store_snapshots"] = {"cmorph": obs_snapshot, "forecast": fc_snapshot}
            write_json(out / "inspection.json", report)
            coverage.to_csv(out / "coverage.csv", index=False)
            print(json.dumps(report, indent=2))
            print(coverage.to_string(index=False))
            if report["problems"]:
                raise ValueError("Inspection failed; review inspection.json and coverage.csv. "
                                 "No new thresholds were written.")
            if inspection_only:
                write_status(out, "ok", filename=status_file, stage="inspect")
                print("Inspection passed. Run extract to generate or refresh results.")
                return
            stage = "extract"
            write_status(out, "running", filename=status_file, stage=stage)
            # Stage every result, then promote it together. A failed run therefore
            # cannot leave new tables beside an old manifest or map.
            with tempfile.TemporaryDirectory(prefix=".extract-", dir=out) as tmp:
                staging = Path(tmp)
                points, regional = extract_arrays(obs, config)
                quality = validate_arrays(points, regional, config)
                thresholds, maxima = tables(points, config)
                departures, sensitivity = diagnostics(thresholds, maxima)
                thresholds.to_csv(staging / "thresholds.csv", index=False)
                maxima.to_csv(staging / "annual_maxima.csv", index=False)
                departures.to_csv(staging / "fit_departures.csv", index=False)
                sensitivity.to_csv(staging / "sensitivity_50yr.csv", index=False)
                map_name = regional_map_name(config, "npz")
                np.savez_compressed(staging / map_name, latitude=regional.lat.values,
                                    longitude=regional.lon.values, threshold_mm=regional.values)
                write_json(staging / "settings_used.json", config)
                manifest = provenance(config, {"cmorph": obs_snapshot, "forecast": fc_snapshot})
                manifest["quality_checks"] = quality
                manifest["inspection"] = report
                manifest["output_sha256"] = {
                    name: file_sha256(staging / name) for name in
                    ["thresholds.csv", "annual_maxima.csv", "fit_departures.csv",
                     "sensitivity_50yr.csv", map_name, "settings_used.json"]}
                write_json(staging / "manifest.json", manifest)
                promote_results(staging, out)
            write_status(out, "ok", filename=status_file, stage="complete")
            print(f"Extracted {len(thresholds)} thresholds and {len(maxima)} annual maxima to {out}")
    except Exception as exc:
        write_status(out, "failed", filename=status_file, stage=stage, error=str(exc))
        raise


def verify_saved_settings(config, out):
    """Verify settings, snapshot and result checksums against the manifest."""
    manifest = json.loads((out / "manifest.json").read_text())
    expected_extraction = manifest.get("extraction_sha256")
    if expected_extraction is not None:
        if expected_extraction != extraction_hash(config):
            raise ValueError("Observed-extraction settings differ from the extracted data. "
                             "Re-extract or use settings_used.json.")
    elif manifest.get("config_sha256") != config_hash(config):
        # Older runs hashed their full v1 JSON. Verify that original hash and
        # require exact equality after migration, rather than dropping the check.
        saved_path = out / "settings_used.json"
        saved = json.loads(saved_path.read_text()) if saved_path.exists() else None
        if (saved is None or manifest.get("config_sha256") != config_hash(saved)
                or migrate_legacy(saved) != config):
            raise ValueError("Settings differ from the extracted data. Re-extract or use settings_used.json.")
    expected_snapshot = config["cmorph_reference"]["snapshot_id"]
    actual_snapshot = manifest.get("store_snapshots", {}).get("cmorph")
    if expected_snapshot and actual_snapshot and expected_snapshot != actual_snapshot:
        raise ValueError(f"Configured CMORPH snapshot {expected_snapshot} differs from extracted snapshot "
                         f"{actual_snapshot}; re-extract with the current settings.")
    for name, digest in manifest.get("output_sha256", {}).items():
        path = out / name
        if not path.exists() or file_sha256(path) != digest:
            raise ValueError(f"Result file {name} is missing or does not match manifest.json; re-extract.")


def plot_outputs(config, out):
    """Offline plotting from the small exported tables and map cache."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    validate_common(config)
    validate_thresholds(config)
    require_complete_run(out)
    verify_saved_settings(config, out)
    thresholds = pd.read_csv(out / "thresholds.csv")
    maxima = pd.read_csv(out / "annual_maxima.csv")
    figures = out / "figures"
    # savefig replaces each named output; unrelated files are left untouched.
    figures.mkdir(exist_ok=True)
    for town in config["towns"]:
        fig, axes = plt.subplots(2, 2, figsize=(13, 9), squeeze=False)
        for row, duration in enumerate(config["thresholds"]["durations"]):
            data = maxima[(maxima.town == town["name"]) & (maxima.duration == duration)].sort_values("year")
            levels = thresholds[(thresholds.town == town["name"]) & (thresholds.duration == duration)].sort_values("return_period_years")
            ax = axes[row, 0]
            ax.bar(data.year, data.rainfall_mm, color="steelblue")
            for level, colour in zip(levels.itertuples(), ["grey", "darkorange", "crimson"]):
                ax.axhline(level.threshold_mm, color=colour, linestyle="--",
                           label=f"{level.return_period_years}-year: {level.threshold_mm:.1f} mm")
            ax.set(title=f"{duration}: annual maxima", xlabel="Year", ylabel=f"Rainfall depth (mm / {duration})")
            ax.legend(fontsize=8)
            ax = axes[row, 1]
            order, periods = empirical_positions(data.rainfall_mm)
            # Connect stored levels linearly in the Gumbel reduced variate.
            smooth_t = np.geomspace(2, 50, 150)
            curve = np.interp(gumbel_reduced_variate(smooth_t),
                              gumbel_reduced_variate(levels.return_period_years.to_numpy()),
                              levels.threshold_mm)
            ax.semilogx(smooth_t, curve, color="crimson", label="Stored Gumbel levels (2–50 years)")
            ax.scatter(levels.return_period_years, levels.threshold_mm, color="crimson")
            sorted_values = data.rainfall_mm.to_numpy()[order]
            ax.scatter(periods, sorted_values, color="black", s=18, label="Observed maxima (Weibull ranks)")
            for idx, period, value in zip(order[:3], periods[:3], sorted_values[:3]):
                ax.annotate(str(int(data.iloc[idx].year)), (period, value), xytext=(4, 5), textcoords="offset points", fontsize=8)
            ax.set(title=f"{duration}: fit versus observations", xlabel="Return period (years)", ylabel=f"Rainfall depth (mm / {duration})")
            ax.legend(fontsize=8)
            ax.grid(alpha=.3, which="both")
        ref = config["cmorph_reference"]
        years = ref["reference_end_year"] - ref["reference_start_year"] + 1
        fig.suptitle(f"{town['name']}: CMORPH annual maxima, {ref['reference_start_year']}–{ref['reference_end_year']}\n"
                     f"Nearest town-centre pixel; 50-year levels extrapolate beyond {years} years")
        fig.tight_layout()
        fig.savefig(figures / f"{slugify(town['name'])}_return_levels.png", dpi=150)
        plt.close(fig)
    duration = config["thresholds"]["map_duration"]
    period = config["thresholds"]["map_return_period_years"]
    with np.load(out / regional_map_name(config, "npz")) as grid:
        fig, ax = plt.subplots(figsize=(12, 6))
        mesh = ax.pcolormesh(grid["longitude"], grid["latitude"], np.ma.masked_invalid(grid["threshold_mm"]),
                             shading="auto", cmap="YlGnBu")
        fig.colorbar(mesh, ax=ax, label=f"{period}-year rainfall depth (mm over {duration})")
    for town in config["towns"]:
        ax.plot(town["longitude"], town["latitude"], "r^", markersize=6)
        near_east = town["longitude"] > config["region_extent"]["east"] - 1
        ax.annotate(town["name"], (town["longitude"], town["latitude"]),
                    xytext=(-5 if near_east else 5, 5), textcoords="offset points",
                    ha="right" if near_east else "left")
    box = config["region_extent"]
    ax.set(xlim=(box["west"], box["east"]), ylim=(box["south"], box["north"]),
           title=f"CMORPH {ref['reference_start_year']}–{ref['reference_end_year']}: {period}-year, {duration} rainfall level\n"
                 f"{config['country']} study box (box also includes neighbouring areas)",
           xlabel="Longitude (°E)", ylabel="Latitude (°N)", aspect="equal")
    fig.tight_layout()
    fig.savefig(figures / regional_map_name(config, "png"), dpi=150)
    plt.close(fig)
    print(f"Saved {len(config['towns'])} town figures and one regional map in {figures}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["inspect", "extract", "plots"])
    parser.add_argument("--config", type=Path, help="optional JSON override or saved settings; defaults to scripts/common.py")
    parser.add_argument("--out", type=Path, help="output directory; defaults to execution.output_directory")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        validate_thresholds(config)
    except ConfigError as exc:
        parser.error(str(exc))
    out = args.out or ROOT / config["execution"]["output_directory"]
    if args.stage == "plots":
        plot_outputs(config, out)
    else:
        run_remote(config, out, inspection_only=args.stage == "inspect")


if __name__ == "__main__":
    main()
