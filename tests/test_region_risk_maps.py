"""Offline checks for the Part D region-risk probability and frequency maps."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from scripts import region_risk_maps as risk
from scripts.common import load_config


@pytest.fixture
def synthetic_stores():
    """A small five-day forecast/CMORPH pair covering the configured region."""
    config = load_config()

    obs_lat = np.arange(10.0, 18.01, 1.0)
    obs_lon = np.arange(23.0, 38.01, 1.0)
    threshold = np.where(obs_lon[None, :] > 30.0, 35.0, 20.0)
    threshold = np.broadcast_to(threshold, (len(obs_lat), len(obs_lon))).copy()
    observed = xr.Dataset(
        {"return_period_precip": (
            ("duration", "return_period", "lat", "lon"),
            np.stack([threshold, threshold + 10.0])[None, ...],
            {"units": "mm"},
        )},
        coords={
            "duration": ["24hr"],
            "return_period": [2, 10],
            "lat": obs_lat,
            "lon": obs_lon,
        },
    )

    fc_lat = np.arange(18.0, 10.99, -0.5)
    fc_lon = np.arange(23.0, 37.01, 0.5)
    times = pd.to_datetime([
        "2025-06-01", "2025-07-01", "2025-08-01", "2025-08-20",
    ])
    # Include every three hours so the whole-day selection is exercised.
    steps = pd.to_timedelta(np.arange(21) * 6, unit="h")
    n_starts, n_days, n_members = len(times), 5, 3
    members = np.array([10.0, 20.0, 30.0])
    daily_mm = np.broadcast_to(
        members[None, None, :, None, None],
        (n_starts, n_days, n_members, len(fc_lat), len(fc_lon)),
    ).copy()
    zero = np.zeros((n_starts, 1, n_members, len(fc_lat), len(fc_lon)))
    daily_steps = np.concatenate([zero, np.cumsum(daily_mm, axis=1)], axis=1)
    cumulative = np.zeros((n_starts, len(steps), n_members, len(fc_lat), len(fc_lon)))
    cumulative[:, [0, 4, 8, 12, 16, 20]] = daily_steps / 1000.0
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
    return config, observed, forecast, times


def test_random_starts_are_reproducible_and_stratified(synthetic_stores):
    _, _, _, times = synthetic_stores
    starts = risk.choose_random_starts(times, n_starts=4, seed=42)
    assert starts.equals(risk.choose_random_starts(times, n_starts=4, seed=42))
    assert len(starts) == 4
    blocks = np.array_split(np.arange(len(times)), 4)
    positions = [times.get_loc(start) for start in starts]
    assert all(int(position) in block for position, block in zip(positions, blocks))
    assert risk.parse_start_dates(
        ["2025-06-01,2025-07-01", "2025-08-01"]
    ).tolist() == [pd.Timestamp("2025-06-01"),
                   pd.Timestamp("2025-07-01"),
                   pd.Timestamp("2025-08-01")]
    with pytest.raises(ValueError, match="3 or 4"):
        risk.parse_start_dates(["2025-06-01"])
    with pytest.raises(ValueError, match="3 or 4"):
        risk.choose_random_starts(times, n_starts=2, seed=42)


def test_whole_day_indices_ignore_six_hourly_steps():
    forecast = xr.Dataset(
        coords={"step": pd.to_timedelta(np.arange(21) * 6, unit="h")}
    )
    lead_h, day_indices = risk.daily_step_indices(forecast)
    assert lead_h[day_indices].tolist() == list(range(0, 121, 24))
    assert day_indices == [0, 4, 8, 12, 16, 20]
    indices, days = risk.cumulative_indices(forecast, (1, 2, 3, 4, 5))
    assert indices == day_indices
    assert days == (1, 2, 3, 4, 5)


def test_threshold_map_uses_nearest_cmorph_levels(synthetic_stores):
    config, observed, forecast, _ = synthetic_stores
    region = risk.select_region(
        forecast, config, "latitude", "longitude", ascending=False
    )
    threshold, units = risk.read_threshold_map(observed, region, config)
    assert units["effective_units"] == "mm"
    assert threshold.dims == ("latitude", "longitude")
    assert threshold.sizes == {"latitude": region.sizes["latitude"],
                               "longitude": region.sizes["longitude"]}
    assert float(threshold.min()) == pytest.approx(20.0)
    assert float(threshold.max()) == pytest.approx(35.0)


def test_probability_uses_strict_member_threshold_and_masks_small_samples(synthetic_stores):
    config, observed, forecast, times = synthetic_stores
    region = risk.select_region(
        forecast, config, "latitude", "longitude", ascending=False
    )
    threshold, _ = risk.read_threshold_map(observed, region, config)
    probability, elapsed = risk.read_probability_for_start(
        region, config, times[1], threshold, (1, 2, 3, 4, 5)
    )
    assert elapsed >= 0
    assert probability.dims == ("time", "step", "latitude", "longitude")
    assert probability.sizes == {
        "time": 1,
        "step": 5,
        "latitude": region.sizes["latitude"],
        "longitude": region.sizes["longitude"],
    }
    # Members 20 and 30 are not above the 20 mm threshold; only 30 is above.
    western = probability.sel(longitude=24.5)
    assert np.allclose(western.values, 1.0 / 3.0)
    # The eastern threshold is 35 mm, so even the 30 mm member is below it.
    eastern = probability.sel(longitude=36.5)
    assert np.allclose(eastern.values, 0.0)


def test_frequency_counts_cases_above_the_chosen_probability(synthetic_stores):
    config, observed, forecast, times = synthetic_stores
    region = risk.select_region(
        forecast, config, "latitude", "longitude", ascending=False
    )
    threshold, _ = risk.read_threshold_map(observed, region, config)
    probabilities, kept, skipped, timings = risk.read_probabilities(
        region, config, times, threshold, (1, 2, 3, 4, 5)
    )
    assert len(kept) == 4
    assert len(skipped) == 0
    assert len(timings) == 4
    frequency = risk.frequency_map(probabilities, 0.20)
    assert frequency.dims == ("latitude", "longitude")
    assert frequency.attrs["cases"] == 20
    assert int(frequency.sel(longitude=24.5).max()) == 20
    assert int(frequency.sel(longitude=36.5).max()) == 0
    assert int(risk.frequency_map(probabilities, 0.5).max()) == 0


def test_all_nan_start_is_skipped(synthetic_stores):
    config, observed, forecast, times = synthetic_stores
    forecast = forecast.copy(deep=True)
    forecast["tp"].loc[{"time": times[1]}] = np.nan
    region = risk.select_region(
        forecast, config, "latitude", "longitude", ascending=False
    )
    threshold, _ = risk.read_threshold_map(observed, region, config)
    probabilities, kept, skipped, timings = risk.read_probabilities(
        region, config, times, threshold, (1, 2, 3, 4, 5)
    )
    assert len(kept) == 3
    assert skipped.tolist() == [times[1]]
    assert len(timings) == 3
    assert probabilities.sizes["time"] == 3


def test_partial_missing_data_is_rejected(synthetic_stores):
    config, _, forecast, times = synthetic_stores
    forecast = forecast.copy(deep=True)
    forecast["tp"].loc[{
        "time": times[0],
        "step": forecast["step"].values[4],
    }] = np.nan
    region = risk.select_region(
        forecast, config, "latitude", "longitude", ascending=False
    )
    threshold = xr.DataArray(
        np.full((region.sizes["latitude"], region.sizes["longitude"]), 20.0),
        dims=("latitude", "longitude"),
        coords={"latitude": region["latitude"], "longitude": region["longitude"]},
    )
    with pytest.raises(ValueError, match="partial missing data"):
        risk.read_probability_for_start(
            region, config, times[0], threshold, (1, 2, 3, 4, 5)
        )


def test_plots_and_summary_are_written(synthetic_stores, tmp_path):
    config, observed, forecast, times = synthetic_stores
    region = risk.select_region(
        forecast, config, "latitude", "longitude", ascending=False
    )
    threshold, _ = risk.read_threshold_map(observed, region, config)
    probabilities, kept, skipped, timings = risk.read_probabilities(
        region, config, times, threshold, (1, 2, 3, 4, 5)
    )
    frequency = risk.frequency_map(probabilities, 0.20)
    summary = risk.summarize_starts(
        probabilities, kept, skipped, timings, 0.20
    )
    assert len(summary) == 5
    paths = risk.plot_probability_maps(probabilities, config, tmp_path, 0.20)
    frequency_path = risk.plot_frequency_map(
        frequency, config, tmp_path, 0.20, 20
    )
    assert len(paths) == 4
    assert all(path.exists() and path.stat().st_size > 1000 for path in paths)
    assert frequency_path.exists() and frequency_path.stat().st_size > 1000


def test_run_with_synthetic_stores(synthetic_stores, tmp_path, monkeypatch):
    config, observed, forecast, times = synthetic_stores

    def fake_open(settings):
        if settings["prefix"] == config["cmorph_reference"]["prefix"]:
            return observed, "synthetic-cmorph"
        return forecast, "synthetic-forecast"

    monkeypatch.setattr(risk, "open_store", fake_open)
    result = risk.run(
        config, tmp_path,
        start_dates=times, days=(1, 2, 3, 4, 5),
        probability_threshold=0.20,
    )
    assert result["forecast_snapshot"] == "synthetic-forecast"
    assert result["observed_snapshot"] == "synthetic-cmorph"
    assert len(result["starts"]) == 4
    assert result["n_cases"] == 20
    assert result["summary_path"].exists()
    assert result["hotspot_path"].exists()
    assert len(result["probability_paths"]) == 4
    assert result["frequency_path"].exists()
    assert len(list(tmp_path.glob("*.png"))) == 5
    assert len(list(tmp_path.glob("*.csv"))) == 2
    summary = pd.read_csv(result["summary_path"])
    assert len(summary) == 5
    assert summary.iloc[-1]["start_date"] == "season"
    hotspots = pd.read_csv(result["hotspot_path"])
    assert not hotspots.empty
    assert {"latitude", "longitude", "frequency"}.issubset(hotspots.columns)
