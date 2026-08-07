"""Independent WNBA slate sources + slate-integrity validation policy.

Why this module exists
----------------------
The canonical WNBA slate is built ESPN-first (``fetch_wnba_data.resolve_schedule_today``).
Validating that canonical slate against ESPN alone therefore had two problems:

1. it is nearly self-validating (same provider, same feed), and
2. it made ESPN a single point of failure. On 2026-08-06 ESPN/Akamai began returning
   ``HTTP 403 Access Denied`` to the production server and the whole WNBA refresh stopped.

This module adds a genuinely independent secondary validator (Yahoo Sports' public
scoreboard feed: different provider, different CDN/WAF, no API key) and encodes the
failover policy so that:

* an unavailable *validator* never silently self-validates the canonical slate, and
* a real slate *disagreement* always fails hard.

Everything here is pure schedule metadata. No projection, model, scoring, simulation or
calibration behaviour lives in this module.
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

import pandas as pd


# --- team code normalization -------------------------------------------------
# Base aliases (historical, unchanged) plus the extra spellings the secondary
# provider uses. Applied to BOTH sides of every comparison, so a provider-specific
# spelling can never look like a slate mismatch.
WNBA_TEAM_ALIASES = {
    "GS": "GSV",
    "GSW": "GSV",
    "LV": "LVA",
    "NY": "NYL",
    "WSH": "WAS",
    "LA": "LAS",
    # secondary-provider spellings
    "PDX": "POR",   # Yahoo spells Portland PDX; canonical/ESPN uses POR
    "PHO": "PHX",
    "CONN": "CON",
}

# Full-name fallback, used only when a provider omits an abbreviation.
WNBA_TEAM_NAMES = {
    "ATLANTA DREAM": "ATL",
    "CHICAGO SKY": "CHI",
    "CONNECTICUT SUN": "CON",
    "DALLAS WINGS": "DAL",
    "GOLDEN STATE VALKYRIES": "GSV",
    "INDIANA FEVER": "IND",
    "LAS VEGAS ACES": "LVA",
    "LOS ANGELES SPARKS": "LAS",
    "MINNESOTA LYNX": "MIN",
    "NEW YORK LIBERTY": "NYL",
    "PHOENIX MERCURY": "PHX",
    "PORTLAND FIRE": "POR",
    "SEATTLE STORM": "SEA",
    "TORONTO TEMPO": "TOR",
    "WASHINGTON MYSTICS": "WAS",
}

EASTERN = "America/New_York"


def normalize_team_code(value: object, *, full_name: object = "") -> str:
    text = str(value or "").strip().upper()
    if text:
        return WNBA_TEAM_ALIASES.get(text, text)
    name = str(full_name or "").strip().upper()
    return WNBA_TEAM_NAMES.get(name, "")


# --- source status vocabulary ------------------------------------------------
SOURCE_OK = "OK"
SOURCE_HTTP_403 = "HTTP_403"
SOURCE_HTTP_429 = "HTTP_429"
SOURCE_HTTP_4XX = "HTTP_4XX"
SOURCE_HTTP_5XX = "HTTP_5XX"
SOURCE_TIMEOUT = "TIMEOUT"
SOURCE_NETWORK_ERROR = "NETWORK_ERROR"
SOURCE_PARSE_ERROR = "PARSE_ERROR"
SOURCE_MISMATCH = "MISMATCH"
SOURCE_NOT_ATTEMPTED = "NOT_ATTEMPTED"

# Statuses that mean "the validator could not be reached / could not answer".
# These trigger failover. They never mean "the slate is fine".
UNAVAILABLE_STATUSES = {
    SOURCE_HTTP_403,
    SOURCE_HTTP_429,
    SOURCE_HTTP_4XX,
    SOURCE_HTTP_5XX,
    SOURCE_TIMEOUT,
    SOURCE_NETWORK_ERROR,
    SOURCE_PARSE_ERROR,
}

# --- validation status vocabulary -------------------------------------------
STATUS_PASS = "PASS"
STATUS_DEGRADED_PASS = "DEGRADED_PASS"
STATUS_FAIL = "FAIL"

VALIDATOR_ESPN = "espn"
VALIDATOR_SECONDARY = "secondary"
VALIDATOR_NONE = "none"

PUBLIC_LABELS = {
    STATUS_PASS: "Verified",
    STATUS_DEGRADED_PASS: "Verified (secondary source)",
    STATUS_FAIL: "Not verified",
}

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
YAHOO_SCOREBOARD_URL = "https://api-secure.sports.yahoo.com/v1/editorial/s/scoreboard"
# Corroboration only — TheSportsDB's WNBA coverage is incomplete (observed missing one of
# three games on 2026-08-06), so it can confirm games but must never be authoritative.
THESPORTSDB_DAY_URL = "https://www.thesportsdb.com/api/v1/json/3/eventsday.php"

# How a canonical `_data_source` label maps onto a schedule-provider family. The validator
# must not treat a provider as independent evidence for a slate that same provider produced.
CANONICAL_SOURCE_FAMILIES = {
    "api:espn": "espn",
    "espn": "espn",
    "api:yahoo": "yahoo",
    "yahoo": "yahoo",
    "yahoo_sports": "yahoo",
    "api:stats_wnba": "stats_wnba",
    "stats_wnba": "stats_wnba",
}

VALIDATOR_SOURCES = ("espn", "yahoo")

INDEPENDENCE_INDEPENDENT = "independent"
INDEPENDENCE_SAME_SOURCE = "same_source_refetch"
INDEPENDENCE_UNKNOWN = "unknown"
INDEPENDENCE_NONE = "none"


def canonical_source_family(canonical_source: object) -> str:
    text = str(canonical_source or "").strip().lower()
    if not text:
        return "unknown"
    if text in CANONICAL_SOURCE_FAMILIES:
        return CANONICAL_SOURCE_FAMILIES[text]
    if text.startswith("csv"):
        return "csv"
    for label, family in CANONICAL_SOURCE_FAMILIES.items():
        if label in text:
            return family
    return "unknown"


def validator_order(canonical_source: object) -> list:
    """Validator sources, most independent first.

    A provider that produced the canonical slate is demoted to last: re-fetching it can only
    corroborate the write/normalize path, never the slate itself.
    """
    family = canonical_source_family(canonical_source)
    independent = [name for name in VALIDATOR_SOURCES if name != family]
    same_source = [name for name in VALIDATOR_SOURCES if name == family]
    return independent + same_source

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_ATTEMPTS = 2
DEFAULT_RETRY_SLEEP_SECONDS = 2.0
DEFAULT_TIME_TOLERANCE_MINUTES = 15


def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default


@dataclass
class SlateFetchResult:
    """Outcome of one attempt to read a slate from an external provider."""

    source: str
    url: str
    status: str = SOURCE_OK
    rows: list = field(default_factory=list)
    http_code: object = None
    detail: str = ""  # internal-only; never rendered to customers

    @property
    def ok(self) -> bool:
        return self.status == SOURCE_OK


def classify_fetch_exception(exc: BaseException) -> tuple[str, object]:
    """Map a transport exception onto the source-status vocabulary."""
    if isinstance(exc, urllib.error.HTTPError):
        code = int(getattr(exc, "code", 0) or 0)
        if code == 403:
            return SOURCE_HTTP_403, code
        if code == 429:
            return SOURCE_HTTP_429, code
        if 500 <= code <= 599:
            return SOURCE_HTTP_5XX, code
        return SOURCE_HTTP_4XX, code
    if isinstance(exc, (TimeoutError, )):
        return SOURCE_TIMEOUT, None
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, )) or "timed out" in str(reason).lower():
            return SOURCE_TIMEOUT, None
        return SOURCE_NETWORK_ERROR, None
    if "timed out" in str(exc).lower():
        return SOURCE_TIMEOUT, None
    if isinstance(exc, (json.JSONDecodeError, ValueError, KeyError, TypeError)):
        return SOURCE_PARSE_ERROR, None
    return SOURCE_NETWORK_ERROR, None


def _get_json(url: str, headers: dict) -> dict:
    request = urllib.request.Request(url, headers=headers)
    timeout = _int_env("WNBA_SLATE_FETCH_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_with_retry(source: str, url: str, headers: dict, parser) -> SlateFetchResult:
    """Fetch + parse, retrying only transient/blocked responses.

    A retry is worth one extra request: the 2026-08-06 ESPN block was intermittent
    (edge nodes returned 200 and 403 seconds apart), so a single retry avoids
    failing over on a one-off edge rejection.
    """
    attempts = max(1, _int_env("WNBA_SLATE_FETCH_ATTEMPTS", DEFAULT_ATTEMPTS))
    sleep_seconds = _float_env("WNBA_SLATE_FETCH_RETRY_SLEEP", DEFAULT_RETRY_SLEEP_SECONDS)
    last = SlateFetchResult(source=source, url=url, status=SOURCE_NETWORK_ERROR)
    for attempt in range(1, attempts + 1):
        try:
            payload = _get_json(url, headers)
        except Exception as exc:  # noqa: BLE001 - classified below
            status, code = classify_fetch_exception(exc)
            last = SlateFetchResult(
                source=source,
                url=url,
                status=status,
                http_code=code,
                detail=f"attempt {attempt}/{attempts}: {type(exc).__name__}: {exc}",
            )
            if attempt < attempts and status in UNAVAILABLE_STATUSES:
                time.sleep(sleep_seconds)
                continue
            return last
        try:
            rows = parser(payload)
        except Exception as exc:  # noqa: BLE001 - malformed payload
            return SlateFetchResult(
                source=source,
                url=url,
                status=SOURCE_PARSE_ERROR,
                detail=f"{type(exc).__name__}: {exc}",
            )
        return SlateFetchResult(source=source, url=url, status=SOURCE_OK, rows=rows, http_code=200)
    return last


def _normalized_row(game_id: object, away: str, home: str, start: object) -> dict:
    start_ts = pd.to_datetime(start, utc=True, errors="coerce")
    return {
        "game_id": str(game_id or ""),
        "home_team": home,
        "away_team": away,
        "start_time_utc": "" if pd.isna(start_ts) else start_ts.strftime("%Y-%m-%dT%H:%MZ"),
    }


def _sorted_rows(rows: list) -> list:
    return sorted(rows, key=lambda item: (item["start_time_utc"], item["away_team"], item["home_team"]))


def filter_rows_to_et_day(rows: list, slate_date: object) -> list:
    """Keep rows whose tip-off falls inside the Eastern calendar day of ``slate_date``.

    Both providers group their scoreboards by the ET day, and the canonical slate is
    already ET-filtered upstream, so this only guards against a provider returning
    neighbouring days in the same payload.
    """
    target = pd.Timestamp(slate_date).date()
    kept = []
    for row in rows:
        start = pd.to_datetime(row.get("start_time_utc"), utc=True, errors="coerce")
        if pd.isna(start):
            kept.append(row)  # undated rows are compared as-is (and will surface as mismatches)
            continue
        if start.tz_convert(EASTERN).date() == target:
            kept.append(row)
    return kept


# --- primary source: ESPN ----------------------------------------------------
def parse_espn_payload(payload: dict) -> list:
    rows = []
    for event in payload.get("events", []) or []:
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors", []) or []
        home = next((item for item in competitors if item.get("homeAway") == "home"), None)
        away = next((item for item in competitors if item.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        home_team = home.get("team") or {}
        away_team = away.get("team") or {}
        rows.append(
            _normalized_row(
                event.get("id", ""),
                normalize_team_code(away_team.get("abbreviation", ""), full_name=away_team.get("displayName", "")),
                normalize_team_code(home_team.get("abbreviation", ""), full_name=home_team.get("displayName", "")),
                event.get("date", ""),
            )
        )
    return _sorted_rows(rows)


def fetch_espn_slate(slate_date: object) -> SlateFetchResult:
    url = f"{ESPN_SCOREBOARD_URL}?dates={pd.Timestamp(slate_date).strftime('%Y%m%d')}"
    result = _fetch_with_retry(
        "espn",
        url,
        {"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        parse_espn_payload,
    )
    if result.ok:
        result.rows = _sorted_rows(filter_rows_to_et_day(result.rows, slate_date))
    return result


# --- secondary source: Yahoo Sports -----------------------------------------
def _yahoo_start_time(value: object) -> object:
    """Yahoo returns RFC-2822 timestamps ('Thu, 06 Aug 2026 23:00:00 +0000')."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return text


