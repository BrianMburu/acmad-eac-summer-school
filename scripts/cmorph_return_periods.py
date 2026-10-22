"""Supplementary 27-year CMORPH return-period figures for the shared town list.

This uses the same settings, pinned CMORPH snapshot and Gumbel helpers as the
Part A threshold analysis. ``grid.json`` is the generated export of the shared
settings in ``scripts/common.py``; either can be supplied with ``--config``.
One three-panel figure is written per town.

Run:  uv run python -m scripts.cmorph_return_periods
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts.common import (
    ROOT,
    ConfigError,
    config_hash,
    load_config,
    slugify,
    validate_common,
    validate_thresholds,
)
from scripts.data_access import open_store, town_indexers
from scripts.return_levels import empirical_positions, gumbel_return_level
from scripts.validation import check_town_coverage, units_report

DEFAULT_RETURN_PERIOD = 27
OUTPUT_DIRECTORY = ROOT / "out"


def read_points(ds, config, duration):
    """Read every town in one graph: annual maxima, stored levels, mu and beta."""
    ref = config["cmorph_reference"]
    variables = [ref["annual_maxima_variable"], ref["variable"], "dist_location", "dist_scale"]
    return (ds[variables].sel(duration=duration)
            .sel(**town_indexers(config), method="nearest").compute())


def check_parameters(points, config):
    """Check that the stored mu/beta reproduce every stored return level."""
    ref = config["cmorph_reference"]
    stored = points[ref["variable"]]
    computed = gumbel_return_level(points["dist_location"], points["dist_scale"], stored.return_period)
    difference_values = np.abs(computed - stored).values
    if not np.isfinite(difference_values).all():
        raise ValueError("nonfinite Gumbel parameters or stored return levels")
    difference = float(difference_values.max())
    if difference > 0.01:
        raise ValueError(
            f"Gumbel mu/beta do not reproduce the stored return levels (max difference {difference:.3f} mm)")
    return difference


def validate_store(ds, config, duration):
    """Validate record, units, levels and town coverage before selecting points."""
    ref = config["cmorph_reference"]
    expected_years = list(range(ref["reference_start_year"], ref["reference_end_year"] + 1))
    years = ds.year.values.tolist()
    if years != expected_years:
        raise ValueError(f"expected exactly the years {expected_years[0]}-{expected_years[-1]}; got {years}")
    if duration not in ds.duration.values:
        raise ValueError(f"duration {duration!r} not available; choose from {ds.duration.values.tolist()}")
    missing = set(config["thresholds"]["return_periods_years"]) - set(ds.return_period.values.tolist())
    if missing:
        raise ValueError(f"stored return periods are missing {sorted(missing)}")
    for variable in ("dist_location", "dist_scale"):
        if variable not in ds:
            raise ValueError(f"missing Gumbel parameter variable: {variable}")
    units = {}
    for variable in (ref["annual_maxima_variable"], ref["variable"]):
        if variable not in ds:
            raise ValueError(f"missing CMORPH variable: {variable}")
        units[variable] = units_report(ds[variable], config["thresholds"].get("units_if_missing"))
        if not units[variable]["accepted_as_mm_depth"]:
            raise ValueError(f"unsupported rainfall-depth units for {variable}: {units[variable]}")
    domain_box = check_town_coverage(ds, config)
    return domain_box, units


def plot_town(points, rp_map, town, config, duration, return_period, out):
    """Save the three-panel figure for one town."""
    ref = config["cmorph_reference"]
    name = town["name"]
    amax = points[ref["annual_maxima_variable"]].sel(town=name)
    rp_point = points[ref["variable"]].sel(town=name)
    mu = float(points["dist_location"].sel(town=name))
    beta = float(points["dist_scale"].sel(town=name))
    rp_value = float(gumbel_return_level(mu, beta, return_period))

    vals = amax.values
    if not np.isfinite(vals).all():
        raise ValueError(f"NaN in annual maxima at {name}: check the point is inside the domain")
    print(f"[{name}] nearest pixel ({float(amax.lat):.2f}, {float(amax.lon):.2f}); "
          f"annual max: median {np.median(vals):.0f} mm, wettest {vals.max():.0f} mm "
          f"in {int(amax.year[vals.argmax()])}")
    print(f"[{name}] {return_period:g}-yr {duration} return level: {rp_value:.1f} mm "
          f"(mu={mu:.1f}, beta={beta:.1f})")
    print(f"[{name}] stored return levels (mm):",
          dict(zip(rp_point.return_period.values.tolist(), np.round(rp_point.values, 1).tolist())))

    # Empirical exceedance of the annual maxima should sit near the fitted Gumbel curve.
    order, empirical_T = empirical_positions(vals)
    sorted_vals = vals[order]

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8),
                             gridspec_kw={"width_ratios": [1, 1.15, 1]})
    ax = axes[0]
    pm = ax.pcolormesh(rp_map.lon, rp_map.lat, rp_map, cmap="YlGnBu", shading="auto",
                       vmax=float(rp_map.quantile(0.99)))
    fig.colorbar(pm, ax=ax, label="mm")
    ax.plot(town["longitude"], town["latitude"], "r^", ms=8, label=name)
    ax.set(title=f"{return_period:g}-year {duration} rainfall (Gumbel)", xlabel="lon", ylabel="lat")
    ax.set_aspect("equal")
    ax.legend(loc="lower left")

    ax = axes[1]
    ax.bar(amax.year, vals, color="steelblue")
    for period, colour in zip(config["thresholds"]["return_periods_years"],
                              ["grey", "darkorange", "crimson"]):
        if period in rp_point.return_period.values:
            ax.axhline(float(rp_point.sel(return_period=period)), color=colour, ls="--", lw=1.5,
                       label=f"{period}-yr level")
    ax.set(title=f"{name}: annual max {duration} rainfall, "
                 f"{ref['reference_start_year']}-{ref['reference_end_year']}",
           xlabel="year", ylabel="mm")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    ax = axes[2]
    ax.semilogx(rp_point.return_period, rp_point, "o-", color="crimson", label="Gumbel fit")
    ax.semilogx(empirical_T, sorted_vals, "k.", label="observed annual maxima")
    ax.set(title="Does the fit match the data?", xlabel="return period (years)",
           ylabel=f"{duration} rainfall (mm)")
    ax.legend()
    ax.grid(alpha=0.3, which="both")
    fig.suptitle(f"CMORPH {ref['reference_start_year']}-{ref['reference_end_year']}, "
                 f"{config['country']}: observed rainfall extremes at {name}")
    fig.tight_layout()

    path = out / f"04_cmorph_return_periods_{slugify(name)}.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print("saved", path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", "--grid", dest="config", type=Path,
                        help="JSON settings override or grid.json export; defaults to scripts/common.py")
    parser.add_argument("--duration", help="duration to plot; defaults to thresholds.map_duration")
    parser.add_argument("--return-period", type=float, default=DEFAULT_RETURN_PERIOD,
                        help=f"return period in years (default: {DEFAULT_RETURN_PERIOD})")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIRECTORY,
                        help=f"output directory (default: {OUTPUT_DIRECTORY})")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        validate_common(config)
        validate_thresholds(config)
    except ConfigError as exc:
        parser.error(str(exc))
    if not np.isfinite(args.return_period) or args.return_period <= 1:
        parser.error("--return-period must be a finite number greater than 1 year")
    duration = args.duration or config["thresholds"]["map_duration"]
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    ref = config["cmorph_reference"]
    ds, snapshot = open_store(ref)
    try:
        try:
            domain_box, units = validate_store(ds, config, duration)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"CMORPH snapshot {snapshot}; duration {duration}; return period {args.return_period:g} years")
        print("dims:", dict(ds.sizes))
        print("durations:", ds.duration.values.tolist(), "| return periods:", ds.return_period.values.tolist())
        print(f"domain: {domain_box}; units: { {k: v['effective_units'] for k, v in units.items()} }")
        print(f"latitude runs {float(ds.lat[0]):.1f} -> {float(ds.lat[-1]):.1f}")

        t0 = time.time()
        rp_map = gumbel_return_level(
            ds["dist_location"].sel(duration=duration),
            ds["dist_scale"].sel(duration=duration),
            args.return_period,
        ).compute()
        if not np.isfinite(rp_map.values).any():
            parser.error("the Gumbel parameter map contains no finite values")
        print(f"map computed ({duration}, {args.return_period:g}-yr from mu/beta): "
              f"{time.time() - t0:.1f}s, 2 chunks")

        t0 = time.time()
        points = read_points(ds, config, duration)
        print(f"point reads for {len(config['towns'])} towns: {time.time() - t0:.1f}s")
        difference = check_parameters(points, config)
        print(f"Gumbel parameter check: stored levels reproduced within {difference:.2e} mm")

        paths = [plot_town(points, rp_map, town, config, duration, args.return_period, out)
                 for town in config["towns"]]
        manifest = {"created_utc": datetime.now(UTC).isoformat(),
                    "config_sha256": config_hash(config), "snapshot": snapshot,
                    "duration": duration, "return_period_years": args.return_period,
                    "reference_start_year": ref["reference_start_year"],
                    "reference_end_year": ref["reference_end_year"],
                    "units": units, "gumbel_parameter_max_difference_mm": difference,
                    "files": [path.name for path in paths]}
        manifest_path = out / "04_cmorph_return_periods_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
        print("saved", manifest_path)
    finally:
        ds.close()


if __name__ == "__main__":
    main()
