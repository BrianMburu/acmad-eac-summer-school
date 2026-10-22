"""Shared Gumbel return-level and plotting-position helpers.

These functions are pure NumPy and keep xarray objects intact, so the same code
serves the Part A threshold analysis and the supplementary 27-year figures.
"""

import numpy as np


def gumbel_reduced_variate(return_period):
    """Reduced Gumbel variate y = -ln(-ln(1 - 1/T)), increasing with T."""
    values = np.asarray(return_period, dtype=float)
    if not values.size or not np.isfinite(values).all() or (values <= 1).any():
        raise ValueError("return period must be finite and greater than 1 year")
    return -np.log(-np.log1p(-1.0 / return_period))


def gumbel_return_level(location, scale, return_period):
    """Gumbel quantile x_T = mu - beta * ln(-ln(1 - 1/T))."""
    return location + scale * gumbel_reduced_variate(return_period)


def empirical_positions(values):
    """Weibull plotting positions (n + 1) / rank, with descending order indices."""
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("Empirical positions require a finite, nonempty 1D series")
    order = np.argsort(-values, kind="stable")
    return order, (len(values) + 1) / np.arange(1, len(values) + 1)
