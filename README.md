# crypto-strategy-lab

A **research-first crypto strategy laboratory**: historical market data from
the Bitunix public API, validation/normalisation, Parquet storage, local
indicator computation, a deterministic rule-based **Market Regime Detector**,
and reproducible research reports.

This is **not** a trading bot. There is no live trading, no order
execution, no AI/ML component and no live infrastructure (Telegram,
Supabase) in this milestone. Regime labels are *not* buy/sell signals.

---

## 1. Project Overview

Milestone 1 delivers this pipeline:

```text
Bitunix public market API
   ↓
Historical Market Data (candles)
   ↓
Validation / Normalisation
   ↓
Parquet Dataset  (+ JSON metadata)
   ↓
Indicators  (EMA50/200, ATR14, RSI14, ADX14)
   ↓
Regime Detector v001  (TREND_UP / TREND_DOWN / RANGE / HIGH_VOLATILITY / UNCERTAIN)
   ↓
Research Report (distribution, transitions, durations)
```

Everything is deterministic and explainable: every candle carries the
conditions that produced its regime label.

## 2. Goals

- Pull historical OHLCV from Bitunix public endpoints (no API key).
- Validate and normalise candles into one canonical model.
- Store datasets as Parquet with JSON metadata for reproducibility.
- Implement EMA / ATR / RSI / ADX locally (pandas + numpy only).
- Detect market regimes with an explicit, configurable rule set.
- Generate per-asset markdown research reports.
- Keep the whole core pure and testable (no network in the research core).

## 3. Non-Goals (Milestone 1)

- ❌ Telegram bot, ❌ Supabase, ❌ live trading, ❌ futures trading/leverage/shorts
- ❌ AI signals, ❌ ML prediction, ❌ reinforcement learning
- ❌ automatic parameter optimisation / hyperparameter search
- ❌ dashboards, ❌ a strategy engine or backtester (next milestone)

`Regime = TREND_UP` **does not** mean *BUY*. Regime and Signal are
separate concepts; the Strategy engine comes later on top of this lab.

## 4. Architecture

```text
src/crypto_strategy_lab/
├── config.py            # YAML + env configuration (all thresholds live here)
├── cli.py               # typer CLI (download / indicators / regime / report / pipeline)
├── data/
│   ├── models.py        # canonical Candle model + timeframe helpers
│   ├── loader.py        # loading helpers (validated raw datasets)
│   ├── validator.py     # OHLCV validation, duplicate/sort checks, gap detection
│   ├── storage.py       # Parquet storage, atomic writes, metadata sidecars
│   └── exchanges/
│       ├── base.py      # ExchangeDataProvider protocol (exchange-agnostic)
│       └── bitunix.py   # Bitunix-specific normalisation + pagination
├── indicators/          # EMA, ATR (Wilder), RSI (Wilder), ADX (Wilder), registry
├── regime/              # Regime labels, conditions, rule-based detector
├── research/            # report generation (markdown)
└── utils/               # logging
```

Separation of concerns (kept strictly):

```text
Data → Indicators → Regime → (Strategy) → (Risk) → (Execution)
```

Nothing in `data/` decides buy/sell; nothing in `regime/` creates orders.
The research core (`indicators`, `regime`, `reports`, `validator`) is pure:
`detect_regime(df, config)` runs without API, database or network, so the
same code can later run inside a Supabase Edge Function or any backend.

## 5. Installation

Requires Python **3.11+** (3.12+ recommended).

