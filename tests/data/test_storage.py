"""Storage tests: merge semantics, atomic writes, metadata sidecars."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.config import LabConfig
from crypto_strategy_lab.data.storage import (
    StorageError,
    load_processed,
    load_raw_candles,
    merge_raw_candles,
    read_metadata,
    save_processed,
    save_raw_candles,
)
from tests.helpers import log_walk, make_ohlcv


@pytest.fixture
def config(tmp_path) -> LabConfig:
    return LabConfig(data_dir=tmp_path / "data", reports_dir=tmp_path / "reports")


def make_df(n: int = 300, seed: int = 5) -> pd.DataFrame:
    close = log_walk(n, 0.0, 0.01, seed=seed)
    return make_ohlcv(close, seed=seed)


def test_save_and_load_raw_roundtrip(config: LabConfig) -> None:
    df = make_df()
    _, path = save_raw_candles(config, "bitunix", "BTCUSDT", "4h", df)
    assert path.name == "4h.parquet"
    loaded = load_raw_candles(config, "bitunix", "BTCUSDT", "4h")
    assert loaded is not None and loaded.equals(df)


def test_save_raw_writes_metadata(config: LabConfig) -> None:
    df = make_df()
    _, path = save_raw_candles(
        config, "bitunix", "BTCUSDT", "4h", df, extra_metadata={"market": "futures"}
    )
    meta_path = config.data_dir / "metadata" / "raw" / "bitunix" / "BTCUSDT_4h.json"
    metadata = read_metadata(meta_path)
    assert metadata is not None
    assert metadata["exchange"] == "bitunix"
    assert metadata["symbol"] == "BTCUSDT"
    assert metadata["timeframe"] == "4h"
    assert metadata["market"] == "futures"
    assert metadata["rows"] == len(df)
    assert metadata["schema_version"] == "1.0"
    assert metadata["start"] == str(df.index.min())
    assert metadata["end"] == str(df.index.max())
    json.loads(meta_path.read_text())  # valid JSON


def test_incremental_save_merges_and_deduplicates(config: LabConfig) -> None:
    df = make_df()
    save_raw_candles(config, "bitunix", "ETHUSDT", "4h", df)

    # "new" download overlaps existing rows and extends by 10 newer candles
    newer = df.tail(10).copy()
    newer.index = newer.index + pd.Timedelta(days=100)
    newer = newer * 0.5  # different values; OHLC relations stay valid

    merged, _ = save_raw_candles(config, "bitunix", "ETHUSDT", "4h", newer)
    assert len(merged) == len(df) + 10
    # existing rows were kept (raw data never overwritten destructively)
    assert merged["close"].iloc[-11] == df["close"].iloc[-1]
    assert merged.index.is_unique and merged.index.is_monotonic_increasing
    assert not np.allclose(merged["close"].iloc[-1], df["close"].iloc[-1])


def test_save_raw_tolerates_ohlc_anomalies_but_records_them(config: LabConfig) -> None:
    df = make_df()
    df.loc[df.index[10], "high"] = df.loc[df.index[10], "low"] - 1  # high < low
    merged, _ = save_raw_candles(config, "bitunix", "BTCUSDT", "4h", df)
    assert len(merged) == len(df)
    metadata = read_metadata(config.data_dir / "metadata" / "raw" / "bitunix" / "BTCUSDT_4h.json")
    assert metadata["ohlc_anomalies"] >= 1


def test_save_raw_deduplicates_download_payload_idempotently(config: LabConfig) -> None:
    # re-downloading an overlapping range must be idempotent: duplicate rows
    # collapse onto the existing dataset (first wins) instead of corrupting it.
    df = make_df()
    duplicated = pd.concat([df, df.iloc[[5]]]).sort_index()
    merged, _ = save_raw_candles(config, "bitunix", "BTCUSDT", "4h", duplicated)
    assert len(merged) == len(df)
    assert merged.index.is_unique


def test_save_raw_rejects_empty(config: LabConfig) -> None:
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    with pytest.raises(StorageError, match="empty"):
        save_raw_candles(config, "bitunix", "BTCUSDT", "4h", empty)


def test_merge_raw_candles_handles_none_and_gaps() -> None:
    df = make_df(10)
    assert merge_raw_candles(None, df).equals(df)
    later = df.copy()
    later.index = later.index + pd.Timedelta(days=5)
    merged = merge_raw_candles(df, later)
    assert len(merged) == 20
    assert merged.index.is_monotonic_increasing


def test_save_and_load_processed(config: LabConfig) -> None:
    df = make_df()
    df["regime"] = "RANGE"
    path = save_processed(config, "regimes", "SOLUSDT", "4h", df, extra_metadata={"regime_config_fingerprint": "abc"})
    assert path.name == "4h_regimes.parquet"
    loaded = load_processed(config, "regimes", "SOLUSDT", "4h")
    assert loaded is not None and len(loaded) == len(df)
    assert loaded["regime"].eq("RANGE").all()

    metadata = read_metadata(
        config.data_dir / "metadata" / "processed" / "SOLUSDT_4h_regimes.json"
    )
    assert metadata["artifact"] == "regimes"
    assert metadata["regime_config_fingerprint"] == "abc"


def test_load_missing_returns_none(config: LabConfig) -> None:
    assert load_raw_candles(config, "bitunix", "BTCUSDT", "4h") is None
    assert load_processed(config, "regimes", "BTCUSDT", "4h") is None
