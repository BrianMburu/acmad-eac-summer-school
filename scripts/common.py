"""Edit shared settings here. Inspect them with ``python -m scripts.common``.

grid.json is a generated export. This module imports only the standard library
and performs no network access. Data helpers live in scripts/data_access.py.
"""

import argparse
import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXTRACTION_KEYS = ("region_extent", "towns", "cmorph_reference", "thresholds")

# Geography: named bounds in degrees east/north (WGS84).
COUNTRY = "Sudan"
COUNTRY_CODE = "SD"
COORDINATE_REFERENCE_SYSTEM = "EPSG:4326"
COORDINATE_SOURCE = "https://www.geonames.org/search.html?country=SD"
REGION = {"west": 24.25, "east": 37.0, "south": 11.5, "north": 16.25}
TOWNS = [
    {"name": "Khartoum", "latitude": 15.551772, "longitude": 32.532406},
    {"name": "Kassala", "latitude": 15.450992, "longitude": 36.399980},
    {"name": "Gedaref", "latitude": 14.034927, "longitude": 35.383444},
    {"name": "El Obeid", "latitude": 13.184212, "longitude": 30.216694},
    {"name": "Nyala", "latitude": 12.048882, "longitude": 24.880694},
]
TOWN_EXTENT_HALF_WIDTH_DEGREES = 0.5  # derive 1° × 1° boxes from the centres

# Forecast dates are separate from historical CMORPH reference years.
FORECAST_START_DATE = "2025-06-01"
FORECAST_END_DATE = "2025-08-31"
FORECAST_START_DATES = None  # whole-group decision; required before forecast reads
CMORPH_YEARS = (1998, 2024)

# Pinned snapshots reproduce the completed run. Set snapshot_id to None to
# follow the named branch; the actual snapshot is always recorded in results.
PUBLIC_STORAGE = {"endpoint": "https://data.source.coop", "bucket": "e4drr-project",
                  "region": "us-east-1", "branch": "main"}
CMORPH_STORE = {
    **PUBLIC_STORAGE, "prefix": "observations/cmorph_rp_icechunk",
    "snapshot_id": "309ZYV7EMDMNPD0EDZK0", "variable": "return_period_precip",
    "annual_maxima_variable": "annual_maxima", "latitude_order": "ascending",
}
FORECAST_STORE = {
    **PUBLIC_STORAGE, "prefix": "forecasts/ecmwf-ifs-ea-swio-realized-v3/49r1-jja2025",
    "snapshot_id": "212QY6MDW3RZ7PWD7A2G", "variable": "tp",
    "latitude_order": "descending", "available_start_date": "2025-06-01",
    "available_end_date": "2025-08-31",
}

# Observed rainfall threshold settings. Depths are in mm over each duration.
DURATIONS = ("24hr", "48hr")
RETURN_PERIODS = (2, 10, 50)
MAP_DURATION = "24hr"
MAP_RETURN_PERIOD = 10
UNITS_IF_MISSING = "mm"  # E4 assumption; inspection records every use
COMPARISON = {"duration": "24hr", "return_period_years": 2,
              "exceedance_operator": ">", "matching": "nearest"}
WORKERS = 2
OUTPUT_DIRECTORY = "out/rainfall_thresholds"


def default_config():
    """Build a fresh dictionary; callers cannot mutate the module's defaults."""
    towns = deepcopy(TOWNS)
    for town in towns:
        lat, lon, half = town["latitude"], town["longitude"], TOWN_EXTENT_HALF_WIDTH_DEGREES
        town["extent"] = {"west": round(lon - half, 6), "east": round(lon + half, 6),
                          "south": round(lat - half, 6), "north": round(lat + half, 6)}
    return {"schema_version": 2, "country": COUNTRY, "country_code": COUNTRY_CODE,
            "coordinate_reference_system": COORDINATE_REFERENCE_SYSTEM,
            "coordinate_source": COORDINATE_SOURCE, "region_extent": deepcopy(REGION),
            "towns": towns, "start_date": FORECAST_START_DATE, "end_date": FORECAST_END_DATE,
            "forecast": {**deepcopy(FORECAST_STORE), "start_dates": deepcopy(FORECAST_START_DATES)},
            "cmorph_reference": {**deepcopy(CMORPH_STORE),
                                 "reference_start_year": CMORPH_YEARS[0],
                                 "reference_end_year": CMORPH_YEARS[1]},
            "thresholds": {"durations": list(DURATIONS), "return_periods_years": list(RETURN_PERIODS),
                           "map_duration": MAP_DURATION, "map_return_period_years": MAP_RETURN_PERIOD,
                           "units_if_missing": UNITS_IF_MISSING},
            "comparison": deepcopy(COMPARISON),
            "execution": {"workers": WORKERS, "output_directory": OUTPUT_DIRECTORY}}


