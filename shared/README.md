# shared — reusable contracts for all modules

This layer contains code/contracts that multiple modules genuinely need
through stable interfaces. It exists to keep the dependency direction
acyclic:

```text
        Shared (models / config / utils)
               ▲
   ┌───────────┼───────────┐
Research   Strategy   Paper Trading
```

## Current contents

Deliberately empty. Existing research models (`Candle`, regime labels,
indicators) stay inside `modules/research` because only Research uses them
today.

## Rules

- Move something into `shared/` only when **multiple modules** consume it
  through a **stable interface**.
- Never import module internals across module boundaries; communicate via
  shared models and explicit outputs (e.g. parquet artifacts + metadata).
- No speculative abstractions: no `Signal`, `Order`, `Position`, `Trade`
  or `EquityPoint` models until a second module actually needs them.

## Planned shared models (future, only when needed)

- `Candle` — when Strategy/Paper Trading consume market data
- `Signal` — Strategy → Risk/Paper interface
- `Order` / `Position` / `Trade` — Paper Trading contract
- `EquityPoint` — performance metrics contract
