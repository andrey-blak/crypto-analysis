"""Engine invariants: non-negativity, fee crediting, III/IV semantics."""
import numpy as np
import pandas as pd
import pytest

from crypto_analysis.core.data import Bars
from crypto_analysis.core.engine import FeeCtx, simulate_asset_hold, simulate_hold, simulate_lp


def make_bars(prices, quote_vol=1_000_000.0):
    prices = np.asarray(prices, dtype=float)
    ts = pd.date_range("2026-01-01", periods=len(prices), freq="5min").to_numpy()
    return Bars(ts=ts,
                open=prices, high=prices * 1.0001, low=prices * 0.9999,
                close=prices, quote_volume=np.full(len(prices), quote_vol))


def flat_ctx(n=300, mode="proxy", tvl=1_000_000.0, k=0.1, apr=0.0):
    return FeeCtx(mode=mode, vol_bar=np.full(n, 1_000_000.0 * k),
                  tvl_of=lambda i: tvl,
                  fee_tier=0.0005, static_apr=apr, seconds_per_bar=300)


def test_hold_and_asset_hold():
    bars = make_bars([100.0, 110.0, 121.0])
    r1 = simulate_hold(bars, 1000.0)
    assert r1.final == 1000.0
    r2 = simulate_asset_hold(bars, 1000.0, flat_ctx(n=3))
    assert 1200 < r2.final < 1210


def test_lp_positive_fees_are_credited():
    """The original bug: fee income vanished. Flat price + pool volume must
    raise the final equity above the zero-income run (net of small costs)."""
    bars = make_bars([100.0] * 300)
    with_fees = simulate_lp(bars, flat_ctx(k=1.0, tvl=1e6), 1000.0, 0.02, "IV",
                            "exit", gas_per_reset=0.01)
    no_fees = simulate_lp(bars, flat_ctx(k=0.0), 1000.0, 0.02, "IV",
                          "exit", gas_per_reset=0.01)
    assert with_fees.fees_earned > 0
    assert with_fees.final > no_fees.final
    assert with_fees.resets == 0


def test_equity_never_negative():
    """The original bug: negative portfolios. Crash through every range."""
    prices = list(np.linspace(100, 10, 400))
    bars = make_bars(prices)
    for rng in (0.005, 0.05, 0.2):
        r = simulate_lp(bars, flat_ctx(n=400, k=0.1), 1000.0, rng, "IV", "exit",
                        gas_per_reset=0.08)
        assert (r.equity >= -1e-9).all(), f"rng={rng} min={r.equity.min()}"
        assert r.final >= -1e-9


def test_strategy_IV_resets_on_both_sides_III_only_up():
    prices = list(np.linspace(100, 80, 50)) + list(np.linspace(80, 130, 50))
    bars = make_bars(prices)
    iv_full = simulate_lp(bars, flat_ctx(n=100, k=0.0), 1000.0, 0.05, "IV", "exit", gas_per_reset=0.0)
    iii_full = simulate_lp(bars, flat_ctx(n=100, k=0.0), 1000.0, 0.05, "III", "exit", gas_per_reset=0.0)
    # falling leg alone: IV re-centers down repeatedly, III does nothing
    down = make_bars(list(np.linspace(100, 80, 50)))
    iv_d = simulate_lp(down, flat_ctx(n=50, k=0.0), 1000.0, 0.05, "IV", "exit", gas_per_reset=0.0)
    iii_d = simulate_lp(down, flat_ctx(n=50, k=0.0), 1000.0, 0.05, "III", "exit", gas_per_reset=0.0)
    assert iv_d.resets > 2 and iii_d.resets == 0
    # a monotone up leg after: III (which kept its ORIGINAL [95,105] range while
    # waiting) exits upward exactly like IV from 105 on -> same up-leg resets
    assert iv_full.resets > iii_full.resets          # extra = downward resets
    assert iii_full.resets >= 1                      # did re-enter + upper exits
    # while III waits below it holds token only -> equity tracks price 1:1
    assert iii_d.equity[49] == pytest.approx(iii_d.equity[48] * prices[49] / prices[48], rel=0.01)


def test_ruin_guard_stops_and_stays_nonnegative():
    """If reset costs consume the position, the run liquidates, stops,
    and equity/final never go negative (regression: BTC X=0.5% death spiral)."""
    rng_state = np.random.default_rng(7)
    walk = 100.0 * np.exp(np.cumsum(rng_state.normal(0, 0.002, 3000)))
    bars = make_bars(walk)
    res = simulate_lp(bars, flat_ctx(n=3000), 1000.0, 0.001, "IV", "exit",
                      gas_per_reset=25.0)   # brutal vs capital
    assert res.ruined
    assert (res.equity >= 0).all()
    assert res.final >= 0
    assert (res.fees_earned >= 0).all() if np.ndim(res.fees_earned) else res.fees_earned >= 0


def test_concentration_gain_scales_fees():
    """A +/-0.5% range in a pool with +/-5% active spread captures 10x the
    pool-average fee rate while in range."""
    bars = make_bars([100.0] * 300)
    base_ctx = FeeCtx("fixed_apr", None, lambda i: 0.0, 0.0005, static_apr=0.10)
    gain_ctx = FeeCtx("fixed_apr", None, lambda i: 0.0, 0.0005, static_apr=0.10,
                      active_span=0.05)
    base = simulate_lp(bars, base_ctx, 1000.0, 0.05, "IV", "exit", gas_per_reset=0.0)
    narrow = simulate_lp(bars, gain_ctx, 1000.0, 0.005, "IV", "exit", gas_per_reset=0.0)
    assert narrow.fees_earned == pytest.approx(10.0 * base.fees_earned, rel=0.01)


def test_zero_costs_conserves_value_on_flat_market():
    bars = make_bars([100.0] * 100)
    r = simulate_lp(bars, flat_ctx(k=0.0, tvl=1e6), 1000.0, 0.02, "IV", "exit",
                    gas_per_reset=0.0)
    # only entry swap fee and dust remain: loss must be tiny and < entry fee
    assert 996.0 < r.final < 1000.0


def test_periodic_policy_buffer():
    drift = list(np.linspace(100, 115, 300))     # slow +15% drift
    bars = make_bars(drift)
    per = simulate_lp(bars, flat_ctx(k=0.0), 1000.0, 0.10, "IV", "periodic",
                      every_bars=60, buffer_frac=0.5, gas_per_reset=0.0)
    exit_only = simulate_lp(bars, flat_ctx(k=0.0), 1000.0, 0.10, "IV", "exit",
                            gas_per_reset=0.0)
    assert exit_only.resets == 1                 # single upper exit at 110
    assert per.resets > exit_only.resets         # periodic re-centers fired earlier
