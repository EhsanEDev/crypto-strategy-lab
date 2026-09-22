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
Historical Market Data (closed candles only)
   ↓
Validation / Normalisation (audit + strict research-ready gate)
   ↓
Parquet Dataset  (+ JSON metadata with content hashes)
   ↓
Indicators  (EMA50/200, ATR14, RSI14, ADX14 - TA-Lib-compatible)
   ↓
Regime Detector v001  (TREND_UP / TREND_DOWN / RANGE / HIGH_VOLATILITY / UNCERTAIN)
   ↓
Research Report (distribution, transitions, durations, provenance)
```

Everything is deterministic and explainable: every candle carries the
conditions that produced its regime label, and every processed artifact
carries the content hash of the raw dataset it was generated from.

## 2. Goals

- Pull historical closed-candle OHLCV from Bitunix public endpoints (no API key).
- Validate and normalise candles into one canonical model.
- Store datasets as Parquet with JSON metadata for reproducibility.
- Implement EMA / ATR / RSI / ADX locally (pandas + numpy only).
- Detect market regimes with an explicit, configurable rule set.
- Enforce data-quality gates before indicators/regimes/reports.
- Generate per-asset markdown research reports with full provenance.
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
│   ├── models.py        # canonical Candle model, date bounds, content hash
│   ├── loader.py        # loading helpers + research-ready quality gate
│   ├── validator.py     # audit + strict validation, duplicate/sort/gap checks
│   ├── storage.py       # Parquet storage, atomic writes, metadata, freshness
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
     ema_fast: 50            # must be < ema_slow (validated)
     ema_slow: 200
     adx_period: 14
     adx_trend_threshold: 20 # must be within (0, 100)
     atr_period: 14
     rsi_period: 14
     volatility_percentile: 90   # must be within (0, 100]
     volatility_lookback: 200
     range_volatility_percentile: 80
     slope_lookback: 5
   timeframes: [1h, 4h, 1d]
   regime_timeframe: 4h       # must be one of `timeframes` (validated)
   default_market: futures    # futures | spot (validated)
   ```

2. `.env` (copy from `.env.example`) — API base URLs, data/report
   directories, log level. No credentials needed: all endpoints used are
   public. Never commit real secrets.

## 7. Downloading Data

```bash
python -m crypto_strategy_lab download --symbol BTCUSDT --timeframe 4h --start 2022-04-17
python -m crypto_strategy_lab download --symbol BTCUSDT --timeframe 4h --market spot   # kline/history (deep)
python -m crypto_strategy_lab download --symbol BTCUSDT --timeframe 4h --end 2024-06-30
```

**Date semantics (all UTC, unambiguous):**

- `--start YYYY-MM-DD` begins at that day's **00:00 UTC** (inclusive).
- `--end YYYY-MM-DD` includes the **whole UTC calendar day** (implemented
  internally as a next-day 00:00 UTC exclusive boundary).
- Timestamp inputs (`2024-01-02T13:30`) are supported: start is the exact
  instant, end is treated as an inclusive instant.
- In-progress candles are **never** persisted: a candle is stored only
  when `open_time + timeframe <= now` (now captured once per fetch).

Data layout and idempotency:

- Raw candles: `data/raw/bitunix/{market}/{SYMBOL}/{timeframe}.parquet`
Processed artifacts: `data/processed/bitunix/{market}/{SYMBOL}/{timeframe}_{indicators|regimes}.parquet`
(migration note: market namespaces were added in Milestone 1 because spot
and futures are different instruments that can never share or overwrite
each other's datasets; legacy marketless processed files are detected and
refused — regenerate them with `pipeline --market ...`).
- Raw data is **never overwritten destructively**: a download is merged
  into the existing dataset per timestamp. The single exception is a
  bounded trailing overlap (`exchange.refresh_tail_candles`, default 1):
  the last stored candle is re-fetched and replaced on every download so a
  previously stored not-yet-closed candle can never stick around with
  stale values.
- Downloads are **incremental**: the CLI computes the missing date range
  from the stored dataset (forward/backward extension) and only fetches
  what is missing.
- Metadata: `data/metadata/raw/bitunix/{SYMBOL}_{timeframe}.json`
  (exchange, market, symbol, timeframe, start, end, rows, gaps,
  ohlc_anomalies, research_ready, candles_policy, raw_content_hash,
  downloaded_at, schema_version).

