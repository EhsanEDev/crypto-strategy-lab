"""Parquet storage for raw candles, processed datasets and metadata.

Layout (Milestone 1)::

    data/
        raw/
            bitunix/
                BTCUSDT/1h.parquet, 4h.parquet, 1d.parquet
                ...
        processed/
            BTCUSDT/4h_indicators.parquet, 4h_regimes.parquet
            ...
        metadata/
            raw/{exchange}/{SYMBOL}_{timeframe}.json
            processed/{SYMBOL}_{timeframe}_{artifact}.json

Rules:

* Raw data is never overwritten destructively - new downloads are *merged*
  per timestamp. The only exception is a bounded trailing overlap
  (``refresh_tail_candles``) that is re-fetched and replaced on every
  download, so a previously stored not-yet-closed candle can never stick
  around with stale values.
* Writes are atomic: a uniquely-named temporary file (per-process UUID, so
  concurrent runs cannot collide) is written first, then ``os.replace``d
  onto the target. Remaining limitation (documented): the parquet file and
  its JSON metadata sidecar are two separate atomic writes, so a crash
  exactly between them can leave them momentarily out of sync; the next
  successful run rewrites both.
* Every artifact gets a JSON metadata sidecar for reproducibility, and
  processed artifacts record the content hash of the raw dataset they were
  generated from (freshness proof).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import SCHEMA_VERSION, LabConfig
from ..config import data_dir as cfg_data_dir
from .models import ALL_COLUMNS, raw_content_hash
from .validator import ValidationResult, is_research_ready, validate_ohlcv

CANDLES_POLICY = "closed-only"


class StorageError(RuntimeError):
    pass


def _require_valid(df: pd.DataFrame, timeframe: str) -> ValidationResult:
    result = validate_ohlcv(df, timeframe)
    if not result.is_valid:
        details = "; ".join(result.errors[:5])
        raise StorageError(f"refusing to store invalid data: {details}")
    return result


def raw_root(config: LabConfig, exchange: str, market: str = "futures") -> Path:
    """Raw storage root. The market segment keeps spot/futures candles in
    separate, correctly-labelled datasets (they are different instruments
    and must never be merged into one file)."""
    return cfg_data_dir(config) / "raw" / exchange / market


def processed_root(config: LabConfig) -> Path:
    return cfg_data_dir(config) / "processed"


def metadata_root(config: LabConfig) -> Path:
    return cfg_data_dir(config) / "metadata"


def raw_candles_path(
    config: LabConfig, exchange: str, market: str, symbol: str, timeframe: str
) -> Path:
    return raw_root(config, exchange, market) / symbol.upper() / f"{timeframe}.parquet"


def processed_indicators_path(config: LabConfig, symbol: str, timeframe: str) -> Path:
    return processed_root(config) / symbol.upper() / f"{timeframe}_indicators.parquet"


def processed_regimes_path(config: LabConfig, symbol: str, timeframe: str) -> Path:
    return processed_root(config) / symbol.upper() / f"{timeframe}_regimes.parquet"


def merge_raw_candles(
    existing: pd.DataFrame | None, new: pd.DataFrame, refresh_tail: int = 0
) -> pd.DataFrame:
    """Merge incremental candles into an existing dataset (idempotent).

    ``refresh_tail`` > 0 replaces the last ``refresh_tail`` stored candles
    with the newly downloaded values (only when the new data actually
    reaches the current tail), so a candle that was stored while still in
    progress gets corrected on the next download instead of sticking
    around via keep-first deduplication.
    """
    if existing is None or existing.empty:
        merged = new.copy()
    else:
        base = existing
        if refresh_tail > 0 and not new.empty and new.index.max() >= existing.index.max():
            base = existing.iloc[:-refresh_tail] if len(existing) > refresh_tail else existing.iloc[0:0]
        merged = pd.concat([base, new])
    if merged.empty:
        return merged
    merged = merged[~merged.index.duplicated(keep="first")].sort_index()
    return merged


def save_raw_candles(
    config: LabConfig,
    exchange: str,
    market: str,
    symbol: str,
    timeframe: str,
    new_df: pd.DataFrame,
    extra_metadata: dict[str, Any] | None = None,
    refresh_tail: int | None = None,
) -> tuple[pd.DataFrame, Path]:
    """Validate, merge and persist raw candles. Returns (merged_df, path)."""
    symbol = symbol.upper()
    if new_df.empty:
        raise StorageError("refusing to store empty dataset")
    if refresh_tail is None:
        refresh_tail = config.exchange.refresh_tail_candles
    existing = load_raw_candles(config, exchange, market, symbol, timeframe)

    merged = merge_raw_candles(existing, new_df, refresh_tail=refresh_tail)
    ordered = [c for c in ALL_COLUMNS if c in merged.columns]
    merged = merged[ordered]

    result = _require_valid(merged, timeframe)
    path = raw_candles_path(config, exchange, market, symbol, timeframe)
    write_parquet_atomic(merged, path)

    metadata = {
        "exchange": exchange,
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "start": str(merged.index.min()),
        "end": str(merged.index.max()),
        "rows": int(len(merged)),
        "gaps": len(result.gaps),
        "ohlc_anomalies": result.ohlc_anomalies,
        "research_ready": is_research_ready(merged, timeframe),
        "candles_policy": CANDLES_POLICY,
        "refresh_tail_candles": refresh_tail,
        "raw_content_hash": raw_content_hash(merged),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    write_metadata(
        metadata_root(config) / "raw" / exchange / market / f"{symbol}_{timeframe}.json",
        metadata,
    )
    return merged, path


def load_raw_candles(
    config: LabConfig, exchange: str, market: str, symbol: str, timeframe: str
) -> pd.DataFrame | None:
    path = raw_candles_path(config, exchange, market, symbol, timeframe)
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    return df


def save_processed(
    config: LabConfig,
    artifact: str,  # "indicators" | "regimes"
    symbol: str,
    timeframe: str,
    df: pd.DataFrame,
    raw_df: pd.DataFrame,
    extra_metadata: dict[str, Any] | None = None,
) -> Path:
    """Persist a processed artifact with full provenance metadata."""
    from .. import __version__

    symbol = symbol.upper()
    if artifact == "indicators":
        path = processed_indicators_path(config, symbol, timeframe)
    elif artifact == "regimes":
        path = processed_regimes_path(config, symbol, timeframe)
    else:
        raise StorageError(f"unknown artifact {artifact!r}")
    if df.empty:
        raise StorageError("refusing to store empty processed dataset")

    write_parquet_atomic(df, path)
    metadata = {
        "artifact": artifact,
        "symbol": symbol,
        "timeframe": timeframe,
        "start": str(df.index.min()),
        "end": str(df.index.max()),
        "rows": int(len(df)),
        "columns": list(df.columns),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "code_version": __version__,
        # provenance / freshness proof
        "source": {
            "exchange": "bitunix",
            "raw_content_hash": raw_content_hash(raw_df),
            "raw_rows": int(len(raw_df)),
            "raw_start": str(raw_df.index.min()),
            "raw_end": str(raw_df.index.max()),
            "raw_schema_version": SCHEMA_VERSION,
        },
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    write_metadata(
        metadata_root(config) / "processed" / f"{symbol}_{timeframe}_{artifact}.json", metadata
    )
    return path


def load_processed(
    config: LabConfig, artifact: str, symbol: str, timeframe: str
) -> pd.DataFrame | None:
    if artifact == "indicators":
        path = processed_indicators_path(config, symbol, timeframe)
    elif artifact == "regimes":
        path = processed_regimes_path(config, symbol, timeframe)
    else:
        raise StorageError(f"unknown artifact {artifact!r}")
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    return df


def load_processed_metadata(
    config: LabConfig, artifact: str, symbol: str, timeframe: str
) -> dict[str, Any] | None:
    return read_metadata(
        metadata_root(config) / "processed" / f"{symbol.upper()}_{timeframe}_{artifact}.json"
    )


def load_raw_metadata(
    config: LabConfig, exchange: str, market: str, symbol: str, timeframe: str
) -> dict[str, Any] | None:
    return read_metadata(
        metadata_root(config)
        / "raw" / exchange / market / f"{symbol.upper()}_{timeframe}.json"
    )


@dataclass
class FreshnessStatus:
    """Whether a processed artifact matches the current raw dataset."""

    fresh: bool
    reasons: list[str]
    artifact_raw_hash: str | None = None
    current_raw_hash: str | None = None
    artifact_config_fingerprint: str | None = None
    current_config_fingerprint: str | None = None

    def describe(self) -> str:
        if self.fresh:
            return "fresh"
        return "stale: " + "; ".join(self.reasons)


def check_freshness(
    config: LabConfig,
    artifact: str,
    symbol: str,
    timeframe: str,
    raw_df: pd.DataFrame,
    config_fingerprint: str | None = None,
) -> FreshnessStatus:
    """Compare a processed artifact's provenance against the current raw data."""
    metadata = load_processed_metadata(config, artifact, symbol, timeframe)
    if metadata is None:
        return FreshnessStatus(fresh=False, reasons=[f"no {artifact} metadata found"])
    source = metadata.get("source") or {}
    artifact_hash = source.get("raw_content_hash")
    current_hash = raw_content_hash(raw_df)
    reasons: list[str] = []
    if artifact_hash != current_hash:
        reasons.append("raw dataset changed since the artifact was generated")
    artifact_fp = metadata.get("regime_config_fingerprint")
    if config_fingerprint is not None and artifact_fp != config_fingerprint:
        reasons.append("regime configuration changed since the artifact was generated")
    return FreshnessStatus(
        fresh=not reasons,
        reasons=reasons,
        artifact_raw_hash=artifact_hash,
        current_raw_hash=current_hash,
        artifact_config_fingerprint=artifact_fp,
        current_config_fingerprint=config_fingerprint,
    )


def write_parquet_atomic(df: pd.DataFrame, path: Path) -> None:
    """Atomic write via a uniquely-named temp file + os.replace.

    The UUID suffix makes concurrent writers collision-free; os.replace is
    atomic on POSIX, so readers never see a partially written parquet.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
    try:
        df.to_parquet(tmp_path, index=True)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def read_metadata(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def config_fingerprint(config: dict[str, Any]) -> str:
    """Stable hash of a config dict - used to tag processed artifacts."""
    payload = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]
