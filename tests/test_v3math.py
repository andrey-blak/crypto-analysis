"""V3 math tests: closed forms, boundary continuity, round-trips."""
import math

import pytest

from crypto_analysis.core import v3math as v3


def test_amounts_in_range():
    # price 100, range 81..121 -> sp=10, sl=9, su=11; L=1: x = 1*(11-10)/(10*11)
    x, y = v3.amounts_for_liquidity(1.0, 100.0, 81.0, 121.0)
    assert x == pytest.approx(1 / 110)
    assert y == pytest.approx(1.0)


def test_amounts_one_sided_outside():
    x, y = v3.amounts_for_liquidity(1.0, 64.0, 81.0, 121.0)   # below range
    assert y == 0.0 and x > 0.0
    x, y = v3.amounts_for_liquidity(1.0, 144.0, 81.0, 121.0)  # above range
    assert x == 0.0 and y > 0.0


def test_boundary_continuity():
    """Value at exactly lower/upper must match both branch formulas."""
    L, lo, up = 5.0, 81.0, 121.0
    x_below, y_below = v3.amounts_for_liquidity(L, lo - 1e-9, lo, up)
    x_in, y_in = v3.amounts_for_liquidity(L, lo + 1e-9, lo, up)
    assert x_below * lo == pytest.approx(x_in * lo + y_in, rel=1e-6)


def test_liquidity_roundtrip():
    p, lo, up = 100.0, 90.0, 110.0
    L = 3.7
    x, y = v3.amounts_for_liquidity(L, p, lo, up)
    L2 = v3.liquidity_from_amounts(x, y, p, lo, up)
    assert L2 == pytest.approx(L)


def test_50_50_split_value_le_capital():
    """A 50/50 value split into a position may leave dust but never more."""
    p, rng = 100.0, 0.05
    x, y = 5.0, 500.0            # 50/50 by value
    L = v3.liquidity_from_amounts(x, y, p, p * (1 - rng), p * (1 + rng))
    nx, ny = v3.amounts_for_liquidity(L, p, p * (1 - rng), p * (1 + rng))
    assert 0.97 * (x * p + y) < nx * p + ny <= x * p + y + 1e-9


def test_impermanent_loss_vs_hodl():
    """V3 over a huge range must reproduce the classic v2 IL law:
    V_lp / V_hodl = 2*sqrt(r)/(1+r) for a 50/50 value entry."""
    r = 1.44
    p0, p1 = 100.0, 100.0 * r
    lo, up = 1e-6, 1e9
    token, cash = 5.0, 500.0            # $500/$500 entry
    L = v3.liquidity_from_amounts(token, cash, p0, lo, up)
    v_lp = v3.position_value(L, p1, lo, up)
    v_hodl = token * p1 + cash
    assert v_lp / v_hodl == pytest.approx(2 * math.sqrt(r) / (1 + r), rel=1e-3)


def test_rebalance_swap_amount():
    sb, sq = v3.rebalance_swap_amount(0.0, 1000.0, 100.0)   # all quote
    assert sb == 0.0 and sq == pytest.approx(500.0)
    sb, sq = v3.rebalance_swap_amount(10.0, 0.0, 100.0)     # all base ($1000)
    assert sb == pytest.approx(5.0) and sq == 0.0
