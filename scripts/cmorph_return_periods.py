"""Exercise 4: explore 27 years of observed rainfall extremes (CMORPH, 1998-2024) for East Africa.

The store holds annual maxima and Gumbel return-period depths that were computed from a pencil-chunked
copy of 236,688 CMORPH files (all 27 years at each grid point in one chunk). This store itself is
pan-chunked (one map per chunk), so maps are cheap and a 27-year point series costs 27 fetches.

Every town listed in grid.json (name, latitude, longitude) gets its own three-panel figure, e.g.
Sudan's five towns produce five plots under out/.

Run:  uv run --project ../python-workshop python scripts/cmorph_return_periods.py
"""
import argparse
import json
import os
import pathlib
import re
import time

# Stray AWS_* variables silently redirect the open; the store is public, so drop them first.
for k in [k for k in os.environ if k.startswith("AWS_")]:
    os.environ.pop(k)

import icechunk
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

ENDPOINT = "https://data.source.coop"
BUCKET = "e4drr-project"
PREFIX = "observations/cmorph_rp_icechunk"
DURATION = "24hr"
RETURN_PERIOD = 27                       # years; computed from Gumbel mu/beta when not stored
HERE = pathlib.Path(__file__).resolve()
DEFAULT_GRID = HERE.parents[2] / "acmad-eac-summer-school" / "grid.json"
out = pathlib.Path("out")
out.mkdir(parents=True, exist_ok=True)


