"""Uniswap/Pancake V3 concentrated-liquidity math.

Prices are token1-per-token0 (quote per base). All amount math is in units
of the two tokens; values in USDT are obtained as ``x * price + y``.
"""
from __future__ import annotations

import math


def liquidity_from_amounts(x: float, y: float, price: float, lower: float, upper: float) -> float:
    """Largest liquidity whose position fits inside (x, y) amounts at *price*.

    Mirrors Uniswap V3 `getLiquidityForAmounts`: with a 50/50 portfolio the
    binding side determines L and the leftover amount is dust.
    """
    sp, sl, su = math.sqrt(price), math.sqrt(lower), math.sqrt(upper)
    if sp <= sl:
        return x * sl * su / (su - sl)
    if sp >= su:
        return y / (su - sl)
    return min(x * sp * su / (su - sp), y / (sp - sl))


def amounts_for_liquidity(L: float, price: float, lower: float, upper: float) -> tuple[float, float]:
    """(x, y) held by liquidity L over [lower, upper] at *price*."""
    sp, sl, su = math.sqrt(price), math.sqrt(lower), math.sqrt(upper)
    if sp <= sl:
        # fully in token1? no: below range the position is all token0 (base)
        return L * (su - sl) / (sl * su), 0.0
    if sp >= su:
        # above range: all token1 (quote/USDT)
        return 0.0, L * (su - sl)
    return L * (su - sp) / (sp * su), L * (sp - sl)


def position_value(L: float, price: float, lower: float, upper: float) -> float:
    """Value of the position in quote (USDT) terms at *price*."""
    x, y = amounts_for_liquidity(L, price, lower, upper)
    return x * price + y


def rebalance_swap_amount(x: float, y: float, price: float) -> tuple[float, float]:
    """Split of (token-amount to sell, quote-amount to sell) to reach 50/50.

    Returns ``(sell_base, sell_quote)`` — at most one is nonzero.
    """
    v = x * price + y
    target = v / 2.0
    dv_base = x * price - target
    if dv_base > 0:
        return dv_base / price, 0.0
    return 0.0, -dv_base
