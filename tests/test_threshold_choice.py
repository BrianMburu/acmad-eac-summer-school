"""Offline Part B checks with controlled rainfall, missing starts and source chunks."""

import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from scripts import threshold_choice
from scripts.common import (ConfigError, config_hash, extraction_hash, load_config,
                            validate_threshold_choice)
from scripts.forecast_rainfall import (daily_rainfall, daily_step_indices,
                                       forecast_unit_report, select_town_forecasts)
from scripts.rainfall_thresholds import file_sha256, write_json


@pytest.fixture
def forecast():
    config = load_config()
    config["forecast"]["start_dates"] = ["2025-06-01", "2025-07-01"]
    config["threshold_choice"]["towns"] = ["Khartoum", "Gedaref"]
    steps = np.array([0, 3, 24, 27, 48], dtype="timedelta64[h]")
    values = np.zeros((2, 5, 51, 4, 4), dtype="float64")
    # Spatial differences catch accidental selection of a lat/lon cross product.
    for j in range(4):
        values[:, 2:, :, j, :] = .021 + j * .001
        values[:, 4:, :, j, :] += .020
    ds = xr.Dataset({"tp": (("time", "step", "number", "latitude", "longitude"), values)},
        coords={"time": pd.DatetimeIndex(config["forecast"]["start_dates"]), "step": steps,
                "number": np.arange(51), "latitude": [17, 15.5, 14, 11],
                "longitude": [23, 32.5, 35.5, 38]})
    ds.tp.encoding["chunks"] = (1, 1, 51, 4, 4)
    return config, ds


def handoff(tmp_path, config):
    directory = tmp_path / "observations"
    directory.mkdir()
    thresholds, maxima = [], []
    for town in config["threshold_choice"]["towns"]:
        for period, value in [(2, 25.), (10, 50.)]:
            thresholds.append({"town": town, "duration": "24hr", "return_period_years": period,
                               "threshold_mm": value, "units": "mm"})
        for year in range(1998, 2025):
            maxima.append({"town": town, "duration": "24hr", "year": year,
                           "rainfall_mm": 20 + year - 1998, "units": "mm"})
    pd.DataFrame(thresholds).to_csv(directory / "thresholds.csv", index=False)
    pd.DataFrame(maxima).to_csv(directory / "annual_maxima.csv", index=False)
    write_json(directory / "settings_used.json", config)
    write_json(directory / "manifest.json", {
        "config_sha256": config_hash(config), "extraction_sha256": extraction_hash(config),
        "store_snapshots": {"cmorph": config["cmorph_reference"]["snapshot_id"]},
        "git_commit": "test", "output_sha256": {name: file_sha256(directory / name) for name in
            ["thresholds.csv", "annual_maxima.csv", "settings_used.json"]}})
    return directory


def test_daily_leads_and_shared_chunk_selection(forecast):
    config, ds = forecast
    selected, report = select_town_forecasts(ds.chunk({"time": 1, "step": 1}), config)
    assert selected.sizes == {"time": 2, "step": 3, "number": 51, "town": 2}
    assert report["daily_lead_hours"] == [0, 24, 48]
    assert report["source_chunks_touched"] == 6  # shared by both towns, not doubled
    assert report["decoded_source_mib"] == 6 * 51 * 4 * 4 * 8 / 2**20
    assert report["units"]["used_workshop_fallback"]
    daily = daily_rainfall(selected.isel(time=0).compute(), 1000)
    assert daily.forecast_day.values.tolist() == [1, 2]
    assert pd.Timestamp(daily.time.values[0]) == pd.Timestamp("2025-06-02")
    np.testing.assert_allclose(daily.sel(town="Khartoum").isel(time=0), 22)
    np.testing.assert_allclose(daily.sel(town="Gedaref").isel(time=0), 23)
    np.testing.assert_allclose(daily.isel(time=1), 20)
    without_zero = daily_rainfall(selected.isel(time=0, step=slice(1, None)).compute(), 1000)
    xr.testing.assert_equal(daily, without_zero)


@pytest.mark.parametrize("hours", [[0, 24, 72], [0, 24, 24], [-24, 0, 24], [0, 3, 6], [48, 72]])
def test_non_daily_or_missing_intervals_rejected(hours):
    with pytest.raises(ValueError, match="daily|increasing"):
        daily_step_indices(np.array(hours, dtype="timedelta64[h]"))


