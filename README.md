# crypto-trading-system

A modular cryptocurrency **research, strategy, paper-trading and
eventually execution** system — structured as a monorepo with logically
independent modules.

## Project status

```text
Module 1 — Research:                 implemented ✅
Module 2 — Strategy + Backtester:    planned ⏳
Module 3 — Paper Trading:            planned ⏳
Module 4 — Infrastructure (Supabase): planned ⏳
Module 5 — Telegram:                 planned ⏳
```

## Architecture

```text
                 crypto-trading-system
                         │
        ┌────────────────┼────────────────┐
        │                │                │
     Research         Strategy       Paper Trading
        │                │                │
        └────────────────┴────────────────┘
                         │
                   Infrastructure
                         │
                      Telegram
```

Dependency direction (one-way, no cycles):

```text
                    ┌──────────────┐
                    │    Shared    │
                    │ models/utils │
                    └──────┬───────┘
                           ▲
          ┌────────────────┼────────────────┐
          │                │                │
      Research         Strategy       Paper Trading
                                           │
                                           ▼
                                      Infrastructure
                                           │
                                           ▼
                                        Telegram
```

Modules communicate through explicit interfaces and data contracts —
never by importing each other's internals. Today the only implemented
module is Research; shared models will be extracted into `shared/` only
when a second module actually needs them (no speculative abstractions).

## Layout

```text
modules/research/         # Market data → indicators → regime → reports
modules/strategy/         # planned: strategies, backtester, risk, metrics
modules/paper_trading/    # planned
modules/infrastructure/   # planned (Supabase)
modules/telegram/         # planned
shared/                   # cross-module contracts (currently empty by design)
configs/                  # global config (module config stays inside modules)
docs/                     # cross-module agreements and decisions
tests/                    # cross-module integration tests (future)
```

## Principles

- **Research first** — understand data and regime behaviour before any strategy.
- **Paper trading before live trading.** Nothing here places real orders.
- **Spot / long-only initially** — no leverage, no futures trading, no shorts.
- **No lookahead** — signals and regimes use only current/past data.
- **Reproducibility** — content-hashed datasets, config fingerprints, provenance in every artifact.
- **Explicit module boundaries** — dependency direction: shared ← research/strategy/paper-trading → infrastructure → telegram.
- **Exchange abstraction** — exchange-specific code lives behind provider interfaces.
- **Auditable decisions** — every regime/regime-artifact carries its conditions and reasons.
- **Never commit secrets** (`.env`, API keys, bot tokens, service-role keys).

## Getting started

```bash
git clone https://github.com/EhsanEDev/crypto-trading-system.git
cd crypto-trading-system
python -m venv .venv && source .venv/bin/activate
cp .env.example .env          # optional: API base URLs, data dirs, log level

# Module 1 — Research (the only implemented module today)
pip install -e modules/research[dev]
cd modules/research && pytest
python -m crypto_research pipeline --symbol BTCUSDT --timeframe 4h
```

See `modules/research/README.md` for the full research documentation.
