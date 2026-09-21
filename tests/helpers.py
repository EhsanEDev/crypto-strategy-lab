"""Deterministic OHLCV builders shared by the test suite."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_ohlcv(
    close: np.ndarray | list[float],
    spread_pct: np.ndarray | list[float] | float = 0.002,
    seed: int = 7,
    freq: str = "4h",
    start: str = "2022-01-01",
) -> pd.DataFrame:
    """Build a canonical OHLCV frame from a close-price series."""
    rng = np.random.default_rng(seed)
    close = np.asarray(close, dtype=float)
    n = len(close)
    if np.isscalar(spread_pct):
        spread = np.full(n, float(spread_pct))
    else:
        spread = np.asarray(spread_pct, dtype=float)
    open_ = close * (1 + rng.normal(0, 0.0005, n))
    high = np.maximum(open_, close) * (1 + np.abs(spread))
    low = np.minimum(open_, close) * (1 - np.abs(spread))
    index = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(50, 500, n).astype(float),
        },
        index=index,
    )


def log_walk(
    n: int,
    drift: float,
    sigma: float,
    seed: int = 1,
    start: float = 100.0,
) -> np.ndarray:
    """Deterministic geometric random walk."""
    rng = np.random.default_rng(seed)
    return start * np.exp(np.cumsum(rng.normal(drift, sigma, n)))
