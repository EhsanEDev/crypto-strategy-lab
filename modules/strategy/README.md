# Module — Strategy (planned, NOT implemented)

This module will contain the trading-strategy layer of
`crypto-trading-system`. It is intentionally empty in this migration:
**Milestone 1 remains research-only.**

## Planned contents (future milestones)

- **Strategy definitions** — rules that turn research outputs into signals
- **Backtester** — event-driven execution simulation
- **Risk management** — position sizing, exposure limits (research/analysis level)
- **Execution simulator** — fees, slippage, fills
- **Portfolio simulation** — cash/equity tracking
- **Performance metrics** — Total Return, CAGR, Max Drawdown, Sharpe,
  Sortino, Win Rate, Profit Factor, Expectancy, streaks, ...

## Planned pipeline

```text
Research Data
     ↓
Strategy
     ↓
Signal
     ↓
Risk Manager
     ↓
Execution Simulator
     ↓
Portfolio
     ↓
Backtester
     ↓
Metrics
```

## Boundary rules (do not violate later)

- Strategy consumes **well-defined research outputs** (OHLCV, indicators,
  regime labels — files + metadata contracts), never Research internals.
- `modules/research` must never import Strategy.
- Regime labels are hypotheses, not signals; strategy code owns the
  signal decision.
- Package will be `crypto_strategy` under `src/` (analogous to Research).
