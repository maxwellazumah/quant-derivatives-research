"""Schema checks for option-chain research data.

The repository is intentionally local-first and portable.  These checks keep
example notebooks honest by making data quality and synthetic provenance
explicit before any modeling code runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


REQUIRED_OPTION_COLUMNS: tuple[str, ...] = (
    "as_of",
    "symbol",
    "expiry",
    "option_type",
    "strike",
    "spot",
    "bid",
    "ask",
    "mid",
    "volume",
    "open_interest",
    "source",
    "is_synthetic",
)


@dataclass(frozen=True)
class OptionSchemaReport:
    """Result of validating an option-chain table."""

    valid: bool
    rows: int
    columns: tuple[str, ...]
    issues: tuple[str, ...]


def _missing_columns(columns: Iterable[str]) -> list[str]:
    available = set(columns)
    return [col for col in REQUIRED_OPTION_COLUMNS if col not in available]


def validate_option_schema(df: pd.DataFrame, *, raise_on_error: bool = True) -> OptionSchemaReport:
    """Validate the core option-chain schema.

    Parameters
    ----------
    df:
        Option-chain data with one row per contract quote.
    raise_on_error:
        When true, raise ``ValueError`` on validation failure.  Tests and
        notebooks can set this false to display issues without interrupting.
    """

    issues: list[str] = []
    missing = _missing_columns(df.columns)
    if missing:
        issues.append(f"missing required columns: {', '.join(missing)}")

    if not missing:
        option_types = set(df["option_type"].astype(str).str.upper().unique())
        if not option_types <= {"C", "P"}:
            issues.append("option_type must use C/P literals")
        if (pd.to_numeric(df["strike"], errors="coerce") <= 0).any():
            issues.append("strike must be positive")
        if (pd.to_numeric(df["spot"], errors="coerce") <= 0).any():
            issues.append("spot must be positive")
        if (pd.to_numeric(df["bid"], errors="coerce") < 0).any():
            issues.append("bid must be non-negative")
        if (pd.to_numeric(df["ask"], errors="coerce") < 0).any():
            issues.append("ask must be non-negative")
        if (pd.to_numeric(df["ask"], errors="coerce") < pd.to_numeric(df["bid"], errors="coerce")).any():
            issues.append("ask must be greater than or equal to bid")
        if pd.to_datetime(df["expiry"], errors="coerce").isna().any():
            issues.append("expiry must parse as dates")
        if pd.to_datetime(df["as_of"], errors="coerce").isna().any():
            issues.append("as_of must parse as dates")

    report = OptionSchemaReport(
        valid=not issues,
        rows=int(len(df)),
        columns=tuple(str(col) for col in df.columns),
        issues=tuple(issues),
    )
    if raise_on_error and issues:
        raise ValueError("; ".join(issues))
    return report