```bash
git clone <repo-url>
cd crypto-strategy-lab
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## 6. Configuration

Two layers, later wins:

1. `config/default.yaml` — assets, timeframes, regime thresholds.
   All thresholds live here; nothing is hard-coded in the algorithms:

   ```yaml
   regime:
     ema_fast: 50
     ema_slow: 200
     adx_period: 14
     adx_trend_threshold: 20
     atr_period: 14
     rsi_period: 14
     volatility_percentile: 90
     volatility_lookback: 200
     range_volatility_percentile: 80
     slope_lookback: 5
   ```

2. `.env` (copy from `.env.example`) — API base URLs, data/report
   directories, log level. No credentials needed: all endpoints used are
   public. Never commit real secrets.

## 7. Downloading Data

```bash
python -m crypto_strategy_lab download --symbol BTCUSDT --timeframe 4h --start 2022-04-17
python -m crypto_strategy_lab download --symbol BTCUSDT --timeframe 4h --market spot   # latest ~201 candles only
```

Data layout and idempotency:

- Raw candles: `data/raw/bitunix/{SYMBOL}/{timeframe}.parquet`
- Raw data is **never overwritten destructively**: a download is merged
  into the existing dataset (missing timestamps appended, duplicates
  keep the existing row), validated and written atomically.
- Downloads are **incremental**: the CLI computes the missing date range
  from the stored dataset (forward/backward extension) and only fetches
  what is missing. Re-running the same command is a no-op or a tiny
  "top-up" fetch.
- Metadata: `data/metadata/raw/bitunix/{SYMBOL}_{timeframe}.json`
  (exchange, symbol, timeframe, start, end, rows, gaps, OHLC anomalies,
  downloaded_at, schema_version, market).

### Real Bitunix API behaviour (verified live, documented - not guessed)

The Bitunix API differs from what one might assume; the real behaviour is
the source of truth here:

| Topic | Observed behaviour |
| --- | --- |
| Spot klines | `GET https://openapi.bitunix.com/api/spot/v1/market/kline?symbol=..&interval={60|240|D}` — returns at most **201 candles**, `limit` is ignored, **no pagination**. Spot history is therefore research-limited. |
| Futures klines | `GET https://fapi.bitunix.com/api/v1/futures/market/kline?symbol=..&interval={1h|4h|1d}&limit≤200&endTime=<ms>` — public, no key. Rows newest-first. |
| Futures pagination | `endTime` is **exclusive by candle open time** (returns candles opening strictly before it). Backward paging uses `endTime = oldest open time of the previous page`. |
| Page size | Futures kline cap: **200 rows** per request. |
| History depth | Futures 4h/1d history starts **2022-04-17** (BTC/ETH); 1h history starts **2024-05-15** for SOL (shorter granularity kept shorter). Bitunix does **not** serve 2020+ klines. |
| Response shapes | Spot: `{"code": "0", "data": [{"open","high","low","close","volume","ts"(ISO-8601 UTC)}]}` (code is a string). Futures: `{"code": 0, "data": [{"open","high","low","close","baseVol","quoteVol","time"(ms)}]}`. Both newest-first, all values as strings. |
| Data quality | A handful of candles per multi-year dataset violate standard OHLC relations (e.g. `high` a few ticks below `close`). These are **kept as received** in raw storage, counted as `ohlc_anomalies` in metadata, and reported - never silently repaired or hidden. |

Because spot history is capped at ~201 candles, the default download
market is **futures** (public, key-less). The market choice is recorded in
dataset metadata; `--market spot` remains available for short snapshots.

## 8. Indicators

All indicators are implemented locally with pandas/numpy — fully
deterministic, unit-tested against hand-computed values, no external
indicator library, no lookahead.

| Indicator | Definition |
| --- | --- |
| EMA50 / EMA200 | SMA-seeded EMA, `alpha = 2/(period+1)`, `ema(series, period)` |
| ATR14 | Wilder smoothing (`alpha = 1/period`) of standard True Range; `TR_0 = high_0 - low_0` |
| RSI14 | Standard Wilder RSI (SMA seed + Wilder recursion of gains/losses) |
| ADX14 | Wilder +DM/-DM → +DI/-DI → DX → Wilder-smoothed ADX (TA-Lib-compatible seeding, first ADX at bar `2*period-2`) |
| atr_pct | `ATR14 / Close * 100` (volatility as % of price) |

**Warm-up behaviour (documented, honest):** bars before an indicator's
first defined value are NaN — EMA200 needs 199 bars, ADX needs
`2*period-2 = 26` bars, RSI/ATR need `period` bars. The warm-up window is
never faked, filled or back-projected; regime detection labels those bars
`UNCERTAIN`. E.g. EMA200 needs 199 bars, so the first ~200 4h candles of a
fresh dataset are UNCERTAIN by design.

## 9. Regime Detection

Regime Detector **v001** is a *rule-based hypothesis generator*, not an
oracle. It runs on the configured timeframe (default **4h**) and is
deterministic and explainable: each candle stores machine-readable
condition flags (`regime_flags` JSON) and a human-readable
`regime_reason`.

Classification priority (top to bottom, first match wins):

```text
1. HIGH_VOLATILITY : atr_pct > rolling 90th percentile of its own trailing
                     history (threshold window strictly past: t-1..t-200)
2. TREND_UP        : EMA50 > EMA200 AND close > EMA200
                     AND EMA50 slope(5) > 0 AND ADX >= 20
3. TREND_DOWN      : EMA50 < EMA200 AND close < EMA200
                     AND EMA50 slope(5) < 0 AND ADX >= 20
4. RANGE           : ADX < 20 AND atr_pct <= rolling 80th percentile
5. UNCERTAIN       : warm-up (NaN indicators) or no rule matched
```

Notes:

- HIGH_VOLATILITY deliberately dominates: a volatility anomaly suppresses
  trend/range labels even when trend conditions also match.
- Percentile thresholds use **only past bars** (`shift(1)` trailing
  window) — the current bar can never set its own threshold.
- Known baseline behaviour: sustained steep declines inflate `atr_pct`
  against its own trailing distribution, so a share of strong downtrend
  bars legitimately lands in HIGH_VOLATILITY. This is honest behaviour of
  the v001 rule, visible in the reports, to be evaluated (not tuned) in
  the next milestone.

