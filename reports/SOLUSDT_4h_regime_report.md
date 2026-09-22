# SOLUSDT — 4h Regime Report

Regime Detector v001 (rule-based hypothesis, no lookahead).

## Dataset

- Symbol: `SOLUSDT`
- Timeframe: `4h`
- Start: `2022-04-17 16:00:00+00:00`
- End: `2026-09-21 16:00:00+00:00`
- Rows: **9709**
- Missing candles (gaps): **0**
- Duplicate candles: **0**
- OHLC anomalies (exchange-reported inconsistencies): **77**
- Misaligned timestamps: **0** | NaN/infinite values: **0**

## Data quality
- Quality gate: **NOT READY (strict validation failed: gaps/OHLC anomalies/misalignment)**
- Candle policy: **closed-only** — in-progress candles are never persisted as history; the last stored candle is refreshed (replaced) on re-download if the exchange revised it.
- OHLC anomalies are kept as received (audit trail), never silently repaired; strict validation refuses them for research use.

## Provenance & freshness

- Exchange: `bitunix` | market: `futures`
- Raw range: `2022-04-17 16:00:00+00:00` → `2026-09-21 16:00:00+00:00` (9709 candles)
- Raw content hash: `6d54d38b7f4b85d6…`
- Regime config fingerprint: `c2f45dc0350e`
- Generated at: `2026-09-22T04:06:20.587013+00:00` (code v0.1.0, schema v1.0)
- Artifact freshness: **fresh**

## Indicator summary

| Indicator | Defined | NaN (warm-up) | Mean | Min | Max |
| --- | --- | --- | --- | --- | --- |
| EMA50 | 9660 | 49 | 100.6280 | 10.3378 | 247.7356 |
| EMA200 | 9510 | 199 | 100.8734 | 12.5558 | 226.2890 |
| ATR14 % | 9695 | 14 | 2.8528 | 0.7495 | 28.0172 |
| RSI14 | 9695 | 14 | 50.0359 | 12.2439 | 91.5406 |
| ADX14 | 9682 | 27 | 27.7493 | 8.0686 | 72.0489 |

> Warm-up (TA-Lib-compatible conventions): EMA slow needs `ema_slow - 1` bars, ADX needs `2*period - 1` bars (first ADX at bar 27 for period 14), RSI/ATR need `period` bars. Early NaNs are expected and never filled.

## Regime distribution

| Regime | Share | Candles |
| --- | --- | --- |
| TREND_UP |   18.1% | 1758 |
| TREND_DOWN |   20.8% | 2023 |
| RANGE |   26.3% | 2551 |
| HIGH_VOLATILITY |   10.9% | 1055 |
| UNCERTAIN |   23.9% | 2322 |

## Regime transitions

| Transition | Count |
| --- | --- |
| RANGE -> UNCERTAIN | 85 |
| UNCERTAIN -> RANGE | 79 |
| UNCERTAIN -> TREND_UP | 59 |
| UNCERTAIN -> TREND_DOWN | 54 |
| TREND_UP -> UNCERTAIN | 49 |
| TREND_DOWN -> UNCERTAIN | 48 |
| HIGH_VOLATILITY -> UNCERTAIN | 43 |
| TREND_DOWN -> RANGE | 41 |
| TREND_DOWN -> HIGH_VOLATILITY | 39 |
| HIGH_VOLATILITY -> TREND_DOWN | 38 |
| TREND_UP -> HIGH_VOLATILITY | 38 |
| RANGE -> TREND_DOWN | 36 |
| UNCERTAIN -> HIGH_VOLATILITY | 34 |
| HIGH_VOLATILITY -> TREND_UP | 33 |
| TREND_UP -> RANGE | 30 |
| RANGE -> TREND_UP | 26 |
| RANGE -> HIGH_VOLATILITY | 3 |

## Regime duration (candles)

| Regime | Median | Mean | Max |
| --- | --- | --- | --- |
| TREND_UP | 7 | 14.9 | 69 |
| TREND_DOWN | 8 | 15.8 | 78 |
| RANGE | 12 | 17.0 | 87 |
| HIGH_VOLATILITY | 4 | 9.3 | 58 |
| UNCERTAIN | 6 | 10.3 | 199 |

## Reproducibility

- regime config fingerprint: `c2f45dc0350e`
- thresholds live in `config/default.yaml` (section `regime`)
- regenerate: `python -m crypto_strategy_lab regime --symbol SOLUSDT --timeframe 4h`
