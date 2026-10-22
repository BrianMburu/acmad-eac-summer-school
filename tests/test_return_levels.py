"""Shared return-level and plotting-position helpers."""

import numpy as np
import pytest
import xarray as xr
from scipy.stats import gumbel_r

from scripts.common import slugify
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
