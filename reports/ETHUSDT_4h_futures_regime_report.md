# ETHUSDT — 4h Regime Report

Regime Detector v001 (rule-based hypothesis, no lookahead).

## Dataset

- Symbol: `ETHUSDT`
- Timeframe: `4h`
- Start: `2022-04-17 16:00:00+00:00`
- End: `2026-09-22 08:00:00+00:00`
- Rows: **9713**
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
- Raw range: `2022-04-17 16:00:00+00:00` → `2026-09-22 08:00:00+00:00` (9713 candles)
- Raw content hash: `61c0c2efb7a288ae…`
- Regime config fingerprint: `c2f45dc0350e`
- Generated at: `2026-09-22T15:27:52.492992+00:00` (code v0.1.0, schema v1.0)
- Artifact freshness: **fresh**

## Indicator summary

| Indicator | Defined | NaN (warm-up) | Mean | Min | Max |
| --- | --- | --- | --- | --- | --- |
| EMA50 | 9664 | 49 | 2391.4401 | 1096.8064 | 4533.3665 |
| EMA200 | 9514 | 199 | 2390.9683 | 1227.6481 | 4392.4890 |
| ATR14 % | 9699 | 14 | 1.9908 | 0.3839 | 7.9844 |
| RSI14 | 9699 | 14 | 50.4098 | 6.1027 | 96.2053 |
| ADX14 | 9686 | 27 | 27.8308 | 7.8314 | 73.0014 |

> Warm-up (TA-Lib-compatible conventions): EMA slow needs `ema_slow - 1` bars, ADX needs `2*period - 1` bars (first ADX at bar 27 for period 14), RSI/ATR need `period` bars. Early NaNs are expected and never filled.

## Regime distribution

| Regime | Share | Candles |
| --- | --- | --- |
| TREND_UP |   19.0% | 1845 |
| TREND_DOWN |   19.4% | 1885 |
| RANGE |   29.9% | 2907 |
| HIGH_VOLATILITY |   10.5% | 1016 |
| UNCERTAIN |   21.2% | 2060 |

## Regime transitions

| Transition | Count |
| --- | --- |
| RANGE -> UNCERTAIN | 100 |
| UNCERTAIN -> RANGE | 96 |
| UNCERTAIN -> TREND_UP | 55 |
| TREND_DOWN -> RANGE | 50 |
| TREND_UP -> RANGE | 46 |
| HIGH_VOLATILITY -> TREND_DOWN | 45 |
| TREND_UP -> UNCERTAIN | 45 |
| RANGE -> TREND_DOWN | 44 |
| TREND_DOWN -> UNCERTAIN | 43 |
| UNCERTAIN -> TREND_DOWN | 42 |
| TREND_UP -> HIGH_VOLATILITY | 41 |
| RANGE -> TREND_UP | 41 |
| TREND_DOWN -> HIGH_VOLATILITY | 38 |
| HIGH_VOLATILITY -> UNCERTAIN | 37 |
| HIGH_VOLATILITY -> TREND_UP | 37 |
| UNCERTAIN -> HIGH_VOLATILITY | 33 |
| RANGE -> HIGH_VOLATILITY | 9 |
| HIGH_VOLATILITY -> RANGE | 2 |

## Regime duration (candles)

| Regime | Median | Mean | Max |
| --- | --- | --- | --- |
| TREND_UP | 9 | 13.9 | 75 |
| TREND_DOWN | 9 | 14.4 | 85 |
| RANGE | 10 | 15.0 | 88 |
| HIGH_VOLATILITY | 4 | 8.4 | 57 |
| UNCERTAIN | 5 | 9.1 | 199 |

## Reproducibility

- regime config fingerprint: `c2f45dc0350e`
- thresholds live in `config/default.yaml` (section `regime`)
- regenerate: `python -m crypto_strategy_lab regime --symbol ETHUSDT --timeframe 4h`
