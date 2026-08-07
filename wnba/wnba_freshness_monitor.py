#!/usr/bin/env python3
"""WNBA production freshness monitor (read-only).

The 2026-08-06 slate-validation outage went unnoticed until a subscriber emailed
support. This monitor closes that gap: it inspects the WNBA production status
artifacts, writes a machine-readable health file, and alerts the owner when the
public board has not successfully published inside its expected refresh window.

It is strictly read-only with respect to production: it never touches projections,
best bets, models, the canonical slate, or the published status file. Its only
writes are its own health/state/alert artifacts.

Run:   python3 wnba_freshness_monitor.py [--check-only] [--force-alert]
Health artifact: data/processed/wnba_freshness_health.json
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pandas as pd


WNBA_DIR = Path(os.environ.get("EDGERANKED_WNBA_BASE_DIR", str(Path(__file__).resolve().parent)))
PROCESSED_DIR = WNBA_DIR / "data" / "processed"

PRODUCTION_STATUS_PATH = PROCESSED_DIR / "wnba_production_status.json"
INTERNAL_STATUS_PATH = PROCESSED_DIR / "wnba_production_status_internal.json"
PUBLISH_LEDGER_PATH = PROCESSED_DIR / "wnba_publish_ledger.json"
SLATE_MANIFEST_PATH = PROCESSED_DIR / "wnba_slate_validation_manifest.json"
GATE_STATUS_PATH = PROCESSED_DIR / "wnba_publish_gate_status.json"
SCHEDULE_PATH = WNBA_DIR / "data" / "raw" / "wnba_schedule_today.csv"

HEALTH_PATH = PROCESSED_DIR / "wnba_freshness_health.json"
ALERT_STATE_PATH = PROCESSED_DIR / "wnba_freshness_alert_state.json"
ALERT_DIR = WNBA_DIR / "outputs" / "freshness_alerts"

EASTERN = "America/New_York"

# Production refresh crons (UTC): 11:30, 18:00, 22:30 -> 07:30, 14:00, 18:30 ET.
DEFAULT_FIRST_REFRESH_ET = "07:30"
DEFAULT_LAST_REFRESH_ET = "18:30"
# Grace after the first daily refresh before a missing publish counts as stale.
DEFAULT_DEADLINE_ET_HOUR = 10  # ~2h after the 07:30 ET full rebuild
DEFAULT_MAX_AGE_MINUTES = 1500  # 25h: one missed daily cycle
DEFAULT_REALERT_HOURS = 6
# A publish gate block (e.g. a blocked late refresh) is worth an alert even when the
# morning board is still fresh and serving.
DEFAULT_GATE_BLOCK_WINDOW_MINUTES = 240


def _env(name: str, default):
    value = str(os.environ.get(name, "")).strip()
    return value or default


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, default))
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _parse_ts(value: object):
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize(EASTERN)
    return ts.tz_convert(EASTERN)


def schedule_expectation(now_et) -> tuple[object, str]:
    """Is a slate expected today? -> (True/False/None, reason).

    None means 'unknown' (the canonical schedule itself is stale), which is treated as
    "a refresh was expected" so a broken pipeline can never hide behind an off day.
    """
    if not SCHEDULE_PATH.exists():
        return None, "schedule_file_missing"
    try:
        schedule = pd.read_csv(SCHEDULE_PATH)
    except Exception:
        return None, "schedule_file_unreadable"
    if schedule.empty:
        return None, "schedule_file_empty"
    date_col = next((col for col in schedule.columns if str(col).lower() in {"game_date", "date"}), None)
    if not date_col:
        return None, "schedule_missing_date_column"
    dates = pd.to_datetime(schedule[date_col], errors="coerce").dropna()
    if dates.empty:
        return None, "schedule_no_valid_dates"
    today = now_et.date()
    day_set = {value.date() for value in dates}
    if today in day_set:
        return True, "slate_today"
    if max(day_set) > today:
        return False, "no_slate_today_next_slate_upcoming"
    return None, "schedule_stale"


def evaluate(now_et=None) -> dict:
    now_et = now_et or pd.Timestamp.now(tz=EASTERN)
    status = _read_json(PRODUCTION_STATUS_PATH)
    internal = _read_json(INTERNAL_STATUS_PATH)
    ledger = _read_json(PUBLISH_LEDGER_PATH)
    manifest = _read_json(SLATE_MANIFEST_PATH)

    current_status = str(status.get("WNBA_PRODUCTION_STATUS") or "UNKNOWN")
    published = str(status.get("published") or "").lower()

    last_success = _parse_ts(ledger.get("last_successful_publish_at"))
    if last_success is None and current_status == "PASS" and published == "yes":
        last_success = _parse_ts(status.get("generated_at"))

    age_minutes = None if last_success is None else round((now_et - last_success).total_seconds() / 60.0, 1)

    slate_expected, slate_reason = schedule_expectation(now_et)
    deadline_hour = _int_env("WNBA_FRESHNESS_DEADLINE_ET_HOUR", DEFAULT_DEADLINE_ET_HOUR)
    max_age_minutes = _int_env("WNBA_FRESHNESS_MAX_AGE_MINUTES", DEFAULT_MAX_AGE_MINUTES)
    past_deadline = now_et.hour >= deadline_hour

    refresh_required = slate_expected is not False

    reasons = []
    if last_success is None:
        reasons.append("no_successful_publish_recorded")
    else:
        if age_minutes is not None and age_minutes > max_age_minutes:
            reasons.append("last_success_older_than_max_age")
        if refresh_required and past_deadline and last_success.date() != now_et.date():
            reasons.append("no_successful_publish_today_past_deadline")
    if refresh_required and current_status != "PASS":
        reasons.append(f"current_status_{current_status.lower()}")
    if refresh_required and current_status == "PASS" and published != "yes":
        reasons.append("pass_but_not_published")

    stale = bool(reasons) and refresh_required

    failure_reason = ""
    if current_status != "PASS":
        failure_reason = str(internal.get("failure_category") or status.get("failure_category") or "unknown")

    gate = _read_json(GATE_STATUS_PATH)
    gate_checked = _parse_ts(gate.get("checked_at"))
    gate_age_minutes = None if gate_checked is None else round((now_et - gate_checked).total_seconds() / 60.0, 1)
    gate_window = _int_env("WNBA_FRESHNESS_GATE_BLOCK_WINDOW_MINUTES", DEFAULT_GATE_BLOCK_WINDOW_MINUTES)
    gate_blocked = bool(
        gate
        and gate.get("publish_allowed") is False
        and gate_age_minutes is not None
        and gate_age_minutes <= gate_window
    )

    health = {
        "generated_at": now_et.isoformat(),
        "last_successful_publish_at": None if last_success is None else last_success.isoformat(),
        "last_successful_slate_date": ledger.get("last_successful_slate_date"),
        "current_slate_date": status.get("slate_date"),
        "current_status": current_status,
        "published": status.get("published"),
        "age_minutes": age_minutes,
        "expected_refresh_window": {
            "first_refresh_et": _env("WNBA_FRESHNESS_FIRST_REFRESH_ET", DEFAULT_FIRST_REFRESH_ET),
            "last_refresh_et": _env("WNBA_FRESHNESS_LAST_REFRESH_ET", DEFAULT_LAST_REFRESH_ET),
            "daily_deadline_et_hour": deadline_hour,
            "max_age_minutes": max_age_minutes,
        },
        "slate_expected_today": slate_expected,
        "slate_expectation_reason": slate_reason,
        "stale": stale,
        "stale_reasons": reasons,
        "publish_gate": {
            "blocked": gate_blocked,
            "status": gate.get("status"),
            "context": gate.get("context"),
            "failure_reason": gate.get("failure_reason"),
            "checked_at": gate.get("checked_at"),
            "age_minutes": gate_age_minutes,
            "validator_source": gate.get("validator_source"),
            "validation_independence": gate.get("validation_independence"),
            "canonical_source": gate.get("canonical_source"),
        },
        "needs_attention": bool(stale or gate_blocked),
        "failure_reason": failure_reason,
        "validator_used": manifest.get("validator_used") or status.get("slate_validator_used") or "none",
        "slate_validation_status": manifest.get("status") or status.get("slate_validation_status"),
        "primary_source_status": manifest.get("primary_source_status"),
        "secondary_source_status": manifest.get("secondary_source_status"),
        # internal-only diagnostic detail; this artifact is never served to customers
        "internal_error": internal.get("internal_error", ""),
        "validator_detail": manifest.get("internal_detail", ""),
    }
    return health


# --- alerting ---------------------------------------------------------------
def _load_smtp_env() -> None:
    """Reuse the credentials the Best Bets email bot already uses on this server."""
    for env_path in [
        Path("/home/ubuntu/EdgeRanked/.env"),
        Path("/home/ubuntu/EdgeRanked/tools/best_bets_bot/.env"),
    ]:
        if not env_path.exists():
            continue
        try:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except Exception:
            continue


def _send_email(subject: str, body: str) -> bool:
    _load_smtp_env()
    host = os.environ.get("SMTP_HOST", "")
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    sender = os.environ.get("EMAIL_FROM", user)
    recipient = os.environ.get("WNBA_ALERT_EMAIL") or os.environ.get("EMAIL_TO", "")
    if not (host and user and password and sender and recipient):
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(message)
        return True
    except Exception as exc:
        print(f"WARNING: WNBA freshness email delivery failed: {exc}")
        return False


def _send_webhook(subject: str, body: str) -> bool:
    webhook = os.environ.get("WNBA_ALERT_WEBHOOK", "")
    if not webhook:
        return False
    try:
        payload = json.dumps({"text": f"{subject}\n\n{body}"}).encode("utf-8")
        request = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=15)
        return True
    except Exception as exc:
        print(f"WARNING: WNBA freshness webhook delivery failed: {exc}")
        return False


def deliver_alert(health: dict, kind: str) -> list[str]:
    """Webhook -> email -> file. The file/log record is always written."""
    slate = health.get("current_slate_date")
    gate_blocked = bool((health.get("publish_gate") or {}).get("blocked"))
    if kind == "recovered":
        subject = f"[EdgeRanked] WNBA refresh recovered ({slate})"
    elif health.get("stale"):
        subject = f"[EdgeRanked] WNBA board is STALE ({slate})"
    elif gate_blocked:
        subject = f"[EdgeRanked] WNBA publish gate blocked a refresh ({slate})"
    else:
        subject = f"[EdgeRanked] WNBA needs attention ({slate})"
    body = json.dumps(health, indent=2, sort_keys=True)

    methods = []
    if _send_webhook(subject, body):
        methods.append("webhook")
    if _send_email(subject, body):
        methods.append("email")

    try:
        ALERT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S_%f")
        (ALERT_DIR / f"wnba_freshness_{kind}_{stamp}.json").write_text(body, encoding="utf-8")
        (ALERT_DIR / "latest_alert.json").write_text(body, encoding="utf-8")
        with (ALERT_DIR / "freshness_alerts.log").open("a", encoding="utf-8") as handle:
            handle.write(
                f"{health.get('generated_at')} {kind} stale={health.get('stale')} "
                f"reasons={health.get('stale_reasons')} via={methods or ['file']}\n"
            )
        methods.append("file")
    except Exception as exc:
        print(f"WARNING: could not persist WNBA freshness alert: {exc}")
    return methods


def alert_key(health: dict) -> str:
    gate = health.get("publish_gate") or {}
    return (
        f"{health.get('current_slate_date')}|{sorted(health.get('stale_reasons') or [])}"
        f"|gate={gate.get('blocked')}:{gate.get('context')}:{gate.get('failure_reason')}"
    )


def should_alert(health: dict, state: dict, now_et) -> tuple[bool, str]:
    """Alert on entering a bad state, on a changed reason, on periodic re-alert, and once on recovery.

    A "bad state" is a stale board or a recent publish-gate block — the latter matters even
    while a previously verified board is still serving.
    """
    was_stale = bool(state.get("stale"))
    if not health.get("needs_attention"):
        return (was_stale, "recovered") if was_stale else (False, "")
    if not was_stale:
        return True, "stale"
    if alert_key(health) != str(state.get("alert_key") or ""):
        return True, "stale"
    last_alert = _parse_ts(state.get("last_alert_at"))
    realert_hours = _int_env("WNBA_FRESHNESS_REALERT_HOURS", DEFAULT_REALERT_HOURS)
    if last_alert is None or (now_et - last_alert).total_seconds() / 3600.0 >= realert_hours:
        return True, "stale"
    return False, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="WNBA production freshness monitor")
    parser.add_argument("--check-only", action="store_true", help="write the health artifact, never alert")
    parser.add_argument("--force-alert", action="store_true", help="send an alert regardless of dedupe state")
    parser.add_argument("--test-alert", action="store_true", help="send a clearly labelled delivery test and exit")
    args = parser.parse_args()

    if args.test_alert:
        subject = "[EdgeRanked] WNBA freshness monitor test alert (no action needed)"
        body = (
            "This is a delivery test of the WNBA freshness monitor. The board is not stale.\n"
            f"Checked at {pd.Timestamp.now(tz=EASTERN).isoformat()}.\n"
        )
        methods = [name for name, sent in [("webhook", _send_webhook(subject, body)), ("email", _send_email(subject, body))] if sent]
        print(f"WNBA freshness test alert delivered via {methods or ['none']}")
        return 0 if methods else 1

    now_et = pd.Timestamp.now(tz=EASTERN)
    health = evaluate(now_et)

    HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_PATH.write_text(json.dumps(health, indent=2, sort_keys=True), encoding="utf-8")

    print(
        f"WNBA freshness: stale={health['stale']} gate_blocked={(health.get('publish_gate') or {}).get('blocked')} "
        f"status={health['current_status']} "
        f"slate_date={health['current_slate_date']} age_minutes={health['age_minutes']} "
        f"validator_used={health['validator_used']} reasons={health['stale_reasons']}"
    )

    state = _read_json(ALERT_STATE_PATH)
    fire, kind = should_alert(health, state, now_et)
    if args.force_alert:
        fire, kind = True, ("stale" if health["stale"] else "recovered")

    if fire and not args.check_only:
        methods = deliver_alert(health, kind)
        print(f"WNBA freshness alert sent ({kind}) via {methods}")
        state["last_alert_at"] = now_et.isoformat()
        state["last_alert_kind"] = kind

    state["stale"] = bool(health["needs_attention"])
    state["alert_key"] = alert_key(health)
    state["last_checked_at"] = now_et.isoformat()
    try:
        ALERT_STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    except Exception as exc:
        print(f"WARNING: could not write WNBA freshness alert state: {exc}")

    # Non-zero exit makes a bad state visible to cron mail / log scrapers too.
    return 2 if health["needs_attention"] else 0


if __name__ == "__main__":
    sys.exit(main())
