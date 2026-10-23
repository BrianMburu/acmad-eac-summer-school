"""Shared return-level and plotting-position helpers."""

import numpy as np
import pytest
import xarray as xr
from scipy.stats import gumbel_r

from scripts.common import RETURN_PERIODS, slugify
from scripts.return_levels import (
    empirical_positions,
    gumbel_reduced_variate,
    gumbel_return_level,
)


def test_gumbel_return_level_matches_scipy():
    location, scale = 18.4, 14.8
    periods = np.array([2, 5, 10, 20, 50, 100])
    expected = gumbel_r.isf(1 / periods, loc=location, scale=scale)
    np.testing.assert_allclose(gumbel_return_level(location, scale, periods), expected)
    np.testing.assert_allclose(gumbel_return_level(location, scale, 27),
                               gumbel_r.isf(1 / 27, loc=location, scale=scale))


@pytest.mark.parametrize("container", [list, tuple])
def test_gumbel_return_level_accepts_shared_periods_as_sequences(container):
    periods = container(RETURN_PERIODS)
    expected = gumbel_r.isf(1 / np.asarray(periods), loc=18.4, scale=14.8)
    np.testing.assert_allclose(gumbel_return_level(18.4, 14.8, periods), expected)


def test_gumbel_return_period_array_preserves_coordinates():
    periods = xr.DataArray([2, 10, 50], dims="return_period",
                           coords={"return_period": [2, 10, 50]})
    level = gumbel_return_level(18.4, 14.8, periods)
    assert isinstance(level, xr.DataArray)
    xr.testing.assert_equal(level.return_period, periods.return_period)
    np.testing.assert_allclose(level.values, gumbel_r.isf(1 / periods.values, loc=18.4, scale=14.8))


def test_gumbel_helpers_preserve_xarray_coordinates():
    location = xr.DataArray([10.0, 20.0], dims="town", coords={"town": ["A", "B"]})
    scale = xr.DataArray([2.0, 3.0], dims="town", coords={"town": ["A", "B"]})
    level = gumbel_return_level(location, scale, 27)
    assert isinstance(level, xr.DataArray)
    assert level.dims == ("town",)
    assert level.town.values.tolist() == ["A", "B"]


@pytest.mark.parametrize("period", [0, 1, -2, np.nan, np.inf])
def test_gumbel_rejects_invalid_periods(period):
    with pytest.raises(ValueError, match="greater than 1"):
        gumbel_reduced_variate(period)


def test_empirical_positions_and_slugify():
    order, periods = empirical_positions([10, 40, 20])
    assert order.tolist() == [1, 2, 0]
    np.testing.assert_allclose(periods, [4, 2, 4 / 3])
    assert slugify("El Obeid") == "el_obeid"
    assert slugify("  Nyala / South ") == "nyala_south"
