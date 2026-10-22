"""Layered configuration: built-in defaults < config.yaml < CLI flags.

Everything optional. See config.yaml in repo root for the annotated template.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "capital_usd": 1000.0,
    "out_dir": "results",
    "detailed_outputs": False,
    "symbols": ["xaut", "btc"],
    "data": {
        "xaut": {"klines": "data/xautusdt-5m-2025-2026.csv", "start": None, "end": None},
        # gold proxy: PAXG (Paxos Gold) tracks the same LBMA ounce as XAUT but
        # has Binance history since 2019, giving the full 1-2 year window the
        # task asks for. Price PATH of gold is what the LP strategies see.
        "gold": {"klines": "data/paxgusdt-5m-2024-2026.csv", "start": None, "end": None},
        "btc": {"klines": "data/btcusdt-5m-2025-2026.csv", "start": None, "end": None},
    },
    "pools": {
        "xaut": {
            "fee_tier": 0.0005,        # Pancake v3 XAUT/USDT 0.05%
            "protocol_fee_cut": 0.34,  # LP share of tier fee = 1 - cut.
            # Verified on-chain 2026-10-22: pool slot0.feeProtocol = 0x0d48_0d48
            # (3400 bp); Pancake official swap FAQ: for the 0.05% tier Treasury
            # takes 19% + CAKE holders 15% = 34%, LPs get ~66%.
            "fee_model": "fixed_apr",  # proxy | fixed_apr
            "proxy_volume_k": 0.10,    # pool volume = k * exchange quote volume
            "static_tvl_usd": None,    # share denominator if not in CSV
            # observed pool economics at 2026-10-22 (GeckoTerminal snapshot):
            # volume24h $1,124,875 x 0.05% / TVL $1,979,284 x 365 ~ 10.4% APR
            "static_apr": 0.104,
            # half-width of the pool's ACTIVE liquidity spread (+/-5% around
            # price = rough assumption; refine with tick data)
            "active_liquidity_span": 0.05,
            "concentration_gain_cap": 50.0,
        },
        "btc": {
            "fee_tier": 0.0005,        # Pancake v3 BTCB/USDT 0.05%
            "protocol_fee_cut": 0.34,  # same verified Pancake BSC v3 default
            "fee_model": "fixed_apr",
            "proxy_volume_k": 0.10,
            "static_tvl_usd": None,
            # volume24h $33,827,944 x 0.05% / TVL $25,837,269 x 365 ~ 23.9% APR
            "static_apr": 0.239,
            "active_liquidity_span": 0.05,
            "concentration_gain_cap": 50.0,
        },
        # gold proxy pool: same as xaut (we simulate the XAUT/USDT pool over
        # PAXG's price path; PAXG/XAUT track the same LBMA ounce)
        "gold": {
            "fee_tier": 0.0005,
            "protocol_fee_cut": 0.34,  # Pancake BSC v3 factory default (same as xaut)
            "fee_model": "fixed_apr",
            "proxy_volume_k": 0.10,
            "static_tvl_usd": None,
            "static_apr": 0.104,
            "active_liquidity_span": 0.05,
            "concentration_gain_cap": 50.0,
        },
    },
    "gas": {"usd_per_tx": 0.02, "txs_per_rebalance": 4, "txs_per_collect": 1},
    "ranges_pct": [0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.075, 0.1, 0.15, 0.2],
    "policies": {
        "exit": {"strategies": ["III", "IV"]},
        "periodic": {"every_days": [1, 3, 7, 14], "buffer_frac_of_range": 0.5},
    },
    "boundary": "intrabar",            # intrabar | close
}


def load_config(path: str | None = None, overrides: dict | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if path and Path(path).exists():
        user = yaml.safe_load(Path(path).read_text()) or {}
        _merge(cfg, user)
    if overrides:
        _merge(cfg, {k: v for k, v in overrides.items() if v is not None})
    return cfg


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


def cli_overrides(argv: list[str] | None = None):
    """Return (config_path, overrides, date_overrides)."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="config.yaml", help="optional YAML config")
    p.add_argument("--symbols", nargs="+", help="subset of symbols to run")
    p.add_argument("--start", help="backtest start date (YYYY-MM-DD)")
    p.add_argument("--end", help="backtest end date (YYYY-MM-DD)")
    p.add_argument("--fee-model", choices=["proxy", "fixed_apr"])
    p.add_argument("--ranges", nargs="+", type=float, help="range widths as one-sided fractions, e.g. 0.02 = +/-2%%")
    p.add_argument("--out", dest="out_dir", help="output directory")
    a = p.parse_args(argv)
    ov = {"symbols": a.symbols, "out_dir": a.out_dir}
    if a.fee_model:
        ov["pools"] = {s: {"fee_model": a.fee_model} for s in DEFAULTS["pools"]}
    if a.ranges:
        ov["ranges_pct"] = a.ranges
    dates = {"start": a.start, "end": a.end}
    return a.config, ov, dates


__all__ = ["load_config", "cli_overrides", "DEFAULTS"]