def slugify(text):
    """Turn a town name into a safe file-name fragment."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def nearest_point(da, lat, lon):
    """Nearest grid point; select each axis separately so the 1-D indexes stay well behaved."""
    return da.sel(lat=lat, method="nearest").sel(lon=lon, method="nearest")


def gumbel_return_level(location, scale, return_period):
    """Gumbel quantile x_T = mu - beta * ln(-ln(1 - 1/T)); mu and beta come from the store."""
    return location - scale * np.log(-np.log1p(-1.0 / return_period))


def plot_town(ds, rp_map, town, country):
    """Read the 27-year point series for one town and save its three-panel figure."""
    NAME = town["name"]
    LAT = float(town["latitude"])
    LON = float(town["longitude"])

    # Point series read: one duration, every year -> one chunk per year.
    t0 = time.time()
    amax = nearest_point(ds["annual_maxima"].sel(duration=DURATION), LAT, LON).compute()
    rp_point = nearest_point(ds["return_period_precip"].sel(duration=DURATION), LAT, LON).compute()
    mu = nearest_point(ds["dist_location"].sel(duration=DURATION), LAT, LON).compute()
    beta = nearest_point(ds["dist_scale"].sel(duration=DURATION), LAT, LON).compute()
    rp_value = float(gumbel_return_level(mu, beta, RETURN_PERIOD))
    print(f"[{NAME}] series read ({ds.sizes['year']} annual maxima): {time.time() - t0:.1f}s, "
          f"{ds.sizes['year']} chunks")

    vals = amax.values
    assert np.isfinite(vals).all(), f"NaN in annual maxima at {NAME}: check the point is inside the domain"
    print(f"[{NAME}] nearest pixel ({float(amax.lat):.2f}, {float(amax.lon):.2f}); "
          f"annual max: median {np.median(vals):.0f} mm, wettest {vals.max():.0f} mm "
          f"in {int(amax.year[vals.argmax()])}")
    print(f"[{NAME}] {RETURN_PERIOD}-yr {DURATION} return level: {rp_value:.1f} mm "
          f"(mu={float(mu):.1f}, beta={float(beta):.1f})")
    print(f"[{NAME}] stored return levels (mm):",
          dict(zip(rp_point.return_period.values.tolist(), np.round(rp_point.values, 1).tolist())))

    # Sanity check: the empirical exceedance of the 27 maxima should sit near the fitted Gumbel curve.
    sorted_vals = np.sort(vals)[::-1]
    empirical_T = (len(vals) + 1) / np.arange(1, len(vals) + 1)        # Weibull plotting position

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), gridspec_kw=dict(width_ratios=[1, 1.15, 1]))
    ax = axes[0]
    pm = ax.pcolormesh(rp_map.lon, rp_map.lat, rp_map, cmap="YlGnBu", shading="auto",
                       vmax=float(rp_map.quantile(0.99)))
    fig.colorbar(pm, ax=ax, label="mm")
    ax.plot(LON, LAT, "r^", ms=8, label=NAME)
    ax.set(title=f"{RETURN_PERIOD}-year {DURATION} rainfall (Gumbel)", xlabel="lon", ylabel="lat")
    ax.set_aspect("equal")
    ax.legend(loc="lower left")

    ax = axes[1]
    ax.bar(amax.year, vals, color="steelblue")
    for T, c in [(2, "grey"), (10, "darkorange"), (50, "crimson")]:
        ax.axhline(float(rp_point.sel(return_period=T)), color=c, ls="--", lw=1.5, label=f"{T}-yr level")
    ax.set(title=f"{NAME}: annual max {DURATION} rainfall, 1998-2024", xlabel="year", ylabel="mm")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    ax = axes[2]
    ax.semilogx(rp_point.return_period, rp_point, "o-", color="crimson", label="Gumbel fit")
    ax.semilogx(empirical_T, sorted_vals, "k.", label="observed annual maxima")
    ax.set(title="Does the fit match the data?", xlabel="return period (years)",
           ylabel=f"{DURATION} rainfall (mm)")
    ax.legend()
    ax.grid(alpha=0.3, which="both")
    fig.suptitle(f"CMORPH 1998-2024, {country}: observed rainfall extremes at {NAME}")
    fig.tight_layout()

    path = out / f"04_cmorph_return_periods_{slugify(NAME)}.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print("saved", path)
    return path


def main():
    default_grid = DEFAULT_GRID if DEFAULT_GRID.exists() else pathlib.Path("grid.json")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=pathlib.Path, default=default_grid,
                        help=f"JSON file listing towns (default: {default_grid})")
    args = parser.parse_args()

    meta = json.loads(args.grid.read_text())
    towns = meta["towns"]
    country = meta.get("country", "East Africa")
    print(f"{len(towns)} towns from {args.grid}: {[t['name'] for t in towns]}")

    storage = icechunk.s3_storage(
        bucket=BUCKET, prefix=PREFIX, endpoint_url=ENDPOINT, region="us-east-1",
        anonymous=True, from_env=False, force_path_style=True)
    repo = icechunk.Repository.open(storage, config=icechunk.RepositoryConfig.default())
    ds = xr.open_zarr(repo.readonly_session("main").store, zarr_format=3, consolidated=False, chunks={})

    print("dims:", dict(ds.sizes))
    print("variables:", list(ds.data_vars))
    print("durations:", ds.duration.values.tolist(), "| return periods:", ds.return_period.values.tolist())
    print(f"latitude runs {float(ds.lat[0]):.1f} -> {float(ds.lat[-1]):.1f} "
          f"(ASCENDING here, unlike the forecast store)")
    for v in ds.data_vars:
        print(f"  {v}: chunks {ds[v].encoding['chunks']}")

    available = ds.return_period.values.tolist()
    if RETURN_PERIOD in available:
        # Map read: one duration -> one chunk, shared by every town.
        t0 = time.time()
        rp_map = ds["return_period_precip"].sel(duration=DURATION, return_period=RETURN_PERIOD).compute()
        print(f"map read ({DURATION}, {RETURN_PERIOD}-yr): {time.time() - t0:.1f}s, 1 chunk")
    else:
        # Arbitrary return period: evaluate the fitted Gumbel quantile from mu and beta.
        t0 = time.time()
        mu_map = ds["dist_location"].sel(duration=DURATION)
        beta_map = ds["dist_scale"].sel(duration=DURATION)
        rp_map = gumbel_return_level(mu_map, beta_map, RETURN_PERIOD).compute()
        print(f"map computed ({DURATION}, {RETURN_PERIOD}-yr from mu/beta, "
              f"not stored): {time.time() - t0:.1f}s, 2 chunks")

    for town in towns:
        plot_town(ds, rp_map, town, country)


if __name__ == "__main__":
    main()