### Real Bitunix API behaviour (verified live, documented - not guessed)

The Bitunix API differs from what one might assume; the real behaviour is
the source of truth here:

| Topic | Observed behaviour |
| --- | --- |
| Spot history | `GET https://openapi.bitunix.com/api/spot/v1/market/kline/history?symbol=..&interval={60|240|D}&limit<=500&endTime=<unix SECONDS>` — public, no key. Rows newest-first; `ts` is the candle **open** time (ISO-8601 UTC). |
| Spot history pagination | `limit` is capped at **500** (asking for more returns an empty array, no error). `endTime` is in **unix seconds**; its exact boundary semantics differ between the exchange's hot/cold storage eras, and short pages can occur at era boundaries, so the provider pages with `endTime = oldest open of previous page − 1s`, de-duplicates, and only stops on an empty page / the start bound / a no-progress guard. |
| Spot history depth | 4h candles back to **2017-08-17** for BTCUSDT (much deeper than futures). Pre-listing-era data is whatever the exchange serves; its provenance is Bitunix's. |
| Spot snapshot | `GET .../api/spot/v1/market/kline` returns only the latest ~201 candles **including the in-progress candle**. Retained as `fetch_latest_snapshot()` for utility — it is NOT historical downloading. |
| Futures klines | `GET https://fapi.bitunix.com/api/v1/futures/market/kline?symbol=..&interval={1h|4h|1d}&limit<=200&endTime=<ms epoch>` — public, no key. Rows newest-first; `time` is the candle OPEN time (ms epoch). |
| Futures pagination | `endTime` is **exclusive by candle open time** (candles opening strictly before it), so backward paging uses `endTime = oldest open time of the previous page`. |
| Futures page size | Capped at **200** rows per request. |
| Futures history depth | 4h/1d from **2022-04-17** (BTC/ETH); 1h depth is shorter for some symbols (e.g. SOL from 2024-05-15). Bitunix does not serve 2020+ futures klines. |
| Closed candles | The spot **history** endpoint returns only closed candles (the in-progress candle is excluded server-side). The futures endpoint INCLUDES the in-progress candle — the provider filters it out client-side (`open + timeframe <= now`). |
| Response shapes | Spot: `{"code": "0", "data": [{"open","high","low","close","volume","ts"}]}` (code is a string). Futures: `{"code": 0, "data": [{"open","high","low","close","baseVol","quoteVol","time"}]}`. Both newest-first, values as strings. |
| Data quality | A handful of candles per multi-year dataset violate standard OHLC relations (e.g. `high` a few ticks below `close`). These are **kept as received** in raw storage, counted as `ohlc_anomalies` in metadata, and reported — never silently repaired. |

Because the spot history endpoint now provides deep paginated history,
**both** markets are usable for research downloads (`default_market:
futures` remains the default; futures has `quote_volume`).

### Data quality gates

- **Audit validation** (on every download): structural problems (missing
  columns, duplicates, unsorted/non-UTC timestamps, non-positive prices,
  negative volume) refuse the write. Gaps and exchange-reported OHLC
  inconsistencies are quantified warnings — raw observations are preserved
  for auditability and never silently repaired.
- **Strict (research-ready) gate**: indicators, regime detection and
  reports refuse to run on data that fails strict validation — gaps,
  duplicates, misaligned timestamps, NaN/infinite values, OHLC violations,
  non-positive prices. The explicit, documented override is
  `--allow-non-ready` (the exchange's ~29–300 anomalies per multi-year
  dataset then flow through, clearly labelled in reports).
- Quality status and counts (`research_ready`, `gaps`, `ohlc_anomalies`)
  are stored in the raw metadata and printed in every report.

## 8. Indicators

All indicators are implemented locally with pandas/numpy — deterministic,
unit-tested, no external indicator library, no lookahead. ATR, RSI and ADX
follow the **TA-Lib-compatible Wilder conventions** (verified against
frozen TA-Lib reference vectors and, when the optional `talib` package is
installed, live cross-checked against it):

