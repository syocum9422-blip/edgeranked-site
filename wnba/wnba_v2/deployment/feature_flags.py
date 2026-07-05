"""Production feature flags for WNBA V2 deployment.

The default is unchanged production serving. V2 can only be selected explicitly,
and by default the Phase 6 promotion gate must already be PROMOTE.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from wnba_v2 import config as C

PROMOTION_STATUS_PATH = C.OUTPUTS / "tracker" / "promotion_status.json"
DASHBOARD_PATH = C.OUTPUTS / "tracker" / "dashboard.json"
LEARNED_CALIBRATION_PATH = C.OUTPUTS / "phase53" / "phase53_learned_calibration.json"
REALISM_SUMMARY_PATH = C.OUTPUTS / "phase53" / "phase53_validation_summary.json"

REQUIRED_SIMULATION_VERSION = "sim-5.4-conserved"
EMERGENCY_MODE = "staged_v2_emergency"
DEFAULT_EMERGENCY_MAX_TRAFFIC_PERCENT = 10
DEFAULT_MIN_GRADED_RECOMMENDATIONS = 500
DEFAULT_MIN_BRIER_IMPROVEMENT = 0.02
DEFAULT_MIN_COMBO_BRIER_IMPROVEMENT = 0.02
DEFAULT_MIN_ECE_IMPROVEMENT = 0.05


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _mode() -> str:
    return os.environ.get("EDGERANKED_WNBA_SERVING_MODE", "production").strip().lower()


def _int_env(name: str, default: int, *, lo: int | None = None, hi: int | None = None) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if lo is not None and value < lo:
        raise ValueError(f"{name} must be >= {lo}")
    if hi is not None and value > hi:
        raise ValueError(f"{name} must be <= {hi}")
    return value


def _float_env(name: str, default: float, *, lo: float | None = None) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric, got {raw!r}") from exc
    if lo is not None and value < lo:
        raise ValueError(f"{name} must be >= {lo}")
    return value


def _traffic_percent() -> int:
    return _int_env("EDGERANKED_WNBA_V2_TRAFFIC_PERCENT", 0, lo=0, hi=100)


@dataclass(frozen=True)
class WnbaV2Flags:
    serving_mode: str
    traffic_percent: int
    require_promote_signal: bool
    rollback_force_production: bool
    promotion_status_path: Path = PROMOTION_STATUS_PATH

    @property
    def v2_requested(self) -> bool:
        return self.serving_mode in {"v2", "staged_v2", EMERGENCY_MODE} or self.traffic_percent > 0

    @property
    def emergency_staged(self) -> bool:
        return self.serving_mode == EMERGENCY_MODE

    @property
    def production_only(self) -> bool:
        return self.rollback_force_production or not self.v2_requested


def load_flags() -> WnbaV2Flags:
    mode = _mode()
    valid_modes = {"production", "staged_v2", "v2", EMERGENCY_MODE}
    if mode not in valid_modes:
        raise ValueError(f"EDGERANKED_WNBA_SERVING_MODE must be one of {sorted(valid_modes)}, got {mode!r}")
    traffic = _traffic_percent()
    if mode == "production" and traffic:
        raise ValueError("EDGERANKED_WNBA_V2_TRAFFIC_PERCENT must be 0 when serving mode is production")
    if mode == "v2" and traffic not in {0, 100}:
        raise ValueError("Full V2 mode requires EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=0 or 100")
    if mode in {"staged_v2", EMERGENCY_MODE} and traffic <= 0:
        raise ValueError(f"{mode} mode requires EDGERANKED_WNBA_V2_TRAFFIC_PERCENT > 0")
    if mode == EMERGENCY_MODE:
        max_traffic = _int_env(
            "EDGERANKED_WNBA_V2_EMERGENCY_MAX_TRAFFIC_PERCENT",
            DEFAULT_EMERGENCY_MAX_TRAFFIC_PERCENT,
            lo=1,
            hi=25,
        )
        if traffic > max_traffic:
            raise ValueError(
                "staged_v2_emergency traffic is capped by "
                f"EDGERANKED_WNBA_V2_EMERGENCY_MAX_TRAFFIC_PERCENT={max_traffic}"
            )
    return WnbaV2Flags(
        serving_mode=mode,
        traffic_percent=100 if mode == "v2" and traffic == 0 else traffic,
        require_promote_signal=_truthy("EDGERANKED_WNBA_V2_REQUIRE_PROMOTE_SIGNAL", True),
        rollback_force_production=_truthy("EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION", False),
    )


def _json_file(path: Path, missing_decision: str) -> dict:
    if not path.exists():
        return {"decision": missing_decision, "path": str(path)}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return {"decision": "INVALID", "path": str(path), "error": str(exc)}
    payload.setdefault("path", str(path))
    return payload


def promotion_status(path: Path = PROMOTION_STATUS_PATH) -> dict:
    return _json_file(path, "MISSING")


def dashboard_status(path: Path = DASHBOARD_PATH) -> dict:
    return _json_file(path, "MISSING_DASHBOARD")


def learned_calibration_status(path: Path = LEARNED_CALIBRATION_PATH) -> dict:
    payload = _json_file(path, "MISSING_CALIBRATION")
    return {
        "path": str(path),
        "exists": path.exists(),
        "accepted": bool(payload.get("accepted")),
        "phase": payload.get("phase"),
        "decision": "ACCEPTED" if payload.get("accepted") else payload.get("decision", "MISSING_CALIBRATION"),
    }


def realism_status(path: Path = REALISM_SUMMARY_PATH) -> dict:
    payload = _json_file(path, "MISSING_REALISM_SUMMARY")
    checks = payload.get("acceptance_checks", {}) or {}
    accepted = bool(payload.get("accepted") and checks.get("all_pass"))
    return {
        "path": str(path),
        "exists": path.exists(),
        "accepted": accepted,
        "phase53_accepted": bool(payload.get("accepted")),
        "all_pass": bool(checks.get("all_pass")),
        "decision": "PASS" if accepted else payload.get("decision", "MISSING_REALISM_SUMMARY"),
        "acceptance_checks": checks,
    }


def emergency_policy_status(dashboard: dict | None = None, promotion: dict | None = None) -> dict:
    dashboard = dashboard or dashboard_status()
    promotion = promotion or promotion_status()
    min_graded = _int_env("EDGERANKED_WNBA_V2_EMERGENCY_MIN_GRADED", DEFAULT_MIN_GRADED_RECOMMENDATIONS, lo=1)
    min_brier = _float_env("EDGERANKED_WNBA_V2_EMERGENCY_MIN_BRIER_IMPROVEMENT", DEFAULT_MIN_BRIER_IMPROVEMENT, lo=0.0)
    min_combo_brier = _float_env(
        "EDGERANKED_WNBA_V2_EMERGENCY_MIN_COMBO_BRIER_IMPROVEMENT",
        DEFAULT_MIN_COMBO_BRIER_IMPROVEMENT,
        lo=0.0,
    )
    min_ece = _float_env("EDGERANKED_WNBA_V2_EMERGENCY_MIN_ECE_IMPROVEMENT", DEFAULT_MIN_ECE_IMPROVEMENT, lo=0.0)

    v2 = dashboard.get("v2_overall", {})
    prod = dashboard.get("production_overall", {})
    combos = dashboard.get("combos", {})
    gate = dashboard.get("gate", {})
    versions = dashboard.get("versions", {}) or {}
    simulation_version = versions.get("simulation_version")
    calibration = learned_calibration_status()
    realism = realism_status()
    graded = int(dashboard.get("graded_recommendations") or 0)

    brier_delta = None if v2.get("brier") is None or prod.get("brier") is None else prod["brier"] - v2["brier"]
    combo_delta = None if combos.get("v2_brier") is None or combos.get("prod_brier") is None else combos["prod_brier"] - combos["v2_brier"]
    ece_delta = None if v2.get("ece") is None or prod.get("ece") is None else prod["ece"] - v2["ece"]

    rollback_reasons = []
    if promotion.get("decision") == "ROLLBACK_CANDIDATE" or gate.get("decision") == "ROLLBACK_CANDIDATE":
        rollback_reasons.append("phase6_rollback_candidate")
    if brier_delta is not None and brier_delta < 0:
        rollback_reasons.append("v2_brier_worse_than_production")
    if combo_delta is not None and combo_delta < 0:
        rollback_reasons.append("v2_combo_brier_worse_than_production")
    if ece_delta is not None and ece_delta < 0:
        rollback_reasons.append("v2_ece_worse_than_production")

    checks = {
        "simulation_version_conserved": simulation_version == REQUIRED_SIMULATION_VERSION,
        "learned_calibration_available": bool(calibration["exists"] and calibration["accepted"]),
        "realism_gates_passing": bool(realism["accepted"]),
        "old_independent_simulator_disabled": simulation_version == REQUIRED_SIMULATION_VERSION,
        "phase6_not_rollback_candidate": "phase6_rollback_candidate" not in rollback_reasons,
        "min_graded_recommendations": graded >= min_graded,
        "brier_materially_better": brier_delta is not None and brier_delta >= min_brier,
        "combo_brier_materially_better": combo_delta is not None and combo_delta >= min_combo_brier,
        "calibration_materially_better": ece_delta is not None and ece_delta >= min_ece,
        "no_major_regression": not rollback_reasons,
        "rollback_available": True,
    }
    allowed = all(checks.values())
    return {
        "decision": "EMERGENCY_STAGED_ALLOWED" if allowed else "EMERGENCY_STAGED_BLOCKED",
        "allowed": allowed,
        "checks": checks,
        "rollback_reasons": rollback_reasons,
        "metrics": {
            "graded_recommendations": graded,
            "v2_brier": v2.get("brier"),
            "production_brier": prod.get("brier"),
            "brier_delta": brier_delta,
            "v2_combo_brier": combos.get("v2_brier"),
            "production_combo_brier": combos.get("prod_brier"),
            "combo_brier_delta": combo_delta,
            "v2_ece": v2.get("ece"),
            "production_ece": prod.get("ece"),
            "ece_delta": ece_delta,
            "phase6_gate": gate.get("decision") or promotion.get("decision"),
            "simulation_version": simulation_version,
            "required_simulation_version": REQUIRED_SIMULATION_VERSION,
        },
        "calibration": calibration,
        "realism": realism,
        "thresholds": {
            "min_graded_recommendations": min_graded,
            "min_brier_improvement": min_brier,
            "min_combo_brier_improvement": min_combo_brier,
            "min_ece_improvement": min_ece,
        },
    }


def require_v2_deploy_allowed(flags: WnbaV2Flags | None = None) -> dict:
    flags = flags or load_flags()
    status = promotion_status(flags.promotion_status_path)
    if flags.rollback_force_production:
        return status
    if flags.emergency_staged:
        emergency = emergency_policy_status(promotion=status)
        if not emergency["allowed"]:
            raise RuntimeError(
                "WNBA V2 emergency staged serving was requested, but emergency policy is blocked: "
                f"{emergency}"
            )
        return {**status, "emergency_policy": emergency}
    if flags.v2_requested and flags.require_promote_signal and status.get("decision") != "PROMOTE":
        raise RuntimeError(
            "WNBA V2 serving was requested, but the Phase 6 promotion gate is "
            f"{status.get('decision')!r}; set EDGERANKED_WNBA_SERVING_MODE=production "
            "or use staged_v2_emergency only when the emergency policy checks pass."
        )
    return status
