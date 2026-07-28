"""Chronological replay runner.

Walks tip-offs in order and, for each one, hands a projector a state object that
physically cannot see the future. The runner owns the ordering, freezing and
grading; an experiment only supplies :class:`Projector.project`.

Per checkpoint:

  1. slice history to strictly-before the tip-off        (AsOfState)
  2. determine who is on the slate                       (roster resolver)
  3. build features from the slice                       (projector)
  4. produce projections                                 (projector)
  5. freeze the projection artifact                      (immutable, written once)
  6. attach actual results once the game is complete     (grading)
  7. advance

No step may consult a season-level aggregate computed through a later date; the
only history a projector receives is the ``AsOfState`` slice.

This module is the interface plus the loop. It intentionally ships without a
concrete projector: writing one requires the feature-reconstruction decisions
recorded in ``reports/initial_feasibility_report.md``.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
    from analytics_lab.replay.as_of_state import AsOfState, HistoryStore
else:
    from ..config import lab_config as C
    from .as_of_state import AsOfState, HistoryStore


class Projector(Protocol):
    """What an experiment must implement to be replayable."""

    name: str

    def project(self, state: AsOfState, slate: pd.DataFrame) -> pd.DataFrame:
        """Return one row per (player_key, stat) with a ``projection`` column.

        ``slate`` lists the players and matchups for this checkpoint. ``state``
        is the only permitted source of history.
        """


@dataclass
class ReplayConfig:
    """Chronological, never random. Boundaries are ET slate dates."""

    experiment: str
    train_end: str                    # inclusive; model fitting may use <= this
    validation_end: str               # inclusive; tuning may use <= this
    test_end: str | None = None       # inclusive; touched once, at the end
    start: str | None = None
    stats: tuple[str, ...] = tuple(C.STAT_TARGETS)
    notes: str = ""
    extra: dict = field(default_factory=dict)

    def split_for(self, slate_date: str) -> str:
        if slate_date <= self.train_end:
            return "train"
        if slate_date <= self.validation_end:
            return "validation"
        return "test"

    def to_dict(self) -> dict:
        return {
            "experiment": self.experiment, "start": self.start,
            "train_end": self.train_end, "validation_end": self.validation_end,
            "test_end": self.test_end, "stats": list(self.stats),
            "notes": self.notes, **self.extra,
        }


class ReplayRunner:
    """Drives a projector across checkpoints and freezes what it produced."""

    def __init__(self, config: ReplayConfig, store: HistoryStore | None = None) -> None:
        self.config = config
        self.store = store or HistoryStore.from_lab_data()
        self.output_dir = C.LAB_EXPERIMENTS / config.experiment / "frozen"

    def checkpoints(self) -> pd.DataFrame:
        frame = self.store.slate_cutoffs()
        if self.config.start:
            frame = frame[frame["slate_date_et"] >= self.config.start]
        if self.config.test_end:
            frame = frame[frame["slate_date_et"] <= self.config.test_end]
        return frame.reset_index(drop=True)

    def freeze(self, checkpoint_id: str, projections: pd.DataFrame) -> Path:
        """Write a projection artifact exactly once.

        A frozen artifact is never rewritten: re-running a checkpoint must not
        be able to quietly improve a past projection. That also makes the replay
        resumable — an existing file means the checkpoint is done.
        """
        target = C.lab_path(
            self.config.experiment, "frozen", f"{checkpoint_id}.csv", root=C.LAB_EXPERIMENTS
        )
        if target.exists():
            return target
        projections.to_csv(target, index=False)
        return target

    def run(self, projector: Projector, checkpoints: Iterable[dict] | None = None) -> pd.DataFrame:
        manifest = C.lab_path(
            self.config.experiment, "manifest.json", root=C.LAB_EXPERIMENTS
        )
        manifest.write_text(json.dumps(
            {**self.config.to_dict(), "projector": getattr(projector, "name", type(projector).__name__)},
            indent=2,
        ) + "\n")

        rows = checkpoints if checkpoints is not None else self.checkpoints().to_dict("records")
        produced: list[dict] = []
        for checkpoint in rows:
            state = self.store.as_of(checkpoint["start_utc"])
            slate = self.resolve_slate(checkpoint)
            projections = projector.project(state, slate)
            projections["checkpoint_id"] = checkpoint["game_id"]
            projections["slate_date_et"] = checkpoint["slate_date_et"]
            projections["split"] = self.config.split_for(checkpoint["slate_date_et"])
            path = self.freeze(str(checkpoint["game_id"]), projections)
            produced.append({
                "checkpoint_id": checkpoint["game_id"],
                "slate_date_et": checkpoint["slate_date_et"],
                "start_utc": checkpoint["start_utc"],
                "rows": len(projections),
                "artifact": str(path),
            })
        return pd.DataFrame(produced)

    def resolve_slate(self, checkpoint: dict) -> pd.DataFrame:
        """Who was expected to play in this game.

        Not implemented: pregame roster/availability for past dates is not
        recoverable from current repository data (the injury feed keeps no
        history, and the ESPN summary injury block reflects scrape time, not
        game time). The honest options are documented in the feasibility
        report; each changes what a replay means, so the choice is deliberate
        rather than defaulted.
        """
        raise NotImplementedError(
            "roster resolution is unresolved — see reports/initial_feasibility_report.md, "
            "'Injury / availability reconstruction'"
        )
