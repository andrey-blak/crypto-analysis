"""Performance metrics over bar-granular equity curves."""
from __future__ import annotations

import numpy as np


def compute_metrics(equity: np.ndarray, seconds_per_bar: float) -> dict:
    eq = np.asarray(equity, dtype=float)
    years = len(eq) * seconds_per_bar / (365.0 * 86400.0)
    ret = eq[1:] / eq[:-1] - 1.0
    final = eq[-1]
    cagr = (final / eq[0]) ** (1.0 / years) - 1.0 if years > 0 and final > 0 else -1.0
    dd = eq / np.maximum.accumulate(eq) - 1.0
    ann = np.sqrt(365.0 * 86400.0 / seconds_per_bar)
    sharpe = ret.mean() / ret.std() * ann if ret.std() > 0 else 0.0
    return {
        "final": float(final),
        "return": float(final / eq[0] - 1.0),
        "cagr": float(cagr),
        "max_drawdown": float(dd.min()),
        "sharpe": float(sharpe),
    }
