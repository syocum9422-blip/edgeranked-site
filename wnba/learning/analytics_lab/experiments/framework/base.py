"""The plug-in contract. The runner knows only this; it knows no experiment.

An experiment supplies a manifest and a `build_variant` that returns a
production-shaped feature frame differing from the baseline in **exactly** the
columns its manifest declares. The runner verifies that claim before scoring —
an undeclared column change aborts the run, which is how "only one variable may
change per experiment" is enforced mechanically rather than by convention.
"""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from analytics_lab.experiments.framework.baseline import Baseline
from analytics_lab.experiments.framework.manifest import ExperimentManifest


class SingleVariableViolation(RuntimeError):
    """A variant changed a column its manifest did not declare."""


@dataclass(frozen=True)
class ExperimentContext:
    """Everything an experiment is allowed to read.

    `asof` is the full as-of feature table; `baseline` carries the shared rows,
    the production-shaped frame and the baseline predictions. Nothing here can
    reach production outputs or the future — the as-of table was built under the
    Phase 2B exclusion rules.
    """

    asof: pd.DataFrame
    baseline: Baseline

    @property
    def rows(self) -> pd.DataFrame:
        return self.baseline.rows

    @property
    def baseline_frame(self) -> pd.DataFrame:
        return self.baseline.frame

    def asof_rows(self) -> pd.DataFrame:
        """As-of features for the shared rows, i.e. the non-stale view."""
        return self.asof.loc[self.baseline.rows.index]


class Experiment(ABC):
    """Base class for a lab experiment."""

    @property
    @abstractmethod
    def manifest(self) -> ExperimentManifest:
        ...

    @abstractmethod
    def build_variant(self, context: ExperimentContext) -> pd.DataFrame:
        """Return a production-shaped frame, identical to the baseline except in
        the columns named by `manifest.features_modified`."""

    def interpretation(self, comparison: dict) -> str:
        """Optional prose the experiment adds to its own report.

        Default is empty: an experiment that has nothing specific to say should
        not pad the report with restated numbers.
        """
        return ""


def changed_columns(baseline_frame: pd.DataFrame, variant_frame: pd.DataFrame,
                    tolerance: float = 1e-9) -> list[str]:
    """Columns that actually differ, NaN-aware.

    NaN==NaN counts as unchanged; NaN vs a value counts as changed. Without that
    an experiment could null a feature and have it read as untouched.
    """
    if list(baseline_frame.columns) != list(variant_frame.columns):
        missing = set(baseline_frame.columns) ^ set(variant_frame.columns)
        raise SingleVariableViolation(f"variant changed the frame's schema: {sorted(missing)}")

    changed = []
    for column in baseline_frame.columns:
        left, right = baseline_frame[column], variant_frame[column]
        both_null = left.isna() & right.isna()
        if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
            difference = (left - right).abs() > tolerance
        else:
            difference = left.astype("string") != right.astype("string")
        if (difference & ~both_null).any() or (left.isna() != right.isna()).any():
            changed.append(column)
    return changed


def assert_single_variable(baseline_frame: pd.DataFrame, variant_frame: pd.DataFrame,
                           declared: list[str]) -> list[str]:
    """Verify the variant changed only what it said it would."""
    if len(baseline_frame) != len(variant_frame):
        raise SingleVariableViolation(
            f"variant has {len(variant_frame)} rows, baseline has {len(baseline_frame)}; "
            "experiments must be scored on identical player-games"
        )
    if not baseline_frame.index.equals(variant_frame.index):
        raise SingleVariableViolation("variant index does not match the baseline index")

    actual = changed_columns(baseline_frame, variant_frame)
    undeclared = sorted(set(actual) - set(declared))
    if undeclared:
        raise SingleVariableViolation(
            f"variant changed undeclared columns {undeclared}; "
            f"manifest declares {sorted(declared)}"
        )
    return actual
