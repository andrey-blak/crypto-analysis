"""Strategy simulation engine (I, II, III, IV) over candle bars.

Position model (V3): a position is (L, lower, upper) plus idle cash/token
leftovers and accrued (uncollected) fees. Value at price p is
amounts_for_liquidity(L, p)·p + idle + fees.

Strategy III resets only on UPPER exits — a lower exit leaves the position
one-sided in token, earning nothing until price re-enters the range
("leave as is and wait"); IV resets on both.

Policies:
  exit     : reset solely on range exits (task definition).
  periodic : additionally re-center every `every_bars` bars when price moved
             more than buffer_frac * rng from the current center (no-op buffer).

Cost model:
  * rebalance swap fee is charged on the *traded notional only* (at a
    boundary exit that is half the portfolio, not the whole portfolio).
  * gas_per_reset covers a full open/close op, configured as
    usd_per_tx * txs_per_rebalance; charged on initial open, each reset,
    and final liquidation.
  * final liquidation sells remaining token (swap fee) + gas.

Intrabar boundary detection uses high/low; if both boundaries are pierced in
one bar, the exit matching the bar's directional bias is taken (III: an
ambiguous both-broken bar is treated as a no-op for resets). At most one
exit per bar. Documented in README.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import v3math as v3


@dataclass
class FeeCtx:
    mode: str                       # proxy | fixed_apr
    vol_bar: np.ndarray | None      # per-bar pool volume USD (proxy)
    tvl_of: object                  # callable i -> pool TVL USD
    fee_tier: float                 # e.g. 0.0005
    lp_share: float = 1.0           # fraction of tier fee reaching LPs
    static_apr: float = 0.0
    seconds_per_bar: float = 300.0
    # Concentration gain: our liquidity density vs the pool's average active
    # liquidity spread. For a position of value V over +/-rng in a pool whose
    # active liquidity spans +/-S, fee capture per dollar is ~ (S/rng) times
    # the pool-average APR. Set S = pools.<sym>.active_liquidity_span.
    # gain = min(S/rng, gain_cap); S=0 disables the correction.
    active_span: float = 0.0
    gain_cap: float = 50.0


@dataclass
class SimResult:
    strategy: str
    range_pct: float | None
    policy: str
    label: str
    equity: np.ndarray
    final: float
    fees_earned: float
    swap_fees_paid: float
    gas_paid: float
    resets: int
    frac_in_range: float
    ruined: bool = False       # position consumed by costs, trading stopped


def _open_from_split(token: float, cash: float, p: float, rng: float):
    """Build position at price p from given amounts.
    Returns (L, lower, upper, idle_cash, idle_token)."""
    lower, upper = p * (1 - rng), p * (1 + rng)
    L = v3.liquidity_from_amounts(token, cash, p, lower, upper)
    x, y = v3.amounts_for_liquidity(L, p, lower, upper)
    return L, lower, upper, max(cash - y, 0.0), max(token - x, 0.0)


def _recenter(idle_cash: float, idle_token: float, v: float, px: float, rng: float):
    """Fold leftovers into a fresh 50/50 position at px."""
    return _open_from_split(v / 2.0 / px, v / 2.0, px, rng)


def _value(L, lower, upper, p, idle_cash, idle_token, fees):
    x, y = v3.amounts_for_liquidity(L, p, lower, upper)
    return x * p + y + idle_cash + idle_token * p + fees


def simulate_hold(bars, capital: float) -> SimResult:
    eq = np.full(bars.n, capital, dtype=float)
    return SimResult("I", None, "-", "I", eq, capital, 0.0, 0.0, 0.0, 0, 0.0)


def simulate_asset_hold(bars, capital: float, fee_ctx: FeeCtx) -> SimResult:
    """II: buy asset with everything at start, sell at end. Fee on each leg."""
    p0, pf = float(bars.close[0]), float(bars.close[-1])
    qty = capital * (1 - fee_ctx.fee_tier) / p0
    eq = qty * bars.close
    swap_paid = capital * fee_ctx.fee_tier + qty * pf * fee_ctx.fee_tier
    final = qty * pf * (1 - fee_ctx.fee_tier)
    return SimResult("II", None, "-", f"II", eq, final, 0.0, swap_paid, 0.0, 0, 1.0)


def simulate_lp(bars, fee_ctx: FeeCtx, capital: float, rng: float,
                strategy: str, policy: str = "exit", every_bars: int | None = None,
                buffer_frac: float = 0.5, gas_per_reset: float = 0.0) -> SimResult:
    assert strategy in ("III", "IV")
    fee = fee_ctx.fee_tier
    O, H, LO, C = bars.open, bars.high, bars.low, bars.close
    n = bars.n

    # initial open: swap half into token, mint position, pay open gas
    p0 = float(C[0])
    half = capital / 2.0
    token = half * (1 - fee) / p0
    swap_paid = half * fee
    gas_paid = gas_per_reset
    L, lower, upper, idle_cash, idle_token = _open_from_split(token, half, p0, rng)
    ruined = False
    fees = 0.0                  # accrued, uncollected (USDT)
    fees_earned = 0.0           # lifetime income (diagnostic)
    resets = 0
    center = p0
    in_range_bars = 0
    eq = np.empty(n)
    eq[0] = _value(L, lower, upper, p0, idle_cash, idle_token, 0.0)

    for i in range(1, n):
        h, lo, o, c = float(H[i]), float(LO[i]), float(O[i]), float(C[i])

        # fee accrual: only when close price is inside the range
        if lower <= c <= upper:
            v_now = _value(L, lower, upper, c, idle_cash, idle_token, fees)
            gain = (min(fee_ctx.active_span / rng, fee_ctx.gain_cap)
                    if fee_ctx.active_span > 0 else 1.0)
            if fee_ctx.mode == "fixed_apr":
                inc = (v_now * fee_ctx.static_apr * gain * fee_ctx.lp_share
                       * fee_ctx.seconds_per_bar / (365.0 * 86400.0))
            else:
                tvl = fee_ctx.tvl_of(i)
                if tvl > 0:
                    inc = (fee_ctx.vol_bar[i] * fee * fee_ctx.lp_share
                           * min(1.0, v_now / tvl) * gain)
            fees += inc
            fees_earned += inc
            in_range_bars += 1

        # exit detection (intrabar)
        up_break, dn_break = h >= upper, lo <= lower
        exit_px = None
        if strategy == "IV":
            if up_break and dn_break:
                exit_px = upper if c >= o else lower
            elif up_break:
                exit_px = upper
            elif dn_break:
                exit_px = lower
        else:  # III: only an unambiguous upper exit triggers a reset
            if up_break and not (dn_break and c < o):
                exit_px = upper

        # periodic re-center: only when the bar did not already exit
        do_periodic = (policy == "periodic" and every_bars is not None
                       and exit_px is None and lower <= c <= upper
                       and i % every_bars == 0
                       and abs(c / center - 1.0) > buffer_frac * rng)

        if exit_px is not None or do_periodic:
            px = c if exit_px is None else exit_px
            v = _value(L, lower, upper, px, idle_cash, idle_token, fees)
            x, y = v3.amounts_for_liquidity(L, px, lower, upper)
            base_val = (x + idle_token) * px
            swap_usd = abs(base_val - (v - gas_per_reset) / 2.0)
            cost = gas_per_reset + swap_usd * fee
            if v <= cost:
                # RUIN: one open/reset/close op consumes the whole position.
                # Realistic response: liquidate instead of reopening, hold the
                # remainder as cash, stop trading.
                v_left = max(v - gas_per_reset - base_val * fee, 0.0)
                gas_paid += min(gas_per_reset, v)
                swap_paid += base_val * fee
                resets += 1
                L, lower, upper = 0.0, np.inf, -np.inf
                idle_cash, idle_token, fees = v_left, 0.0, 0.0
                eq[i:] = v_left
                ruined = True
                break
            v -= gas_per_reset
            gas_paid += gas_per_reset
            swap_paid += swap_usd * fee
            v_net = max(v - swap_usd * fee, 0.0)
            L, lower, upper, idle_cash, idle_token = _open_from_split(
                v_net / 2.0 / px, v_net / 2.0, px, rng)
            fees = 0.0          # collected into the rebalanced value
            center = px
            resets += 1

        eq[i] = _value(L, lower, upper, c, idle_cash, idle_token, fees)

    if ruined:
        final = float(idle_cash)          # already liquid; no further costs
    else:
        # final liquidation: burn (+collect), sell remaining token at last close
        pf = float(C[-1])
        v = _value(L, lower, upper, pf, idle_cash, idle_token, fees)
        x, _y = v3.amounts_for_liquidity(L, pf, lower, upper)
        sell_val = (x + idle_token) * pf
        final = v - sell_val * fee - gas_per_reset
        gas_paid += gas_per_reset
        swap_paid += sell_val * fee

    pol = f"|T={every_bars}b" if every_bars else ""
    label = f"{strategy}|{policy}{pol}|{rng:.4f}"
    return SimResult(strategy, rng, policy, label, eq, final,
                     fees_earned, swap_paid, gas_paid, resets,
                     in_range_bars / n, ruined)
