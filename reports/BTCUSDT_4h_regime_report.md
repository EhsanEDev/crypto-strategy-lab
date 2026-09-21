# BTCUSDT — 4h Regime Report

Regime Detector v001 (rule-based hypothesis, no lookahead).

## Dataset

- Symbol: `BTCUSDT`
- Timeframe: `4h`
- Start: `2022-04-17 16:00:00+00:00`
- End: `2026-09-21 00:00:00+00:00`
- Rows: **9705**
- Missing candles (gaps): **0**
- Duplicate candles: **0**
- OHLC anomalies (exchange-reported inconsistencies): **29**

## Indicator summary

| Indicator | Defined | NaN (warm-up) | Mean | Min | Max |
| --- | --- | --- | --- | --- | --- |
| EMA50 | 9656 | 49 | 59789.1565 | 16450.9727 | 121048.3677 |
| EMA200 | 9506 | 199 | 59867.3856 | 16893.4762 | 116875.2523 |
| ATR14 % | 9692 | 13 | 1.4634 | 0.3961 | 5.4580 |
| RSI14 | 9691 | 14 | 50.8716 | 5.3569 | 94.3777 |
| ADX14 | 9679 | 26 | 28.3581 | 7.5173 | 74.0477 |

> Warm-up: EMA/ATR/RSI/ADX need history before their first defined value (EMA200 ≈ 199 bars, ADX ≈ 2×period−2 bars). Early NaNs are expected and never filled.

## Regime distribution

| Regime | Share | Candles |
| --- | --- | --- |
| TREND_UP |   21.5% | 2088 |
| TREND_DOWN |   17.4% | 1684 |
| RANGE |   26.6% | 2581 |
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
| TREND_UP | 10 | 16.1 | 82 |
| TREND_DOWN | 7 | 12.6 | 93 |
| RANGE | 10 | 14.8 | 73 |
| HIGH_VOLATILITY | 3 | 8.6 | 63 |
| UNCERTAIN | 6 | 10.3 | 199 |

## Reproducibility

- regime config fingerprint: `c2f45dc0350e`
- thresholds live in `config/default.yaml` (section `regime`)
