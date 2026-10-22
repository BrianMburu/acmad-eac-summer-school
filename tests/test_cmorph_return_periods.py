"""Offline checks for the supplementary 27-year return-period figures."""

import copy
import json
import sys

import numpy as np
import pytest
import xarray as xr
from scipy.stats import gumbel_r

from scripts import cmorph_return_periods
from scripts.cmorph_return_periods import (
    check_parameters,
    plot_town,
    read_points,
    validate_store,
)
from scripts.common import load_config
from scripts.return_levels import gumbel_return_level


@pytest.fixture
def stores():
    config = load_config()
    lat = np.arange(11, 18, .5)
    lon = np.arange(23, 39, .5)
    year = np.arange(1998, 2025)
    duration = ["24hr", "48hr"]
    periods = np.array([2, 10, 50])
    location = 25 + np.arange(2)[:, None, None] * 20 + lat[None, :, None] + lon[None, None, :] / 10
    scale = 8.0
    quantiles = (np.arange(27) + .5) / 27
    maxima = location[:, None, :, :] + gumbel_r.ppf(quantiles, scale=scale)[None, :, None, None]
    levels = location[:, None, :, :] + gumbel_r.isf(1 / periods, scale=scale)[None, :, None, None]
    obs = xr.Dataset({
        "annual_maxima": (("duration", "year", "lat", "lon"), maxima, {"units": "mm"}),
        "return_period_precip": (("duration", "return_period", "lat", "lon"), levels, {"units": "mm"}),
        "dist_location": (("duration", "lat", "lon"), location, {"units": "mm"}),
        "dist_scale": (("duration", "lat", "lon"), np.full_like(location, scale), {"units": "mm"}),
    }, coords={"duration": duration, "year": year, "lat": lat, "lon": lon, "return_period": periods})
    return config, obs


def test_read_points_and_parameter_check(stores):
    config, obs = stores
    points = read_points(obs, config, "24hr")
    assert points.sizes["town"] == 5
    assert "lat" not in points.dims and "lon" not in points.dims
    assert check_parameters(points, config) < 1e-6
    # The paired selection must use each town's own nearest pixel, not a cross product.
    for town in config["towns"]:
        point = points.annual_maxima.sel(town=town["name"])
        assert float(point.lat) == pytest.approx(town["latitude"], abs=0.25)
        assert float(point.lon) == pytest.approx(town["longitude"], abs=0.25)


def test_parameter_check_rejects_inconsistent_store(stores):
    config, obs = stores
    points = read_points(obs, config, "24hr")
    broken = points.copy(deep=True)
    broken["dist_scale"] = broken["dist_scale"] + 1
    with pytest.raises(ValueError, match="do not reproduce"):
        check_parameters(broken, config)


def test_parameter_check_rejects_nonfinite_parameters(stores):
    config, obs = stores
    points = read_points(obs, config, "24hr")
    broken = points.copy(deep=True)
    broken["dist_scale"].loc[{"town": config["towns"][0]["name"]}] = np.nan
    with pytest.raises(ValueError, match="nonfinite"):
        check_parameters(broken, config)


def test_validate_store_rejects_bad_years_units_and_domain(stores):
    config, obs = stores
    domain_box, units = validate_store(obs, config, "24hr")
    assert domain_box["west"] == pytest.approx(float(obs.lon.min()))
    assert units["annual_maxima"]["accepted_as_mm_depth"]

    with pytest.raises(ValueError, match="expected exactly the years"):
        validate_store(obs.sel(year=slice(1999, 2024)), config, "24hr")

    bad_units = obs.copy(deep=True)
    bad_units.return_period_precip.attrs["units"] = "mm/day"
    with pytest.raises(ValueError, match="units"):
        validate_store(bad_units, config, "24hr")

    bad_domain = copy.deepcopy(config)
    bad_domain["towns"][0]["longitude"] = 100
    with pytest.raises(ValueError, match="outside the CMORPH domain"):
        validate_store(obs, bad_domain, "24hr")


def test_plot_town_writes_one_figure(stores, tmp_path):
    config, obs = stores
    points = read_points(obs, config, "24hr")
    rp_map = gumbel_return_level(
        obs.dist_location.sel(duration="24hr"), obs.dist_scale.sel(duration="24hr"), 27)
    path = plot_town(points, rp_map, config["towns"][0], config, "24hr", 27, tmp_path)
    assert path.exists() and path.stat().st_size > 1000
    assert path.name == "04_cmorph_return_periods_khartoum.png"


def test_main_rejects_duplicate_town_slugs(tmp_path, monkeypatch):
    config = load_config()
    config["towns"][1]["name"] = config["towns"][3]["name"].replace(" ", "-")
    settings = tmp_path / "grid.json"
    settings.write_text(json.dumps(config))
    monkeypatch.setattr(sys, "argv", ["cmorph_return_periods", "--config", str(settings)])
    with pytest.raises(SystemExit) as excinfo:
        cmorph_return_periods.main()
    assert excinfo.value.code == 2
