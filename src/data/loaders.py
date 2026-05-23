"""File loaders with explicit synthetic fallback behavior."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .schema import validate_option_schema
from .synthetic import generate_synthetic_chain


def load_option_snapshot(path: str | Path) -> pd.DataFrame:
    """Load a CSV/JSON/Parquet option snapshot and validate its schema."""

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix in {".json", ".jsonl"}:
        df = pd.read_json(path, lines=suffix == ".jsonl")
    elif suffix in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    else:
        raise ValueError(f"unsupported snapshot format: {suffix}")
    validate_option_schema(df)
    return df


def load_or_generate_snapshot(path: str | Path | None = None, *, seed: int = 11) -> pd.DataFrame:
    """Load a snapshot when present; otherwise return deterministic synthetic data."""

    if path is not None and Path(path).exists():
        return load_option_snapshot(path)
    return generate_synthetic_chain(seed=seed)