class ConfigError(ValueError):
    """A settings problem, with the field path in its message."""


def _object(value, path, required, optional=()):
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: expected an object")
    for key in required:
        if key not in value:
            raise ConfigError(f"{path}.{key}: required field is missing")
    extra = set(value) - set(required) - set(optional)
    if extra:
        raise ConfigError(f"{path}: unknown fields {', '.join(sorted(extra))}")


def _text(value, path):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ConfigError(f"{path}: expected nonempty text without surrounding whitespace")


def _number(value, path, low, high, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high
            or (integer and not isinstance(value, int))):
        kind = "integer" if integer else "finite number"
        raise ConfigError(f"{path}: expected a {kind} between {low} and {high}")


def _date(value, path):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (TypeError, ValueError):
        raise ConfigError(f"{path}: expected an ISO date YYYY-MM-DD") from None


def inside(box, latitude, longitude):
    return (box["south"] <= latitude <= box["north"]
            and box["west"] <= longitude <= box["east"])


def box_inside(domain, box):
    return inside(domain, box["south"], box["west"]) and inside(domain, box["north"], box["east"])


def slugify(text):
    """Lowercase file-name fragment with non-alphanumerics collapsed to underscores."""
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def config_hash(config):
    """Stable hash of the full settings, for provenance and replay checks."""
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def extraction_hash(config):
    """Hash only the settings that determine the observed extraction."""
    inputs = {key: config[key] for key in EXTRACTION_KEYS}
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def _extent(box, path):
    _object(box, path, ("west", "east", "south", "north"))
    for key in ("west", "east", "south", "north"):
        limit = 180 if key in ("west", "east") else 90
        _number(box[key], f"{path}.{key}", -limit, limit)
    if box["west"] >= box["east"] or box["south"] >= box["north"]:
        raise ConfigError(f"{path}: require west < east and south < north")


def _store(settings, path, extra):
    _object(settings, path, ("endpoint", "bucket", "prefix", "region", "branch",
                             "snapshot_id", "variable", "latitude_order", *extra))
    for key in ("endpoint", "bucket", "prefix", "region", "branch", "variable"):
        _text(settings[key], f"{path}.{key}")
    try:
        url = urlsplit(settings["endpoint"])
        host = url.hostname
        _ = url.port
    except ValueError:
        raise ConfigError(f"{path}.endpoint: malformed HTTPS URL") from None
    if url.scheme != "https" or not host or url.username or url.password or url.query or url.fragment:
        raise ConfigError(f"{path}.endpoint: expected a public HTTPS URL without credentials/query/fragment")
    if settings["snapshot_id"] is not None:
        _text(settings["snapshot_id"], f"{path}.snapshot_id")
    if settings["latitude_order"] not in ("ascending", "descending"):
        raise ConfigError(f"{path}.latitude_order: choose ascending or descending")


