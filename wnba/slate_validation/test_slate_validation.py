#!/usr/bin/env python3
"""Regression tests for WNBA slate-validation resilience (ESPN 403 failover).

Contract under test:
  * ESPN reachable -> validate against ESPN (PASS/FAIL); a real mismatch is final and
    must never be overridden by consulting the secondary source.
  * ESPN unavailable (403/429/timeout/network/5xx) -> validate against an INDEPENDENT
    secondary source. Agreement -> DEGRADED_PASS (publication allowed).
  * Secondary disagrees, or neither source answers -> FAIL (publication blocked).
  * The canonical slate is NEVER used to validate itself.
  * Customer-facing status text never carries raw upstream/HTTP detail.
  * The freshness monitor flags a board that missed its refresh window.

Run: python3 slate_validation/test_slate_validation.py
"""
from __future__ import annotations

import ast
import json
import os
import socket
import sys
import tempfile
import urllib.error
from pathlib import Path

WNBA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WNBA))

from wnba_model.pipeline import slate_sources as ss  # noqa: E402

SLATE_DATE = "2026-08-06"
VIEWS_PATH = Path("/home/ubuntu/EdgeRanked/site/nba_model/webapp/wnba_views.py")
SERVICE_PATH = WNBA / "wnba_model" / "pipeline" / "service.py"


# --- helpers -----------------------------------------------------------------
def row(away: str, home: str, start: str, game_id: str = "") -> dict:
    return {"game_id": game_id or f"{away}{home}", "away_team": away, "home_team": home, "start_time_utc": start}


BASE_SLATE = [
    row("LVA", "IND", "2026-08-06T23:00Z"),
    row("LAS", "MIN", "2026-08-07T01:00Z"),
    row("TOR", "POR", "2026-08-07T02:00Z"),
]


def ok_source(rows, source="espn"):
    def fetcher(_slate_date):
        return ss.SlateFetchResult(source=source, url=f"https://{source}.test", status=ss.SOURCE_OK, rows=list(rows))

    return fetcher


def failing_source(status, source="espn", http_code=None):
    def fetcher(_slate_date):
        return ss.SlateFetchResult(
            source=source,
            url=f"https://{source}.test",
            status=status,
            http_code=http_code,
            detail=f"simulated {status}",
        )

    return fetcher


def counting(fetcher):
    calls = {"n": 0}

    def wrapped(slate_date):
        calls["n"] += 1
        return fetcher(slate_date)

    return wrapped, calls


def check(fails, condition, message):
    if not condition:
        fails.append(message)


# --- 1. ESPN 200 + exact match ----------------------------------------------
def test_espn_ok_exact_match():
    fails = []
    result = ss.run_slate_validation(
        SLATE_DATE, BASE_SLATE, primary_fetcher=ok_source(BASE_SLATE), secondary_fetcher=ok_source(BASE_SLATE, "yahoo")
    )
    check(fails, result["status"] == ss.STATUS_PASS, f"expected PASS, got {result['status']}")
    check(fails, result["validator_used"] == "espn", f"expected validator espn, got {result['validator_used']}")
    check(fails, result["primary_source_status"] == ss.SOURCE_OK, "primary status should be OK")
    check(fails, result["secondary_source_status"] == ss.SOURCE_NOT_ATTEMPTED, "secondary must not be consulted")
    check(fails, ss.publication_allowed(result), "publication must be allowed")
    return fails


# --- 2-5. ESPN unavailable + secondary exact match --------------------------
def _degraded_case(primary_status, http_code=None):
    fails = []
    secondary, calls = counting(ok_source(BASE_SLATE, "yahoo"))
    result = ss.run_slate_validation(
        SLATE_DATE,
        BASE_SLATE,
        primary_fetcher=failing_source(primary_status, http_code=http_code),
        secondary_fetcher=secondary,
    )
    check(fails, result["status"] == ss.STATUS_DEGRADED_PASS, f"{primary_status}: expected DEGRADED_PASS, got {result['status']}")
    check(fails, result["validator_used"] == "secondary", f"{primary_status}: expected validator secondary")
    check(fails, result["primary_source_status"] == primary_status, f"{primary_status}: primary status not recorded")
    check(fails, result["secondary_source_status"] == ss.SOURCE_OK, f"{primary_status}: secondary status should be OK")
    check(fails, calls["n"] == 1, f"{primary_status}: secondary should be consulted exactly once")
    check(fails, ss.publication_allowed(result), f"{primary_status}: publication must be allowed")
    check(fails, result["trusted_source"] != "canonical_schedule_emergency_fallback", "must not self-validate")
    return fails


