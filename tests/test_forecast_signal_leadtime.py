"""Offline checks for the Part C forecast lead-time analysis; no remote reads."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from scripts import forecast_signal_leadtime as leadtime
from scripts.common import load_config


@pytest.fixture
def synthetic_stores():
    """A small three-start forecast/CMORPH pair covering all five towns."""
    config = load_config()
    names = [town["name"] for town in config["towns"]]

    obs_lat = np.arange(10.0, 18.01, 1.0)
    obs_lon = np.arange(23.0, 38.01, 1.0)
    base = 15.0 + 0.2 * (obs_lat[:, None] - 10.0) + 0.2 * (obs_lon[None, :] - 23.0)
    observed = xr.Dataset(
        {"return_period_precip": (
            ("duration", "return_period", "lat", "lon"),
            np.stack([base, base + 30.0])[None, ...],
            {"units": "mm"},
        )},
        coords={
            "duration": ["24hr"],
            "return_period": [2, 10],
            "lat": obs_lat,
            "lon": obs_lon,
        },
    )

    fc_lat = np.arange(18.0, 9.99, -1.0)
    fc_lon = np.arange(23.0, 38.01, 1.0)
    times = pd.to_datetime(["2025-07-01", "2025-07-02", "2025-07-03"])
    steps = pd.to_timedelta(np.arange(11) * 24, unit="h")
    n_starts, n_steps, n_members = len(times), len(steps), 51
    start = np.arange(n_starts)[:, None, None, None, None]
    day = np.arange(n_steps - 1)[None, :, None, None, None]
    member = np.arange(n_members)[None, None, :, None, None]
    daily_mm = (
        8.0
        + 4.0 * start
        + 5.0 * member
        + 6.0 * day
        + 0.2 * (fc_lat - 10.0)[None, None, None, :, None]
        + 0.2 * (fc_lon - 23.0)[None, None, None, None, :]
    )
    zero = np.zeros((n_starts, 1, n_members, len(fc_lat), len(fc_lon)))
    cumulative = np.concatenate([zero, np.cumsum(daily_mm, axis=1)], axis=1) / 1000.0
    forecast = xr.Dataset(
        {"tp": (
            ("time", "step", "number", "latitude", "longitude"),
            cumulative,
        )},
        coords={
            "time": times,
            "step": steps,
            "number": np.arange(n_members),
            "latitude": fc_lat,
            "longitude": fc_lon,
        },
    )
    return config, observed, forecast, names


@pytest.fixture
def direct_daily():
    """Known two-start daily totals for exact count, summary and plot checks."""
    config = load_config()
    names = [town["name"] for town in config["towns"]]
    # time, number, step; strict > 25 gives 1, 2, 0 on the first start
    # and 3, 1, 3 on the second, for every town.
    by_member = np.array([
        [[30.0, 30.0, 10.0], [25.0, 30.0, 10.0], [10.0, 10.0, 10.0]],
        [[30.0, 30.0, 30.0], [30.0, 10.0, 30.0], [30.0, 10.0, 30.0]],
    ])
    values = np.broadcast_to(by_member[:, :, :, None],
                             (2, 3, 3, len(names))).copy()
    starts = pd.to_datetime(["2025-07-01", "2025-07-02"])
    days = [1, 2, 3]
    valid = np.asarray([
        [start + pd.Timedelta(days=day) for day in days]
        for start in starts
    ], dtype="datetime64[ns]")
    daily = xr.DataArray(
        values,
        dims=("time", "number", "step", "town"),
        coords={
            "time": starts,
            "number": [0, 1, 2],
            "step": [0, 1, 2],
            "town": names,
            "forecast_day": ("step", days),
            "valid_time": (("time", "step"), valid),
        },
        name="daily_precipitation",
        attrs={"units": "mm/day"},
    )
    thresholds = xr.DataArray(
        [25.0] * len(names), dims="town", coords={"town": names},
        name="threshold_mm",
    )
    counts = leadtime.count_members(daily, thresholds)
    return config, names, daily, thresholds, counts


def test_window_and_start_lookup(synthetic_stores):
    _, _, forecast, _ = synthetic_stores
    starts = leadtime.window_starts("2025-07-01", "2025-07-03")
    assert starts.tolist() == [pd.Timestamp("2025-07-01"),
                               pd.Timestamp("2025-07-02"),
                               pd.Timestamp("2025-07-03")]
    assert leadtime.forecast_start_indices(forecast, starts).tolist() == [0, 1, 2]
    with pytest.raises(ValueError, match="not found"):
        leadtime.forecast_start_indices(forecast, starts.append(
            pd.DatetimeIndex(["2025-07-04"])))
    with pytest.raises(ValueError, match="start must not be after"):
        leadtime.window_starts("2025-07-03", "2025-07-01")
    with pytest.raises(ValueError, match="at least two"):
        leadtime.window_starts("2025-07-01", "2025-07-01")


def test_daily_step_indices_ignore_three_hourly_steps():
    forecast = xr.Dataset(
        coords={"step": pd.to_timedelta(np.arange(41) * 6, unit="h")}
    )
    lead_h, day_indices = leadtime.daily_step_indices(forecast)
    assert lead_h[day_indices].tolist() == list(range(0, 241, 24))
    assert day_indices == [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40]


def test_reads_only_whole_day_leads_and_differences_cumulative(synthetic_stores):
    config, _, forecast, names = synthetic_stores
    starts = leadtime.window_starts("2025-07-01", "2025-07-03")
    daily, kept, skipped = leadtime.read_window_daily_totals(forecast, config, starts)
    assert kept.tolist() == starts.tolist()
    assert len(skipped) == 0
    assert daily.dims == ("time", "number", "step", "town")
    assert daily.sizes == {"time": 3, "number": 51, "step": 10, "town": 5}
    assert daily["forecast_day"].values.tolist() == list(range(1, 11))
    assert str(daily["valid_time"].values[0, 0])[:10] == "2025-07-02"
    for town in config["towns"]:
        point = forecast["tp"].isel(time=0).sel(
            latitude=town["latitude"], longitude=town["longitude"], method="nearest"
        )
        expected = point.diff("step").transpose("number", "step").values * 1000.0
        np.testing.assert_allclose(
            daily.sel(time=starts[0], town=town["name"]).transpose("number", "step").values,
            expected,
        )
    assert names[0] in daily["town"].values


def test_single_start_read_works_for_plume_regeneration(synthetic_stores):
    config, _, forecast, _ = synthetic_stores
    starts = pd.DatetimeIndex(["2025-07-02"])
    daily, kept, skipped = leadtime.read_window_daily_totals(forecast, config, starts)
    assert kept.tolist() == starts.tolist()
    assert len(skipped) == 0
    assert daily.sizes["time"] == 1


def test_all_nan_start_is_skipped(synthetic_stores):
    config, _, forecast, _ = synthetic_stores
    forecast = forecast.copy(deep=True)
    forecast["tp"].loc[{"time": forecast["time"].values[1]}] = np.nan
    starts = leadtime.window_starts("2025-07-01", "2025-07-03")
    daily, kept, skipped = leadtime.read_window_daily_totals(forecast, config, starts)
    assert kept.tolist() == [starts[0], starts[2]]
    assert skipped.tolist() == [starts[1]]
    assert daily.sizes["time"] == 2


def test_counts_are_strict_and_summary_is_consistent(direct_daily):
    config, names, daily, thresholds, counts = direct_daily
    # Exactly 25 mm is not above the strict > threshold.
    assert int(counts.sel(town=names[0], time=pd.Timestamp("2025-07-01")).sum()) == 3
    assert counts.sizes == {"time": 2, "step": 3, "town": 5}
    summary = leadtime.summarize_signals(counts, daily, thresholds, config)
    row = summary[(summary.town == names[0]) & (summary.valid_date == "2025-07-03")
                  & (summary.criterion == "any_member")].iloc[0]
    assert row.earliest_signal_start == "2025-07-01"
    assert row.earliest_signal_lead_day == 2
    assert row.signaling_starts == 2
    assert row.available_starts == 2
    assert row.fraction_starts_with_signal == 1.0
    assert row.total_member_days_above == 5
    assert row.max_members_above_in_day == 3
    assert row.longest_consecutive_start_run == 2


def test_most_alarming_start_selection(direct_daily):
    _, names, _, _, counts = direct_daily
    best = leadtime.most_alarming_start(counts)
    assert best["town"] == names[0]
    assert best["start"] == pd.Timestamp("2025-07-02")
    assert best["total_member_days"] == 7
    assert best["peak_members"] == 3
    assert best["peak_forecast_day"] == 1


def test_heatmap_and_plume_outputs(direct_daily, tmp_path):
    _, names, daily, thresholds, counts = direct_daily
    best = leadtime.most_alarming_start(counts)
    paths = [
        leadtime.plot_heatmap(counts, thresholds, name, tmp_path)
        for name in names
    ]
    plume = leadtime.plot_plume(daily, counts, thresholds, best, tmp_path)
    assert len(paths) == len(names)
    assert all(path.exists() and path.stat().st_size > 1000 for path in paths)
    assert plume.exists() and plume.stat().st_size > 1000


def test_run_with_synthetic_stores(synthetic_stores, tmp_path, monkeypatch):
    config, observed, forecast, names = synthetic_stores

    def fake_open(settings):
        if settings["prefix"] == config["cmorph_reference"]["prefix"]:
            return observed, "synthetic-cmorph"
        return forecast, "synthetic-forecast"

    monkeypatch.setattr(leadtime, "open_store", fake_open)
    result = leadtime.run(
        config, tmp_path,
        window_start="2025-07-01", window_end="2025-07-03",
    )
    assert result["forecast_snapshot"] == "synthetic-forecast"
    assert result["observed_snapshot"] == "synthetic-cmorph"
    assert len(result["starts"]) == 3
    assert set(result["summary"].town) == set(names)
    assert set(result["summary"].criterion) == {"any_member", "probability_threshold"}
    assert result["summary_path"].exists()
    assert result["counts_path"].exists()
    assert len(result["heatmap_paths"]) == len(names)
    assert result["plume_path"].exists()
    assert len(list(tmp_path.glob("*.png"))) == len(names) + 1
    assert len(list(tmp_path.glob("*.csv"))) == 2
    saved = pd.read_csv(result["summary_path"])
    assert set(saved.town) == set(names)
    assert len(saved) == len(names) * 12 * 2
    assert saved.available_starts.between(1, 3).all()
    long_counts = pd.read_csv(result["counts_path"])
    assert len(long_counts) == 3 * 10 * len(names)
    assert long_counts.columns.tolist() == [
        "forecast_start", "valid_date", "forecast_day", "town", "members_above",
    ]


def test_read_two_year_uses_nearest_pixel(synthetic_stores):
    config, observed, _, _ = synthetic_stores
    thresholds, units = leadtime.read_two_year(observed, config)
    assert thresholds.dims == ("town",)
    assert thresholds.sizes["town"] == 5
    assert units["effective_units"] == "mm"
    for town in config["towns"]:
        expected = observed["return_period_precip"].sel(
            duration="24hr", return_period=2
        ).sel(lat=town["latitude"], lon=town["longitude"], method="nearest").item()
        assert thresholds.sel(town=town["name"]).item() == pytest.approx(expected)


def test_partial_missing_data_is_rejected(synthetic_stores):
    config, _, forecast, _ = synthetic_stores
    forecast = forecast.copy(deep=True)
    forecast["tp"].loc[{
        "time": forecast["time"].values[1],
        "step": forecast["step"].values[3],
    }] = np.nan
    with pytest.raises(ValueError, match="partial missing data"):
        leadtime.read_window_daily_totals(
            forecast, config,
            leadtime.window_starts("2025-07-01", "2025-07-03"),
        )


def test_signals_for_different_valid_days_do_not_imply_event_consistency(direct_daily):
    config, names, daily, thresholds, counts = direct_daily
    counts = counts.copy(deep=True)
    counts[:] = 0
    counts[0, 0, :] = 1  # July 2, only the July 1 start can reach this day.
    counts[1, 0, :] = 1  # July 3: the July 1 start did not warn for this day.
    summary = leadtime.summarize_signals(counts, daily, thresholds, config)
    row = summary[(summary.town == names[0]) & (summary.valid_date == '2025-07-03')
                  & (summary.criterion == 'any_member')].iloc[0]
    assert row.available_starts == 2
    assert row.signaling_starts == 1
    assert row.fraction_starts_with_signal == 0.5
    assert row.earliest_signal_start == '2025-07-02'
    assert row.earliest_signal_lead_day == 1


def test_calendar_gap_breaks_consistency_and_probability_requires_eleven_members(direct_daily):
    config, names, daily, thresholds, counts = direct_daily
    starts = pd.to_datetime(['2025-07-01', '2025-07-03'])
    # Both starts reach July 4: day 3 for July 1, day 1 for July 3.
    counts = counts.assign_coords(time=starts)
    counts.attrs['ensemble_size'] = 51
    counts[:] = 0
    counts[0, 2, :] = 11
    counts[1, 0, :] = 10
    valid = np.array([[start + pd.Timedelta(days=int(day)) for day in [1, 2, 3]]
                      for start in starts], dtype='datetime64[ns]')
    daily = daily.assign_coords(time=starts, valid_time=(('time', 'step'), valid))
    summary = leadtime.summarize_signals(counts, daily, thresholds, config)
    event = summary[(summary.town == names[0]) & (summary.valid_date == '2025-07-04')]
    any_member = event[event.criterion == 'any_member'].iloc[0]
    warning = event[event.criterion == 'probability_threshold'].iloc[0]
    assert any_member.signaling_starts == 2
    assert any_member.longest_consecutive_start_run == 1
    assert warning.minimum_members == 11
    assert warning.signaling_starts == 1
    assert warning.earliest_signal_start == '2025-07-01'
    assert warning.earliest_signal_lead_day == 3


def test_explicit_mm_depths_and_default_three_windows(synthetic_stores, tmp_path, monkeypatch):
    config, observed, forecast, names = synthetic_stores
    starts = pd.DatetimeIndex([d for w in config['forecast_analysis']['lead_time_windows']
                               for d in pd.date_range(w['start'], w['end'])])
    forecast = xr.concat([forecast.isel(time=[0]).assign_coords(time=[start]) for start in starts], dim='time')
    forecast.tp.attrs['units'] = 'mm'
    monkeypatch.setattr(leadtime, 'open_store', lambda settings:
                        (observed, 'synthetic-cmorph') if settings['prefix'] == config['cmorph_reference']['prefix']
                        else (forecast, 'synthetic-forecast'))
    monkeypatch.setattr(leadtime, 'plot_heatmap', lambda *args, **kwargs: tmp_path / 'heatmap.png')
    monkeypatch.setattr(leadtime, 'plot_plume', lambda *args: tmp_path / 'plume.png')
    result = leadtime.run(config, tmp_path)
    assert result['starts'].equals(starts)
    assert result['counts'].sizes == {'time': 42, 'step': 10, 'town': len(names)}
    assert float(result['daily'].max()) < 1
    assert int(result['counts'].max()) == 0