def validate_common(config, require_forecast_dates=False):
    """Validate shared settings without imposing the threshold task's requirements."""
    _object(config, "config", ("schema_version", "country", "country_code", "coordinate_reference_system",
            "coordinate_source", "region_extent", "towns", "start_date", "end_date", "forecast",
            "cmorph_reference", "comparison", "execution"), optional=("thresholds",))
    if type(config["schema_version"]) is not int or config["schema_version"] != 2:
        raise ConfigError("schema_version: expected 2")
    for key in ("country", "country_code", "coordinate_source"):
        _text(config[key], key)
    if config["coordinate_reference_system"] != "EPSG:4326":
        raise ConfigError("coordinate_reference_system: only EPSG:4326 degrees are supported")
    _extent(config["region_extent"], "region_extent")
    if not isinstance(config["towns"], list) or not 3 <= len(config["towns"]) <= 5:
        raise ConfigError("towns: configure 3–5 towns")
    names = set()
    for i, town in enumerate(config["towns"]):
        path = f"towns[{i}]"
        _object(town, path, ("name", "latitude", "longitude", "extent"))
        _text(town["name"], f"{path}.name")
        if town["name"].casefold() in names:
            raise ConfigError(f"{path}.name: town names must be unique")
        names.add(town["name"].casefold())
        _number(town["latitude"], f"{path}.latitude", -90, 90)
        _number(town["longitude"], f"{path}.longitude", -180, 180)
        _extent(town["extent"], f"{path}.extent")
        if not inside(town["extent"], town["latitude"], town["longitude"]):
            raise ConfigError(f"{path}: town centre is outside its extent")
        if not box_inside(config["region_extent"], town["extent"]):
            raise ConfigError(f"{path}.extent: must lie entirely within region_extent")
    slugs = [slugify(town["name"]) for town in config["towns"]]
    if any(not slug for slug in slugs) or len(set(slugs)) != len(slugs):
        raise ConfigError("towns: names must produce unique file-name slugs")
    start, end = _date(config["start_date"], "start_date"), _date(config["end_date"], "end_date")
    if start > end:
        raise ConfigError("start_date: must not be after end_date")
    fc, obs = config["forecast"], config["cmorph_reference"]
    _store(fc, "forecast", ("start_dates", "available_start_date", "available_end_date"))
    _store(obs, "cmorph_reference", ("annual_maxima_variable", "reference_start_year", "reference_end_year"))
    _text(obs["annual_maxima_variable"], "cmorph_reference.annual_maxima_variable")
    for key in ("reference_start_year", "reference_end_year"):
        _number(obs[key], f"cmorph_reference.{key}", 1, 9999, integer=True)
    if obs["reference_start_year"] > obs["reference_end_year"]:
        raise ConfigError("cmorph_reference.reference_start_year: must not exceed reference_end_year")
    available_start = _date(fc["available_start_date"], "forecast.available_start_date")
    available_end = _date(fc["available_end_date"], "forecast.available_end_date")
    if not available_start <= start <= end <= available_end:
        raise ConfigError("start_date/end_date: must lie within forecast available_start_date/available_end_date")
    dates = fc["start_dates"]
    if dates is None:
        if require_forecast_dates:
            raise ConfigError("forecast.start_dates: select start dates before forecast analysis")
    else:
        if not isinstance(dates, list) or not dates:
            raise ConfigError("forecast.start_dates: expected a nonempty list of ISO dates or null")
        parsed = [_date(value, f"forecast.start_dates[{i}]") for i, value in enumerate(dates)]
        if len(set(parsed)) != len(parsed) or not all(start <= d <= end for d in parsed):
            raise ConfigError("forecast.start_dates: dates must be unique and inside start_date/end_date")
    _object(config["execution"], "execution", ("workers", "output_directory"))
    _number(config["execution"]["workers"], "execution.workers", 1, 32, integer=True)
    _text(config["execution"]["output_directory"], "execution.output_directory")
    comparison = config["comparison"]
    _object(comparison, "comparison", ("duration", "return_period_years", "exceedance_operator", "matching"))
    _text(comparison["duration"], "comparison.duration")
    _number(comparison["return_period_years"], "comparison.return_period_years", 2, 10000, integer=True)
    if comparison["exceedance_operator"] != ">" or comparison["matching"] != "nearest":
        raise ConfigError("comparison: supported choices are exceedance_operator '>' and matching 'nearest'")


