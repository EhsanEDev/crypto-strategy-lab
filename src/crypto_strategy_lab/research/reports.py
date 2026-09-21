"""Research report generation (markdown) for regime datasets.

Reports are derived from already-validated artifacts; they never mutate
datasets and never generate signals.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..config import LabConfig, RegimeConfig, reports_dir
from ..data.validator import validate_ohlcv

logger = logging.getLogger(__name__)

REGIME_ORDER = ["TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOLATILITY", "UNCERTAIN"]


@dataclass
class RegimeStats:
    """Aggregated regime statistics for one dataset."""

    distribution: dict[str, float]
    counts: dict[str, int]
    transitions: dict[str, int]
    duration_median: dict[str, float]
    duration_max: dict[str, int]
    duration_mean: dict[str, float]


def compute_regime_stats(regimes: pd.DataFrame) -> RegimeStats:
    """Distribution, transitions and run-duration statistics."""
    counts = regimes["regime"].value_counts()
    total = int(len(regimes))
    distribution = {label: counts.get(label, 0) / total * 100.0 for label in REGIME_ORDER}
    count_map = {label: int(counts.get(label, 0)) for label in REGIME_ORDER}

    transitions: dict[str, int] = {}
    series = regimes["regime"].tolist()
    for prev, cur in zip(series[:-1], series[1:]):
        if prev != cur:
            key = f"{prev} -> {cur}"
            transitions[key] = transitions.get(key, 0) + 1

    durations: dict[str, list[int]] = {}
    run_length = 1
    for i in range(1, len(series)):
        if series[i] == series[i - 1]:
            run_length += 1
        else:
            durations.setdefault(series[i - 1], []).append(run_length)
            run_length = 1
    if series:
        durations.setdefault(series[-1], []).append(run_length)

    duration_median = {
        label: float(pd.Series(durations.get(label, [])).median()) if durations.get(label) else 0.0
        for label in REGIME_ORDER
    }
    duration_mean = {
        label: float(pd.Series(durations.get(label, [])).mean()) if durations.get(label) else 0.0
        for label in REGIME_ORDER
    }
    duration_max = {
        label: int(max(durations.get(label, [0]))) if durations.get(label) else 0
        for label in REGIME_ORDER
    }
    return RegimeStats(
        distribution=distribution,
        counts=count_map,
        transitions=transitions,
        duration_median=duration_median,
        duration_max=duration_max,
        duration_mean=duration_mean,
    )


def _fmt_pct(value: float) -> str:
    return f"{value:6.1f}%"


def build_report(
    symbol: str,
    timeframe: str,
    raw: pd.DataFrame,
    regimes: pd.DataFrame,
    config: RegimeConfig,
    stats: RegimeStats,
    regime_config_fingerprint: str | None = None,
) -> str:
    """Render the markdown report for one asset/timeframe."""
    validation = validate_ohlcv(raw, timeframe)
    ind_summary = _indicator_summary(regimes, config)
    lines: list[str] = []
    lines.append(f"# {symbol} — {timeframe} Regime Report")
    lines.append("")
    lines.append("Regime Detector v001 (rule-based hypothesis, no lookahead).")
    lines.append("")

    lines.append("## Dataset")
    lines.append("")
    lines.append(f"- Symbol: `{symbol}`")
    lines.append(f"- Timeframe: `{timeframe}`")
    lines.append(f"- Start: `{regimes.index.min()}`")
    lines.append(f"- End: `{regimes.index.max()}`")
    lines.append(f"- Rows: **{len(raw)}**")
    lines.append(f"- Missing candles (gaps): **{len(validation.gaps)}**")
    lines.append(f"- Duplicate candles: **{len(validation.duplicate_timestamps)}**")
    lines.append(
        f"- OHLC anomalies (exchange-reported inconsistencies): **{validation.ohlc_anomalies}**"
    )
    lines.append("")

    lines.append("## Indicator summary")
    lines.append("")
    lines.append("| Indicator | Defined | NaN (warm-up) | Mean | Min | Max |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for column, label in ind_summary:
        s = regimes[column]
        lines.append(
            f"| {label} | {int(s.notna().sum())} | {int(s.isna().sum())} "
            f"| {s.mean():.4f} | {s.min():.4f} | {s.max():.4f} |"
        )
    lines.append("")
    lines.append(
        "> Warm-up: EMA/ATR/RSI/ADX need history before their first defined value "
        "(EMA200 ≈ 199 bars, ADX ≈ 2×period−2 bars). Early NaNs are expected and never filled."
    )
    lines.append("")

    lines.append("## Regime distribution")
    lines.append("")
    lines.append("| Regime | Share | Candles |")
    lines.append("| --- | --- | --- |")
    for label in REGIME_ORDER:
        lines.append(f"| {label} | {_fmt_pct(stats.distribution[label])} | {stats.counts[label]} |")
    lines.append("")

    lines.append("## Regime transitions")
    lines.append("")
    if stats.transitions:
        lines.append("| Transition | Count |")
        lines.append("| --- | --- |")
        for key, count in sorted(stats.transitions.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {key} | {count} |")
    else:
        lines.append("_No transitions (single regime for the whole dataset)._")
    lines.append("")

    lines.append("## Regime duration (candles)")
    lines.append("")
    lines.append("| Regime | Median | Mean | Max |")
    lines.append("| --- | --- | --- | --- |")
    for label in REGIME_ORDER:
        lines.append(
            f"| {label} | {stats.duration_median[label]:.0f} "
            f"| {stats.duration_mean[label]:.1f} | {stats.duration_max[label]} |"
        )
    lines.append("")

    if regime_config_fingerprint:
        lines.append("## Reproducibility")
        lines.append("")
        lines.append(f"- regime config fingerprint: `{regime_config_fingerprint}`")
        lines.append("- thresholds live in `config/default.yaml` (section `regime`)")
        lines.append("")

    return "\n".join(lines)


def _indicator_summary(regimes: pd.DataFrame, config: RegimeConfig) -> list[tuple[str, str]]:
    return [
        (f"ema{config.ema_fast}", f"EMA{config.ema_fast}"),
        (f"ema{config.ema_slow}", f"EMA{config.ema_slow}"),
        ("atr_pct", f"ATR{config.atr_period} %"),
        (f"rsi{config.rsi_period}", f"RSI{config.rsi_period}"),
        (f"adx{config.adx_period}", f"ADX{config.adx_period}"),
    ]


def write_regime_report(
    config: LabConfig,
    symbol: str,
    timeframe: str,
    raw: pd.DataFrame,
    regimes: pd.DataFrame,
    regime_config: RegimeConfig | None = None,
    fingerprint: str | None = None,
) -> Path:
    """Render and write ``reports/{SYMBOL}_{timeframe}_regime_report.md``."""
    regime_config = regime_config or config.regime
    stats = compute_regime_stats(regimes)
    markdown = build_report(
        symbol=symbol.upper(),
        timeframe=timeframe,
        raw=raw,
        regimes=regimes,
        config=regime_config,
        stats=stats,
        regime_config_fingerprint=fingerprint,
    )
    path = reports_dir(config) / f"{symbol.upper()}_{timeframe}_regime_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    logger.info("Report written: %s", path)
    return path


def dump_stats_json(path: Path, stats: RegimeStats) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "distribution": stats.distribution,
                "counts": stats.counts,
                "transitions": stats.transitions,
                "duration_median": stats.duration_median,
                "duration_mean": stats.duration_mean,
                "duration_max": stats.duration_max,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