def test_espn_403_secondary_match():
    return _degraded_case(ss.SOURCE_HTTP_403, 403)


def test_espn_429_secondary_match():
    return _degraded_case(ss.SOURCE_HTTP_429, 429)


def test_espn_timeout_secondary_match():
    return _degraded_case(ss.SOURCE_TIMEOUT)


def test_espn_500_secondary_match():
    return _degraded_case(ss.SOURCE_HTTP_5XX, 500)


# --- 6. ESPN unavailable + secondary mismatch -------------------------------
def test_secondary_mismatch_fails():
    fails = []
    other = [row("LVA", "IND", "2026-08-06T23:00Z"), row("ATL", "CHI", "2026-08-07T00:00Z")]
    result = ss.run_slate_validation(
        SLATE_DATE,
        BASE_SLATE,
        primary_fetcher=failing_source(ss.SOURCE_HTTP_403, http_code=403),
        secondary_fetcher=ok_source(other, "yahoo"),
    )
    check(fails, result["status"] == ss.STATUS_FAIL, f"expected FAIL, got {result['status']}")
    check(fails, not ss.publication_allowed(result), "publication must be blocked")
    check(fails, result["secondary_source_status"] == ss.SOURCE_MISMATCH, "secondary status should be MISMATCH")
    check(fails, result["failure_reason"] == "secondary_source_slate_mismatch", "failure_reason should name the mismatch")
    return fails


# --- 7. both sources unavailable --------------------------------------------
def test_both_sources_unavailable_fails():
    fails = []
    result = ss.run_slate_validation(
        SLATE_DATE,
        BASE_SLATE,
        primary_fetcher=failing_source(ss.SOURCE_HTTP_403, http_code=403),
        secondary_fetcher=failing_source(ss.SOURCE_TIMEOUT, source="yahoo"),
    )
    check(fails, result["status"] == ss.STATUS_FAIL, f"expected FAIL, got {result['status']}")
    check(fails, not ss.publication_allowed(result), "publication must be blocked")
    check(fails, result["validator_used"] == "none", "validator_used should be none")
    check(fails, result["failure_reason"] == "validator_infrastructure_unavailable", "must flag validator infrastructure failure")
    check(fails, result["trusted_games"] == [], "must not adopt the canonical slate as trusted")
    return fails


# --- 8. ESPN available but true mismatch (no secondary override) -------------
def test_primary_mismatch_is_final():
    fails = []
    espn_rows = [row("LVA", "IND", "2026-08-06T23:00Z")]
    secondary, calls = counting(ok_source(BASE_SLATE, "yahoo"))
    result = ss.run_slate_validation(
        SLATE_DATE, BASE_SLATE, primary_fetcher=ok_source(espn_rows), secondary_fetcher=secondary
    )
    check(fails, result["status"] == ss.STATUS_FAIL, f"expected FAIL, got {result['status']}")
    check(fails, calls["n"] == 0, "secondary must NOT be consulted to override a real primary mismatch")
    check(fails, result["primary_source_status"] == ss.SOURCE_MISMATCH, "primary status should be MISMATCH")
    check(fails, not ss.publication_allowed(result), "publication must be blocked")
    return fails


# --- 9. duplicate canonical game --------------------------------------------
def test_duplicate_canonical_game_fails():
    fails = []
    duplicated = [*BASE_SLATE, row("LVA", "IND", "2026-08-06T23:00Z")]
    result = ss.run_slate_validation(
        SLATE_DATE, duplicated, primary_fetcher=ok_source(BASE_SLATE), secondary_fetcher=ok_source(BASE_SLATE, "yahoo")
    )
    check(fails, result["status"] == ss.STATUS_FAIL, f"expected FAIL, got {result['status']}")
    check(fails, result["duplicate_games"], "duplicate_games must be reported")
    check(fails, "duplicate_games" in result["mismatch_reasons"], "mismatch_reasons must include duplicate_games")
    return fails


