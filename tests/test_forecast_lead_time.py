"""Part C's time alignment, scientific counts and resumable/offline workflow."""

import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from scripts import forecast_lead_time as lead
from scripts.common import (ConfigError, config_hash, extraction_hash, lead_time_windows,
                            load_config, validate_lead_time)
from scripts.rainfall_thresholds import file_sha256, write_json


@pytest.fixture
def inputs(tmp_path):
    config = load_config()
    config["forecast"]["start_dates"] = ["2025-07-16"]
    config["lead_time"]["cache_directory"] = str(tmp_path / "shared_cache")
    dates = pd.date_range("2025-07-09", "2025-07-22")
    values = np.zeros((14, 5, 51, 4, 4), dtype="float32")
    values[:, 2:, :, :, :] = .030
    values[:, 4:, :, :, :] += .010
    ds = xr.Dataset({"tp": (("time", "step", "number", "latitude", "longitude"), values)},
        coords={"time": dates, "step": np.array([0, 12, 24, 36, 48], dtype="timedelta64[h]"),
                "number": np.arange(51), "latitude": [17, 15.5, 14, 11],
                "longitude": [23, 32.5, 35.5, 38]})
    ds.tp.encoding["chunks"] = (1, 1, 51, 4, 4)
    obs = tmp_path / "observations"
    obs.mkdir()
    levels, maxima = [], []
    for town in config["towns"]:
        for period, value in [(2, 25.), (10, 50.)]:
            levels.append({"town": town["name"], "duration": "24hr", "return_period_years": period,
                           "threshold_mm": value, "units": "mm"})
        for year in range(1998, 2025):
            maxima.append({"town": town["name"], "duration": "24hr", "year": year,
                           "rainfall_mm": year - 1970, "units": "mm"})
    pd.DataFrame(levels).to_csv(obs / "thresholds.csv", index=False)
    pd.DataFrame(maxima).to_csv(obs / "annual_maxima.csv", index=False)
    write_json(obs / "settings_used.json", config)
    write_json(obs / "manifest.json", {"config_sha256": config_hash(config),
        "extraction_sha256": extraction_hash(config),
        "store_snapshots": {"cmorph": config["cmorph_reference"]["snapshot_id"]},
        "output_sha256": {name: file_sha256(obs / name) for name in
            ["settings_used.json", "thresholds.csv", "annual_maxima.csv"]}})
    return config, ds, obs


def test_windows_preserve_monthly_anchors_and_cover_42_daily_starts():
    config = load_config()
    validate_lead_time(config)
    expanded = lead.effective_config(config)
    assert config["forecast"]["start_dates"] == ["2025-06-16", "2025-07-16", "2025-08-16"]
    assert len(expanded["forecast"]["start_dates"]) == 42
    assert expanded["forecast"]["start_dates"][:2] == ["2025-06-09", "2025-06-10"]
    assert expanded["forecast"]["start_dates"][-1] == "2025-08-22"
    assert all(len(window["start_dates"]) == 14 for window in lead_time_windows(config))


@pytest.mark.parametrize("key,value", [("days_before", 1), ("days_after", True),
    ("signal_probability", 0), ("signal_probability", 1.1), ("max_source_mib", 0)])
def test_bad_lead_time_settings_fail_with_field_path(key, value):
    config = load_config()
    config["lead_time"][key] = value
    with pytest.raises(ConfigError, match="lead_time"):
        validate_lead_time(config)


def test_windows_must_fit_season_and_not_overlap():
    config = load_config()
    config["forecast"]["start_dates"] = ["2025-06-01"]
    with pytest.raises(ConfigError, match="within"):
        validate_lead_time(config)
    config["forecast"]["start_dates"] = ["2025-07-15", "2025-07-16"]
    with pytest.raises(ConfigError, match="overlap"):
        validate_lead_time(config)


def test_lead_time_compares_the_same_valid_day_and_keeps_missing_coverage():
    config = load_config()
    rows = []
    # Same valid day: 10-day first signal, a missing start and a later stronger signal.
    for start, day, count in [("2025-07-11", 10, 2), ("2025-07-12", 9, np.nan),
                               ("2025-07-13", 8, 11), ("2025-07-14", 7, 0)]:
        rows.append({"town": "Khartoum", "window_anchor": "2025-07-16", "initialization": start,
                     "forecast_day": day, "valid_end": "2025-07-21T00:00:00", "members_above": count})
    # A different valid day must not be conflated with the above event.
    rows.append({"town": "Khartoum", "window_anchor": "2025-07-16", "initialization": "2025-07-11",
                 "forecast_day": 1, "valid_end": "2025-07-12T00:00:00", "members_above": 1})
    events, summary, alarming = lead.diagnose_lead_time(pd.DataFrame(rows), config)
    target = summary[summary.criterion == "any_member"].iloc[0]
    assert target.valid_end == "2025-07-21T00:00:00"
    assert target.earliest_lead_days == 10
    assert target.available_starts == 3 and target.scheduled_starts == 4
    assert target.signaling_starts == 2 and target.consistency_percent == pytest.approx(200 / 3)
    strong = summary[summary.criterion == "configured_probability"].iloc[0]
    assert strong.minimum_members == 11
    assert strong.earliest_lead_days == 8
    assert alarming.initialization.iloc[0] == "2025-07-13"
    assert len(events) == 4


