# BTCUSDT — 4h Regime Report

Regime Detector v001 (rule-based hypothesis, no lookahead).

## Dataset

- Symbol: `BTCUSDT`
- Timeframe: `4h`
- Start: `2022-04-17 16:00:00+00:00`
- End: `2026-09-24 00:00:00+00:00`
- Rows: **9723**
- Missing candles (gaps): **0**
- Duplicate candles: **0**
- OHLC anomalies (exchange-reported inconsistencies): **29**
- Misaligned timestamps: **0** | NaN/infinite values: **0**

## Data quality
- Quality gate: **NOT READY (strict validation failed: gaps/OHLC anomalies/misalignment)**
- Candle policy: **closed-only** — in-progress candles are never persisted as history; the last stored candle is refreshed (replaced) on re-download if the exchange revised it.
- OHLC anomalies are kept as received (audit trail), never silently repaired; strict validation refuses them for research use.

## Provenance & freshness

- Exchange: `bitunix` | market: **`futures`**
- Raw range: `2022-04-17 16:00:00+00:00` → `2026-09-24 00:00:00+00:00` (9723 candles)
- Raw content hash: `71f90165711108ec…`
- Regime config fingerprint: `c2f45dc0350e`
- Generated at: `2026-09-24T06:13:02.894585+00:00` (code v0.1.0, schema v1.0)
- Artifact freshness: **fresh**

## Indicator summary

| Indicator | Defined | NaN (warm-up) | Mean | Min | Max |
| --- | --- | --- | --- | --- | --- |
| EMA50 | 9674 | 49 | 59828.4811 | 16450.9727 | 121048.3677 |
| EMA200 | 9524 | 199 | 59899.9873 | 16893.4762 | 116875.2523 |
| ATR14 % | 9709 | 14 | 1.4629 | 0.3961 | 5.4580 |
| RSI14 | 9709 | 14 | 50.9097 | 5.3569 | 94.3777 |
| ADX14 | 9696 | 27 | 28.3912 | 7.5173 | 74.0477 |

> Warm-up (TA-Lib-compatible conventions): EMA slow needs `ema_slow - 1` bars, ADX needs `2*period - 1` bars (first ADX at bar 27 for period 14), RSI/ATR need `period` bars. Early NaNs are expected and never filled.

## Regime distribution

| Regime | Share | Candles |
| --- | --- | --- |
| TREND_UP |   21.7% | 2106 |
| TREND_DOWN |   17.3% | 1684 |
| RANGE |   26.5% | 2581 |
| HIGH_VOLATILITY |   10.9% | 1058 |
| UNCERTAIN |   23.6% | 2294 |

## Regime transitions

| Transition | Count |
| --- | --- |
| RANGE -> UNCERTAIN | 99 |
| UNCERTAIN -> RANGE | 84 |
| UNCERTAIN -> TREND_UP | 53 |
| UNCERTAIN -> TREND_DOWN | 51 |
| TREND_UP -> RANGE | 50 |
| HIGH_VOLATILITY -> TREND_DOWN | 49 |
| TREND_DOWN -> UNCERTAIN | 48 |
| TREND_DOWN -> HIGH_VOLATILITY | 46 |
| TREND_DOWN -> RANGE | 40 |
| TREND_UP -> HIGH_VOLATILITY | 40 |
| TREND_UP -> UNCERTAIN | 39 |
| HIGH_VOLATILITY -> TREND_UP | 39 |
| RANGE -> TREND_UP | 38 |
| HIGH_VOLATILITY -> UNCERTAIN | 35 |
| RANGE -> TREND_DOWN | 34 |
| UNCERTAIN -> HIGH_VOLATILITY | 34 |
| RANGE -> HIGH_VOLATILITY | 3 |

## Regime duration (candles)

| Regime | Median | Mean | Max |
| --- | --- | --- | --- |
| TREND_UP | 10 | 16.2 | 82 |
| TREND_DOWN | 7 | 12.6 | 93 |
| RANGE | 10 | 14.8 | 73 |
| HIGH_VOLATILITY | 3 | 8.6 | 63 |
| UNCERTAIN | 6 | 10.3 | 199 |

## Reproducibility

- regime config fingerprint: `c2f45dc0350e`
- thresholds live in `config/default.yaml` (section `regime`)
- regenerate: `python -m crypto_research regime --symbol BTCUSDT --timeframe 4h`