# --- 10. missing canonical game ---------------------------------------------
def test_missing_canonical_game_fails():
    fails = []
    result = ss.run_slate_validation(
        SLATE_DATE, BASE_SLATE[:2], primary_fetcher=ok_source(BASE_SLATE), secondary_fetcher=ok_source(BASE_SLATE, "yahoo")
    )
    check(fails, result["status"] == ss.STATUS_FAIL, f"expected FAIL, got {result['status']}")
    check(fails, result["missing_games"] == [["TOR", "POR"]], f"missing_games wrong: {result['missing_games']}")
    return fails


# --- 11. unexpected canonical game ------------------------------------------
def test_unexpected_canonical_game_fails():
    fails = []
    extra = [*BASE_SLATE, row("ATL", "CHI", "2026-08-07T00:00Z")]
    result = ss.run_slate_validation(
        SLATE_DATE, extra, primary_fetcher=ok_source(BASE_SLATE), secondary_fetcher=ok_source(BASE_SLATE, "yahoo")
    )
    check(fails, result["status"] == ss.STATUS_FAIL, f"expected FAIL, got {result['status']}")
    check(fails, result["unexpected_games"] == [["ATL", "CHI"]], f"unexpected_games wrong: {result['unexpected_games']}")
    return fails


# --- 12. start-time difference inside tolerance -----------------------------
def test_small_time_difference_passes():
    fails = []
    shifted = [
        row("LVA", "IND", "2026-08-06T23:10Z"),
        row("LAS", "MIN", "2026-08-07T01:00Z"),
        row("TOR", "POR", "2026-08-07T02:00Z"),
    ]
    result = ss.run_slate_validation(
        SLATE_DATE, shifted, primary_fetcher=ok_source(BASE_SLATE), secondary_fetcher=ok_source(BASE_SLATE, "yahoo")
    )
    check(fails, result["status"] == ss.STATUS_PASS, f"expected PASS, got {result['status']} {result['mismatch_reasons']}")
    check(fails, len(result["time_discrepancies"]) == 1, "the 10-minute difference must be recorded")
    check(fails, result["time_discrepancies"][0]["delta_minutes"] == 10.0, "delta_minutes should be 10")
    check(fails, not result["material_time_differences"], "10 minutes must not count as material")
    return fails


# --- 13. start-time difference outside tolerance ----------------------------
def test_material_time_difference_fails():
    fails = []
    shifted = [
        row("LVA", "IND", "2026-08-07T00:15Z"),
        row("LAS", "MIN", "2026-08-07T01:00Z"),
        row("TOR", "POR", "2026-08-07T02:00Z"),
    ]
    result = ss.run_slate_validation(
        SLATE_DATE, shifted, primary_fetcher=ok_source(BASE_SLATE), secondary_fetcher=ok_source(BASE_SLATE, "yahoo")
    )
    check(fails, result["status"] == ss.STATUS_FAIL, f"expected FAIL, got {result['status']}")
    check(fails, result["material_time_differences"], "75-minute difference must be flagged as material")
    check(fails, "material_start_time_difference" in result["mismatch_reasons"], "mismatch_reasons must name the time difference")
    return fails


# --- 14. empty canonical slate while the external source has games ----------
def test_empty_canonical_slate_fails():
    fails = []
    result = ss.run_slate_validation(
        SLATE_DATE, [], primary_fetcher=ok_source(BASE_SLATE), secondary_fetcher=ok_source(BASE_SLATE, "yahoo")
    )
    check(fails, result["status"] == ss.STATUS_FAIL, f"expected FAIL, got {result['status']}")
    check(fails, len(result["missing_games"]) == 3, "all three games must be reported missing")

    # And with ESPN blocked: an empty canonical slate must still fail, never self-validate.
    degraded = ss.run_slate_validation(
        SLATE_DATE,
        [],
        primary_fetcher=failing_source(ss.SOURCE_HTTP_403, http_code=403),
        secondary_fetcher=ok_source(BASE_SLATE, "yahoo"),
    )
    check(fails, degraded["status"] == ss.STATUS_FAIL, "empty canonical slate must fail under failover too")
    return fails


