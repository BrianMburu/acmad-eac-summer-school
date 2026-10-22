"""Configuration regression checks for the audit findings; no network reads."""

import json
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.common import (
    ROOT,
    ConfigError,
    config_hash,
    extraction_hash,
    load_config,
    slugify,
    validate_common,
    validate_thresholds,
)


@pytest.mark.parametrize("path,value,field", [
    (("forecast", "start_dates"), ["not-a-date"], "forecast.start_dates"),
    (("forecast", "start_dates"), ["2025-05-31"], "forecast.start_dates"),
    (("forecast", "start_dates"), ["2025-06-01", "2025-06-01"], "forecast.start_dates"),
    (("forecast", "start_dates"), [], "forecast.start_dates"),
    (("forecast", "endpoint"), "not-a-url", "forecast.endpoint"),
    (("forecast", "endpoint"), "https://[", "forecast.endpoint"),
    (("forecast", "snapshot_id"), "", "forecast.snapshot_id"),
    (("forecast", "variable"), "", "forecast.variable"),
    (("cmorph_reference", "reference_start_year"), 2025, "reference_start_year"),
    (("cmorph_reference", "reference_start_year"), True, "reference_start_year"),
    (("towns", 0, "name"), "", "towns[0].name"),
    (("towns", 0, "longitude"), "32.53", "towns[0].longitude"),
    (("towns", 0, "latitude"), float("nan"), "towns[0].latitude"),
    (("towns", 0, "latitude"), True, "towns[0].latitude"),
    (("region_extent", "south"), 11.9, "towns[4].extent"),
    (("coordinate_reference_system",), "EPSG:3857", "coordinate_reference_system"),
    (("start_date",), "2025-09-01", "start_date"),
    (("start_date",), "2025-05-01", "start_date/end_date"),
    (("execution", "workers"), 0, "execution.workers"),
    (("execution", "workers"), True, "execution.workers"),
    (("schema_version",), True, "schema_version"),
])
def test_rejects_invalid_shared_settings_with_field_path(path, value, field):
    config = load_config()
    target = config
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ConfigError) as error:
        validate_common(config)
    assert field in str(error.value)


def test_missing_and_unknown_fields_are_explicit():
    config = load_config()
    config["region_extent"]["wset"] = config["region_extent"].pop("west")
    with pytest.raises(ConfigError, match="region_extent.west"):
        validate_common(config)
    config = load_config()
    config["forecast"]["start_dtaes"] = None
    with pytest.raises(ConfigError, match="start_dtaes"):
        validate_common(config)


def test_town_names_are_unique_ignoring_case():
    config = load_config()
    config["towns"][1]["name"] = config["towns"][0]["name"].lower()
    with pytest.raises(ConfigError, match="unique"):
        validate_common(config)


def test_town_names_must_produce_unique_file_slugs():
    config = load_config()
    config["towns"][1]["name"] = config["towns"][3]["name"].replace(" ", "-")
    assert config["towns"][1]["name"].casefold() != config["towns"][3]["name"].casefold()
    assert slugify(config["towns"][1]["name"]) == slugify(config["towns"][3]["name"])
    with pytest.raises(ConfigError, match="unique file-name slugs"):
        validate_common(config)


def test_comparison_must_name_an_exported_threshold():
    config = load_config()
    config["comparison"]["duration"] = "7day"
    config["comparison"]["return_period_years"] = 20
    with pytest.raises(ConfigError, match="comparison.duration"):
        validate_thresholds(config)
    config["comparison"]["duration"] = "24hr"
    with pytest.raises(ConfigError, match="comparison.return_period_years"):
        validate_thresholds(config)


def test_extraction_hash_ignores_forecast_and_output_settings():
    config = load_config()
    changed = deepcopy(config)
    changed["forecast"]["start_dates"] = ["2025-06-01"]
    changed["comparison"]["duration"] = "48hr"
    changed["execution"]["output_directory"] = "somewhere/else"
    assert config_hash(config) != config_hash(changed)
    assert extraction_hash(config) == extraction_hash(changed)
    changed["towns"][0]["latitude"] += 0.01
    assert extraction_hash(config) != extraction_hash(changed)


