"""Config layering and data loading (both CSV dialects)."""
import numpy as np
import pandas as pd
import pytest

from crypto_analysis.core.config import DEFAULTS, load_config
from crypto_analysis.core.data import Bars, load_klines


def _write(tmp, dialect):
    if dialect == "5m":
        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=10, freq="5min", tz="UTC"),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1.0, "quote_volume": 1000.0})
    else:
        df = pd.DataFrame({
            "open_time": pd.date_range("2026-01-01", periods=10, freq="1h", tz="UTC"),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1.0, "quote_asset_volume": 1000.0, "unused": 0})
    p = tmp / f"{dialect}.csv"
    df.to_csv(p, index=False)
    return str(p)


def test_load_both_dialects(tmp_path):
    for d, expected_bpd in (("5m", 288), ("1h", 24)):
        b = load_klines(_write(tmp_path, d))
        assert b.n == 10
        assert b.bars_per_day == expected_bpd
        assert b.quote_volume.sum() == pytest.approx(10000.0)


def test_date_slicing(tmp_path):
    p = _write(tmp_path, "5m")
    b = load_klines(p, start="2026-01-01T00:10", end="2026-01-01T00:30")
    assert 1 < b.n < 10


def test_config_layering(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("capital_usd: 500\npools:\n  xaut: {fee_tier: 0.0025}\n")
    cfg = load_config(str(cfg_file), {"capital_usd": 700.0, "symbols": ["btc"]})
    assert cfg["capital_usd"] == 700.0                     # CLI beats file
    assert cfg["pools"]["xaut"]["fee_tier"] == 0.0025      # file beats default
    assert cfg["pools"]["xaut"]["fee_model"] == DEFAULTS["pools"]["xaut"]["fee_model"]
    assert cfg["symbols"] == ["btc"]