# --- 15. customer-facing status never exposes raw upstream errors -----------
def _load_views_sanitizer():
    """Exec only the sanitizer + its constants from wnba_views (no Flask needed)."""
    tree = ast.parse(VIEWS_PATH.read_text())
    wanted_funcs = {"public_safe_status_detail"}
    wanted_names = {"WNBA_PUBLIC_UNAVAILABLE_MESSAGE", "WNBA_PUBLIC_UNAVAILABLE_DETAIL", "_WNBA_LEAKY_ERROR_MARKERS"}
    namespace: dict = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            exec(compile(ast.Module([node], []), "<views>", "exec"), namespace)
        elif isinstance(node, ast.Assign):
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if targets & wanted_names:
                exec(compile(ast.Module([node], []), "<views>", "exec"), namespace)
    return namespace


def test_customer_facing_status_is_sanitized():
    fails = []
    base = tempfile.mkdtemp(prefix="wnba_status_test_")
    live = tempfile.mkdtemp(prefix="wnba_live_test_")
    env_backup = {k: os.environ.get(k) for k in ["EDGERANKED_WNBA_BASE_DIR", "EDGERANKED_LIVE_SITE_DIR"]}
    os.environ["EDGERANKED_WNBA_BASE_DIR"] = base
    os.environ["EDGERANKED_LIVE_SITE_DIR"] = live
    for module in [m for m in list(sys.modules) if m.startswith("wnba_model")]:
        sys.modules.pop(module, None)
    try:
        from wnba_model.pipeline import service  # noqa: PLC0415 - re-imported against temp paths

        payload = service.write_production_status(
            "FAIL",
            error="HTTPError: HTTP Error 403: Forbidden (Akamai Access Denied) at /home/ubuntu/EdgeRanked/...",
            failure_category="slate_validation_unavailable",
        )
        blob = json.dumps(payload).lower()
        for token in ["403", "akamai", "http error", "traceback", "/home/ubuntu", "espn"]:
            check(fails, token not in blob, f"published status leaked '{token}'")
        check(fails, payload["message"] == service.PUBLIC_FAILURE_MESSAGE, "public message copy is wrong")
        check(fails, payload["error"], "public status should still explain the hold in product language")
        internal = json.loads((Path(base) / "data/processed/wnba_production_status_internal.json").read_text())
        check(fails, "403" in internal["internal_error"], "internal artifact must retain the technical detail")
    finally:
        for key, value in env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for module in [m for m in list(sys.modules) if m.startswith("wnba_model")]:
            sys.modules.pop(module, None)

    views = _load_views_sanitizer()
    sanitize = views.get("public_safe_status_detail")
    check(fails, callable(sanitize), "wnba_views.public_safe_status_detail is missing")
    if callable(sanitize):
        leaky = sanitize("HTTP Error 403: Forbidden")
        check(fails, "403" not in leaky, "view sanitizer leaked an HTTP code")
        check(fails, sanitize("WNBA refresh passed.") == "WNBA refresh passed.", "clean copy must pass through")
    return fails