def test_no_signal_is_not_reported_as_an_early_warning():
    config = load_config()
    counts = pd.DataFrame([{"town": "Nyala", "window_anchor": "2025-07-16", "initialization": "2025-07-16",
        "forecast_day": 1, "valid_end": "2025-07-17T00:00:00", "members_above": 0.}])
    _, summary, alarming = lead.diagnose_lead_time(counts, config)
    assert set(summary.status) == {"no_signal"}
    assert summary.first_signal_start.isna().all()
    assert summary.earliest_lead_days.isna().all()
    assert alarming.status.iloc[0] == "no_signal"


def test_strict_member_count_at_exact_threshold():
    daily = xr.DataArray([[[25., 25.01], [26., 24.]]], dims=("town", "number", "time"),
        coords={"town": ["Nyala"], "number": [0, 1], "time": pd.date_range("2025-07-17", periods=2),
                "forecast_day": ("time", [1, 2])})
    thresholds = pd.DataFrame([{"town": "Nyala", "threshold_mm": 25.}])
    counts = lead.member_counts(daily, thresholds, "2025-07-16")
    assert counts.members_above.tolist() == [1, 1]


def test_full_run_missing_start_cache_reuse_and_offline_plots(inputs, tmp_path, monkeypatch):
    config, ds, obs = inputs
    ds.tp.loc[{"time": "2025-07-10"}] = np.nan
    monkeypatch.setattr(lead, "open_store", lambda _: (ds.copy(), "test-forecast"))
    out = tmp_path / "lead_time"
    lead.run_remote(config, obs, out)
    counts = pd.read_csv(out / "daily_member_counts.csv")
    assert len(counts) == 14 * 5 * 2
    missing = counts[counts.initialization == "2025-07-10"]
    assert missing.members_above.isna().all()
    assert set(missing.start_status) == {"skipped_all_nan"}
    assert counts[counts.initialization != "2025-07-10"].members_above.notna().all()
    assert json.loads((out / "manifest.json").read_text())["mode"] == "complete"
    assert len(pd.read_csv(out / "most_alarming_starts.csv")) == 5
    assert len(pd.read_csv(out / "lead_time_summary.csv")) == 10
    before = (out / "run_status.json").read_bytes()
    monkeypatch.setattr(xr.DataArray, "compute", lambda *a, **k: pytest.fail("unexpected source compute"))
    lead.run_remote(config, obs, out, inspection_only=True)
    assert (out / "run_status.json").read_bytes() == before
    lead.run_remote(config, obs, out)  # all 14 raw slices are cached, including the NaN start
    monkeypatch.setattr(lead, "open_store", lambda _: pytest.fail("offline plots opened a store"))
    (out / "figures").mkdir()
    unrelated = out / "figures" / "other.png"
    unrelated.write_bytes(b"keep")
    lead.plot_outputs(out)
    assert unrelated.read_bytes() == b"keep"
    assert len(list((out / "figures").glob("*_heatmap.png"))) == 5
    assert len(list((out / "figures").glob("*_plume.png"))) == 5
    with (out / "daily_member_counts.csv").open("a") as stream:
        stream.write("corrupted\n")
    with pytest.raises(ValueError, match="manifest"):
        lead.plot_outputs(out)


def test_cache_preview_does_not_download_missing_starts(inputs, tmp_path, monkeypatch):
    config, ds, obs = inputs
    monkeypatch.setattr(lead, "open_store", lambda _: (ds.copy(), "test-forecast"))
    effective, selected, report = lead.inspect_selection(ds, config, tmp_path, "test-forecast")
    lead.read_start(selected, "2025-07-16", effective, tmp_path, "test-forecast", report,
                    cache_directory=config["lead_time"]["cache_directory"])
    monkeypatch.setattr(xr.DataArray, "compute", lambda *a, **k: pytest.fail("preview fetched rainfall"))
    out = tmp_path / "preview"
    lead.run_remote(config, obs, out, cache_only=True)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["mode"] == "cache_preview"
    assert sum(row["status"] == "not_cached" for row in manifest["forecast_starts"]) == 13
    counts = pd.read_csv(out / "daily_member_counts.csv")
    assert counts.members_above.notna().sum() == 10
    assert counts[counts.initialization != "2025-07-16"].members_above.isna().all()


def test_budget_and_partial_missingness_stop_extraction(inputs, tmp_path, monkeypatch):
    config, ds, obs = inputs
    ds.tp.encoding["chunks"] = (1, 1, 51, 321, 261)
    config["lead_time"]["max_source_mib"] = 1
    monkeypatch.setattr(lead, "open_store", lambda _: (ds.copy(), "test-forecast"))
    out = tmp_path / "lead_time"
    with pytest.raises(ValueError, match="max_source_mib"):
        lead.run_remote(config, obs, out)
    assert not (out / "daily_member_counts.csv").exists()
    ds.tp.encoding["chunks"] = (1, 1, 51, 4, 4)
    ds.tp.loc[{"time": "2025-07-09", "step": np.timedelta64(24, "h"),
               "number": 0, "latitude": 15.5, "longitude": 32.5}] = np.nan
    config["lead_time"]["max_source_mib"] = 8192
    with pytest.raises(ValueError, match="Partially missing"):
        lead.run_remote(config, obs, out)
    assert json.loads((out / "run_status.json").read_text())["status"] == "failed"