def test_missingness_and_cumulative_resets(forecast):
    config, ds = forecast
    selected, _ = select_town_forecasts(ds, config)
    one = selected.isel(time=0).copy(deep=True)
    one.values[:] = np.nan
    assert daily_rainfall(one, 1000) is None
    one.values[0, 0, 0] = 0
    with pytest.raises(ValueError, match="Partially missing"):
        daily_rainfall(one, 1000)
    one = selected.isel(time=0).copy(deep=True)
    one.loc[{"step": np.timedelta64(48, "h")}] = 0
    with pytest.raises(ValueError, match="decreases"):
        daily_rainfall(one, 1000)
    one.loc[{"step": np.timedelta64(0, "h")}] = .1
    with pytest.raises(ValueError, match="step 0"):
        daily_rainfall(one, 1000)


def test_packing_traces_zeroed_and_reported(forecast):
    config, ds = forecast
    selected, _ = select_town_forecasts(ds, config)
    one = selected.isel(time=0).copy(deep=True)
    one.loc[{"step": np.timedelta64(24, "h")}] = .00003  # 0.03 mm positive trace
    one.loc[{"step": np.timedelta64(48, "h")}] = .000015  # -0.015 mm packing increment
    daily = daily_rainfall(one, 1000, .04)
    assert not daily.values.any()
    assert daily.attrs["tiny_negative_totals_clipped"] == 102
    assert daily.attrs["positive_trace_totals_zeroed"] == 102
    assert daily.attrs["minimum_uncorrected_daily_mm"] == pytest.approx(-.015)
    with pytest.raises(ValueError, match="decreases"):
        daily_rainfall(one, 1000, .01)


def test_units_metadata_overrides_fallback(forecast):
    _, ds = forecast
    ds.tp.attrs["units"] = "mm"
    assert forecast_unit_report(ds.tp, "m")["mm_factor"] == 1
    ds.tp.attrs["units"] = "mm/day"
    with pytest.raises(ValueError, match="units"):
        forecast_unit_report(ds.tp, "m")


def test_invalid_domain_starts_and_member_count(forecast):
    config, ds = forecast
    with pytest.raises(ValueError, match="coordinate order"):
        select_town_forecasts(ds.sortby("latitude"), config)
    config["forecast"]["start_dates"] = ["2025-06-02"]
    with pytest.raises(ValueError, match="absent"):
        select_town_forecasts(ds, config)
    config["forecast"]["start_dates"] = ["2025-06-01"]
    with pytest.raises(ValueError, match="51-member"):
        select_town_forecasts(ds.isel(number=slice(0, 50)), config)


def test_strict_comparison_and_real_xclim_agree():
    # Equality is deliberately included to distinguish strict > from xclim's >= default.
    pr = xr.DataArray([[[20., 21., 50.], [0., 50., 51.]]], dims=("town", "number", "time"),
        coords={"town": ["Khartoum"], "number": [0, 1],
                "time": pd.date_range("2025-07-02", periods=3), "forecast_day": ("time", [1, 2, 3])},
        attrs={"units": "mm/day", "standard_name": "precipitation_flux"})
    levels = pd.DataFrame([{"town": "Khartoum", "threshold": "fixed_20mm", "threshold_mm": 20.},
                           {"town": "Khartoum", "threshold": "local_10yr", "threshold_mm": 50.}])
    counts, heavy, summary = threshold_choice.count_thresholds(pr, levels, "2025-07-01")
    assert counts.members_above.tolist() == [0, 2, 2, 0, 0, 1]
    assert heavy.heavy_days.tolist() == [2, 2, 0, 1]
    assert summary.member_days_above.tolist() == [4, 1]
    assert summary.members_with_any_heavy_day.tolist() == [2, 1]


def test_handoff_validates_snapshot_settings_and_checksums(tmp_path, forecast):
    config, _ = forecast
    directory = handoff(tmp_path, config)
    levels, info = threshold_choice.load_handoff(directory, config)
    assert len(levels) == 6 and len(info["sha256"]) == 4
    assert levels.annual_maxima_above.tolist() == [26, 21, 0, 26, 21, 0]
    config["cmorph_reference"]["snapshot_id"] = "other-snapshot"
    with pytest.raises(ValueError, match="snapshot"):
        threshold_choice.load_handoff(directory, config)
    config["cmorph_reference"]["snapshot_id"] = info["cmorph_snapshot"]
    config["towns"][0]["latitude"] += .01
    with pytest.raises(ValueError, match="geography"):
        threshold_choice.load_handoff(directory, config)
    config["towns"][0]["latitude"] -= .01
    with (directory / "thresholds.csv").open("a") as stream:
        stream.write("bad data\n")
    with pytest.raises(ValueError, match="manifest"):
        threshold_choice.load_handoff(directory, config)