# --- 16. freshness monitor ---------------------------------------------------
def test_freshness_monitor_detects_stale_publication():
    fails = []
    import importlib.util

    import pandas as pd

    base = Path(tempfile.mkdtemp(prefix="wnba_fresh_test_"))
    (base / "data" / "processed").mkdir(parents=True)
    (base / "data" / "raw").mkdir(parents=True)
    os.environ["EDGERANKED_WNBA_BASE_DIR"] = str(base)
    try:
        spec = importlib.util.spec_from_file_location("wnba_freshness_monitor_test", WNBA / "wnba_freshness_monitor.py")
        monitor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(monitor)

        now = pd.Timestamp("2026-08-06 14:00:00", tz="America/New_York")
        pd.DataFrame(
            [{"game_date": "2026-08-06", "home_team": "IND", "away_team": "LVA", "start_time_utc": "2026-08-06T23:00Z"}]
        ).to_csv(base / "data" / "raw" / "wnba_schedule_today.csv", index=False)

        # (a) fresh: today's slate published today
        (base / "data/processed/wnba_production_status.json").write_text(
            json.dumps({"WNBA_PRODUCTION_STATUS": "PASS", "published": "yes", "slate_date": "2026-08-06", "generated_at": "2026-08-06T11:00:00-04:00"})
        )
        (base / "data/processed/wnba_publish_ledger.json").write_text(
            json.dumps({"last_successful_publish_at": "2026-08-06T11:00:00-04:00", "last_successful_slate_date": "2026-08-06"})
        )
        health = monitor.evaluate(now)
        check(fails, health["stale"] is False, f"fresh board flagged stale: {health['stale_reasons']}")
        check(fails, health["age_minutes"] == 180.0, f"age_minutes wrong: {health['age_minutes']}")

        # (b) stale: last success was yesterday and today's deadline has passed
        (base / "data/processed/wnba_publish_ledger.json").write_text(
            json.dumps({"last_successful_publish_at": "2026-08-05T11:00:00-04:00", "last_successful_slate_date": "2026-08-05"})
        )
        (base / "data/processed/wnba_production_status.json").write_text(
            json.dumps({"WNBA_PRODUCTION_STATUS": "FAIL", "published": "no", "slate_date": "2026-08-06", "generated_at": "2026-08-06T11:00:00-04:00"})
        )
        (base / "data/processed/wnba_production_status_internal.json").write_text(
            json.dumps({"failure_category": "slate_validation_unavailable", "internal_error": "HTTP Error 403"})
        )
        health = monitor.evaluate(now)
        check(fails, health["stale"] is True, "missed refresh was not flagged stale")
        check(fails, "no_successful_publish_today_past_deadline" in health["stale_reasons"], f"reasons: {health['stale_reasons']}")
        check(fails, health["failure_reason"] == "slate_validation_unavailable", "failure_reason not surfaced")
        for key in ["last_successful_publish_at", "current_slate_date", "current_status", "age_minutes",
                    "expected_refresh_window", "stale", "failure_reason", "validator_used"]:
            check(fails, key in health, f"health artifact missing required field '{key}'")

        # (c) off day: no slate today -> not stale
        pd.DataFrame(
            [{"game_date": "2026-08-08", "home_team": "IND", "away_team": "LVA", "start_time_utc": "2026-08-08T23:00Z"}]
        ).to_csv(base / "data" / "raw" / "wnba_schedule_today.csv", index=False)
        health = monitor.evaluate(now)
        check(fails, health["stale"] is False, "off day must not alert")
    finally:
        os.environ.pop("EDGERANKED_WNBA_BASE_DIR", None)
    return fails


# --- extra guards ------------------------------------------------------------
def test_exception_classification():
    fails = []
    cases = [
        (urllib.error.HTTPError("u", 403, "Forbidden", None, None), ss.SOURCE_HTTP_403),
        (urllib.error.HTTPError("u", 429, "Too Many Requests", None, None), ss.SOURCE_HTTP_429),
        (urllib.error.HTTPError("u", 503, "Server Error", None, None), ss.SOURCE_HTTP_5XX),
        (urllib.error.HTTPError("u", 404, "Not Found", None, None), ss.SOURCE_HTTP_4XX),
        (socket.timeout("timed out"), ss.SOURCE_TIMEOUT),
        (urllib.error.URLError(socket.timeout("timed out")), ss.SOURCE_TIMEOUT),
        (urllib.error.URLError("connection refused"), ss.SOURCE_NETWORK_ERROR),
    ]
    for exc, expected in cases:
        status, _ = ss.classify_fetch_exception(exc)
        check(fails, status == expected, f"{type(exc).__name__} -> {status}, expected {expected}")
    check(fails, all(status in ss.UNAVAILABLE_STATUSES for _, status in cases), "all transport failures must trigger failover")
    return fails


