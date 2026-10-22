# AGENTS.md — working rules for this repo

## Mission
Backtest research: PancakeSwap v3 (BNB Chain) concentrated-liquidity strategies I–IV vs holding (XAUT/USDT and BTCB/USDT pools, 1000 USDT), finding the range width X and re-centering cadence where strategy IV wins. Methodology decisions are listed in README.md — if you change an assumption that moves numbers, ask the user first, don't silently "improve" it.

## Commands
- Setup (once per environment): `pip install -e ".[dev]"` — installs the `crypto_analysis` package (src layout), dependencies from `pyproject.toml`, and the `backtest` console script. No-install fallback: prefix commands with `PYTHONPATH=src`.
- Tests: `pytest -q` — must stay green when you touch `src/crypto_analysis/core/`. Engine invariants live in `tests/test_engine.py` (non-negative equity, fees credited, ruin guard, III-vs-IV reset semantics).
- Run: `backtest` or `python -m crypto_analysis.core.run` (config: `config.yaml`, all optional).
- Never hardcode paths/dates/tiers in code — add a key to `src/crypto_analysis/core/config.py` DEFAULTS + `config.yaml`.
- Do not `git commit` or install packages / create environments without the user's explicit permission; if the environment is broken, stop and ask.

## Pitfalls (verified 2026-10)
- pandas ≥3.1 deprecates `.values` on tz-aware datetime data (Pandas4Warning; python 3.14 + `-W error` fails): use `.dt.tz_convert(None).to_numpy()` for naive-UTC `datetime64` arrays (see `src/crypto_analysis/core/data.py`), and check dtype before epoch-unit math.
- pandas 3.0: `pd.concat` compares `df.attrs` — never put numpy arrays or dataclasses into `.attrs` (ValueError on broadcast compare).
- Filesystems are often case-sensitive: data files are lowercase (`data/xautusdt-5m-2025-2026.csv`). Don't guess paths — list them.
- BSC public RPCs: free plans cap `eth_getLogs` at ~10k blocks (BSC now runs 0.45–0.75 s blocks → ~190k blocks/day) and often block historical `eth_call` without a token. Don't attempt full-history event scans through them.
- Per-pool daily volume/TVL history is not available from free public aggregators for these v3 pools (GeckoTerminal `/ohlcv` returns 404; DeFiLlama `yields` doesn't list them), so fee income uses the snapshot-based `fixed_apr` model (or the crude `proxy` model) — see README "Fee-income models".

## Domain facts (verified on-chain 2026-10-22)
- Pools (Pancake v3, BSC, fee tier 500 = 0.05%): XAUT/USDT `0x83a0a8A723262651aE9C54bBbA929f167443bC59`; BTCB/USDT `0x46CF1CF8c69595804bA91DfdD8d6b960C9B0A7C4`.
- XAUT/USDT pool snapshot 2026-10-22: TVL ≈ $1.98M, volume24h ≈ $1.12M. BTCB/USDT: TVL ≈ $25.8M, volume24h ≈ $33.8M.
- Binance XAUTUSDT klines start 2026-03-26 only (~6-month window); use the `gold` symbol (PAXG/USDT 2024-10→2026-09) as the 2-year gold price proxy — paths deviate by max 0.68% on the overlap.
