"""WNBA readiness notification layer (Phase 6, shadow-only).

Fires an alert ONLY when the Variant C readiness state changes along a notify-worthy
transition, and never duplicates while the state is unchanged. Persists the last observed
state in a small JSON file.

Notify-worthy transitions:
    INSUFFICIENT_DATA -> PROMOTE
    INSUFFICIENT_DATA -> HOLD
    HOLD              -> PROMOTE
    PROMOTE           -> HOLD
    (any state)       -> ROLLBACK

Notification method: the simplest path available on the server. If $WNBA_ALERT_WEBHOOK or
$WNBA_ALERT_EMAIL is set it is used; otherwise the payload is written to a clearly named file
and logged (the weekly cron pipes the log to site/logs/cron/wnba_canary.log). Touches no
production projection/model/site file.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

WNBA = Path(__file__).resolve().parent
OUT = WNBA / "outputs" / "phase6"
DEFAULT_STATE_FILE = OUT / "readiness_notify_state.json"
DEFAULT_NOTIFY_DIR = OUT / "notifications"

ALLOWED_TRANSITIONS = {
    ("INSUFFICIENT_DATA", "PROMOTE"),
    ("INSUFFICIENT_DATA", "HOLD"),
    ("HOLD", "PROMOTE"),
    ("PROMOTE", "HOLD"),
}
ALWAYS_NOTIFY_TARGET = "ROLLBACK"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def should_notify(prev_state: str | None, current_state: str) -> bool:
    """True iff this is a notify-worthy state change (no duplicates when unchanged)."""
    if current_state == prev_state:
        return False
    if current_state == ALWAYS_NOTIFY_TARGET:
        return True  # any-state -> ROLLBACK (incl. first-ever observation)
    if prev_state is None:
        return False  # silent baseline init for non-ROLLBACK first observation
    return (prev_state, current_state) in ALLOWED_TRANSITIONS


def build_payload(prev_state: str | None, scorecard: dict) -> dict:
    latest = scorecard.get("latest_run") or {}
    cov_delta = None
    if latest.get("A_coverage"):
        cov_delta = round((latest["A_coverage"] - latest["C_coverage"]) / latest["A_coverage"] * 100, 2)
    gates = latest.get("gates", {})
    return {
        "alert": "WNBA Variant C readiness state change",
        "generated_at_utc": _utc(),
        "current_state": scorecard.get("recommendation"),
        "previous_state": prev_state,
        "reason": scorecard.get("reason"),
        "consecutive_passing_weeks": scorecard.get("consecutive_passing_weeks"),
        "consecutive_failing_weeks": scorecard.get("consecutive_failing_weeks"),
        "latest_30d": {
            "brier": {"variantC": latest.get("C_brier"), "production": latest.get("A_brier")},
            "log_loss": {"variantC": latest.get("C_log_loss"), "production": latest.get("A_log_loss")},
            "coverage": {"variantC": latest.get("C_coverage"), "production": latest.get("A_coverage"),
                         "reduction_pct": cov_delta},
        },
        "gates_passed": [k for k, v in gates.items() if v],
        "gates_failed": [k for k, v in gates.items() if not v],
        "report_file": str(OUT / "promotion_readiness_scorecard.json"),
    }


def _deliver(payload: dict, notify_dir: Path, logger=None) -> str:
    """Send via webhook/email if configured, else file+log. Returns method used."""
    method = "file"
    webhook = os.environ.get("WNBA_ALERT_WEBHOOK")
    email = os.environ.get("WNBA_ALERT_EMAIL")
    text = json.dumps(payload, indent=2)
    if webhook:
        try:
            req = urllib.request.Request(webhook, data=json.dumps({"text": text}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15)
            method = "webhook"
        except Exception as e:  # fall through to file
            if logger:
                logger.warning("WNBA_ALERT_WEBHOOK delivery failed (%s); falling back to file", e)
    elif email:
        try:
            subprocess.run(["mail", "-s", "WNBA Variant C readiness change", email],
                           input=text.encode(), check=True, timeout=15)
            method = "email"
        except Exception as e:
            if logger:
                logger.warning("WNBA_ALERT_EMAIL delivery failed (%s); falling back to file", e)

    # Always also persist to file (durable record), even when webhook/email succeed.
    notify_dir.mkdir(parents=True, exist_ok=True)
    # microsecond-precision stamp so rapid successive alerts never collide on filename
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
    out_file = notify_dir / f"wnba_readiness_alert_{stamp}.json"
    out_file.write_text(text)
    (notify_dir / "latest_alert.json").write_text(text)
    with (notify_dir / "readiness_alerts.log").open("a") as fh:
        fh.write(f"{payload['generated_at_utc']} {payload['previous_state']} -> "
                 f"{payload['current_state']} (via {method}) :: {out_file.name}\n")
    if logger:
        logger.warning("WNBA READINESS ALERT: %s -> %s (method=%s) file=%s",
                       payload["previous_state"], payload["current_state"], method, out_file)
    payload["_notification_method"] = method
    payload["_notification_file"] = str(out_file)
    return method


def notify_on_change(scorecard: dict, *, state_file: Path = DEFAULT_STATE_FILE,
                     notify_dir: Path = DEFAULT_NOTIFY_DIR, logger=None) -> dict:
    """Compare current readiness to last observed state; alert only on worthy changes.
    Always persists the current state for next-run transition detection."""
    current = scorecard.get("recommendation")
    prev = None
    if state_file.exists():
        try:
            prev = json.loads(state_file.read_text()).get("last_state")
        except Exception:
            prev = None

    fire = should_notify(prev, current)
    result = {"previous_state": prev, "current_state": current, "notified": fire, "method": None}
    if fire:
        payload = build_payload(prev, scorecard)
        result["method"] = _deliver(payload, notify_dir, logger=logger)
        result["payload"] = payload

    # persist current state every run (so unchanged => no alert, and transitions are detected)
    record = {"last_state": current, "last_observed_at": _utc()}
    if state_file.exists():
        try:
            old = json.loads(state_file.read_text())
            record["last_notified_state"] = current if fire else old.get("last_notified_state")
            record["last_notified_at"] = _utc() if fire else old.get("last_notified_at")
        except Exception:
            pass
    else:
        record["last_notified_state"] = current if fire else None
        record["last_notified_at"] = _utc() if fire else None
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(record, indent=2))
    return result
