#!/usr/bin/env python3
"""Phase 2 regression tests: canonical-source resilience, validator independence, and
the single publish gate.

Contract under test:
  * canonical acquisition survives an ESPN outage by using the independent secondary
  * a stale local schedule can never stand in for today's canonical slate
  * acquisition provenance is recorded for every outcome
  * the validator is never the provider that produced the canonical slate, and a
    same-source re-fetch is not treated as a true PASS
  * no WNBA publish path can reach the live site without the central gate

Run: python3 slate_validation/test_phase2_resilience.py
"""
from __future__ import annotations

import glob
import importlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

WNBA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WNBA))
SITE_SCRIPTS = Path("/home/ubuntu/EdgeRanked/site/scripts/aws")

from wnba_model.pipeline import slate_sources as ss  # noqa: E402

SLATE_DATE = "2026-08-06"


def row(away: str, home: str, start: str, game_id: str = "") -> dict:
    return {"game_id": game_id or f"{away}{home}", "away_team": away, "home_team": home, "start_time_utc": start}


BASE_SLATE = [
    row("LVA", "IND", "2026-08-06T23:00Z"),
    row("LAS", "MIN", "2026-08-07T01:00Z"),
]


def ok_source(rows, source="espn"):
    def fetcher(_slate_date):
        return ss.SlateFetchResult(source=source, url=f"https://{source}.test", status=ss.SOURCE_OK, rows=list(rows))

    return fetcher


def failing_source(status, source="espn", http_code=None):
    def fetcher(_slate_date):
        return ss.SlateFetchResult(source=source, url=f"https://{source}.test", status=status, http_code=http_code, detail=f"simulated {status}")

    return fetcher


def corroboration(*, confirmed: bool, contradicted: bool = False) -> dict:
    verdict = ss.CORROBORATION_CONTRADICTED if contradicted else (
        ss.CORROBORATION_CONFIRMED if confirmed else ss.CORROBORATION_INCONCLUSIVE
    )
    return ss.summarize_corroboration([
        {"name": "thesportsdb", "status": "OK", "verdict": verdict, "confirmed_games": 1 if confirmed else 0, "contradictions": [["ATL", "CHI"]] if contradicted else []}
    ])


def check(fails, condition, message):
    if not condition:
        fails.append(message)


# --- canonical acquisition ---------------------------------------------------
class _Logger:
    def __init__(self):
        self.messages = []

    def _log(self, level, msg, *args):
        self.messages.append(f"{level}: {msg % args if args else msg}")

    info = lambda self, msg, *a: self._log("INFO", msg, *a)  # noqa: E731
    warning = lambda self, msg, *a: self._log("WARN", msg, *a)  # noqa: E731
    error = lambda self, msg, *a: self._log("ERROR", msg, *a)  # noqa: E731
    debug = lambda self, msg, *a: self._log("DEBUG", msg, *a)  # noqa: E731


def _acquisition_env():
    """Import fetch_wnba_data against a throwaway base dir so nothing production is touched."""
    base = Path(tempfile.mkdtemp(prefix="wnba_phase2_"))
    (base / "data" / "raw").mkdir(parents=True)
    (base / "data" / "processed").mkdir(parents=True)
    os.environ["EDGERANKED_WNBA_BASE_DIR"] = str(base)
    os.environ["WNBA_SOURCE_MODE"] = "auto"
    for name in [m for m in list(sys.modules) if m.startswith(("wnba_model", "fetch_wnba_data", "wnba_model_config"))]:
        sys.modules.pop(name, None)
    module = importlib.import_module("fetch_wnba_data")
    return base, module


def _restore_env():
    os.environ.pop("EDGERANKED_WNBA_BASE_DIR", None)
    for name in [m for m in list(sys.modules) if m.startswith(("wnba_model", "fetch_wnba_data", "wnba_model_config"))]:
        sys.modules.pop(name, None)


def _acquire(module, espn, yahoo):
    module.fetch_espn_slate = espn
    module.fetch_yahoo_slate = yahoo
    module._check_api_reachable = lambda logger: False
    return module.resolve_schedule_today(_Logger())