Per-candle output columns: `regime`, `trend_condition` (ADX ≥ threshold),
`volatility_condition` (ATR% above percentile), `range_condition`
(ADX < threshold AND volatility normal), `regime_reason` (human-readable)
and `regime_flags` (machine-readable JSON, e.g.
`{"ema_alignment": true, "price_above_ema200": true, "ema50_slope_positive": true, "adx_trending": true, "high_volatility": false, ...}`).

**No lookahead bias:** for candle `t` only information from `t, t-1, ...`
is used. There is no `shift(-1)`, no future close/high/low anywhere in
signal generation. This is enforced by a prefix-invariance test: labels
computed on the first `k` candles are identical to the same labels
computed on the full dataset.

## 10. Running the Pipeline

```bash
# single asset (downloads every configured timeframe, then regime+report on 4h)
python -m crypto_strategy_lab pipeline --symbol BTCUSDT --timeframe 4h

# all configured assets (BTC/ETH/SOL)
python -m crypto_strategy_lab pipeline --all
```

Or step by step:

```bash
python -m crypto_strategy_lab download   --symbol BTCUSDT --timeframe 4h --start 2022-04-17
python -m crypto_strategy_lab indicators --symbol BTCUSDT --timeframe 4h
python -m crypto_strategy_lab regime     --symbol BTCUSDT --timeframe 4h
python -m crypto_strategy_lab report     --symbol BTCUSDT --timeframe 4h
python -m crypto_strategy_lab config     # print resolved configuration
```

## 11. Reports

`python -m crypto_strategy_lab report --symbol BTCUSDT --timeframe 4h`
writes `reports/BTCUSDT_4h_regime_report.md` containing:

- **Dataset**: symbol, timeframe, start, end, rows, gaps, duplicates, OHLC anomalies
- **Indicator summary**: defined/NaN counts and mean/min/max per indicator
- **Regime distribution**: share and candle count per regime
- **Regime transitions**: counts of `A -> B` label changes
- **Duration statistics**: median/mean/max run length per regime
- **Reproducibility**: regime config fingerprint (hash of the YAML thresholds)

## 12. Testing

```bash
pytest            # 68 tests: data, indicators, regime
ruff check src tests
```

Covered: invalid OHLC, duplicates, sorting, UTC enforcement, gap
detection (reported, never filled), idempotent Parquet storage with
metadata, Bitunix normalisation + pagination + error handling (mocked
HTTP, no network in tests), hand-computed EMA/ATR/RSI/ADX values,
synthetic regime fixtures for all five regimes, priority determinism and
no-lookahead (prefix invariance).

## 13. Data Layout

```text
data/
├── raw/
│   └── bitunix/
│       ├── BTCUSDT/{1h,4h,1d}.parquet
│       ├── ETHUSDT/{1h,4h,1d}.parquet
│       └── SOLUSDT/{1h,4h,1d}.parquet
├── processed/
│   ├── BTCUSDT/4h_regimes.parquet
│   ├── ETHUSDT/4h_regimes.parquet
│   └── SOLUSDT/4h_regimes.parquet
└── metadata/
    ├── raw/bitunix/{SYMBOL}_{timeframe}.json
    └── processed/{SYMBOL}_{timeframe}_regimes.json

reports/
├── BTCUSDT_4h_regime_report.md
├── ETHUSDT_4h_regime_report.md
└── SOLUSDT_4h_regime_report.md
```

The regimes parquet contains, per candle: `open..volume, quote_volume,
ema50, ema200, atr14, atr_pct, rsi14, adx14 (+DI/-DI), regime,
trend_condition, volatility_condition, range_condition, regime_reason,
regime_flags`.

## 14. Avoiding Lookahead Bias

- Indicator computations are strictly backward-looking (recursive
  smoothings with past-only seeds).
- Volatility thresholds are rolling percentiles of **past** values only
  (`shift(1)` before the rolling window).
- No `shift(-1)`, no future close/high/low anywhere in the detector.
- `detect_regime(df[:k])` produces byte-identical labels for the first
  `k` candles as `detect_regime(df)` — asserted by a test.
- Warm-up bars are `UNCERTAIN`, never filled with fake values.

## 15. Roadmap

- **Milestone 2 — Strategy v001** (on top of the regime detector):
  4H regime = TREND_UP AND 1H pullback AND momentum recovery AND
  acceptable volatility AND acceptable R/R → LONG (research first).
- **Backtester**: Signal → Entry → Slippage → Fee → Position → Stop/TP →
  Exit → Fee → P&L with metrics (Total Return, CAGR, Max Drawdown,
  Sharpe, Sortino, Win Rate, Profit Factor, Expectancy, streaks, ...).
- Deployment targets (Supabase Edge Function, Telegram bot, paper
  trading, Bitunix execution) will be *adapters* around this core — the
  core stays dependency-free.

Non-goals remain non-goals until the regime baseline is evaluated.
