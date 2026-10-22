"""CMORPH Part A, adapted from workshop E4 with E6 coverage checks.

Stages: inspect (metadata/coordinates), extract (remote data), plots (offline).
Run with: uv run python -m scripts.part_a_thresholds --help
"""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from scipy.stats import gumbel_r

from scripts.common import (
    ROOT, box_inside, domain, inside, load_config, open_store, town_indexers,
)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def config_hash(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def units_report(array, config):
    raw = array.attrs.get("units")
    effective = raw or config["part_a"].get("units_if_missing")
    accepted = {"mm", "millimeter", "millimeters", "millimetre", "millimetres",
                "kg m-2", "kg m^-2", "kg/m2", "kg m**-2"}
    return {"source_units": raw, "effective_units": effective,
            "accepted_as_mm_depth": str(effective).strip().lower() in accepted,
            "used_workshop_fallback": not bool(raw)}


def inspect_stores(obs, forecast, config):
    """Read coordinates/metadata only. Report all problems before stopping."""
    cm_domain = domain(obs, "lat", "lon", ascending=True)
    fc_domain = domain(forecast, "latitude", "longitude", ascending=False)
    ref = config["cmorph_reference"]
    expected_years = list(range(ref["reference_start_year"], ref["reference_end_year"] + 1))
    durations = obs.duration.values.tolist()
    periods = obs.return_period.values.tolist()
    years = obs.year.values.tolist()
    problems = []
    if not set(config["part_a"]["durations"]) <= set(durations):
        problems.append(f"Requested durations unavailable; available durations: {durations}")
    if not set(config["part_a"]["return_periods_years"]) <= set(periods):
        problems.append(f"Requested return periods unavailable; available values: {periods}")
    if sorted(years) != expected_years:
        problems.append(f"Expected exactly the years {expected_years[0]}–{expected_years[-1]}; got {years}")
    units = {}
    for variable in [ref["variable"], ref["annual_maxima_variable"]]:
        if variable not in obs:
            problems.append(f"Missing CMORPH variable: {variable}")
            continue
        units[variable] = units_report(obs[variable], config)
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
    ref, settings = config["cmorph_reference"], config["part_a"]
    indexers = town_indexers(config)
    # Combine all town/duration reads in one graph, sharing map-chunk fetches.
    points = obs[[ref["variable"], ref["annual_maxima_variable"]]].sel(
        duration=settings["durations"], return_period=settings["return_periods_years"]
    ).sel(**indexers, method="nearest").sel(
        year=slice(ref["reference_start_year"], ref["reference_end_year"]))
    box = config["region_extent"]
    regional = obs[ref["variable"]].sel(duration="24hr", return_period=10).sel(
        lat=slice(box["south"], box["north"]), lon=slice(box["west"], box["east"]))
    # Include the map in the same compute: its source chunk can also serve town reads.
    import dask
    points, regional = dask.compute(points, regional, scheduler="threads", num_workers=2)
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


def empirical_positions(values):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("Empirical positions require a finite, nonempty 1D series")
    order = np.argsort(-values, kind="stable")
    return order, (len(values) + 1) / np.arange(1, len(values) + 1)


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
        reduced = lambda t: -np.log(-np.log1p(-1 / np.asarray(t, dtype=float)))
        for rank, idx in enumerate(order[:3]):
            expected = np.interp(reduced(periods[rank]), reduced(levels.return_period_years), levels.threshold_mm)
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
        full = float(gumbel_r.isf(1 / 50, loc=loc, scale=scale))
        trimmed = float(gumbel_r.isf(1 / 50, loc=trim_loc, scale=trim_scale))
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
            return "unavailable (uploaded source bundle)"
    return {"created_utc": datetime.now(timezone.utc).isoformat(),
            "config_sha256": config_hash(config), "store_snapshots": snapshots,
            "git_commit": git("rev-parse", "HEAD"), "git_status": git("status", "--short"),
            "source_bundle_revision": json.loads((ROOT / "source_revision.json").read_text())
                                      if (ROOT / "source_revision.json").exists() else None,
            "python": platform.python_version(),
            "packages": {p: importlib.metadata.version(p) for p in
                         ["icechunk", "zarr", "xarray", "dask", "numpy", "pandas", "scipy", "matplotlib"]},
            "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted((ROOT / "scripts").glob("*.py"))},
            "adapted_from": ["workshop E4: CMORPH extraction and return-level plots",
                             "workshop E6: explicit domain checks before nearest selection"],
            "interpretation": "Historical annual-maxima thresholds, not JJA-only thresholds or observed 2025 rainfall.",
            "sensitivity_note": "Leave-largest-out uses the same MLE method for both refits. Stored fit method may differ. Tied maxima: remove earliest year only."}


def run_remote(config, out, inspection_only=False):
    out.mkdir(parents=True, exist_ok=True)
    obs, obs_snapshot = open_store(config["cmorph_reference"])
    forecast, fc_snapshot = open_store(config["forecast"])
    try:
        report, coverage = inspect_stores(obs, forecast, config)
        report["config_sha256"] = config_hash(config)
        report["store_snapshots"] = {"cmorph": obs_snapshot, "forecast": fc_snapshot}
        write_json(out / "inspection.json", report)
        coverage.to_csv(out / "coverage.csv", index=False)
        print(json.dumps(report, indent=2))
        print(coverage.to_string(index=False))
        if report["problems"]:
            raise ValueError("Inspection failed; review inspection.json and coverage.csv. "
                             "Do not use any previous thresholds in this output directory.")
        if inspection_only:
            print("Inspection passed. Run the extraction cell next.")
            return
        points, regional = extract_arrays(obs, config)
        quality = validate_arrays(points, regional, config)
        thresholds, maxima = tables(points, config)
        departures, sensitivity = diagnostics(thresholds, maxima)
        thresholds.to_csv(out / "thresholds.csv", index=False)
        maxima.to_csv(out / "annual_maxima.csv", index=False)
        departures.to_csv(out / "fit_departures.csv", index=False)
        sensitivity.to_csv(out / "sensitivity_50yr.csv", index=False)
        np.savez_compressed(out / "regional_10yr_24hr.npz", latitude=regional.lat.values,
                            longitude=regional.lon.values, threshold_mm=regional.values)
        write_json(out / "settings_used.json", config)
        manifest = provenance(config, {"cmorph": obs_snapshot, "forecast": fc_snapshot})
        manifest["quality_checks"] = quality
        manifest["inspection"] = report
        write_json(out / "manifest.json", manifest)
        print(f"Extracted {len(thresholds)} thresholds and {len(maxima)} annual maxima to {out}")
    finally:
        obs.close()
        forecast.close()


def plot_outputs(config, out):
    """Offline plotting from the small exported tables and map cache."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    manifest = json.loads((out / "manifest.json").read_text())
    if manifest["config_sha256"] != config_hash(config):
        raise ValueError("Settings differ from the extracted data. Re-extract or use settings_used.json.")
    thresholds = pd.read_csv(out / "thresholds.csv")
    maxima = pd.read_csv(out / "annual_maxima.csv")
    figures = out / "figures"
    figures.mkdir(exist_ok=True)
    for town in config["towns"]:
        fig, axes = plt.subplots(2, 2, figsize=(13, 9), squeeze=False)
        for row, duration in enumerate(config["part_a"]["durations"]):
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
            reduced = lambda t: -np.log(-np.log1p(-1 / np.asarray(t)))
            curve = np.interp(reduced(smooth_t), reduced(levels.return_period_years.to_numpy()), levels.threshold_mm)
            ax.semilogx(smooth_t, curve, color="crimson", label="Stored Gumbel levels (2–50 years)")
            ax.scatter(levels.return_period_years, levels.threshold_mm, color="crimson")
            sorted_values = data.rainfall_mm.to_numpy()[order]
            ax.scatter(periods, sorted_values, color="black", s=18, label="Observed maxima (Weibull ranks)")
            for idx, period, value in zip(order[:3], periods[:3], sorted_values[:3]):
                ax.annotate(str(int(data.iloc[idx].year)), (period, value), xytext=(4, 5), textcoords="offset points", fontsize=8)
            ax.set(title=f"{duration}: fit versus observations", xlabel="Return period (years)", ylabel=f"Rainfall depth (mm / {duration})")
            ax.legend(fontsize=8)
            ax.grid(alpha=.3, which="both")
        fig.suptitle(f"{town['name']}: CMORPH annual maxima, 1998–2024\nNearest town-centre pixel; 50-year levels extrapolate beyond 27 years")
        fig.tight_layout()
        fig.savefig(figures / f"{town['name'].lower().replace(' ', '_')}_return_levels.png", dpi=150)
        plt.close(fig)
    with np.load(out / "regional_10yr_24hr.npz") as grid:
        fig, ax = plt.subplots(figsize=(12, 6))
        mesh = ax.pcolormesh(grid["longitude"], grid["latitude"], np.ma.masked_invalid(grid["threshold_mm"]),
                             shading="auto", cmap="YlGnBu")
        fig.colorbar(mesh, ax=ax, label="10-year rainfall depth (mm in 24 hours)")
    for town in config["towns"]:
        ax.plot(town["longitude"], town["latitude"], "r^", markersize=6)
        near_east = town["longitude"] > config["region_extent"]["east"] - 1
        ax.annotate(town["name"], (town["longitude"], town["latitude"]),
                    xytext=(-5 if near_east else 5, 5), textcoords="offset points",
                    ha="right" if near_east else "left")
    box = config["region_extent"]
    ax.set(xlim=(box["west"], box["east"]), ylim=(box["south"], box["north"]),
           title="CMORPH 1998–2024: 10-year, 24-hour rainfall level\nSudan study box (box also includes neighbouring areas)",
           xlabel="Longitude (°E)", ylabel="Latitude (°N)", aspect="equal")
    fig.tight_layout()
    fig.savefig(figures / "regional_10yr_24hr.png", dpi=150)
    plt.close(fig)
    print(f"Saved five town figures and one regional map in {figures}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["inspect", "extract", "plots"])
    parser.add_argument("--config", type=Path, default=ROOT / "grid.json")
    parser.add_argument("--out", type=Path, default=ROOT / "out" / "part_a")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.stage == "plots":
        plot_outputs(config, args.out)
    else:
        run_remote(config, args.out, inspection_only=args.stage == "inspect")


if __name__ == "__main__":
    main()
