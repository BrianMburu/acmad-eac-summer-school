"""Offline scientific/workflow checks; no remote data or forecast values."""

import copy
import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from scipy.stats import gumbel_r

from scripts.common import load_config, migrate_legacy, validate_thresholds
from scripts import rainfall_thresholds
from scripts.rainfall_thresholds import (
    config_hash, diagnostics, empirical_positions, extract_arrays, inspect_stores,
    plot_outputs, tables, validate_arrays, write_json,
    verify_saved_settings,
)


@pytest.fixture
def stores():
    config = load_config()
    lat = np.arange(11, 18, .5)
    lon = np.arange(23, 39, .5)
    year = np.arange(1998, 2025)
    duration = ["24hr", "48hr"]
    periods = np.array([2, 10, 50])
    # Different location/duration values catch cross-product or coordinate mistakes.
    loc = 25 + np.arange(2)[:, None, None] * 20 + lat[None, :, None] + lon[None, None, :] / 10
    scale = 8
    quantiles = (np.arange(27) + .5) / 27
    maxima = loc[:, None, :, :] + gumbel_r.ppf(quantiles, scale=scale)[None, :, None, None]
    thresholds = loc[:, None, :, :] + gumbel_r.isf(1 / periods, scale=scale)[None, :, None, None]
    obs = xr.Dataset({
        "annual_maxima": (("duration", "year", "lat", "lon"), maxima, {"units": "mm"}),
        "return_period_precip": (("duration", "return_period", "lat", "lon"), thresholds, {"units": "mm"}),
    }, coords={"duration": duration, "year": year, "lat": lat, "lon": lon, "return_period": periods})
    forecast = xr.Dataset(coords={"latitude": lat[::-1], "longitude": lon})
    return config, obs, forecast


def test_extract_paired_towns_and_complete_handoff(stores):
    config, obs, fc = stores
    report, coverage = inspect_stores(obs, fc, config)
    assert report["problems"] == []
    assert not report["forecast_data_read"]
    assert len(coverage) == 5
    points, regional = extract_arrays(obs.chunk({"year": 1}), config)
    assert points.sizes["town"] == 5
    assert "lat" not in points.dims and "lon" not in points.dims
    assert validate_arrays(points, regional, config)["town_values_finite"]
    thresholds, maxima = tables(points, config)
    assert len(thresholds) == 30
    assert len(maxima) == 270
    assert not thresholds.duplicated(["town", "duration", "return_period_years"]).any()
    assert not maxima.duplicated(["town", "duration", "year"]).any()
    for town in config["towns"]:
        expected = float(obs.return_period_precip.sel(duration="24hr", return_period=2).sel(
            lat=town["latitude"], lon=town["longitude"], method="nearest"))
        actual = thresholds[(thresholds.town == town["name"]) & (thresholds.duration == "24hr")
                            & (thresholds.return_period_years == 2)].threshold_mm.iloc[0]
        assert actual == expected


def test_coverage_does_not_silently_snap(stores):
    config, obs, fc = stores
    config = copy.deepcopy(config)
    config["towns"][0]["longitude"] = 100
    report, coverage = inspect_stores(obs, fc, config)
    assert report["problems"]
    assert not coverage.iloc[0].inside_cmorph
    assert np.isnan(coverage.iloc[0].cmorph_longitude)


def test_missing_duration_and_wrong_latitude_order(stores):
    config, obs, fc = stores
    report, _ = inspect_stores(obs.sel(duration=["24hr"]), fc, config)
    assert any("durations unavailable" in p for p in report["problems"])
    with pytest.raises(ValueError, match="coordinate order"):
        inspect_stores(obs.sortby("lat", ascending=False), fc, config)


def test_units_require_depth_and_record_missing_metadata(stores):
    config, obs, fc = stores
    obs.return_period_precip.attrs["units"] = "mm/day"
    report, _ = inspect_stores(obs, fc, config)
    assert any("Unsupported rainfall-depth units" in p for p in report["problems"])
    obs.return_period_precip.attrs.clear()
    report, _ = inspect_stores(obs, fc, config)
    assert report["problems"] == []
    assert report["units"]["return_period_precip"]["used_workshop_fallback"]


def test_years_and_regional_coverage(stores):
    config, obs, fc = stores
    report, _ = inspect_stores(obs.sel(year=slice(1999, 2024)), fc, config)
    assert any("exactly the years" in p for p in report["problems"])
    config = copy.deepcopy(config)
    config["region_extent"]["west"] = 0
    report, _ = inspect_stores(obs, fc, config)
    assert not report["region_inside"]["cmorph"]


def test_missing_town_values_fail_but_missing_map_pixels_are_masked(stores):
    config, obs, _ = stores
    points, regional = extract_arrays(obs, config)
    regional = regional.copy(deep=True)
    regional.values[0, 0] = np.nan
    assert validate_arrays(points, regional, config)["regional_missing_pixels"] == 1
    points.annual_maxima.values[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="Missing/nonfinite"):
        validate_arrays(points, regional, config)


def test_decreasing_return_levels_rejected(stores):
    config, obs, _ = stores
    points, regional = extract_arrays(obs, config)
    points.return_period_precip.loc[{"return_period": 50}] = 0
    with pytest.raises(ValueError, match="decrease"):
        validate_arrays(points, regional, config)


