"""Backtest runner: sweeps strategies I-IV x ranges x policies per symbol.

Usage:
    backtest                              # console script (after pip install -e .)
    python -m crypto_analysis.core.run    # equivalent module invocation
    ... --symbols xaut                    # subset
    ... --fee-model proxy                 # override fee model
Outputs (directly in out_dir, default results/): report.md (ranked tables +
optimal-X analysis) and config_used.yaml always; summary.csv and equity/*.csv
only when config `detailed_outputs: true`.
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .config import cli_overrides, load_config
from .data import load_klines
from .engine import FeeCtx, simulate_asset_hold, simulate_hold, simulate_lp
from .fees import make_fee_stream
from .metrics import compute_metrics


def build_fee_ctx(cfg, bars, symbol) -> FeeCtx:
    pc = dict(cfg["pools"][symbol])
    vol_bar, tvl_of = make_fee_stream(bars, pc)
    if pc.get("fee_model") == "proxy" and (vol_bar is None or not vol_bar.any()):
        raise ValueError("empty proxy volume stream")
    return FeeCtx(
        mode=pc.get("fee_model"), vol_bar=vol_bar, tvl_of=tvl_of,
        fee_tier=float(pc.get("fee_tier", 0.0005)),
        lp_share=1.0 - float(pc.get("protocol_fee_cut", 0.0)),
        static_apr=float(pc.get("static_apr", 0.0)),
        seconds_per_bar=bars.dt_seconds,
        active_span=float(pc.get("active_liquidity_span", 0.0)),
        gain_cap=float(pc.get("concentration_gain_cap", 50.0)),
    )


def run_symbol(cfg, bars, symbol) -> pd.DataFrame:
    fee_ctx = build_fee_ctx(cfg, bars, symbol)
    cap = float(cfg["capital_usd"])
    gas = float(cfg["gas"]["usd_per_tx"]) * int(cfg["gas"]["txs_per_rebalance"])
    res = [simulate_hold(bars, cap), simulate_asset_hold(bars, cap, fee_ctx)]

    for rng in cfg["ranges_pct"]:
        res.append(simulate_lp(bars, fee_ctx, cap, rng, "III", "exit",
                               gas_per_reset=gas))
        res.append(simulate_lp(bars, fee_ctx, cap, rng, "IV", "exit",
                               gas_per_reset=gas))
        for d in cfg["policies"]["periodic"]["every_days"]:
            every = max(int(round(d * 86400 / bars.dt_seconds)), 1)
            buf = float(cfg["policies"]["periodic"]["buffer_frac_of_range"])
            for strat in cfg["policies"]["exit"]["strategies"]:
                res.append(simulate_lp(bars, fee_ctx, cap, rng, strat, "periodic",
                                       every_bars=every, buffer_frac=buf,
                                       gas_per_reset=gas))

    rows = []
    for r in res:
        m = compute_metrics(r.equity, bars.dt_seconds)
        rows.append({
            "symbol": symbol, "strategy": r.strategy, "range": r.range_pct,
            "policy": r.policy,
            "every_days": (f"{r.label.split('T=')[-1].split('|')[0]}b"
                           if "T=" in r.label else None),
            "final": r.final, **m,
            "fees_earned": r.fees_earned, "swap_fees_paid": r.swap_fees_paid,
            "gas_paid": r.gas_paid, "resets": r.resets, "ruined": r.ruined,
            "frac_in_range": r.frac_in_range, "label": r.label,
        })
    df = pd.DataFrame(rows)
    return df, res


def main(argv=None):
    config_path, ov, dates = cli_overrides(argv)
    cfg = load_config(config_path, ov)
    if dates["start"]:
        for s in cfg["data"].values():
            s["start"] = dates["start"]
    if dates["end"]:
        for s in cfg["data"].values():
            s["end"] = dates["end"]

    run_id = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(cfg["out_dir"])
    detailed = bool(cfg.get("detailed_outputs", False))
    if detailed:
        (out / "equity").mkdir(parents=True, exist_ok=True)
    else:
        out.mkdir(parents=True, exist_ok=True)
    (out / "config_used.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))

    all_rows = []
    for symbol in cfg["symbols"]:
        scfg = cfg["data"][symbol]
        bars = load_klines(scfg["klines"], scfg.get("start"), scfg.get("end"))
        print(f"{symbol}: {bars.n} bars {bars.bars_per_day}/day "
              f"{np.datetime_as_string(bars.ts[0])} -> {np.datetime_as_string(bars.ts[-1])}")
        df, runs = run_symbol(cfg, bars, symbol)
        all_rows.append(df)
        if detailed:
            # export equity for the best run of each strategy
            for strat, g in df.groupby("strategy"):
                best = g.loc[g["final"].idxmax()]
                run = next(r for r in runs if r.label == best["label"])
                pd.DataFrame({"close": bars.close, "equity": run.equity}).to_csv(
                    out / "equity" / f"{symbol}_{run.label.replace('|', '_')}.csv",
                    index=False)

    summary = pd.concat(all_rows, ignore_index=True)
    if detailed:
        summary.to_csv(out / "summary.csv", index=False)

    # console/report tables
    lines = [f"# Backtest {run_id}", ""]
    for symbol in summary["symbol"].unique():
        s = summary[summary["symbol"] == symbol].sort_values("final", ascending=False)
        lines += [f"## {symbol}", "",
                  f"Top 10 (of {len(s)} runs), capital {cfg['capital_usd']:.0f} USDT:", ""]
        cols = ["strategy", "range", "policy", "final", "return", "max_drawdown",
                "fees_earned", "swap_fees_paid", "gas_paid", "resets"]
        lines.append(s[cols].head(10).to_markdown(index=False))
        for strat in ["I", "II", "III", "IV"]:
            top = s[s["strategy"] == strat].head(1)
            if len(top):
                t = top.iloc[0]
                extra = f" (range {t['range']:.1%}, policy {t['policy']})" \
                    if strat in ("III", "IV") else ""
                lines.append(f"- **Best {strat}**: final {t['final']:.2f} "
                             f"= {t['return']:+.1%}{extra}")
        lines += optimal_x_lines(s, cfg["ranges_pct"])
        lines.append("")
    (out / "report.md").write_text("\n".join(lines))
    print("\n" + "\n".join(lines))
    print(f"-> {out}")


def optimal_x_lines(s: pd.DataFrame, grid) -> list[str]:
    """Answer the research question: at what one-sided width X is strategy IV
    most profitable, and is IV ever the overall winner. Grid argmax + the
    full X-by-X comparison; if IV never wins, say so with the measured gap."""
    lines = ["", "### Optimal range width X", ""]
    iv = s[s["strategy"] == "IV"]
    iii = s[s["strategy"] == "III"]
    if not len(iv):
        return lines
    best_iv = iv.loc[iv["final"].idxmax()]
    best_any = s.loc[s["final"].idxmax()]
    verdict = (f"- **X that maximises strategy IV: {best_iv['range']:.1%}** one-sided "
               f"(final {best_iv['final']:.2f} = {best_iv['return']:+.1%}, "
               f"policy {best_iv['policy']}).")
    if len(iii):
        best_iii = iii.loc[iii["final"].idxmax()]
        verdict += (f" Best III: X = {best_iii['range']:.1%} "
                    f"(final {best_iii['final']:.2f} = {best_iii['return']:+.1%}).")
    if best_iv["final"] >= best_any["final"] - 1e-9:
        verdict += " At this X strategy IV **is** the best of all strategies."
    else:
        gap = best_any["final"] - best_iv["final"]
        where = (f" at X={best_any['range']:.1%}" if pd.notna(best_any["range"])
                 else "")
        verdict += (f" No swept X makes IV the overall best: the global winner is "
                    f"strategy {best_any['strategy']}{where} "
                    f"(final {best_any['final']:.2f}), i.e. IV's best trails by "
                    f"{gap:.2f} USDT ({gap / 10:.2f}% of capital) — wider grid or "
                    "higher fee income would be needed to flip this.")
    lines.append(verdict)
    rows = []
    for rng in grid:
        g = s[s["range"] == rng]
        if not len(g):
            continue
        iv_f = float(g[g["strategy"] == "IV"]["final"].max())
        iii_f = float(g[g["strategy"] == "III"]["final"].max())
        any_f = float(g["final"].max())
        rows.append({"X (one-sided)": f"{rng:.1%}", "best IV": round(iv_f, 2),
                     "best III": round(iii_f, 2), "best any": round(any_f, 2),
                     "IV wins?": "YES" if iv_f >= any_f - 1e-9 else "no"})
    lines += ["", "X-by-X comparison (best policy at each width):", "",
              pd.DataFrame(rows).to_markdown(index=False)]
    return lines


if __name__ == "__main__":
    main(sys.argv[1:])
