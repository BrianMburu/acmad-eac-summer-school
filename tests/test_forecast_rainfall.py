"""Regressions for rainfall units, cumulative totals and agreed experiment dates."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from scripts.common import ConfigError, load_config, validate_common
from scripts.forecast_rainfall import daily_totals, daily_step_indices, forecast_unit_report


def cumulative(values=(0, 0.04, 0.08), units=None):
    array = xr.DataArray(np.broadcast_to(np.asarray(values)[:, None], (len(values), 51)).copy(),
                         dims=('step', 'number'),
                         coords={'time': pd.Timestamp('2025-07-16'),
                                 'step': pd.to_timedelta(np.arange(len(values)) * 24, unit='h'),
                                 'number': np.arange(51)})
    if units is not None:
        array.attrs['units'] = units
    return array


@pytest.mark.parametrize('units,expected', [('m', 40), ('mm', 0.04), ('kg m-2', 0.04), (None, 40)])
def test_units_determine_depth_without_implicit_thousandfold_change(units, expected):
    config = load_config()
    # Disable trace cleanup to isolate conversion of the 0.04-mm test depth.
    config['forecast_analysis']['trace_rainfall_mm'] = 0
    array = cumulative(units=units)
    daily = daily_totals(array, config)
    np.testing.assert_allclose(daily.values, expected)
    assert daily.attrs['used_workshop_fallback'] == (units is None)


@pytest.mark.parametrize('units', ['mm/day', 'kg m-2 s-1', 'inches', ''])
def test_contradictory_or_empty_unit_metadata_fails(units):
    with pytest.raises(ValueError, match='units'):
        forecast_unit_report(cumulative(units=units), load_config())


def test_large_decrease_is_rejected_and_packing_traces_are_recorded():
    with pytest.raises(ValueError, match='decreases'):
        daily_totals(cumulative((0, 0.04, 0.01)), load_config())
    array = cumulative((0, 0.04, 0.03995, 0.04))
    daily = daily_totals(array, load_config())
    np.testing.assert_allclose(daily[:, 0], [40, 0, 0])
    assert daily.attrs['negative_traces_zeroed'] == 51
    assert daily.attrs['positive_traces_zeroed'] == 51
    assert daily.attrs['trace_rainfall_mm'] == 0.08


@pytest.mark.parametrize('hours', [[0, 24, 72], [0, 24, 24], [0, 24.5, 48.5], [24, 48]])
def test_missing_or_mislabeled_daily_endpoints_fail(hours):
    with pytest.raises(ValueError, match='steps'):
        daily_step_indices(pd.to_timedelta(hours, unit='h'))


def test_only_an_entirely_nan_complete_start_can_be_skipped():
    config = load_config()
    array = cumulative()
    array[:] = np.nan
    assert daily_totals(array, config) is None
    array[0, 0] = 0
    with pytest.raises(ValueError, match='partial missing'):
        daily_totals(array, config)
    array[:] = np.inf
    with pytest.raises(ValueError, match='nonfinite'):
        daily_totals(array, config)
    with pytest.raises(ValueError, match='51-member'):
        daily_totals(cumulative().isel(number=slice(0, 50)), config)
    array = cumulative().assign_coords(number=[0] * 51)
    with pytest.raises(ValueError, match='unique'):
        daily_totals(array, config)


def test_nonzero_baseline_and_out_of_season_valid_periods_fail():
    with pytest.raises(ValueError, match='step 0'):
        daily_totals(cumulative((0.001, 0.04, 0.08)), load_config())
    array = cumulative().assign_coords(time=pd.Timestamp('2025-08-31'))
    with pytest.raises(ValueError, match='beyond'):
        daily_totals(array, load_config())


def test_defaults_restore_agreed_dates_for_all_five_towns():
    config = load_config()
    assert len(config['towns']) == 5
    assert config['forecast']['start_dates'] == ['2025-06-16', '2025-07-16', '2025-08-16']
    windows = config['forecast_analysis']['lead_time_windows']
    starts = [d for window in windows for d in pd.date_range(window['start'], window['end'])]
    assert len(starts) == len(set(starts)) == 42
    assert all(d.day in range(9, 23) for d in starts)
    assert config['forecast_analysis']['risk_start_dates'] == ['2025-06-16', '2025-07-16', '2025-08-13', '2025-08-16']
    assert config['forecast_analysis']['risk_forecast_days'] == list(range(1, 11))
    for key, value in [('units_if_missing', 'unknown'), ('trace_rainfall_mm', -1),
                       ('risk_start_dates', ['2025-09-01'] * 3), ('risk_forecast_days', [1, 3, 3])]:
        changed = deepcopy(config)
        changed['forecast_analysis'][key] = value
        with pytest.raises(ConfigError, match='forecast_analysis'):
            validate_common(changed)


def test_warns_about_large_source_reads_before_computation():
    from scripts.forecast_rainfall import warn_source_size

    array = cumulative()
    # A whole ensemble map chunk is decoded even for a tiny point selection.
    array.encoding['chunks'] = (1, 1, 51, 321, 261)
    array = array.astype('float32')
    array.encoding['chunks'] = (1, 1, 51, 321, 261)
    with pytest.warns(UserWarning, match='source map chunks'):
        warn_source_size(array, ['2025-06-16', '2025-07-16', '2025-08-16'], list(range(11)))
