# MicroMeanRevertStrategy - Agent Guide

> AI coding agent context for the `micro_mean_revert` strategy.

## Overview

- **Template:** mean_reversion
- **Chain:** arbitrum
- **Class:** `MicroMeanRevertStrategy` in `strategy.py`
- **Config:** `config.json`

This is a self-contained Python project with its own `pyproject.toml`, `.venv/`, and `uv.lock`.
The same `pyproject.toml` + `uv.lock` drive both local development and cloud deployment.

## Files

| File | Purpose |
|------|---------|
| `strategy.py` | Main strategy - edit `decide()` to change trading logic |
| `config.json` | Runtime parameters (tokens, thresholds, chain) |
| `pyproject.toml` | Dependencies plus metadata (`framework`, `version`, `run.interval`) |
| `uv.lock` | Locked dependencies for reproducible builds |
| `.venv/` | Per-strategy virtual environment (created by `uv sync`) |
| `.env` | Secrets (private key, API keys) - never commit this |
| `.gitignore` | Git ignore rules (excludes `.venv/`, `.env`, etc.) |
| `.python-version` | Python version pin (3.12) |
| `tests/test_strategy.py` | Unit tests for the strategy |

## How to Run

```bash
# Single iteration on Anvil fork (safe, no real funds)
almanak strat run --network anvil --once

# Single iteration on mainnet
almanak strat run --once

# Continuous with 30s interval
almanak strat run --network anvil --interval 30

# Dry run (no transactions)
almanak strat run --dry-run --once
```

## Adding Dependencies

```bash
# Add a package (updates pyproject.toml + uv.lock + .venv/)
uv add pandas-ta

# Run tests via uv
uv run pytest tests/ -v
```

## Intent Types Used

This strategy uses these intent types:

- `Intent.swap(from_token, to_token, amount_usd=, max_slippage=Decimal("0.005"))`
- `Intent.hold(reason="...")`

All intents are created via `from almanak.framework.intents import Intent`.

## Key Patterns

- `decide(market)` receives a `MarketSnapshot` with `market.price()`, `market.balance()`, `market.rsi()`, etc.
- Return an `Intent` object or `Intent.hold(reason=...)` from `decide()`
- Always wrap `decide()` logic in try/except, returning `Intent.hold()` on error
- Config values are read via `self.config.get("key", default)` in `__init__`
- State persists between iterations via `self.state` dict

## Teardown (Required)

Every strategy **must** implement three teardown methods. Without them, operator
close-requests are silently ignored and positions remain open.

| Method | Purpose |
|--------|---------|
| `supports_teardown() -> bool` | Return `True` to enable teardown |
| `get_open_positions() -> TeardownPositionSummary` | List positions to close (query on-chain state, not cache) |
| `generate_teardown_intents(mode, market) -> list[Intent]` | Return ordered intents to unwind positions |

**Execution order** (if multiple position types): PERP -> BORROW -> SUPPLY -> LP -> TOKEN

The generated `strategy.py` includes teardown stubs with TODO comments -- fill them in.
See `blueprints/14-teardown-system.md` for the full teardown system reference.

## Testing

```bash
# Run unit tests
uv run pytest tests/ -v

# Paper trade (Anvil fork with PnL tracking)
almanak strat backtest paper --duration 3600 --interval 60

# PnL backtest (historical prices)
almanak strat backtest pnl --start 2024-01-01 --end 2024-06-01
```

## Full SDK Reference

For the complete intent vocabulary, market data API, and advanced patterns,
install the full agent skill:

```bash
almanak agent install
```

Or read the bundled skill directly:

```bash
almanak docs agent-skill --dump
```
