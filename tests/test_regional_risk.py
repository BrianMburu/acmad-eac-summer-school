"""Scientific checks for E8 alignment, strict counts and sampled frequencies."""

import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from scripts import regional_risk as risk
from scripts.common import ConfigError, load_config, risk_map_dates, validate_risk_map


@pytest.fixture
def inputs():
    config = load_config()
    config['risk_map']['forecast_days'] = [1, 2]
    dates = pd.DatetimeIndex(risk_map_dates(config))
    lat, lon = [17., 16., 15.5, 14., 12., 11.], [23., 25., 30., 32.5, 35.5, 36.5, 38.]
    values = np.zeros((4, 3, 51, 6, 7), dtype='float32')
    values[:, 1, :, :, :] = .020
    values[:, 1, :11, :, :] = .030
    values[:, 2, :, :, :] = values[:, 1, :, :, :] + .020
    forecast = xr.Dataset({'tp': (('time', 'step', 'number', 'latitude', 'longitude'), values)},
        coords={'time': dates, 'step': np.array([0, 24, 48], dtype='timedelta64[h]'),
                'number': np.arange(51), 'latitude': lat, 'longitude': lon})
    forecast.tp.encoding['chunks'] = (1, 1, 51, 6, 7)
    obs = xr.Dataset({
        'return_period_precip': (('duration', 'return_period', 'lat', 'lon'),
            np.full((2, 3, 6, 7), 25., dtype='float32')),
        'annual_maxima': (('duration', 'year', 'lat', 'lon'),
            np.full((2, 27, 6, 7), 50., dtype='float32'))},
        coords={'duration': ['24hr', '48hr'], 'return_period': [2, 10, 50],
                'year': np.arange(1998, 2025), 'lat': [10., 12., 14., 15.5, 16., 18.], 'lon': lon})
    obs.return_period_precip.attrs['units'] = 'mm'
    obs.annual_maxima.attrs['units'] = 'mm'
    obs.return_period_precip.encoding['chunks'] = (1, 3, 6, 7)
    obs.return_period_precip.loc[{'duration': '24hr', 'return_period': 2, 'lat': 14., 'lon': 25.}] = np.nan
    return config, obs, forecast


def opener(monkeypatch, obs, forecast):
    monkeypatch.setattr(risk, 'open_store', lambda settings:
        (obs.copy(), 'observed-test') if settings['variable'] == 'return_period_precip'
        else (forecast.copy(), 'forecast-test'))


def test_default_dates_preserve_shared_starts_and_include_strongest_c_start():
    config = load_config()
    validate_risk_map(config)
    assert risk_map_dates(config) == ['2025-06-16', '2025-07-16', '2025-08-13', '2025-08-16']
    assert config['forecast']['start_dates'] == ['2025-06-16', '2025-07-16', '2025-08-16']
    assert config['risk_map']['forecast_days'] == list(range(1, 11))


@pytest.mark.parametrize('key,value', [
    ('additional_start_dates', ['2025-08-16']),
    ('additional_start_dates', ['2025-08-13', '2025-08-14']),
    ('additional_start_dates', ['2025-09-01']),
    ('additional_start_dates', ['bad']), ('additional_start_dates', None),
    ('forecast_days', []), ('forecast_days', [1, 3]), ('forecast_days', [True]),
    ('forecast_days', list(range(1, 12))), ('signal_probability', 0),
    ('signal_probability', 1.1), ('max_source_mib', 0)])
def test_bad_risk_settings_identify_field(key, value):
    config = load_config()
    config['risk_map'][key] = value
    with pytest.raises(ConfigError, match='risk_map'):
        validate_risk_map(config)


def test_local_thresholds_match_each_forecast_pixel_and_use_two_year_level(inputs):
    config, obs, forecast = inputs
    obs.return_period_precip.loc[{'duration': '24hr', 'return_period': 2, 'lat': 14., 'lon': 30.}] = 40.
    selected, threshold, report, _ = risk.select_region(obs, forecast, config)
    assert selected.sizes['latitude'] == 4 and selected.sizes['longitude'] == 5
    assert float(threshold.sel(latitude=14., longitude=30.)) == 40.
    assert np.isnan(threshold.sel(latitude=14., longitude=25.))
    assert np.array_equal(threshold.latitude, selected.latitude)
    assert np.array_equal(threshold.longitude, selected.longitude)
    assert report['threshold_read']['source_chunks_touched'] == 1
    assert report['forecast_read']['source_chunks_touched'] == 12
    assert report['daily_lead_hours'] == [0, 24, 48]
    assert config['thresholds']['map_return_period_years'] == 10  # A's map was not used


def test_probability_is_strict_and_missing_thresholds_are_masked():
    values = np.full((1, 51, 2, 2), 25.)
    values[:, :11, 0, 0] = 25.1
    daily = xr.DataArray(values, dims=('time', 'number', 'latitude', 'longitude'),
        coords={'time': pd.DatetimeIndex(['2025-08-14']), 'number': np.arange(51),
                'latitude': [15., 14.], 'longitude': [30., 31.], 'forecast_day': ('time', [1])})
    threshold = xr.DataArray([[25., 25.], [25., np.nan]], dims=('latitude', 'longitude'),
        coords={'latitude': [15., 14.], 'longitude': [30., 31.]})
    result = risk.probability_for_start(daily, threshold, '2025-08-13')
    assert result.members_above.sel(latitude=15., longitude=30.).item() == 11
    assert result.probability.sel(latitude=15., longitude=30.).item() == pytest.approx(11 / 51)
    assert result.members_above.sel(latitude=15., longitude=31.).item() == 0
    assert np.isnan(result.probability.sel(latitude=14., longitude=31.)).all()
    with pytest.raises(ValueError, match='coordinates differ'):
        risk.probability_for_start(daily, threshold.assign_coords(longitude=[30., 32.]), '2025-08-13')