| Indicator | Definition |
| --- | --- |
| EMA50 / EMA200 | SMA-seeded EMA, `alpha = 2/(period+1)`, `ema(series, period)` |
| ATR14 | `ta_ATR.c` convention: first ATR at bar `period` = mean(TR of bars 1..period), then mean-preserving Wilder recursion `(ATR*(n-1) + TR)/n` |
| RSI14 | Standard Wilder RSI: SMA seed over the first `period` deltas, mean-preserving recursion; first value at bar `period` (matches TA-Lib; flat series windows with zero gain+loss yield NaN instead of TA-Lib's 0) |
| ADX14 | `ta_ADX.c` convention exactly: DM/TR smoothing seeded with the raw sum of bars 1..period−1 and the sum-preserving Wilder recursion `X = X − X/n + v`; +DI/−DI/DX first valid at bar `period`; ADX = Wilder mean of DX, first valid at bar `2*period − 1` (index 27 for period 14); undefined-DX bars carry the previous ADX forward |
| atr_pct | `ATR14 / Close * 100` (volatility as % of price) |

**Warm-up behaviour (documented, honest):** bars before an indicator's
first valid position are NaN — EMA slow needs `ema_slow - 1` bars, ADX
needs `2*period - 1` = 27 bars (period 14), RSI/ATR need `period` bars.
The warm-up window is never faked, filled or back-projected; regime
detection labels those bars `UNCERTAIN`. E.g. with EMA200 the first ~200
4h candles of a fresh dataset are UNCERTAIN by design.

## 9. Regime Detection

Regime Detector **v001** is a *rule-based hypothesis generator*, not an
oracle. It runs on the configured regime timeframe (**4h** for Milestone 1
— configurable via `regime_timeframe`, which must be one of the configured
`timeframes`) and is deterministic and explainable: each candle stores
machine-readable condition flags (`regime_flags` JSON) and a
human-readable `regime_reason` (EMA period names come from the
configuration, never hard-coded).

Classification priority (top to bottom, first match wins):

```text
1. HIGH_VOLATILITY : atr_pct > rolling 90th percentile of its own trailing
                     history (threshold window strictly past: t-1..t-200)
2. TREND_UP        : EMA_fast > EMA_slow AND close > EMA_slow
                     AND EMA_fast slope(slope_lookback) > 0 AND ADX >= 20
3. TREND_DOWN      : EMA_fast < EMA_slow AND close < EMA_slow
                     AND EMA_fast slope(slope_lookback) < 0 AND ADX >= 20
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
(ADX < threshold AND volatility normal), `regime_reason` (human-readable,
uses the configured EMA names) and `regime_flags` (machine-readable JSON:
`ema_alignment`, `price_above_slow_ema`, `fast_ema_slope_positive`,
`adx_trending`, `high_volatility`, `vol_normal`, `range_candidate`,
`warmup_complete`, ...).

**No lookahead bias:** for candle `t` only information from `t, t-1, ...`
is used. There is no `shift(-1)`, no future close/high/low anywhere in
signal generation. This is enforced by a prefix-invariance test: labels
computed on the first `k` candles are identical to the same labels
computed on the full dataset.

## 10. Running the Pipeline

```bash
# single asset (downloads every configured timeframe, then regime+report on the regime timeframe)
python -m crypto_strategy_lab pipeline --symbol BTCUSDT --timeframe 4h

# all configured assets (BTC/ETH/SOL)
python -m crypto_strategy_lab pipeline --all

# real Bitunix data contains exchange-reported OHLC anomalies; the strict
# gate stops the pipeline without an explicit override:
python -m crypto_strategy_lab pipeline --all --allow-non-ready
```

Or step by step:

```bash
python -m crypto_strategy_lab download   --symbol BTCUSDT --timeframe 4h --start 2022-04-17
python -m crypto_strategy_lab indicators --symbol BTCUSDT --timeframe 4h [--market futures] [--allow-non-ready]
python -m crypto_strategy_lab regime     --symbol BTCUSDT --timeframe 4h [--market futures] [--allow-non-ready]
python -m crypto_strategy_lab report     --symbol BTCUSDT --timeframe 4h [--market futures] [--allow-non-ready]
python -m crypto_strategy_lab config     # print resolved configuration
```

`--market` (defaulting to `config.default_market`) is available on
`download`, `indicators`, `regime`, `report` and `pipeline`; spot and
futures raw data, processed artifacts, metadata and reports are always
separate namespaces and never overwrite one another. Report filenames
include the market: `reports/{SYMBOL}_{timeframe}_{market}_regime_report.md`.

`pipeline` regenerates BOTH processed artifacts (`{tf}_indicators.parquet`
and `{tf}_regimes.parquet`), so they are always fresh, and re-attests
their freshness before writing the report.

## 11. Reports

`python -m crypto_strategy_lab report --symbol BTCUSDT --timeframe 4h`
writes `reports/BTCUSDT_4h_regime_report.md` containing:

- **Dataset**: symbol, timeframe, start, end, rows, gaps, duplicates,
  OHLC anomalies, misaligned/NaN counts
- **Data quality**: strict-gate status; closed-candle policy; the
  no-repair audit statement
- **Provenance & freshness**: exchange, market, raw range, raw content
  hash, regime config fingerprint, generation time + code/schema version,
  artifact freshness
- **Indicator summary**: defined/NaN counts and mean/min/max per indicator
- **Regime distribution**: share and candle count per regime
- **Regime transitions**: counts of `A -> B` label changes
- **Duration statistics**: median/mean/max run length per regime
- **Reproducibility**: config fingerprint + the exact regeneration command

The report command **refuses stale artifacts**: if the stored regimes were
generated from a different raw dataset (content-hash mismatch) or a
different regime configuration, it exits with an actionable message
instead of combining current raw data with stale regime rows.

## 12. Testing

```bash
pytest            # 120+ tests: data, indicators, regime, config, CLI, reports
ruff check src tests
```

Covered: invalid OHLC, duplicates, sorting, UTC enforcement, gap
detection (reported, never filled), strict-mode gates (alignment,
NaN/inf, gaps-as-errors), idempotent Parquet storage with metadata and
bounded tail refresh, Bitunix normalisation + pagination (mocked HTTP,
no network in tests) for spot history and futures, date-boundary tests
for 1h/4h/1d, page overlap/short pages/empty history, closed-candle
exclusion, hand-computed EMA/ATR/RSI values, **frozen official TA-Lib
reference vectors for ADX** (+ live cross-check when `talib` is
installed), synthetic regime fixtures for all five regimes, priority
determinism, no-lookahead prefix invariance, config validation, CLI
freshness and quality-gate behaviour.

## 13. Data Layout

```text
data/
├── raw/
│   └── bitunix/
│       ├── futures/{SYMBOL}/{1h,4h,1d}.parquet
│       └── spot/{SYMBOL}/{1h,4h,1d}.parquet
├── processed/
│   └── bitunix/
│       ├── futures/{SYMBOL}/{4h_indicators,4h_regimes}.parquet
│       └── spot/{SYMBOL}/{4h_indicators,4h_regimes}.parquet
└── metadata/
    ├── raw/bitunix/{market}/{SYMBOL}_{timeframe}.json
    └── processed/bitunix/{market}/{SYMBOL}_{timeframe}_{indicators|regimes}.json

reports/
├── BTCUSDT_4h_futures_regime_report.md
├── ETHUSDT_4h_futures_regime_report.md
└── SOLUSDT_4h_futures_regime_report.md
```

The regimes parquet contains, per candle: `open..volume, quote_volume,
ema{fast}, ema{slow}, atr{period}, atr_pct, rsi{period}, adx{period}
(+DI/−DI), regime, trend_condition, volatility_condition,
range_condition, regime_reason, regime_flags`. Every processed artifact's
metadata records the raw dataset's content hash; loading analysis
artifacts whose provenance does not match the current raw data is refused.

## 14. Avoiding Lookahead Bias

- Indicator computations are strictly backward-looking (recursive
  smoothings with past-only seeds; volatility thresholds are rolling
  percentiles of **past** values only via `shift(1)`).
- No `shift(-1)`, no future close/high/low anywhere in the detector.
- `detect_regime(df[:k])` produces byte-identical labels for the first
  `k` candles as `detect_regime(df)` — asserted by a test.
- Warm-up bars are `UNCERTAIN`, never filled with fake values.
- Downloads never persist an in-progress candle; the trailing stored
  candle is refreshed on each re-download.

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