def test_empirical_positions_and_leave_largest_out(stores):
    order, periods = empirical_positions([10, 40, 20])
    assert order.tolist() == [1, 2, 0]
    np.testing.assert_allclose(periods, [4, 2, 4 / 3])
    config, obs, _ = stores
    points, _ = extract_arrays(obs, config)
    thresholds, maxima = tables(points, config)
    departures, sensitivity = diagnostics(thresholds, maxima)
    assert len(departures) == 30
    assert len(sensitivity) == 10
    assert set(sensitivity.removed_year) == {2024}
    assert (sensitivity.change_mm < 0).all()
    np.testing.assert_allclose(sensitivity.change_percent,
                               100 * sensitivity.change_mm / sensitivity.refit_full_50yr_mm)
    # Deliberately shift stored levels: extension change must depend only on refits.
    thresholds.threshold_mm += 10
    _, shifted = diagnostics(thresholds, maxima)
    np.testing.assert_allclose(shifted.change_mm, sensitivity.change_mm)
    np.testing.assert_allclose(shifted.refit_minus_stored_mm, sensitivity.refit_minus_stored_mm - 10)


def test_offline_plotting_and_changed_config_guard(stores, tmp_path):
    config, obs, _ = stores
    points, regional = extract_arrays(obs, config)
    thresholds, maxima = tables(points, config)
    thresholds.to_csv(tmp_path / "thresholds.csv", index=False)
    maxima.to_csv(tmp_path / "annual_maxima.csv", index=False)
    np.savez_compressed(tmp_path / "regional_10yr_24hr.npz", latitude=regional.lat.values,
                        longitude=regional.lon.values, threshold_mm=regional.values)
    write_json(tmp_path / "manifest.json", {"config_sha256": config_hash(config)})
    plot_outputs(config, tmp_path)
    images = list((tmp_path / "figures").glob("*.png"))
    assert len(images) == 6
    assert all(p.stat().st_size > 1000 for p in images)
    changed = copy.deepcopy(config)
    changed["start_date"] = "2025-06-02"
    with pytest.raises(ValueError, match="Settings differ"):
        plot_outputs(changed, tmp_path)


def test_remote_stages_with_synthetic_stores(stores, tmp_path, monkeypatch):
    config, obs, fc = stores
    def fake_open(settings):
        return (obs if settings is config["cmorph_reference"] else fc), "synthetic-snapshot"
    monkeypatch.setattr(rainfall_thresholds, "open_store", fake_open)
    inspection = tmp_path / "inspection_only"
    rainfall_thresholds.run_remote(config, inspection, inspection_only=True)
    assert (inspection / "inspection.json").exists()
    assert not (inspection / "thresholds.csv").exists()
    results = tmp_path / "results"
    rainfall_thresholds.run_remote(config, results)
    assert len(pd.read_csv(results / "thresholds.csv")) == 30
    assert len(pd.read_csv(results / "annual_maxima.csv")) == 270
    manifest = json.loads((results / "manifest.json").read_text())
    assert manifest["store_snapshots"]["cmorph"] == "synthetic-snapshot"
    assert manifest["quality_checks"]["town_values_finite"]
    assert manifest["source_sha256"]
    assert json.loads((results / "settings_used.json").read_text()) == config


def test_failed_remote_inspection_exports_report_only(stores, tmp_path, monkeypatch):
    config, obs, fc = stores
    obs = obs.sel(duration=["24hr"])
    monkeypatch.setattr(rainfall_thresholds, "open_store", lambda settings: (
        obs if settings is config["cmorph_reference"] else fc, "synthetic-snapshot"))
    with pytest.raises(ValueError, match="Inspection failed"):
        rainfall_thresholds.run_remote(config, tmp_path)
    assert (tmp_path / "inspection.json").exists()
    assert (tmp_path / "coverage.csv").exists()
    assert not (tmp_path / "thresholds.csv").exists()


def test_map_selection_and_workers_follow_shared_settings(stores, monkeypatch):
    import dask

    config, obs, _ = stores
    config["thresholds"].update(map_duration="48hr", map_return_period_years=2)
    config["execution"]["workers"] = 1
    original = dask.compute
    seen = {}
    def compute(*args, **kwargs):
        seen.update(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(dask, "compute", compute)
    _, regional = extract_arrays(obs, config)
    assert seen["num_workers"] == 1
    expected = obs.return_period_precip.sel(duration="48hr", return_period=2).sel(
        lat=regional.lat, lon=regional.lon)
    np.testing.assert_allclose(regional.values, expected.values)


def test_legacy_cache_replay_preserves_hash_verification(stores, tmp_path):
    config, _, _ = stores
    legacy = copy.deepcopy(config)
    del legacy["schema_version"]
    del legacy["execution"]
    legacy["part_a"] = legacy.pop("thresholds")
    del legacy["part_a"]["map_duration"]
    del legacy["part_a"]["map_return_period_years"]
    for section in ["forecast", "cmorph_reference"]:
        for key in ["region", "branch", "snapshot_id"]:
            del legacy[section][key]
    del legacy["forecast"]["available_start_date"]
    del legacy["forecast"]["available_end_date"]
    legacy["cmorph_reference"].update(duration="24hr", return_period_years=2)
    settings_path = tmp_path / "settings_used.json"
    write_json(settings_path, legacy)
    write_json(tmp_path / "manifest.json", {"config_sha256": config_hash(legacy)})
    migrated = load_config(settings_path)
    validate_thresholds(migrated)
    assert migrated == migrate_legacy(legacy)
    assert migrated["forecast"]["snapshot_id"] is None
    verify_saved_settings(migrated, tmp_path)
    changed = copy.deepcopy(migrated)
    changed["start_date"] = "2025-06-02"
    with pytest.raises(ValueError, match="Settings differ"):
        verify_saved_settings(changed, tmp_path)
    # Editing saved settings must not make the original extraction hash valid.
    legacy["start_date"] = "2025-06-02"
    write_json(settings_path, legacy)
    with pytest.raises(ValueError, match="Settings differ"):
        verify_saved_settings(load_config(settings_path), tmp_path)
