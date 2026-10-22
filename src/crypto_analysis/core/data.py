"""Market-data loading/validation for the backtests.

Supports both Binance export dialects used in this repo:
- 5m files written by download-binance-5m-gpt.py:  timestamp,open,high,low,close,volume,quote_volume
- 1h files written by download-binance.py:         open_time,...,quote_asset_volume,...
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Bars:
    ts: np.ndarray        # datetime64 UTC values, tz-naive (pandas>=3.1 deprecates
                          # Series.values dropping tz; we convert explicitly)
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    quote_volume: np.ndarray   # USDT traded per bar (proxy fee source)

    @property
    def n(self) -> int:
        return len(self.close)

    @property
    def dt_seconds(self) -> float:
        return float((self.ts[1] - self.ts[0]) / np.timedelta64(1, "s"))

    @property
    def bars_per_day(self) -> int:
        return int(round(86400 / self.dt_seconds))


def load_klines(path: str, start: str | None = None, end: str | None = None) -> Bars:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    tscol = "timestamp" if "timestamp" in df.columns else "open_time"
    qvcol = "quote_volume" if "quote_volume" in df.columns else "quote_asset_volume"
    if qvcol not in df.columns:
        df[qvcol] = df["volume"] * df["close"]  # last resort estimate

    df[tscol] = pd.to_datetime(df[tscol], utc=True, format="ISO8601")
    if start:
        df = df[df[tscol] >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df[tscol] <= pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
    df = df.sort_values(tscol).drop_duplicates(tscol).reset_index(drop=True)

    for c in ("open", "high", "low", "close", qvcol):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close"])

    if len(df) < 3:
        raise ValueError(f"{path}: only {len(df)} bars after filtering {start!r}..{end!r}")

    return Bars(
        ts=df[tscol].dt.tz_convert(None).to_numpy(),
        open=df["open"].values,
        high=df["high"].values,
        low=df["low"].values,
        close=df["close"].values,
        quote_volume=df[qvcol].values,
    )