def test_full_run_uses_available_denominator_caches_and_plots_offline(inputs, tmp_path, monkeypatch):
    config, obs, forecast = inputs
    forecast.tp.loc[{'time': '2025-08-13'}] = np.nan
    opener(monkeypatch, obs, forecast)
    out = tmp_path / 'risk'
    risk.run_remote(config, out)
    with xr.open_dataset(out / 'risk_maps.nc', engine='scipy') as maps:
        assert maps.sizes == {'initialization': 4, 'forecast_day': 2, 'latitude': 4, 'longitude': 5}
        assert maps.probability.sel(initialization='2025-08-13').isnull().all()
        assert float(maps.available_forecasts.sel(latitude=16., longitude=30.)) == 6
        assert float(maps.risk_hits.sel(latitude=16., longitude=30.)) == 3
        assert float(maps.frequency_fraction.sel(latitude=16., longitude=30.)) == .5
        assert float(maps.available_forecasts.sel(latitude=14., longitude=25.)) == 0
        assert np.isnan(maps.frequency_fraction.sel(latitude=14., longitude=25.))
    assert len(pd.read_csv(out / 'town_probabilities.csv')) == 40
    assert len(pd.read_csv(out / 'town_risk_summary.csv')) == 5
    assert len(pd.read_csv(out / 'frequency.csv')) == 20
    starts = json.loads((out / 'forecast_starts.json').read_text())
    assert [s['initialization'] for s in starts] == risk_map_dates(config)
    assert sum(s['status'] == 'ok' for s in starts) == 3
    before = (out / 'run_status.json').read_bytes()
    monkeypatch.setattr(xr.DataArray, 'compute', lambda *a, **k: pytest.fail('unexpected remote compute'))
    risk.run_remote(config, out, inspection_only=True)
    assert (out / 'run_status.json').read_bytes() == before
    config['execution']['workers'] = 8
    risk.run_remote(config, out)  # raw fields and input hashes are independent of worker count
    assert pd.read_csv(out / 'read_timings.csv').cached.all()
    monkeypatch.setattr(risk, 'open_store', lambda _: pytest.fail('plots must be offline'))
    (out / 'figures').mkdir()
    unrelated = out / 'figures' / 'other.png'
    unrelated.write_bytes(b'keep')
    risk.plot_outputs(out)
    assert unrelated.read_bytes() == b'keep'
    assert len(list((out / 'figures').glob('probability_*.png'))) == 4
    assert (out / 'figures' / 'sampled_risk_frequency.png').exists()
    with (out / 'town_probabilities.csv').open('a') as file:
        file.write('tampered\n')
    with pytest.raises(ValueError, match='manifest'):
        risk.plot_outputs(out)


def test_inspection_fetches_no_rainfall_and_reports_budget_before_extraction(inputs, tmp_path, monkeypatch):
    config, obs, forecast = inputs
    config['risk_map']['max_source_mib'] = 1
    forecast.tp.encoding['chunks'] = (1, 1, 51, 321, 261)
    opener(monkeypatch, obs, forecast)
    monkeypatch.setattr(xr.DataArray, 'compute', lambda *a, **k: pytest.fail('unexpected rainfall compute'))
    out = tmp_path / 'risk'
    risk.run_remote(config, out, inspection_only=True)
    assert json.loads((out / 'inspection_status.json').read_text())['status'] == 'ok'
    with pytest.raises(ValueError, match='max_source_mib'):
        risk.run_remote(config, out)
    assert json.loads((out / 'run_status.json').read_text())['status'] == 'failed'
    assert not (out / 'risk_maps.nc').exists()


@pytest.mark.parametrize('bad', [np.nan, np.inf, -.1])
def test_partial_missing_or_decreasing_regional_forecasts_fail(inputs, tmp_path, monkeypatch, bad):
    config, obs, forecast = inputs
    # A regional pixel away from town centres must receive the same checks.
    forecast.tp.loc[{'time': '2025-06-16', 'step': np.timedelta64(48, 'h'),
                     'number': 0, 'latitude': 14., 'longitude': 25.}] = bad
    opener(monkeypatch, obs, forecast)
    with pytest.raises(ValueError, match='missing|infinite|decreases'):
        risk.run_remote(config, tmp_path)
    assert json.loads((tmp_path / 'run_status.json').read_text())['status'] == 'failed'


def test_end_of_season_forecast_days_do_not_enter_frequency_denominator(inputs, tmp_path, monkeypatch):
    config, obs, forecast = inputs
    config['forecast']['start_dates'] = ['2025-06-16', '2025-07-16', '2025-08-31']
    config['risk_map']['additional_start_dates'] = []
    forecast = forecast.sel(time=['2025-06-16', '2025-07-16', '2025-08-16']).assign_coords(
        time=pd.DatetimeIndex(config['forecast']['start_dates']))
    opener(monkeypatch, obs, forecast)
    risk.run_remote(config, tmp_path)
    with xr.open_dataset(tmp_path / 'risk_maps.nc', engine='scipy') as maps:
        assert maps.probability.sel(initialization='2025-08-31', forecast_day=2).isnull().all()
        assert float(maps.available_forecasts.sel(latitude=16., longitude=30.)) == 5
        assert float(maps.frequency_fraction.sel(latitude=16., longitude=30.)) == pytest.approx(3 / 5)