def test_canonical_espn_success():
    fails = []
    base, module = _acquisition_env()
    try:
        frame, source = _acquire(module, ok_source(BASE_SLATE), failing_source(ss.SOURCE_HTTP_403, "yahoo", 403))
        check(fails, source == "api:espn", f"expected api:espn, got {source}")
        check(fails, len(frame) == 2, f"expected 2 schedule rows, got {len(frame)}")
        provenance = json.loads((base / "data/processed/wnba_canonical_schedule_provenance.json").read_text())
        check(fails, provenance["canonical_source"] == "api:espn", "provenance source wrong")
        check(fails, provenance["degraded"] is False, "ESPN success must not be degraded")
        check(fails, provenance["game_count"] == 2, "provenance game_count wrong")
        for column in ["home_team", "away_team", "game_id", "start_time_utc", "start_time", "game_date"]:
            check(fails, column in frame.columns, f"canonical frame missing column {column}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
        _restore_env()
    return fails


def _failover_case(primary_status, http_code=None):
    fails = []
    base, module = _acquisition_env()
    try:
        frame, source = _acquire(module, failing_source(primary_status, "espn", http_code), ok_source(BASE_SLATE, "yahoo"))
        check(fails, source == "api:yahoo", f"{primary_status}: expected api:yahoo, got {source}")
        check(fails, len(frame) == 2, f"{primary_status}: expected 2 rows, got {len(frame)}")
        provenance = json.loads((base / "data/processed/wnba_canonical_schedule_provenance.json").read_text())
        check(fails, provenance["canonical_source"] == "api:yahoo", f"{primary_status}: provenance source wrong")
        check(fails, provenance["primary_source_status"] == primary_status, f"{primary_status}: primary status not recorded")
        check(fails, provenance["secondary_source_status"] == ss.SOURCE_OK, f"{primary_status}: secondary status wrong")
        check(fails, provenance["degraded"] is True, f"{primary_status}: failover must be marked degraded")
        check(fails, provenance["stale_retained"] is False, f"{primary_status}: nothing stale was retained")
    finally:
        shutil.rmtree(base, ignore_errors=True)
        _restore_env()
    return fails


def test_canonical_espn_403_to_yahoo():
    return _failover_case(ss.SOURCE_HTTP_403, 403)


def test_canonical_espn_timeout_to_yahoo():
    return _failover_case(ss.SOURCE_TIMEOUT)


def test_canonical_both_sources_unavailable():
    fails = []
    base, module = _acquisition_env()
    try:
        stale = base / "data" / "raw" / "wnba_schedule_today.csv"
        stale.write_text("game_date,home_team,away_team,game_id,start_time_utc,_data_source\n2026-08-01,IND,LVA,1,2026-08-01T23:00Z,api:espn\n")
        raised = None
        try:
            _acquire(module, failing_source(ss.SOURCE_HTTP_403, "espn", 403), failing_source(ss.SOURCE_TIMEOUT, "yahoo"))
        except Exception as exc:  # noqa: BLE001
            raised = exc
        check(fails, isinstance(raised, module.CanonicalScheduleUnavailable), f"expected CanonicalScheduleUnavailable, got {type(raised).__name__}")
        provenance = json.loads((base / "data/processed/wnba_canonical_schedule_provenance.json").read_text())
        check(fails, provenance["canonical_source"] == "none", "no live source must mean canonical_source=none")
        check(fails, provenance["degraded"] is True, "must be marked degraded")
        check(fails, provenance["stale_retained"] is True, "existing local schedule must be flagged as stale-retained")
        check(fails, provenance["failure_reason"] == "all_live_schedule_sources_unavailable", "failure_reason wrong")
        check(fails, "2026-08-01" in stale.read_text(), "stale file must be left untouched for diagnostics")
    finally:
        shutil.rmtree(base, ignore_errors=True)
        _restore_env()
    return fails


def test_stale_csv_cannot_masquerade_as_current():
    fails = []
    base = Path(tempfile.mkdtemp(prefix="wnba_phase2_stale_"))
    (base / "data" / "raw").mkdir(parents=True)
    (base / "data" / "processed").mkdir(parents=True)
    os.environ["EDGERANKED_WNBA_BASE_DIR"] = str(base)
    for name in [m for m in list(sys.modules) if m.startswith("wnba_model")]:
        sys.modules.pop(name, None)
    try:
        gate = importlib.import_module("wnba_model.pipeline.publish_gate")
        (base / "data/raw/wnba_schedule_today.csv").write_text(
            "game_date,home_team,away_team,game_id,start_time_utc,_data_source\n"
            f"{SLATE_DATE},IND,LVA,1,2026-08-06T23:00Z,api:espn\n"
        )
        gate.write_json(
            gate.CANONICAL_PROVENANCE_PATH,
            {"canonical_source": "none", "degraded": True, "stale_retained": True,
             "failure_reason": "all_live_schedule_sources_unavailable", "slate_date": SLATE_DATE},
        )
        stale, reason = gate.canonical_provenance_is_stale()
        check(fails, stale is True, "provenance marked stale_retained must read back as stale")
        payload = gate.validate_canonical_slate(SLATE_DATE, context="test", write_manifest=False, collect_corroboration=False)
        check(fails, payload["status"] == ss.STATUS_FAIL, f"stale canonical slate must FAIL, got {payload['status']}")
        check(fails, payload["failure_reason"] == "canonical_schedule_is_stale", f"failure_reason wrong: {payload['failure_reason']}")
        check(fails, not ss.publication_allowed(payload), "stale canonical slate must block publication")
        check(fails, reason, "stale reason should be reported")
    finally:
        shutil.rmtree(base, ignore_errors=True)
        os.environ.pop("EDGERANKED_WNBA_BASE_DIR", None)
        for name in [m for m in list(sys.modules) if m.startswith("wnba_model")]:
            sys.modules.pop(name, None)
    return fails


def test_provenance_fields_complete():
    fails = []
    base, module = _acquisition_env()
    try:
        _acquire(module, ok_source(BASE_SLATE), failing_source(ss.SOURCE_HTTP_403, "yahoo", 403))
        provenance = json.loads((base / "data/processed/wnba_canonical_schedule_provenance.json").read_text())
        for field in ["canonical_source", "primary_source_status", "secondary_source_status", "slate_date",
                      "game_count", "fetched_at", "degraded", "failure_reason"]:
            check(fails, field in provenance, f"provenance missing required field '{field}'")
        check(fails, str(provenance["slate_date"]).count("-") == 2, "slate_date should be an ISO date")
    finally:
        shutil.rmtree(base, ignore_errors=True)
        _restore_env()
    return fails


# --- validator independence --------------------------------------------------
def test_canonical_yahoo_does_not_self_validate():
    fails = []

    # ESPN still down: only the canonical provider answers -> not a true PASS.
    espn_down = failing_source(ss.SOURCE_HTTP_403, "espn", 403)
    yahoo_ok = ok_source(BASE_SLATE, "yahoo")

    no_evidence = ss.run_slate_validation(
        SLATE_DATE, BASE_SLATE, primary_fetcher=espn_down, secondary_fetcher=yahoo_ok,
        canonical_source="api:yahoo", corroboration=corroboration(confirmed=False),
    )
    check(fails, no_evidence["status"] == ss.STATUS_FAIL, f"same-source-only must not PASS, got {no_evidence['status']}")
    check(fails, no_evidence["validation_independence"] == ss.INDEPENDENCE_SAME_SOURCE, "independence label wrong")
    check(fails, no_evidence["failure_reason"] == "same_source_validation_without_independent_evidence", "failure_reason wrong")
    check(fails, not ss.publication_allowed(no_evidence), "same-source-only must block publication")

    with_evidence = ss.run_slate_validation(
        SLATE_DATE, BASE_SLATE, primary_fetcher=espn_down, secondary_fetcher=yahoo_ok,
        canonical_source="api:yahoo", corroboration=corroboration(confirmed=True),
    )
    check(fails, with_evidence["status"] == ss.STATUS_DEGRADED_PASS, f"corroborated same-source should be DEGRADED_PASS, got {with_evidence['status']}")
    check(fails, with_evidence["status"] != ss.STATUS_PASS, "same-source evidence must never be a true PASS")
    check(fails, ss.publication_allowed(with_evidence), "corroborated same-source should still publish")

    contradicted = ss.run_slate_validation(
        SLATE_DATE, BASE_SLATE, primary_fetcher=espn_down, secondary_fetcher=yahoo_ok,
        canonical_source="api:yahoo", corroboration=corroboration(confirmed=True, contradicted=True),
    )
    check(fails, contradicted["status"] == ss.STATUS_FAIL, "a contradicting corroborator must FAIL the gate")

    # ESPN back up: the independent source is preferred and yields a true PASS.
    recovered = ss.run_slate_validation(
        SLATE_DATE, BASE_SLATE, primary_fetcher=ok_source(BASE_SLATE), secondary_fetcher=yahoo_ok,
        canonical_source="api:yahoo", corroboration=corroboration(confirmed=False),
    )
    check(fails, recovered["status"] == ss.STATUS_PASS, f"independent validator should PASS, got {recovered['status']}")
    check(fails, recovered["validator_source"] == "espn", f"expected espn validator, got {recovered['validator_source']}")
    check(fails, recovered["validation_independence"] == ss.INDEPENDENCE_INDEPENDENT, "independence label wrong")

    # Canonical from ESPN: Yahoo is preferred because it is the independent one.
    canonical_espn = ss.run_slate_validation(
        SLATE_DATE, BASE_SLATE, primary_fetcher=ok_source(BASE_SLATE), secondary_fetcher=yahoo_ok,
        canonical_source="api:espn", corroboration=corroboration(confirmed=False),
    )
    check(fails, canonical_espn["validator_source"] == "yahoo", f"expected yahoo validator, got {canonical_espn['validator_source']}")
    check(fails, canonical_espn["status"] == ss.STATUS_PASS, "independent validation of an ESPN slate should PASS")
    check(fails, ss.validator_order("api:espn")[0] == "yahoo", "validator order must put the independent source first")
    check(fails, ss.validator_order("api:yahoo")[0] == "espn", "validator order must put the independent source first")
    return fails


# --- late refresh integration ------------------------------------------------
def _late_refresh_module():
    for name in [m for m in list(sys.modules) if m.startswith("late_wnba_board_refresh")]:
        sys.modules.pop(name, None)
    return importlib.import_module("late_wnba_board_refresh")


def test_late_refresh_gate_allows_on_match():
    fails = []
    module = _late_refresh_module()
    original = (module.resolve_slate_status, module.require_validated_slate)
    try:
        module.resolve_slate_status = lambda: (SLATE_DATE, "selected_slate_date=test")
        module.require_validated_slate = lambda slate_date, context="": {
            "status": ss.STATUS_PASS, "validator_source": "yahoo", "validation_independence": ss.INDEPENDENCE_INDEPENDENT
        }
        check(fails, module.gate_or_block(_Logger()) is True, "matching slate must allow the late refresh")
    finally:
        module.resolve_slate_status, module.require_validated_slate = original
    return fails


def _late_refresh_blocked(failure_reason):
    fails = []
    module = _late_refresh_module()
    original = (module.resolve_slate_status, module.require_validated_slate, module.notify_freshness_monitor)
    calls = {"notified": 0}
    try:
        module.resolve_slate_status = lambda: (SLATE_DATE, "selected_slate_date=test")

        def blocked(slate_date, context=""):
            raise module.PublishBlocked(
                "blocked", category="slate_mismatch",
                manifest={"status": ss.STATUS_FAIL, "failure_reason": failure_reason},
            )

        module.require_validated_slate = blocked
        module.notify_freshness_monitor = lambda logger: calls.__setitem__("notified", calls["notified"] + 1)
        check(fails, module.gate_or_block(_Logger()) is False, f"{failure_reason}: gate must block the late refresh")
        check(fails, calls["notified"] == 1, f"{failure_reason}: blocked gate must trigger the freshness/alert mechanism")
    finally:
        module.resolve_slate_status, module.require_validated_slate, module.notify_freshness_monitor = original
    return fails


def test_late_refresh_blocked_on_mismatch():
    return _late_refresh_blocked("yahoo_slate_mismatch")


def test_late_refresh_blocked_when_validator_unavailable():
    return _late_refresh_blocked("validator_infrastructure_unavailable")


def test_late_refresh_main_does_not_touch_board_when_blocked():
    fails = []
    module = _late_refresh_module()
    original = module.gate_or_block
    try:
        module.gate_or_block = lambda logger: False
        before = module.BEST_BETS_PATH.read_bytes() if module.BEST_BETS_PATH.exists() else None
        code = module.main()
        check(fails, code == 3, f"blocked late refresh should exit 3, got {code}")
        after = module.BEST_BETS_PATH.read_bytes() if module.BEST_BETS_PATH.exists() else None
        check(fails, before == after, "blocked late refresh must leave the published board byte-identical")
    finally:
        module.gate_or_block = original
    return fails


# --- publish-path coverage guard ---------------------------------------------
def _wnba_publish_scripts() -> list[Path]:
    scripts = []
    for path in sorted(glob.glob(str(SITE_SCRIPTS / "*.sh"))):
        text = Path(path).read_text()
        publishes = "publish_render_site.sh" in text or "publish_render_snapshot.py" in text
        wnba = "PUBLISH_SPORTS=wnba" in text or 'publish_sport_enabled "wnba"' in text
        if publishes and wnba:
            scripts.append(Path(path))
    return scripts


def test_every_publish_entrypoint_is_gated():
    fails = []
    scripts = _wnba_publish_scripts()
    check(fails, len(scripts) >= 3, f"expected to find the known WNBA publish wrappers, found {[p.name for p in scripts]}")
    for path in scripts:
        text = path.read_text()
        check(fails, "publish_gate" in text, f"{path.name} publishes WNBA artifacts without calling the central slate gate")
        check(fails, "require_slate_gate" in text, f"{path.name} does not call require_slate_gate")
    for name in ["wnba_model/pipeline/service.py", "late_wnba_board_refresh.py"]:
        text = (WNBA / name).read_text()
        check(fails, "publish_gate" in text, f"{name} must reach the central slate gate")
    return fails


def test_guard_detects_a_bypassing_publish_path():
    """The guard itself must fail when a new publish path skips the gate."""
    fails = []
    rogue = SITE_SCRIPTS / "_test_rogue_wnba_publish.sh"
    try:
        rogue.write_text(
            "#!/usr/bin/env bash\n"
            "# deliberately bypasses validation\n"
            "EDGERANKED_PUBLISH_SPORTS=wnba bash scripts/publish_render_site.sh\n"
        )
        detected = test_every_publish_entrypoint_is_gated()
        check(fails, any("_test_rogue_wnba_publish.sh" in message for message in detected),
              "guard failed to detect a publish path that bypasses the gate")
    finally:
        rogue.unlink(missing_ok=True)
    residual = test_every_publish_entrypoint_is_gated()
    check(fails, not residual, f"guard should be clean once the rogue path is removed: {residual}")
    return fails


def test_single_policy_implementation():
    fails = []
    policy_markers = ["run_slate_validation(", "compare_slates("]
    owners = {"wnba_model/pipeline/slate_sources.py", "wnba_model/pipeline/publish_gate.py"}
    for path in WNBA.rglob("*.py"):
        rel = str(path.relative_to(WNBA))
        if rel.startswith((".venv", "backups", "slate_validation", "wnba_v2/")) or "__pycache__" in rel:
            continue
        if rel in owners:
            continue
        text = path.read_text(errors="ignore")
        for marker in policy_markers:
            check(fails, marker not in text, f"{rel} calls {marker} directly instead of using the publish gate")
    return fails


def main() -> None:
    tests = [
        ("1. canonical ESPN success", test_canonical_espn_success),
        ("2. canonical ESPN 403 -> Yahoo", test_canonical_espn_403_to_yahoo),
        ("3. canonical ESPN timeout -> Yahoo", test_canonical_espn_timeout_to_yahoo),
        ("4. both canonical sources unavailable -> no current slate", test_canonical_both_sources_unavailable),
        ("5. stale CSV cannot masquerade as today's slate", test_stale_csv_cannot_masquerade_as_current),
        ("6. canonical provenance written correctly", test_provenance_fields_complete),
        ("7. canonical=Yahoo never self-validates", test_canonical_yahoo_does_not_self_validate),
        ("8. late refresh match -> publish allowed", test_late_refresh_gate_allows_on_match),
        ("9. late refresh mismatch -> blocked", test_late_refresh_blocked_on_mismatch),
        ("10. late refresh validator unavailable -> blocked", test_late_refresh_blocked_when_validator_unavailable),
        ("11. blocked late refresh leaves the board untouched", test_late_refresh_main_does_not_touch_board_when_blocked),
        ("12. every publish entrypoint is gated", test_every_publish_entrypoint_is_gated),
        ("13. guard detects a bypassing publish path", test_guard_detects_a_bypassing_publish_path),
        ("14. one authoritative policy implementation", test_single_policy_implementation),
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
