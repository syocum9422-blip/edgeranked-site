"""Experiment manifest — the contract an experiment declares before it runs.

The manifest is written *before* results exist. It records the question, the
hypothesis and the expected improvement up front, so an experiment cannot be
retrofitted into a success after the numbers arrive.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

STATUS_VALUES = ("draft", "ready", "running", "complete", "abandoned")
RESULT_VALUES = ("meaningful", "marginal", "not_significant", "regression", "pending")


@dataclass
class ExperimentManifest:
    """Declared before the run; results are appended after."""

    experiment_id: str
    title: str
    question: str
    hypothesis: str
    features_modified: list[str]
    expected_improvement: str
    author: str = "analytics_lab"
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    description: str = ""
    baseline_version: str = "reconstructed_production_logic_v1"
    baseline_kind: str = "reconstructed_production_logic"
    feature_flags: dict = field(default_factory=dict)
    seasons: list[int] = field(default_factory=lambda: [2024, 2025, 2026])
    stats: list[str] = field(default_factory=lambda: [
        "points", "rebounds", "assists", "threes_made", "steals", "blocks"])
    status: str = "ready"
    result: str = "pending"
    notes: str = ""
    limitations: list[str] = field(default_factory=list)
    future_work: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in STATUS_VALUES:
            raise ValueError(f"status must be one of {STATUS_VALUES}, got {self.status!r}")
        if self.result not in RESULT_VALUES:
            raise ValueError(f"result must be one of {RESULT_VALUES}, got {self.result!r}")
        if not self.features_modified:
            raise ValueError("features_modified must name at least one column")
        if len(self.question.split()) < 4:
            raise ValueError("question must be a real question, not a label")

    def to_dict(self) -> dict:
        return asdict(self)

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        return path

    @classmethod
    def read(cls, path: Path) -> "ExperimentManifest":
        return cls(**json.loads(Path(path).read_text()))