def test_secondary_parser_and_aliases():
    fails = []
    yahoo_payload = {
        "service": {
            "scoreboard": {
                "games": {
                    "wnba.g.1": {"home_team_id": "t.15", "away_team_id": "t.48", "start_time": "Fri, 07 Aug 2026 02:00:00 +0000"},
                },
                "teams": {
                    "t.15": {"abbr": "PDX", "full_name": "Portland Fire"},
                    "t.48": {"abbr": "TOR", "full_name": "Toronto Tempo"},
                },
            }
        }
    }
    rows = ss.parse_yahoo_payload(yahoo_payload)
    check(fails, len(rows) == 1, "yahoo parser should return one game")
    if rows:
        check(fails, rows[0]["home_team"] == "POR", f"PDX must normalize to POR, got {rows[0]['home_team']}")
        check(fails, rows[0]["start_time_utc"] == "2026-08-07T02:00Z", f"start time wrong: {rows[0]['start_time_utc']}")

    espn_payload = {
        "events": [
            {
                "id": "401857121",
                "date": "2026-08-07T02:00Z",
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "home", "team": {"abbreviation": "POR", "displayName": "Portland Fire"}},
                            {"homeAway": "away", "team": {"abbreviation": "TOR", "displayName": "Toronto Tempo"}},
                        ]
                    }
                ],
            }
        ]
    }
    espn_rows = ss.parse_espn_payload(espn_payload)
    check(fails, espn_rows and espn_rows[0]["home_team"] == "POR", "espn parser broken")
    check(fails, ss.normalize_team_code("GS") == "GSV", "existing aliases must be preserved")
    check(fails, ss.normalize_team_code("", full_name="Las Vegas Aces") == "LVA", "full-name fallback broken")
    return fails


def test_emergency_self_validation_removed():
    fails = []
    source = SERVICE_PATH.read_text()
    for token in ["trusted = generated", "canonical_schedule_emergency_fallback", "fetch_trusted_espn_slate"]:
        check(fails, token not in source, f"emergency self-validation remnant found in service.py: '{token}'")
    # Phase 2 moved the one policy implementation behind the publish gate; service.py must
    # reach it rather than carrying (or re-implementing) validation of its own.
    check(fails, "require_validated_slate" in source, "service.py must use the shared validation policy via the publish gate")
    gate_source = (WNBA / "wnba_model" / "pipeline" / "publish_gate.py").read_text()
    check(fails, "run_slate_validation" in gate_source, "publish gate must run the shared validation policy")
    validator_source = Path(ss.__file__).read_text()
    check(fails, "trusted = generated" not in validator_source, "validator must never self-validate")
    return fails


def main() -> None:
    tests = [
        ("1. ESPN 200 + exact match -> PASS", test_espn_ok_exact_match),
        ("2. ESPN 403 + secondary match -> DEGRADED_PASS", test_espn_403_secondary_match),
        ("3. ESPN 429 + secondary match -> DEGRADED_PASS", test_espn_429_secondary_match),
        ("4. ESPN timeout + secondary match -> DEGRADED_PASS", test_espn_timeout_secondary_match),
        ("5. ESPN 500 + secondary match -> DEGRADED_PASS", test_espn_500_secondary_match),
        ("6. secondary mismatch -> FAIL", test_secondary_mismatch_fails),
        ("7. both validators unavailable -> FAIL", test_both_sources_unavailable_fails),
        ("8. primary mismatch is final (no secondary override)", test_primary_mismatch_is_final),
        ("9. duplicate canonical game -> FAIL", test_duplicate_canonical_game_fails),
        ("10. missing canonical game -> FAIL", test_missing_canonical_game_fails),
        ("11. unexpected canonical game -> FAIL", test_unexpected_canonical_game_fails),
        ("12. small start-time difference -> PASS", test_small_time_difference_passes),
        ("13. material start-time difference -> FAIL", test_material_time_difference_fails),
        ("14. empty canonical slate -> FAIL", test_empty_canonical_slate_fails),
        ("15. customer-facing status sanitized", test_customer_facing_status_is_sanitized),
        ("16. freshness monitor detects stale publication", test_freshness_monitor_detects_stale_publication),
        ("17. transport exceptions classified for failover", test_exception_classification),
        ("18. source parsers + team aliases", test_secondary_parser_and_aliases),
        ("19. emergency self-validation removed", test_emergency_self_validation_removed),
    ]
    any_fail = False
    for name, fn in tests:
        try:
            fails = fn()
        except Exception as exc:  # noqa: BLE001
            fails = [f"raised {type(exc).__name__}: {exc}"]
        if fails:
            any_fail = True
            print(f"FAIL  {name}")
            for failure in fails:
                print(f"      - {failure}")
        else:
            print(f"PASS  {name}")
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
