"""Research artifacts: reports and aggregated statistics."""

from .reports import (
    RegimeStats,
    build_report,
    compute_regime_stats,
    dump_stats_json,
    write_regime_report,
)

__all__ = [
    "RegimeStats",
    "build_report",
    "compute_regime_stats",
    "dump_stats_json",
    "write_regime_report",
]