def parse_yahoo_payload(payload: dict) -> list:
    scoreboard = ((payload or {}).get("service") or {}).get("scoreboard") or {}
    teams = scoreboard.get("teams") or {}
    rows = []
    for game_id, game in (scoreboard.get("games") or {}).items():
        if not isinstance(game, dict):
            continue
        home = teams.get(game.get("home_team_id")) or {}
        away = teams.get(game.get("away_team_id")) or {}
        home_code = normalize_team_code(home.get("abbr", ""), full_name=home.get("full_name", ""))
        away_code = normalize_team_code(away.get("abbr", ""), full_name=away.get("full_name", ""))
        if not home_code or not away_code:
            continue
        rows.append(_normalized_row(game_id, away_code, home_code, _yahoo_start_time(game.get("start_time"))))
    return _sorted_rows(rows)


def fetch_yahoo_slate(slate_date: object) -> SlateFetchResult:
    date_text = pd.Timestamp(slate_date).strftime("%Y-%m-%d")
    url = f"{YAHOO_SCOREBOARD_URL}?leagues=wnba&date={date_text}"
    result = _fetch_with_retry(
        "yahoo",
        url,
        {"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        parse_yahoo_payload,
    )
    if result.ok:
        result.rows = _sorted_rows(filter_rows_to_et_day(result.rows, slate_date))
    return result


# --- corroboration source: TheSportsDB (never authoritative) ----------------
def parse_thesportsdb_payload(payload: dict) -> list:
    rows = []
    for event in (payload or {}).get("events") or []:
        if not str(event.get("strLeague", "")).upper().startswith("WNBA"):
            continue
        home = normalize_team_code(event.get("strHomeTeamShort", ""), full_name=event.get("strHomeTeam", ""))
        away = normalize_team_code(event.get("strAwayTeamShort", ""), full_name=event.get("strAwayTeam", ""))
        if not home or not away:
            continue
        stamp = event.get("strTimestamp") or f"{event.get('dateEvent', '')}T{event.get('strTime', '')}"
        rows.append(_normalized_row(event.get("idEvent", ""), away, home, f"{stamp}Z" if stamp and not str(stamp).endswith("Z") else stamp))
    return _sorted_rows(rows)


def fetch_thesportsdb_slate(slate_date: object) -> SlateFetchResult:
    """Corroboration feed. Groups by UTC day, so both UTC days touching the ET slate are read."""
    target = pd.Timestamp(slate_date)
    urls = [
        f"{THESPORTSDB_DAY_URL}?d={(target + pd.Timedelta(days=offset)).strftime('%Y-%m-%d')}&s=Basketball"
        for offset in (0, 1)
    ]
    rows = []
    last_failure = None
    for url in urls:
        result = _fetch_with_retry("thesportsdb", url, {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, parse_thesportsdb_payload)
        if not result.ok:
            last_failure = result
            continue
        rows.extend(result.rows)
    if last_failure is not None and not rows:
        return last_failure
    seen = set()
    unique = []
    for item in _sorted_rows(rows):
        key = (item["away_team"], item["home_team"], item["start_time_utc"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return SlateFetchResult(
        source="thesportsdb",
        url=urls[0],
        status=SOURCE_OK,
        rows=filter_rows_to_et_day(unique, slate_date),
        http_code=200,
        detail="" if last_failure is None else f"partial: {last_failure.detail}",
    )


CORROBORATION_CONFIRMED = "CONFIRMED"
CORROBORATION_CONTRADICTED = "CONTRADICTED"
CORROBORATION_INCONCLUSIVE = "INCONCLUSIVE"
CORROBORATION_UNAVAILABLE = "UNAVAILABLE"


def corroborate_subset(generated: list, result: SlateFetchResult) -> dict:
    """Subset check: every game the corroborator knows about must exist in the canonical slate.

    The corroborator may know about fewer games (incomplete coverage) without penalty; a game
    it reports that the canonical slate does not contain is a contradiction.
    """
    record = {
        "name": result.source,
        "status": result.status,
        "verdict": CORROBORATION_UNAVAILABLE,
        "confirmed_games": 0,
        "contradictions": [],
        "detail": result.detail,
    }
    if not result.ok:
        return record
    generated_keys = {_matchup_key(row) for row in generated}
    contradictions = []
    confirmed = 0
    for row in result.rows:
        if _matchup_key(row) in generated_keys:
            confirmed += 1
        else:
            contradictions.append([row.get("away_team", ""), row.get("home_team", "")])
    record["confirmed_games"] = confirmed
    record["contradictions"] = contradictions
    if contradictions:
        record["verdict"] = CORROBORATION_CONTRADICTED
    elif confirmed:
        record["verdict"] = CORROBORATION_CONFIRMED
    else:
        record["verdict"] = CORROBORATION_INCONCLUSIVE
    return record


def summarize_corroboration(records: list) -> dict:
    records = list(records or [])
    return {
        "sources": records,
        "confirmed": any(item.get("verdict") == CORROBORATION_CONFIRMED for item in records),
        "contradicted": any(item.get("verdict") == CORROBORATION_CONTRADICTED for item in records),
    }


# --- comparison --------------------------------------------------------------
def _matchup_key(row: dict) -> tuple:
    return (str(row.get("away_team", "")), str(row.get("home_team", "")))


def _minutes_between(left: str, right: str) -> object:
    left_ts = pd.to_datetime(left, utc=True, errors="coerce")
    right_ts = pd.to_datetime(right, utc=True, errors="coerce")
    if pd.isna(left_ts) or pd.isna(right_ts):
        return None
    return abs((left_ts - right_ts).total_seconds()) / 60.0


def compare_slates(
    generated: list,
    trusted: list,
    slate_date: object,
    *,
    tolerance_minutes: float = DEFAULT_TIME_TOLERANCE_MINUTES,
) -> dict:
    """Compare canonical vs trusted slates.

    Hard-integrity rules (any violation fails):
      * game count must match exactly
      * no missing games, no unexpected games, no duplicated matchups
      * every canonical game must fall on ``slate_date`` (Eastern)
      * start times may differ by at most ``tolerance_minutes``

    Start-time differences inside the tolerance window are recorded but never fail:
    providers routinely disagree by a few minutes on tip-off.
    """
    generated_keys = Counter(_matchup_key(row) for row in generated)
    trusted_keys = Counter(_matchup_key(row) for row in trusted)

    duplicates = sorted(key for key, count in generated_keys.items() if count > 1)
    missing = sorted((trusted_keys - generated_keys).elements())
    unexpected = sorted((generated_keys - trusted_keys).elements())

    target_date = pd.Timestamp(slate_date).date()
    wrong_date = []
    for row in generated:
        start = pd.to_datetime(row.get("start_time_utc"), utc=True, errors="coerce")
        if pd.isna(start):
            wrong_date.append([row.get("away_team", ""), row.get("home_team", ""), ""])
            continue
        row_date = start.tz_convert(EASTERN).date()
        if row_date != target_date:
            wrong_date.append([row.get("away_team", ""), row.get("home_team", ""), str(row_date)])

    trusted_by_key = {}
    for row in trusted:
        trusted_by_key.setdefault(_matchup_key(row), row)

    time_discrepancies = []
    material_time_differences = []
    for row in generated:
        key = _matchup_key(row)
        partner = trusted_by_key.get(key)
        if not partner:
            continue
        delta = _minutes_between(row.get("start_time_utc", ""), partner.get("start_time_utc", ""))
        if delta is None or delta <= 0:
            continue
        record = {
            "away_team": key[0],
            "home_team": key[1],
            "generated_start_time_utc": row.get("start_time_utc", ""),
            "trusted_start_time_utc": partner.get("start_time_utc", ""),
            "delta_minutes": round(float(delta), 2),
            "within_tolerance": bool(delta <= tolerance_minutes),
        }
        time_discrepancies.append(record)
        if not record["within_tolerance"]:
            material_time_differences.append(record)

    reasons = []
    if len(generated) != len(trusted):
        reasons.append("game_count_mismatch")
    if missing:
        reasons.append("missing_games")
    if unexpected:
        reasons.append("unexpected_games")
    if duplicates:
        reasons.append("duplicate_games")
    if wrong_date:
        reasons.append("slate_date_mismatch")
    if material_time_differences:
        reasons.append("material_start_time_difference")

    return {
        "expected_game_count": len(trusted),
        "generated_game_count": len(generated),
        "missing_games": [list(key) for key in missing],
        "unexpected_games": [list(key) for key in unexpected],
        "duplicate_games": [list(key) for key in duplicates],
        "wrong_date_games": wrong_date,
        "time_tolerance_minutes": tolerance_minutes,
        "time_discrepancies": time_discrepancies,
        "material_time_differences": material_time_differences,
        "match": not reasons,
        "mismatch_reasons": reasons,
    }


# --- failover policy ---------------------------------------------------------
def run_slate_validation(
    slate_date: object,
    generated: list,
    *,
    primary_fetcher=None,
    secondary_fetcher=None,
    tolerance_minutes: float | None = None,
    canonical_source: object = None,
    corroboration: dict | None = None,
) -> dict:
    """Validate the canonical slate against external sources.

    Legacy mode (``canonical_source`` omitted) keeps the Phase 1 policy: ESPN first
    (PASS), Yahoo on ESPN failure (DEGRADED_PASS), neither -> FAIL.

    Independence mode (``canonical_source`` given) additionally guarantees the validator
    is not the provider that produced the canonical slate:

    * validator independent of the canonical source, agrees .... PASS
    * only the canonical source itself can be re-fetched, it agrees, and at least one
      independent corroborator confirms with no contradiction ... DEGRADED_PASS
    * same-source re-fetch with no independent evidence ......... FAIL
    * any available validator disagrees .......................... FAIL (final; other
      sources are never consulted to override a real disagreement)
    * no validator answers ....................................... FAIL

    The canonical slate is never compared against itself in any path.
    """
    if tolerance_minutes is None:
        tolerance_minutes = _float_env("WNBA_SLATE_TIME_TOLERANCE_MINUTES", DEFAULT_TIME_TOLERANCE_MINUTES)

    fetchers = {
        "espn": primary_fetcher or fetch_espn_slate,
        "yahoo": secondary_fetcher or fetch_yahoo_slate,
    }
    legacy_mode = canonical_source is None
    order = list(VALIDATOR_SOURCES) if legacy_mode else validator_order(canonical_source)
    family = "unknown" if legacy_mode else canonical_source_family(canonical_source)

    generated = _sorted_rows(list(generated))
    corroboration = corroboration or {"sources": [], "confirmed": False, "contradicted": False}

    payload = {
        "generated_at": pd.Timestamp.now(tz=EASTERN).isoformat(),
        "slate_date": str(pd.Timestamp(slate_date).date()),
        "canonical_source": None if legacy_mode else str(canonical_source),
        "canonical_source_family": family,
        "validator_order": order,
        "primary_source": "espn",
        "primary_source_url": ESPN_SCOREBOARD_URL,
        "secondary_source": "yahoo_sports",
        "secondary_source_url": YAHOO_SCOREBOARD_URL,
        "primary_source_status": SOURCE_NOT_ATTEMPTED,
        "secondary_source_status": SOURCE_NOT_ATTEMPTED,
        "validator_used": VALIDATOR_NONE,
        "validator_source": "",
        "validation_independence": INDEPENDENCE_NONE,
        "corroboration": corroboration,
        "trusted_source": "",
        "generated_games": generated,
        "trusted_games": [],
        "generated_game_count": len(generated),
        "expected_game_count": None,
        "missing_games": [],
        "unexpected_games": [],
        "duplicate_games": [],
        "wrong_date_games": [],
        "time_tolerance_minutes": tolerance_minutes,
        "time_discrepancies": [],
        "material_time_differences": [],
        "mismatch_reasons": [],
        "failure_reason": "",
        "internal_detail": "",
        "degraded_validation": False,
        "status": STATUS_FAIL,
    }

    def _record_source(result: SlateFetchResult, status: str | None = None) -> None:
        role = "primary" if result.source == "espn" else "secondary"
        payload[f"{role}_source_status"] = status or result.status
        payload[f"{role}_http_code"] = result.http_code
        if result.detail:
            joiner = "; " if payload["internal_detail"] else ""
            payload["internal_detail"] += f"{joiner}{result.source}: {result.detail}"

    for index, name in enumerate(order):
        result = fetchers[name](slate_date)
        _record_source(result)
        if not result.ok:
            continue

        independence = INDEPENDENCE_UNKNOWN if legacy_mode else (
            INDEPENDENCE_SAME_SOURCE if name == family else INDEPENDENCE_INDEPENDENT
        )
        comparison = compare_slates(generated, result.rows, slate_date, tolerance_minutes=tolerance_minutes)
        payload.update(comparison)
        payload["trusted_games"] = result.rows
        payload["trusted_source"] = result.url
        payload["validator_source"] = name
        payload["validator_used"] = VALIDATOR_ESPN if name == "espn" else VALIDATOR_SECONDARY
        payload["validation_independence"] = independence

        if not comparison["match"]:
            # A real disagreement from a reachable source is final: never shop for a
            # second opinion that would override an integrity failure.
            _record_source(result, SOURCE_MISMATCH)
            payload["status"] = STATUS_FAIL
            payload["failure_reason"] = f"{name}_slate_mismatch" if not legacy_mode else (
                "primary_source_slate_mismatch" if index == 0 else "secondary_source_slate_mismatch"
            )
            payload["public_label"] = PUBLIC_LABELS[STATUS_FAIL]
            return payload

        if legacy_mode:
            payload["status"] = STATUS_PASS if index == 0 else STATUS_DEGRADED_PASS
        elif independence == INDEPENDENCE_INDEPENDENT:
            payload["status"] = STATUS_PASS
        elif corroboration.get("contradicted"):
            payload["status"] = STATUS_FAIL
            payload["failure_reason"] = "independent_corroborator_contradicted_slate"
        elif corroboration.get("confirmed"):
            # Only the canonical provider could be re-fetched, but an unrelated feed
            # independently confirms the slate. Weaker than PASS, still evidence-backed.
            payload["status"] = STATUS_DEGRADED_PASS
        else:
            payload["status"] = STATUS_FAIL
            payload["failure_reason"] = "same_source_validation_without_independent_evidence"

        if payload["status"] == STATUS_DEGRADED_PASS:
            payload["degraded_validation"] = True
            payload["degraded_reason"] = (
                "same_source_refetch_with_independent_corroboration"
                if independence == INDEPENDENCE_SAME_SOURCE
                else "primary_source_unavailable"
            )
        payload["public_label"] = PUBLIC_LABELS[payload["status"]]
        return payload

    payload["status"] = STATUS_FAIL
    payload["validator_used"] = VALIDATOR_NONE
    payload["validation_independence"] = INDEPENDENCE_NONE
    payload["failure_reason"] = "validator_infrastructure_unavailable"
    payload["public_label"] = PUBLIC_LABELS[STATUS_FAIL]
    return payload


PUBLISHABLE_STATUSES = {STATUS_PASS, STATUS_DEGRADED_PASS}


def publication_allowed(payload: dict) -> bool:
    return str(payload.get("status")) in PUBLISHABLE_STATUSES