def validate_thresholds(config):
    """Requirements for observed thresholds, kept out of shared validation."""
    if "thresholds" not in config:
        raise ConfigError("thresholds: required for the rainfall threshold analysis")
    settings = config["thresholds"]
    _object(settings, "thresholds", ("durations", "return_periods_years", "map_duration",
                                   "map_return_period_years", "units_if_missing"))
    durations, periods = settings["durations"], settings["return_periods_years"]
    if (not isinstance(durations, list) or len(durations) != 2
            or not all(isinstance(d, str) and d.strip() == d and d for d in durations)
            or durations[0] != "24hr" or durations[0] == durations[1]):
        raise ConfigError("thresholds.durations: require 24hr followed by one distinct second duration")
    if (not isinstance(periods, list) or not all(type(p) is int for p in periods)
            or sorted(periods) != [2, 10, 50]):
        raise ConfigError("thresholds.return_periods_years: require 2, 10 and 50")
    _number(settings["map_return_period_years"], "thresholds.map_return_period_years", 2, 10000, integer=True)
    if settings["map_duration"] not in durations or settings["map_return_period_years"] not in periods:
        raise ConfigError("thresholds.map_duration/map_return_period_years: must be among the selected levels")
    if settings["units_if_missing"] not in (None, "mm"):
        raise ConfigError("thresholds.units_if_missing: choose mm (E4 assumption) or null (require metadata)")
    comparison = config["comparison"]
    if comparison["duration"] not in durations:
        raise ConfigError("comparison.duration: must be one of thresholds.durations")
    if comparison["return_period_years"] not in periods:
        raise ConfigError("comparison.return_period_years: must be one of thresholds.return_periods_years")
    ref = config["cmorph_reference"]
    if ref["reference_end_year"] - ref["reference_start_year"] < 3:
        raise ConfigError("cmorph_reference: threshold fitting requires at least four annual maxima")


def migrate_legacy(config):
    """Read v1 saved settings for offline replay, without editing the saved file."""
    if not isinstance(config, dict) or "part_a" not in config or "schema_version" in config:
        return config
    legacy = deepcopy(config)
    result = {key: legacy[key] for key in ("country", "country_code", "coordinate_reference_system",
              "coordinate_source", "region_extent", "towns", "start_date", "end_date")}
    result["schema_version"] = 2
    result["cmorph_reference"] = {key: legacy["cmorph_reference"][key] for key in
        ("endpoint", "bucket", "prefix", "variable", "annual_maxima_variable", "latitude_order",
         "reference_start_year", "reference_end_year")}
    result["forecast"] = {key: legacy["forecast"][key] for key in
        ("endpoint", "bucket", "prefix", "variable", "latitude_order", "start_dates")}
    # These were fixed in the original code; preserve them when replaying v1.
    for store in (result["forecast"], result["cmorph_reference"]):
        store.update(region="us-east-1", branch="main", snapshot_id=None)
    result["forecast"].update(available_start_date="2025-06-01", available_end_date="2025-08-31")
    result["thresholds"] = {key: legacy["part_a"][key] for key in
        ("durations", "return_periods_years", "units_if_missing")}
    result["thresholds"].update(map_duration="24hr", map_return_period_years=10)
    result["execution"] = {"workers": 2, "output_directory": "out/rainfall_thresholds"}
    result["comparison"] = {"duration": legacy["cmorph_reference"]["duration"],
                            "return_period_years": legacy["cmorph_reference"]["return_period_years"],
                            "exceedance_operator": legacy["comparison"]["exceedance_operator"], "matching": "nearest"}
    return result


def load_config(path=None):
    """Default to Python settings; JSON is an explicit override/replay input."""
    if path is None:
        config = default_config()
    else:
        try:
            config = migrate_legacy(json.loads(Path(path).read_text()))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ConfigError(f"{path}: cannot load settings: {exc}") from exc
    validate_common(config)
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, help="write a generated JSON snapshot, e.g. grid.json")
    args = parser.parse_args()
    try:
        config = load_config()
        validate_thresholds(config)
    except ConfigError as exc:
        parser.error(str(exc))
    if args.export:
        args.export.write_text(json.dumps(config, indent=2, allow_nan=False) + "\n")
        print(f"Exported settings from scripts/common.py to {args.export}")
    else:
        print(json.dumps(config, indent=2, allow_nan=False))
        print("\nShared and threshold settings valid.")
        if config["forecast"]["start_dates"] is None:
            print("Forecast start dates: NOT SELECTED; required before B/C/D forecast reads.")


if __name__ == "__main__":
    main()
