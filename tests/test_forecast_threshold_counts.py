"""Offline checks for the forecast threshold-count analysis; no remote reads."""

import copy

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from scripts import forecast_threshold_counts as counts
from scripts.common import load_config


@pytest.fixture
def synthetic_stores():
    """A small forecast/CMORPH pair that still covers all five configured towns."""
    config = load_config()
    names = [town["name"] for town in config["towns"]]

    obs_lat = np.arange(10.0, 18.01, 1.0)
    obs_lon = np.arange(23.0, 38.01, 1.0)
    loc = 20.0 + 0.2 * (obs_lat[:, None] - 10.0) + 0.2 * (obs_lon[None, :] - 23.0)
    periods = np.array([2, 10, 50])
    levels = loc[None, None, :, :] + np.array([10.0, 40.0, 70.0])[None, :, None, None]
    observed = xr.Dataset(
        {"return_period_precip": (("duration", "return_period", "lat", "lon"),
                                  levels, {"units": "mm"})},
        coords={"duration": ["24hr"], "return_period": periods, "lat": obs_lat, "lon": obs_lon},
    )

    fc_lat = np.arange(18.0, 9.99, -1.0)
    fc_lon = np.arange(23.0, 38.01, 1.0)
    steps = pd.to_timedelta(np.arange(11) * 24, unit="h")
    n_members = 51
    day = np.arange(10)[:, None, None, None]
    member = np.arange(n_members)[None, :, None, None]
    daily_mm = (8.0 + 6.0 * day + 5.0 * member
                + 0.2 * (fc_lat - 10.0)[None, None, :, None]
                + 0.1 * (fc_lon - 23.0)[None, None, None, :])
    cumulative = np.concatenate(
        [np.zeros((1, n_members, len(fc_lat), len(fc_lon))),
         np.cumsum(daily_mm, axis=0)],
        axis=0,
    ) / 1000.0
    forecast = xr.Dataset(
        {"tp": (("time", "step", "number", "latitude", "longitude"), cumulative[None])},
        coords={"time": [pd.Timestamp("2025-07-16")], "step": steps,
                "number": np.arange(n_members), "latitude": fc_lat, "longitude": fc_lon},
    )
    return config, observed, forecast, names


@pytest.fixture
def tiny_counts():
    """Known counts shared by every town for exact summary assertions."""
    config = load_config()
    names = [town["name"] for town in config["towns"]]
    values = np.array([
        [[10, 10, 10, 10, 10], [15, 15, 15, 15, 15], [12, 12, 12, 12, 12]],
        [[21, 21, 21, 21, 21], [25, 25, 25, 25, 25], [22, 22, 22, 22, 22]],
        [[5, 5, 5, 5, 5], [30, 30, 30, 30, 30], [26, 26, 26, 26, 26]],
    ])
    daily = xr.DataArray(
        values,
        dims=("number", "step", "town"),
        coords={"number": [0, 1, 2], "step": [0, 1, 2], "town": names,
                "forecast_day": ("step", [1, 2, 3]),
                "valid_time": ("step", pd.to_datetime(
                    ["2025-07-17", "2025-07-18", "2025-07-19"]))},
        name="daily_precipitation",
    )
    levels = xr.DataArray(
        [[20.0] * len(names), [22.0] * len(names), [40.0] * len(names)],
        dims=("threshold", "town"),
        coords={"threshold": [counts.fixed_key(20.0), "cmorph_2yr", "cmorph_10yr"],
                "town": names},
        name="threshold_mm",
    )
    count_values = counts.count_members(daily, levels)
    return config, names, daily, levels, count_values


def test_forecast_daily_totals_are_whole_day_differences(synthetic_stores):
    config, _, forecast, _ = synthetic_stores
    time_index, init = counts.forecast_time_index(forecast, "2025-07-16")
    assert time_index == 0 and init == pd.Timestamp("2025-07-16")
    daily, daily_init = counts.forecast_daily_totals(forecast, config, time_index)
    assert daily_init == init
    assert daily.dims == ("number", "step", "town")
    assert daily.sizes == {"number": 51, "step": 10, "town": 5}
    assert daily.forecast_day.values.tolist() == list(range(1, 11))
    assert str(daily.valid_time.values[0])[:10] == "2025-07-17"
    for town in config["towns"]:
        point = forecast["tp"].isel(time=0).sel(
            latitude=town["latitude"], longitude=town["longitude"], method="nearest")
        expected = point.diff("step").transpose("number", "step").values * 1000.0
        np.testing.assert_allclose(daily.sel(town=town["name"]).values, expected)


def test_time_and_coverage_errors_are_explicit(synthetic_stores):
    config, _, forecast, _ = synthetic_stores
    with pytest.raises(ValueError, match="not found"):
        counts.forecast_time_index(forecast, "2025-07-17")

    bad = copy.deepcopy(config)
    bad["towns"][0]["longitude"] = 100.0
    with pytest.raises(ValueError, match="outside the forecast domain"):
        counts.check_forecast_coverage(forecast, bad)


def test_read_thresholds_uses_each_town_nearest_pixel(synthetic_stores):
    config, observed, _, _ = synthetic_stores
    levels, units = counts.read_thresholds(observed, config)
    assert levels.dims == ("return_period", "town")
    assert levels.sizes["town"] == 5
    assert units["effective_units"] == "mm"
    for town in config["towns"]:
        expected = observed["return_period_precip"].sel(
            duration="24hr", return_period=[2, 10]).sel(
            lat=town["latitude"], lon=town["longitude"], method="nearest").values
        np.testing.assert_allclose(levels.sel(town=town["name"]).values, expected)


