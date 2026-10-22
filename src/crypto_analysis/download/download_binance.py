"""Configurable Binance monthly klines downloader (free, no API key).

Usage:
    python -m src.download.download_binance --symbol PAXGUSDT --interval 5m \
        --from 2024-10-01 --to 2026-10-01 --out data/paxgusdt-5m-2024-2026.csv

Output dialect matches src/core/data.py: timestamp,open,high,low,close,
volume,quote_volume (tz-aware ISO).
"""
from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]


def fetch_month(symbol: str, interval: str, month: str) -> pd.DataFrame | None:
    url = (f"https://data.binance.vision/data/spot/monthly/klines/"
           f"{symbol}/{interval}/{symbol}-{interval}-{month}.zip")
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    df = pd.read_csv(z.open(z.namelist()[0]), header=None)
    df = df.iloc[:, :12]
    df.columns = COLS
    ts = pd.to_datetime(df["open_time"], unit="us", utc=True)
    # some older files use milliseconds
    if ts.dt.year.max() < 2020:
        ts = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    out = pd.DataFrame({
        "timestamp": ts, "open": df["open"].astype(float),
        "high": df["high"].astype(float), "low": df["low"].astype(float),
        "close": df["close"].astype(float), "volume": df["volume"].astype(float),
        "quote_volume": df["quote_volume"].astype(float),
    })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--from", dest="frm", required=True, help="YYYY-MM (inclusive)")
    ap.add_argument("--to", dest="to", required=True, help="YYYY-MM (exclusive)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    months = pd.period_range(a.frm[:7], a.to[:7], freq="M")[:-1]
    frames, missing = [], []
    for m in months:
        df = fetch_month(a.symbol.upper(), a.interval, str(m))
        if df is None:
            missing.append(str(m))
            print("skip", m)
            continue
        frames.append(df)
        print(m, len(df), "bars")
    if not frames:
        raise SystemExit("no data downloaded")
    all_df = pd.concat(frames).drop_duplicates("timestamp").sort_values("timestamp")
    # strip empty last bar Binance sometimes writes
    all_df = all_df[all_df["close"] > 0]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    all_df.to_csv(a.out, index=False)
    print(f"wrote {a.out}: {len(all_df)} bars, "
          f"{all_df.timestamp.iloc[0]} -> {all_df.timestamp.iloc[-1]}"
          + (f"; MISSING MONTHS: {missing}" if missing else "; complete"))


if __name__ == "__main__":
    main()
