"""crypto-research: research module of crypto-trading-system.

Milestone 1 scope: market data (Bitunix public API) -> validation ->
Parquet storage -> indicators -> regime detection -> research reports.
No live trading, no orders, no signals - see README Non-Goals.
"""

from .config import LabConfig, load_config

__version__ = "0.1.0"

__all__ = ["LabConfig", "load_config", "__version__"]
