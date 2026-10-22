"""LP fee income models.

Two modes, selected per symbol via pools.<symbol>.fee_model:

proxy      : pool volume is assumed a constant fraction (proxy_volume_k)
             of the exchange quote volume of the same bar; TVL is
             static_tvl_usd. Rough, but needs no pool data.

fixed_apr  : annualized yield (static_apr) on in-range position value.
"""
from __future__ import annotations

import numpy as np


def make_fee_stream(bars, pool_cfg: dict):
    """Return per-bar pool volume (USD) and a tvl(day) lookup closure."""
    mode = pool_cfg.get("fee_model", "proxy")
    if mode == "proxy":
        k = float(pool_cfg.get("proxy_volume_k", 0.1))
        vol = bars.quote_volume * k
        tvl_static = float(pool_cfg.get("static_tvl_usd") or 0.0)
        if tvl_static <= 0:
            raise ValueError("proxy fee model needs pools.<sym>.static_tvl_usd")
        return vol / max(bars.bars_per_day, 1), (lambda i: tvl_static)
    return None, None


def bar_fee_income(mode, vol_bar, i, fee_tier, lp_share, position_value, tvl, static_apr, seconds_per_bar):
    """Fee income (USDT) accrued by our position during bar i. 0 if out of range
    (caller passes position_value=0 or a flag when out of range)."""
    if mode == "fixed_apr":
        return position_value * static_apr * seconds_per_bar / (365.0 * 86400.0)
    if position_value <= 0 or tvl <= 0:
        return 0.0
    share = min(1.0, position_value / tvl)
    return vol_bar[i] * fee_tier * lp_share * share
