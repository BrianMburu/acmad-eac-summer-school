"""Shared settings and public-store access, adapted from workshop E4/E6.

grid.json is the settings source for all subgroups. No credentials are needed.
"""

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_config(path=None):
    config = json.loads(Path(path or ROOT / "grid.json").read_text())
    towns = config["towns"]
    if not 3 <= len(towns) <= 5 or len({t["name"] for t in towns}) != len(towns):
        raise ValueError("Configure 3–5 uniquely named towns.")
    for box in [config["region_extent"], *(t["extent"] for t in towns)]:
        if not (-180 <= box["west"] < box["east"] <= 180
                and -90 <= box["south"] < box["north"] <= 90):
            raise ValueError(f"Invalid extent: {box}")
    for town in towns:
        if not inside(config["region_extent"], town["latitude"], town["longitude"]):
            raise ValueError(f"Town outside region: {town['name']}")
        if not inside(town["extent"], town["latitude"], town["longitude"]):
            raise ValueError(f"Town outside its extent: {town['name']}")
    if date.fromisoformat(config["start_date"]) > date.fromisoformat(config["end_date"]):
        raise ValueError("Analysis dates are reversed.")
    durations = config["part_a"]["durations"]
    if len(durations) != 2 or len(set(durations)) != 2 or durations[0] != "24hr":
        raise ValueError("Part A requires 24hr followed by one distinct second duration.")
    if sorted(config["part_a"]["return_periods_years"]) != [2, 10, 50]:
        raise ValueError("Part A requires the 2-, 10- and 50-year levels.")
    return config


def inside(box, latitude, longitude):
    return (box["south"] <= latitude <= box["north"]
            and box["west"] <= longitude <= box["east"])


def box_inside(domain, box):
    return inside(domain, box["south"], box["west"]) and inside(
        domain, box["north"], box["east"])


def open_store(settings):
    """Open lazily; use explicit anonymous options rather than reading AWS env."""
    import icechunk
    import xarray as xr

    storage = icechunk.s3_storage(
        bucket=settings["bucket"], prefix=settings["prefix"],
        endpoint_url=settings["endpoint"], region="us-east-1",
        anonymous=True, from_env=False, force_path_style=True,
    )
    repo = icechunk.Repository.open(storage, config=icechunk.RepositoryConfig.default())
    session = repo.readonly_session("main")
    ds = xr.open_zarr(session.store, zarr_format=3, consolidated=False,
                      chunks={}, decode_timedelta=True)
    return ds, str(session.snapshot_id)


def domain(ds, lat_name, lon_name, ascending):
    import numpy as np

    for name, expected in [(lat_name, ascending), (lon_name, True)]:
        values = ds[name].values
        if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
            raise ValueError(f"Invalid coordinate: {name}")
        delta = np.diff(values)
        if not ((delta > 0).all() if expected else (delta < 0).all()):
            raise ValueError(f"Unexpected coordinate order: {name}")
    return {"west": float(ds[lon_name].min()), "east": float(ds[lon_name].max()),
            "south": float(ds[lat_name].min()), "north": float(ds[lat_name].max())}


def town_indexers(config):
    """A shared 'town' dimension selects paired points, not a lat/lon cross product."""
    import xarray as xr

    names = [t["name"] for t in config["towns"]]
    return {axis: xr.DataArray([t[key] for t in config["towns"]],
                              dims="town", coords={"town": names})
            for axis, key in [("lat", "latitude"), ("lon", "longitude")]}
