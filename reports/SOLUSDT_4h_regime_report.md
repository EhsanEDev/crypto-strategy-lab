# SOLUSDT — 4h Regime Report

Regime Detector v001 (rule-based hypothesis, no lookahead).

## Dataset

- Symbol: `SOLUSDT`
- Timeframe: `4h`
- Start: `2022-04-17 16:00:00+00:00`
- End: `2026-09-21 00:00:00+00:00`
- Rows: **9705**
- Missing candles (gaps): **0**
- Duplicate candles: **0**
- OHLC anomalies (exchange-reported inconsistencies): **77**

## Indicator summary

| Indicator | Defined | NaN (warm-up) | Mean | Min | Max |
| --- | --- | --- | --- | --- | --- |
| EMA50 | 9656 | 49 | 100.6255 | 10.3378 | 247.7356 |
| EMA200 | 9506 | 199 | 100.8740 | 12.5558 | 226.2890 |
| ATR14 % | 9692 | 13 | 2.8532 | 0.7495 | 28.0172 |
| RSI14 | 9691 | 14 | 50.0256 | 12.2439 | 91.5406 |
| ADX14 | 9679 | 26 | 27.7458 | 8.0686 | 72.0489 |

> Warm-up: EMA/ATR/RSI/ADX need history before their first defined value (EMA200 ≈ 199 bars, ADX ≈ 2×period−2 bars). Early NaNs are expected and never filled.

## Regime distribution

| Regime | Share | Candles |
| --- | --- | --- |
| TREND_UP |   18.1% | 1754 |
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
