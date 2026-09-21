# ETHUSDT — 4h Regime Report

Regime Detector v001 (rule-based hypothesis, no lookahead).

## Dataset

- Symbol: `ETHUSDT`
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
| EMA50 | 9656 | 49 | 2391.2925 | 1096.8064 | 4533.3665 |
| EMA200 | 9506 | 199 | 2390.9448 | 1227.6481 | 4392.4890 |
| ATR14 % | 9692 | 13 | 1.9911 | 0.3839 | 7.9844 |
| RSI14 | 9691 | 14 | 50.3913 | 6.1027 | 96.2053 |
| ADX14 | 9679 | 26 | 27.8186 | 7.8314 | 73.0014 |

> Warm-up: EMA/ATR/RSI/ADX need history before their first defined value (EMA200 ≈ 199 bars, ADX ≈ 2×period−2 bars). Early NaNs are expected and never filled.

## Regime distribution

| Regime | Share | Candles |
| --- | --- | --- |
| TREND_UP |   18.9% | 1837 |
| TREND_DOWN |   19.4% | 1885 |
| RANGE |   30.0% | 2907 |
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
| TREND_UP | 9 | 13.8 | 75 |
| TREND_DOWN | 9 | 14.4 | 85 |
| RANGE | 10 | 15.0 | 88 |
| HIGH_VOLATILITY | 4 | 8.4 | 57 |
| UNCERTAIN | 5 | 9.1 | 199 |

## Reproducibility

- regime config fingerprint: `c2f45dc0350e`
- thresholds live in `config/default.yaml` (section `regime`)
