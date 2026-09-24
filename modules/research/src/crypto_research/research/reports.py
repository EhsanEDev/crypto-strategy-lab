"""Research report generation (markdown) for regime datasets.

Reports are derived from already-validated artifacts; they never mutate
datasets and never generate signals. Each report carries full provenance
(source, raw content hash, config fingerprint), data-quality status and
the closed-candle policy, so a report can always be audited against the
exact raw data it was produced from.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import LabConfig, RegimeConfig, reports_dir
from ..data.storage import FreshnessStatus, load_raw_metadata
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
    raw_metadata: dict[str, Any] | None = None,
    regimes_metadata: dict[str, Any] | None = None,
    freshness: FreshnessStatus | None = None,
    regime_config_fingerprint: str | None = None,
    market: str | None = None,
) -> str:
    """Render the markdown report for one asset/timeframe.

    ``market`` is the exact market of the raw/processed artifacts backing
    this report; it is displayed as-is (no defaults) and cross-checked
    against artifact metadata when present.
    """
    validation = validate_ohlcv(raw, timeframe)
    ind_summary = _indicator_summary(regimes, config)
    raw_metadata = raw_metadata or {}
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
    lines.append(
        f"- Misaligned timestamps: **{validation.misaligned_timestamps}**"
        f" | NaN/infinite values: **{validation.non_finite_values}**"
    )
    lines.append("")

    lines.append("## Data quality")
    lines.append(f"- Quality gate: **{_quality_label(raw_metadata, freshness)}**")
    lines.append("- Candle policy: **closed-only** — in-progress candles are never "
                 "persisted as history; the last stored candle is refreshed "
                 "(replaced) on re-download if the exchange revised it.")
    lines.append(
        "- OHLC anomalies are kept as received (audit trail), never silently "
        "repaired; strict validation refuses them for research use."
    )
    lines.append("")

    lines.append("## Provenance & freshness")
    lines.append("")
    exchange = raw_metadata.get("exchange", (regimes_metadata or {}).get("exchange", "bitunix"))
    resolved_market = market or raw_metadata.get("market") or (regimes_metadata or {}).get("market")
    if resolved_market is None:
        resolved_market = "unverified"  # never guess a market
    lines.append(f"- Exchange: `{exchange}` | market: **`{resolved_market}`**")
    lines.append(f"- Raw range: `{raw_metadata.get('start', '?')}` → `{raw_metadata.get('end', '?')}` "
                 f"({raw_metadata.get('rows', '?')} candles)")
    lines.append(f"- Raw content hash: `{raw_metadata.get('raw_content_hash', 'n/a')[:16]}…`")
    artifact_fp = (regimes_metadata or {}).get("regime_config_fingerprint", regime_config_fingerprint)
    lines.append(f"- Regime config fingerprint: `{artifact_fp}`")
    lines.append(f"- Generated at: `{(regimes_metadata or {}).get('generated_at', 'n/a')}` "
                 f"(code v{(regimes_metadata or {}).get('code_version', '?')}, "
                 f"schema v{(regimes_metadata or {}).get('schema_version', '?')})")
    lines.append(
        f"- Artifact freshness: **{'fresh' if (freshness and freshness.fresh) else 'stale/unverifiable'}**"
        + (f" ({'; '.join(freshness.reasons)})" if freshness and not freshness.fresh else "")
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
        "> Warm-up (TA-Lib-compatible conventions): EMA slow needs `ema_slow - 1` bars, "
        "ADX needs `2*period - 1` bars (first ADX at bar 27 for period 14), RSI/ATR need "
        "`period` bars. Early NaNs are expected and never filled."
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

    lines.append("## Reproducibility")
    lines.append("")
    lines.append(f"- regime config fingerprint: `{regime_config_fingerprint}`")
    lines.append("- thresholds live in `config/default.yaml` (section `regime`)")
    lines.append("- regenerate: `python -m crypto_research regime --symbol "
                 f"{symbol} --timeframe {timeframe}`")
    lines.append("")

    return "\n".join(lines)


def _quality_label(raw_metadata: dict[str, Any], freshness: FreshnessStatus | None) -> str:
    if raw_metadata.get("research_ready") is True:
        return "READY (strict validation passed)"
    label = "NOT READY (strict validation failed: gaps/OHLC anomalies/misalignment)"
    if freshness is not None and not freshness.fresh:
        label += "; artifact freshness: stale"
    return label


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
    market: str,
    regime_config: RegimeConfig | None = None,
    fingerprint: str | None = None,
    raw_metadata: dict[str, Any] | None = None,
    regimes_metadata: dict[str, Any] | None = None,
    freshness: FreshnessStatus | None = None,
) -> Path:
    """Render and write ``reports/{SYMBOL}_{timeframe}_{market}_regime_report.md``."""
    regime_config = regime_config or config.regime
    stats = compute_regime_stats(regimes)
    if raw_metadata is None:
        raw_metadata = load_raw_metadata(config, "bitunix", market, symbol, timeframe) or {}
    markdown = build_report(
        symbol=symbol.upper(),
        timeframe=timeframe,
        raw=raw,
        regimes=regimes,
        config=regime_config,
        stats=stats,
        raw_metadata=raw_metadata,
        regimes_metadata=regimes_metadata,
        freshness=freshness,
        regime_config_fingerprint=fingerprint,
        market=market,
    )
    path = reports_dir(config) / f"{symbol.upper()}_{timeframe}_{market}_regime_report.md"
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
