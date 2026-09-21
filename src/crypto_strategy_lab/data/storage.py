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
  with existing rows (new timestamps appended, duplicates keep the existing
  row) and deduplicated before the atomic write.
* Every artifact gets a JSON metadata sidecar for reproducibility.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import SCHEMA_VERSION, LabConfig
from ..config import data_dir as cfg_data_dir
from .models import ALL_COLUMNS
from .validator import ValidationResult, validate_ohlcv


class StorageError(RuntimeError):
    pass


def _require_valid(df: pd.DataFrame, timeframe: str) -> ValidationResult:
    result = validate_ohlcv(df, timeframe)
    if not result.is_valid:
        details = "; ".join(result.errors[:5])
        raise StorageError(f"refusing to store invalid data: {details}")
    return result


def raw_root(config: LabConfig, exchange: str) -> Path:
    return cfg_data_dir(config) / "raw" / exchange


def processed_root(config: LabConfig) -> Path:
    return cfg_data_dir(config) / "processed"


def metadata_root(config: LabConfig) -> Path:
    return cfg_data_dir(config) / "metadata"


def raw_candles_path(config: LabConfig, exchange: str, symbol: str, timeframe: str) -> Path:
    return raw_root(config, exchange) / symbol.upper() / f"{timeframe}.parquet"


def processed_indicators_path(config: LabConfig, symbol: str, timeframe: str) -> Path:
    return processed_root(config) / symbol.upper() / f"{timeframe}_indicators.parquet"


def processed_regimes_path(config: LabConfig, symbol: str, timeframe: str) -> Path:
    return processed_root(config) / symbol.upper() / f"{timeframe}_regimes.parquet"


def merge_raw_candles(
    existing: pd.DataFrame | None, new: pd.DataFrame
) -> pd.DataFrame:
    """Merge incremental candles into an existing dataset (idempotent)."""
    if existing is None or existing.empty:
        merged = new.copy()
    else:
        merged = pd.concat([existing, new])
    if merged.empty:
        return merged
    merged = merged[~merged.index.duplicated(keep="first")].sort_index()
    return merged


def save_raw_candles(
    config: LabConfig,
    exchange: str,
    symbol: str,
    timeframe: str,
    new_df: pd.DataFrame,
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, Path]:
    """Validate, merge and persist raw candles. Returns (merged_df, path)."""
    symbol = symbol.upper()
    if new_df.empty:
        raise StorageError("refusing to store empty dataset")
    existing = load_raw_candles(config, exchange, symbol, timeframe)

    merged = merge_raw_candles(existing, new_df)
    ordered = [c for c in ALL_COLUMNS if c in merged.columns]
    merged = merged[ordered]

    result = _require_valid(merged, timeframe)
    path = raw_candles_path(config, exchange, symbol, timeframe)
    write_parquet_atomic(merged, path)

    metadata = {
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "start": str(merged.index.min()),
        "end": str(merged.index.max()),
        "rows": int(len(merged)),
        "gaps": len(result.gaps),
        "ohlc_anomalies": result.ohlc_anomalies,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    write_metadata(
        metadata_root(config) / "raw" / exchange / f"{symbol}_{timeframe}.json", metadata
    )
    return merged, path


def load_raw_candles(
    config: LabConfig, exchange: str, symbol: str, timeframe: str
) -> pd.DataFrame | None:
    path = raw_candles_path(config, exchange, symbol, timeframe)
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
    extra_metadata: dict[str, Any] | None = None,
) -> Path:
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
        "symbol": symbol,
        "timeframe": timeframe,
        "artifact": artifact,
        "start": str(df.index.min()),
        "end": str(df.index.max()),
        "rows": int(len(df)),
        "columns": list(df.columns),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "source_rows_sha256": None,
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


def write_parquet_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp_path, index=True)
    tmp_path.replace(path)


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    tmp_path.replace(path)


def read_metadata(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def config_fingerprint(config: dict[str, Any]) -> str:
    """Stable hash of a config dict - used to tag processed artifacts."""
    payload = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]