def test_threshold_rules_are_separate_from_shared_rules():
    config = load_config()
    del config["thresholds"]
    validate_common(config)
    with pytest.raises(ConfigError, match="thresholds: required"):
        validate_thresholds(config)


def test_forecast_reads_require_explicit_start_dates():
    config = load_config()
    config["forecast"]["start_dates"] = None
    validate_common(config)
    with pytest.raises(ConfigError, match="select start dates"):
        validate_common(config, require_forecast_dates=True)
    config["forecast"]["start_dates"] = ["2025-06-01", "2025-08-31"]
    validate_common(config, require_forecast_dates=True)


@pytest.mark.parametrize("key,value", [
    ("durations", ["24hr", "24hr"]),
    ("durations", ["24hr", 48]),
    ("return_periods_years", [2, 10]),
    ("map_duration", "7day"),
    ("map_return_period_years", 10.0),
    ("units_if_missing", "m"),
])
def test_threshold_settings_reject_unsupported_values(key, value):
    config = load_config()
    config["thresholds"][key] = value
    with pytest.raises(ConfigError, match="thresholds"):
        validate_thresholds(config)


def test_defaults_are_independent_and_export_matches_source():
    config = load_config()
    config["towns"][0]["name"] = "Changed"
    config["forecast"]["snapshot_id"] = None
    fresh = load_config()
    assert fresh["towns"][0]["name"] == "Khartoum"
    assert fresh["forecast"]["snapshot_id"] is not None
    assert json.loads((ROOT / "grid.json").read_text()) == fresh


def test_common_cli_needs_no_scientific_imports_and_exports_snapshot(tmp_path):
    script = "import scripts.common, sys; assert not {'icechunk', 'numpy', 'xarray', 'scipy'} & sys.modules.keys()"
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, check=True)
    target = tmp_path / "settings.json"
    subprocess.run([sys.executable, "-m", "scripts.common", "--export", str(target)], cwd=ROOT, check=True)
    assert load_config(target) == load_config()
    result = subprocess.run([sys.executable, "-m", "scripts.common"], cwd=ROOT,
                            check=True, capture_output=True, text=True)
    assert "Shared and threshold settings valid" in result.stdout


def test_json_load_errors_identify_file(tmp_path):
    target = tmp_path / "broken.json"
    target.write_text("{broken")
    with pytest.raises(ConfigError, match="broken.json"):
        load_config(target)


@pytest.mark.parametrize("pinned", [True, False])
def test_data_access_uses_selected_snapshot_or_branch(monkeypatch, pinned):
    import icechunk
    import xarray as xr

    from scripts.data_access import open_store

    settings = load_config()["cmorph_reference"]
    if not pinned:
        settings["snapshot_id"] = None
    session = SimpleNamespace(store=object(), snapshot_id="selected-snapshot")
    repo = SimpleNamespace(readonly_session=Mock(return_value=session))
    monkeypatch.setattr(icechunk, "Repository", SimpleNamespace(open=Mock(return_value=repo)))
    storage = Mock(return_value=object())
    monkeypatch.setattr(icechunk, "s3_storage", storage)
    dataset = object()
    opener = Mock(return_value=dataset)
    monkeypatch.setattr(xr, "open_zarr", opener)
    ds, snapshot = open_store(settings)
    assert ds is dataset and snapshot == "selected-snapshot"
    if pinned:
        repo.readonly_session.assert_called_once_with(snapshot_id=settings["snapshot_id"])
    else:
        repo.readonly_session.assert_called_once_with(settings["branch"])
    assert storage.call_args.kwargs["anonymous"] is True
    assert storage.call_args.kwargs["from_env"] is False