def test_threshold_grid_and_member_counts(tiny_counts):
    config, names, _, _levels, count_values = tiny_counts
    grid = counts.threshold_grid(
        xr.DataArray(
            [[22.0] * len(names), [40.0] * len(names)],
            dims=("return_period", "town"),
            coords={"return_period": [2, 10], "town": names},
        ),
        config,
        20.0,
    )
    assert grid.dims == ("threshold", "town")
    assert grid.sel(threshold=counts.fixed_key(20.0)).values.tolist() == [20.0] * len(names)
    assert grid.sel(threshold="cmorph_2yr").values.tolist() == [22.0] * len(names)

    per_day = count_values["per_day"].sel(town=names[0])
    np.testing.assert_array_equal(
        per_day.sel(threshold=counts.fixed_key(20.0)).values, [1, 2, 2])
    np.testing.assert_array_equal(
        per_day.sel(threshold="cmorph_2yr").values, [0, 2, 1])
    np.testing.assert_array_equal(
        per_day.sel(threshold="cmorph_10yr").values, [0, 0, 0])
    assert int(count_values["members_any"].sel(town=names[0], threshold="cmorph_2yr")) == 2
    assert int(count_values["member_days"].sel(town=names[0], threshold="cmorph_2yr")) == 3
    assert int(count_values["max_per_day"].sel(town=names[0], threshold="cmorph_2yr")) == 2
    assert int(count_values["days_any"].sel(town=names[0], threshold="cmorph_2yr")) == 2


def test_summary_includes_matching_xclim_counts(tiny_counts):
    config, names, daily, levels, count_values = tiny_counts
    table = counts.build_table(
        daily, levels, count_values, config, pd.Timestamp("2025-07-16"), 20.0)
    assert len(table) == len(names) * 3
    fixed = table[(table.town == names[0]) & (table.threshold == counts.fixed_key(20.0))].iloc[0]
    assert fixed.members_above_any_day == 2
    assert fixed.max_members_above_in_day == 2
    assert fixed.member_days_above == 5
    assert fixed.days_with_any_member == 3
    assert fixed.xclim_heavy_days_total == 5
    assert fixed.xclim_members_with_heavy_day == 2
    assert fixed.xclim_max_heavy_days_per_member == 3
    assert (table.member_days_above == table.xclim_heavy_days_total).all()


def test_plot_and_csv_outputs(tiny_counts, tmp_path):
    config, names, _, levels, count_values = tiny_counts
    paths = [
        counts.plot_town(count_values, levels, config, pd.Timestamp("2025-07-16"),
                         20.0, name, tmp_path)
        for name in names
    ]
    overview = counts.plot_overview(
        count_values, levels, config, pd.Timestamp("2025-07-16"), 20.0, tmp_path)
    table = counts.build_table(
        tiny_counts[2], levels, count_values, config, pd.Timestamp("2025-07-16"), 20.0)
    table_path = counts.write_table(table, tmp_path)
    assert len(paths) == len(names)
    assert all(path.exists() and path.stat().st_size > 1000 for path in paths)
    assert overview.exists() and overview.stat().st_size > 1000
    assert table_path.exists()
    assert len(pd.read_csv(table_path)) == len(names) * 3


def test_run_with_synthetic_stores(synthetic_stores, tmp_path, monkeypatch):
    config, observed, forecast, names = synthetic_stores

    def fake_open(settings):
        if settings["prefix"] == config["cmorph_reference"]["prefix"]:
            return observed, "synthetic-cmorph"
        return forecast, "synthetic-forecast"

    monkeypatch.setattr(counts, "open_store", fake_open)
    result = counts.run(config, tmp_path, init="2025-07-16")
    assert result["forecast_snapshot"] == "synthetic-forecast"
    assert result["observed_snapshot"] == "synthetic-cmorph"
    assert result["init"] == pd.Timestamp("2025-07-16")
    assert len(result["table"]) == len(names) * 3
    assert result["table_path"].exists()
    assert len(result["town_paths"]) == len(names)
    assert result["overview_path"].exists()
    assert len(list(tmp_path.glob("*.png"))) == len(names) + 1
    assert len(list(tmp_path.glob("*.csv"))) == 1
    saved = pd.read_csv(result["table_path"])
    assert len(saved) == len(names) * 3
    assert (saved.member_days_above == saved.xclim_heavy_days_total).all()


def test_default_run_uses_shared_monthly_starts_and_reports_unwritten_start(synthetic_stores, tmp_path, monkeypatch):
    config, observed, forecast, names = synthetic_stores
    starts = pd.to_datetime(config['forecast']['start_dates'])
    forecast = xr.concat([forecast.assign_coords(time=[start]) for start in starts], dim='time')
    forecast.tp.loc[{'time': starts[1]}] = np.nan
    monkeypatch.setattr(counts, 'open_store', lambda settings:
                        (observed, 'synthetic-cmorph') if settings['prefix'] == config['cmorph_reference']['prefix']
                        else (forecast, 'synthetic-forecast'))
    monkeypatch.setattr(counts, 'plot_town', lambda *args: tmp_path / 'town.png')
    monkeypatch.setattr(counts, 'plot_overview', lambda *args: tmp_path / 'overview.png')
    result = counts.run(config, tmp_path)
    assert list(result['starts']) == [starts[0], starts[2]]
    assert list(result['skipped_starts']) == [starts[1]]
    assert set(result['table'].forecast_init) == {'2025-06-16', '2025-08-16'}
    assert len(result['table']) == 2 * 3 * len(names)


def test_explicit_mm_depths_are_not_scaled_as_metres(synthetic_stores):
    config, _, forecast, _ = synthetic_stores
    forecast.tp.attrs['units'] = 'mm'
    daily, _ = counts.forecast_daily_totals(forecast, config, 0)
    assert daily.attrs['mm_factor'] == 1
    assert float(daily.max()) < 1
