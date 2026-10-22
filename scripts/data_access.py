"""Public-store and coordinate helpers adapted from workshop E4/E6."""


def open_store(settings):
    """Open a pinned snapshot or branch lazily, with anonymous read-only access."""
    import icechunk
    import xarray as xr

    storage = icechunk.s3_storage(
        bucket=settings["bucket"], prefix=settings["prefix"],
        endpoint_url=settings["endpoint"], region=settings["region"],
        anonymous=True, from_env=False, force_path_style=True,
    )
    repo = icechunk.Repository.open(storage, config=icechunk.RepositoryConfig.default())
    session = (repo.readonly_session(snapshot_id=settings["snapshot_id"])
               if settings["snapshot_id"] else repo.readonly_session(settings["branch"]))
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
    """A shared town dimension selects paired points, not a lat/lon cross product."""
    import xarray as xr

    names = [t["name"] for t in config["towns"]]
    return {axis: xr.DataArray([t[key] for t in config["towns"]],
                              dims="town", coords={"town": names})
            for axis, key in [("lat", "latitude"), ("lon", "longitude")]}
