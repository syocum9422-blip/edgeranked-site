"""Phase 6 — version registry.

Every recommendation records the model / calibration / simulation versions that
produced it, so the dashboard can attribute performance to a specific build and
promotion/rollback is version-aware. Bump these whenever the corresponding layer
changes materially.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from wnba_v2 import config as C

MODEL_VERSION = "v2.0.0"          # engines: minutes/pace/usage(+3.5)/efficiency
CALIBRATION_VERSION = "cal-2026.1"  # per-stat affine scale (Phase 5.1)
SIMULATION_VERSION = "sim-5.4-conserved"  # conserved team/game simulator replacement

REGISTRY_PATH = C.OUTPUTS / "tracker" / "version_registry.json"


def current() -> dict:
    return {"model_version": MODEL_VERSION,
            "calibration_version": CALIBRATION_VERSION,
            "simulation_version": SIMULATION_VERSION}


def record_registry(calib: dict | None = None) -> dict:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {**current(), "calibration_factors": calib or {},
             "registered_at": datetime.now(timezone.utc).isoformat()}
    history = []
    if REGISTRY_PATH.exists():
        history = json.loads(REGISTRY_PATH.read_text())
    if not history or {k: history[-1].get(k) for k in current()} != current():
        history.append(entry)
        REGISTRY_PATH.write_text(json.dumps(history, indent=2))
    return entry
