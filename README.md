# Crypto LP research — PancakeSwap v3 range strategies

Research question: given 1000 USDT, which is better on PancakeSwap v3 (BNB Chain) — holding USDT, holding the asset, or providing concentrated liquidity in a range ±X% (plus the two re-balancing rules), and at what X does strategy IV become the best option? Same study for the BTC pool.

## Strategies

| # | Description |
|---|-------------|
| I | Hold 1000 USDT |
| II | Buy asset (XAUT / BTCB) with everything, hold |
| III | 50/50 into a ±X% LP range. Range exits **below**: leave position as-is and wait. Exits **above**: close, rebalance 50/50, reopen ±X% |
| IV | As III, but rebalance+reopen on **either** exit |

Two rebalancing policies are swept: `exit` (task definition) and `periodic` (re-center every T days when price drifted > 0.5·X from center — the "how often to move the range" dimension).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate  # once (any Python >= 3.11)
pip install -e ".[dev]"                             # once: package + deps + pytest
pytest -q                                           # runs the tests
backtest                                            # uses config.yaml
backtest --symbols xaut --ranges 0.01 0.02 0.05
backtest --fee-model proxy                          # see Fee-income models
python -m crypto_analysis.download.download_binance --symbol PAXGUSDT --interval 5m --from 2024-10 --to 2026-10 --out data/paxgusdt-5m-2024-2026.csv
```

Without installing, prefix runs with `PYTHONPATH=src` (e.g. `PYTHONPATH=src python -m crypto_analysis.core.run`); `pytest` picks `src/` up from `pyproject.toml` automatically.

Every key is optional in `config.yaml` (dates, files, fee tiers, gas, sweeps); built-in defaults live in `src/crypto_analysis/core/config.py`. CLI flags override the file.

Outputs go directly into `results/` (overwritten each run): `report.md` (ranked tables + the optimal-X verdict) and `config_used.yaml` (snapshot). Set `detailed_outputs: true` in `config.yaml` to additionally get `summary.csv` (all runs) and `equity/*.csv` (curves for the best run per strategy).

## Data

- `data/*.csv` — Binance monthly klines (BTC 5m/1h 2025-01→2026-09; XAUT 5m/1h **2026-03-26→2026-09-30** — XAUTUSDT was only listed on Binance in March 2026, so the XAUT study covers ~6 months. Limitation noted in conclusions). Downloader: `src/crypto_analysis/download/download_binance.py` (`--symbol --interval --from --to --out`).
- **Gold proxy (`gold` symbol)**: PAXG/USDT 5m 2024-10→2026-09 (24 months, same LBMA ounce as XAUT; on the 6-month overlap the PAXG/XAUT price paths deviate by max 0.68%). Simulates the XAUT/USDT pool economics over a full 2-year gold history (`backtest --symbols gold`).
- Pool economics: the real pools (verified via `PancakeV3Factory.getPool` on BSC): XAUT/USDT 0.05% — `0x83a0a8A723262651aE9C54bBbA929f167443bC59`; BTCB/USDT 0.05% — `0x46CF1CF8c69595804bA91DfdD8d6b960C9B0A7C4`.

### Fee-income models (`pools.<sym>.fee_model`)

1. **fixed_apr** (current default) — pool-average fee APR estimated from a real pool snapshot of 2026-10-22 (XAUT ~10.4%, BTCB ~23.9% gross; the engine applies `protocol_fee_cut` — 34% on Pancake v3 BSC, verified on-chain — so LPs model at ~66% of those figures), applied to the in-range position value. An estimate, not measured per-bar.
2. **proxy** — pool volume = k × exchange quote volume (`proxy_volume_k`), TVL = `static_tvl_usd` (crude, no pool data needed); income = volume × fee tier × LP share × our fraction of TVL.

**Concentration gain** (`active_liquidity_span`): narrow ranges capture more volume per dollar than the pool average. We model fee income × (S/X), where S is the pool's active-liquidity half-spread (assumed ±5%; refine with tick data), capped at `concentration_gain_cap`. This term is the main reason range-width conclusions depend on fee-model quality.

## Cost model

- Swap fee charged on the **traded notional only** (at a boundary exit that's half the portfolio, not the whole portfolio).
- BSC gas: `gas.usd_per_tx × gas.txs_per_rebalance` per open/reset/close op (default $0.02 × 4 tx — tune against live wallet quotes).
- **Ruin guard**: if a single reset's cost (gas + swap fee) would consume the whole position, the simulation liquidates once, holds cash and stops trading (`ruined=True` in summary.csv). Without it, ultra-narrow ranges produced a negative-equity death spiral (negative liquidity → negative fee accrual).
- Final liquidation costs included in `final`; equity curves are pre-liquidation.

## Findings so far

No range width X in the swept grid (0.5%–20%) makes strategy IV the outright best option — IV ≤ III at every range, in every window tested (down-drift punishes IV, which sells low on each re-center; in chop III ties holding the asset plus fees). IV only overtakes III at the widest range (±20%) in a strong uptrend. Cadence: re-centering more often than ~weekly is pure loss at every width. See `results/<id>/report.md` for the per-window tables.

## Known simplifications

- One exit decision per bar; intrabar path = open→close bias (high/low used).
- Daily pool volume assumed uniform across bars.
- Fee APR/volume/TVL snapshots are static unless `calibrated` data is loaded.
- No CAKE farm emissions, no MEV/slippage beyond the spread, no tick-grid rounding.
- Position dust (50/50 split not exactly mintable on a finite range) is kept idle, and on re-centering is folded back into the split.

## Project layout

```
pyproject.toml  package metadata, dependencies, `backtest` console script
src/crypto_analysis/core/       engine (strategies I-IV), V3 math, fee models, data loading, config, metrics, runner
src/crypto_analysis/download/   Binance klines downloader
tests/          pytest suite (V3 math closed forms, IL law, engine invariants)
```