def test_end_to_end_skips_unwritten_start_and_plots_offline(tmp_path, forecast, monkeypatch):
    config, ds = forecast
    ds.tp.loc[{"time": "2025-06-01"}] = np.nan
    directory = handoff(tmp_path, config)
    monkeypatch.setattr(threshold_choice, "open_store", lambda _: (ds.copy(), "forecast-test"))
    out = tmp_path / "comparison"
    threshold_choice.run_remote(config, directory, out)
    starts = json.loads((out / "forecast_starts.json").read_text())
    assert [row["status"] for row in starts] == ["skipped_all_nan", "ok"]
    assert len(pd.read_csv(out / "daily_member_counts.csv")) == 12
    assert len(pd.read_csv(out / "heavy_rain_days.csv")) == 306
    assert len(pd.read_csv(out / "summary_counts.csv")) == 6
    assert len(pd.read_csv(out / "daily_rainfall.csv")) == 204
    assert len(list((out / "cache").glob("*.nc"))) == 2
    # Rerun from the raw point cache; computing even a synthetic source is forbidden.
    monkeypatch.setattr(xr.DataArray, "compute", lambda *args, **kwargs: pytest.fail("cached rerun computed a source read"))
    threshold_choice.run_remote(config, directory, out)
    before = (out / "run_status.json").read_bytes()
    threshold_choice.run_remote(config, directory, out, inspection_only=True)
    assert (out / "run_status.json").read_bytes() == before
    monkeypatch.setattr(threshold_choice, "open_store", lambda _: pytest.fail("offline plot attempted remote access"))
    (out / "figures").mkdir()
    unrelated = out / "figures" / "other.png"
    unrelated.write_bytes(b"keep")
    threshold_choice.plot_outputs(out)
    assert unrelated.read_bytes() == b"keep"
    assert len(list((out / "figures").glob("*_threshold_choice.png"))) == 2
    with (out / "daily_member_counts.csv").open("a") as stream:
        stream.write("bad data\n")
    with pytest.raises(ValueError, match="manifest"):
        threshold_choice.plot_outputs(out)


def test_no_usable_start_fails_instead_of_exporting_zero_counts(tmp_path, forecast, monkeypatch):
    config, ds = forecast
    ds.tp.values[:] = np.nan
    directory = handoff(tmp_path, config)
    monkeypatch.setattr(threshold_choice, "open_store", lambda _: (ds.copy(), "forecast-test"))
    out = tmp_path / "comparison"
    with pytest.raises(ValueError, match="No usable"):
        threshold_choice.run_remote(config, directory, out)
    assert json.loads((out / "run_status.json").read_text())["status"] == "failed"
    assert not (out / "daily_member_counts.csv").exists()


def test_all_five_towns_share_reads_and_have_complete_outputs(tmp_path, forecast, monkeypatch):
    config, ds = forecast
    config["forecast"]["start_dates"] = ["2025-07-16"]
    ds = ds.assign_coords(time=pd.to_datetime(["2025-07-16", "2025-07-17"]))
    config["threshold_choice"]["towns"] = [town["name"] for town in config["towns"]]
    selected, report = select_town_forecasts(ds, config)
    assert selected.sizes["town"] == 5
    assert report["source_chunks_touched"] == 3  # no extra map chunks for five towns
    directory = handoff(tmp_path, config)
    monkeypatch.setattr(threshold_choice, "open_store", lambda _: (ds.copy(), "forecast-test"))
    out = tmp_path / "comparison"
    threshold_choice.run_remote(config, directory, out)
    counts = pd.read_csv(out / "daily_member_counts.csv")
    assert len(counts) == 1 * 5 * 2 * 3
    assert counts.initialization.unique().tolist() == ["2025-07-16"]
    assert counts.valid_end.min().startswith("2025-07-17")
    assert set(counts.town) == set(config["threshold_choice"]["towns"])
    threshold_choice.plot_outputs(out)
    assert len(list((out / "figures").glob("*_threshold_choice.png"))) == 5


def test_read_budget_refuses_excessive_reads_before_compute(tmp_path, forecast, monkeypatch):
    config, ds = forecast
    config["threshold_choice"]["max_source_mib"] = 1
    directory = handoff(tmp_path, config)
    ds.tp.encoding["chunks"] = (1, 1, 51, 321, 261)
    monkeypatch.setattr(threshold_choice, "open_store", lambda _: (ds, "forecast-test"))
    with pytest.raises(ValueError, match="max_source_mib"):
        threshold_choice.run_remote(config, directory, tmp_path / "comparison")


@pytest.mark.parametrize("key,value", [("towns", ["Khartoum", "Khartoum"]),
    ("towns", ["Khartoum", "Missing"]), ("fixed_threshold_mm", 10),
    ("forecast_units_if_missing", "mm/day"), ("max_source_mib", 0)])
def test_invalid_part_b_settings(key, value):
    config = load_config()
    config["threshold_choice"][key] = value
    with pytest.raises(ConfigError, match="threshold_choice"):
        validate_threshold_choice(config)
