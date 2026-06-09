"""
Auto-backfill MLB live-lineup players that are missing from the hitter
projection / history pool (call-ups, prospects, mid-season trades, etc.).

This script is ADDITIVE-ONLY. It does not modify the MLB model architecture,
prediction formulas, predict_hitter.py, predict_pitchers.py, publishers,
APIs, frontend routes, cron schedules, or AWS configs. It only:

  1. Fetches today's confirmed/projected lineups directly from the MLB
     StatsAPI (the same public source the rest of the pipeline uses).
  2. Compares each lineup hitter against the existing hitter cache pool
     under the active production tree.
  3. For any hitter that is missing from the pool, writes a conservative
     rookie/prospect baseline cache row, marked with:
         data_quality = "rookie_baseline"
         data_source  = "auto_callup_backfill"
     so the downstream hitter projection model finds the player and never
     silently skips them.
  4. Writes an audit row per backfilled player to:
         /home/ubuntu/EdgeRanked/site/mlb/outputs/callup_audit_today.csv
     with columns:
         date, player_name, team, opponent, position,
         baseline_method, confidence, notes

Production paths:
  Source:     /home/ubuntu/EdgeRanked/site/mlb/
  Cache:      /home/ubuntu/EdgeRanked/site/mlb/data/cache/hitters/
              (overridable via env EDGERANKED_HITTER_CACHE_DIR)
  Audit out:  /home/ubuntu/EdgeRanked/site/mlb/outputs/callup_audit_today.csv
              (overridable via env EDGERANKED_MLB_OUTPUTS_DIR)
  Live tgt:   /home/ubuntu/edgeranked-sportsai/mlb/outputs/ (read-only — used
              as the canonical "in projection pool" reference)

Safety:
  - Missing hitters NEVER crash the pipeline. All failures are logged and
    swallowed; the script always exits 0 on hitter-side issues.
  - The script never overwrites an existing hitter cache file.
  - No existing files (other than this day's audit CSV) are modified.

Wiring: the daily pipeline (run_mlb_day.sh) invokes this script BEFORE the
hitter projection step.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ── Active production paths ─────────────────────────────────────────────────
SITE_ROOT = Path(
    os.environ.get("EDGERANKED_SITE_MLB_DIR")
    or "/home/ubuntu/EdgeRanked/site/mlb"
).resolve()

OUTPUTS_DIR = Path(
    os.environ.get("EDGERANKED_MLB_OUTPUTS_DIR")
    or (SITE_ROOT / "outputs")
).resolve()

HITTER_CACHE_DIR = Path(
    os.environ.get("EDGERANKED_HITTER_CACHE_DIR")
    or (SITE_ROOT / "data" / "cache" / "hitters")
).resolve()

# Pool sources: a player is "in the projection / history pool" if their id or
# normalized name appears in any of these recent projection outputs. The list
# is ordered from live publish target → site staging. Only paths that exist
# are read.
LIVE_PUBLISH_OUTPUTS = Path(
    os.environ.get("EDGERANKED_LIVE_MLB_OUTPUTS_DIR")
    or "/home/ubuntu/edgeranked-sportsai/mlb/outputs"
).resolve()

POOL_SOURCES = [
    LIVE_PUBLISH_OUTPUTS / "hitter_predictions_full.csv",
    LIVE_PUBLISH_OUTPUTS / "hitter_predictions_today.csv",
    OUTPUTS_DIR / "hitter_predictions_full.csv",
    OUTPUTS_DIR / "hitter_predictions_today.csv",
]

AUDIT_CSV = OUTPUTS_DIR / "callup_audit_today.csv"

AUDIT_COLUMNS = [
    "date",
    "player_name",
    "team",
    "opponent",
    "position",
    "baseline_method",
    "confidence",
    "notes",
]

# ── MLB StatsAPI (public) — the same source the existing pipeline uses ───────
SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
BOXSCORE_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
PEOPLE_URL = "https://statsapi.mlb.com/api/v1/people/{person_id}"
YBY_URL = (
    "https://statsapi.mlb.com/api/v1/people/{person_id}/stats"
    "?stats=yearByYear&group=hitting"
)


def _log(msg: str) -> None:
    print(f"[CALLUP-BACKFILL] {msg}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Lineup fetch (StatsAPI)
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_json(url: str, timeout: int = 20) -> Optional[Dict[str, Any]]:
    try:
        import requests  # type: ignore
    except Exception:
        return None
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _get_today_schedule(target_date: str) -> List[Dict[str, Any]]:
    url = f"{SCHEDULE_URL}?sportId=1&date={target_date}&hydrate=team,probablePitcher"
    data = _fetch_json(url) or {}
    dates = data.get("dates") or []
    if not dates:
        return []
    return dates[0].get("games") or []


def _get_lineup_from_boxscore(game_pk: int) -> Dict[str, List[Dict[str, Any]]]:
    """Return confirmed (or projected) hitters for a game.

    Mirrors the public StatsAPI shape the rest of the pipeline already uses.
    """
    url = BOXSCORE_URL.format(game_pk=game_pk)
    data = _fetch_json(url) or {}

    result: Dict[str, List[Dict[str, Any]]] = {"home": [], "away": []}

    for side in ("home", "away"):
        team_obj = data.get("teams", {}).get(side, {}) or {}
        team_name = team_obj.get("team", {}).get("name", "") or ""
        players = team_obj.get("players", {}) or {}

        confirmed: List[Dict[str, Any]] = []
        projected: List[Dict[str, Any]] = []

        for p in players.values():
            person = p.get("person", {}) or {}
            pid = person.get("id")
            pname = person.get("fullName")
            position_type = (p.get("position", {}) or {}).get("type", "") or ""

            if not pid or not pname:
                continue

            batting_order = p.get("battingOrder")

            if batting_order:
                confirmed.append({
                    "player_id": pid,
                    "name": pname,
                    "team": team_name,
                    "order": batting_order,
                })
            elif position_type != "Pitcher":
                projected.append({
                    "player_id": pid,
                    "name": pname,
                    "team": team_name,
                    "order": None,
                })

        if confirmed:
            try:
                confirmed = sorted(confirmed, key=lambda x: int(x["order"]))
            except Exception:
                pass
            result[side] = confirmed
        else:
            result[side] = projected

    return result


def _collect_today_lineups(target_date: str) -> List[Dict[str, Any]]:
    """Yield {hitter_id, hitter_name, team, opponent} for every lineup hitter today."""
    out: List[Dict[str, Any]] = []
    games = _get_today_schedule(target_date)
    _log(f"Schedule date: {target_date} | Games found: {len(games)}")
    for g in games:
        try:
            game_pk = int(g.get("gamePk"))
        except Exception:
            continue
        home_team = (g.get("teams", {}).get("home", {}) or {}).get("team", {}) or {}
        away_team = (g.get("teams", {}).get("away", {}) or {}).get("team", {}) or {}
        home_name = home_team.get("name") or ""
        away_name = away_team.get("name") or ""

        try:
            sides = _get_lineup_from_boxscore(game_pk)
        except Exception as exc:
            _log(f"WARNING: lineup lookup failed for game {game_pk}: {exc}")
            continue

        for hitter in sides.get("away", []):
            out.append({
                "hitter_id": hitter["player_id"],
                "hitter_name": hitter["name"],
                "team": hitter["team"] or away_name,
                "opponent": home_name,
                "order": hitter.get("order"),
            })
        for hitter in sides.get("home", []):
            out.append({
                "hitter_id": hitter["player_id"],
                "hitter_name": hitter["name"],
                "team": hitter["team"] or home_name,
                "opponent": away_name,
                "order": hitter.get("order"),
            })
    return out


def _fetch_player_position(hitter_id: int) -> str:
    data = _fetch_json(PEOPLE_URL.format(person_id=int(hitter_id)), timeout=10) or {}
    people = data.get("people") or []
    if not people:
        return ""
    pos = (people[0].get("primaryPosition") or {}).get("abbreviation") or ""
    return str(pos)


def _fetch_milb_baseline(hitter_id: int) -> Optional[Dict[str, Any]]:
    """Best-effort MiLB / yearByYear lookup for a prospect.

    If the player has measurable minor-league or prior-year MLB data, derive
    a heavily-regressed conservative baseline from it. Bounded so it cannot
    create elite projections from a tiny sample.
    """
    payload = _fetch_json(YBY_URL.format(person_id=int(hitter_id)), timeout=15)
    if not payload:
        return None

    try:
        splits = payload.get("stats", [{}])[0].get("splits", []) or []
    except Exception:
        splits = []

    if not splits:
        return None

    rows: List[Dict[str, float]] = []
    for s in splits:
        stat = s.get("stat", {}) or {}
        try:
            pa = float(stat.get("plateAppearances") or 0.0)
            ab = float(stat.get("atBats") or 0.0)
            games = float(stat.get("gamesPlayed") or 0.0)
            avg = float(stat.get("avg") or 0.0)
            obp = float(stat.get("obp") or 0.0)
            slg = float(stat.get("slg") or 0.0)
            ops = float(stat.get("ops") or (obp + slg))
            hr = float(stat.get("homeRuns") or 0.0)
            tb = float(stat.get("totalBases") or 0.0)
        except Exception:
            continue
        if pa < 50 or games < 15:
            continue
        rows.append({
            "pa": pa, "ab": ab, "games": games, "avg": avg, "obp": obp,
            "slg": slg, "ops": ops, "hr": hr, "tb": tb,
        })

    if not rows:
        return None

    total_pa = sum(r["pa"] for r in rows)
    if total_pa <= 0:
        return None

    def w(key: str) -> float:
        return sum(r[key] * r["pa"] for r in rows) / total_pa

    avg_w = w("avg")
    obp_w = w("obp")
    slg_w = w("slg")
    ops_w = w("ops")
    total_games = max(1.0, sum(r["games"] for r in rows))
    hr_w = sum(r["hr"] for r in rows) / total_games
    tb_per_game_w = sum(r["tb"] for r in rows) / total_games

    avg_proj = max(0.215, min(0.275, avg_w * 0.78 + 0.230 * 0.22))
    obp_proj = max(0.275, min(0.345, obp_w * 0.80 + 0.300 * 0.20))
    slg_proj = max(0.340, min(0.460, slg_w * 0.78 + 0.380 * 0.22))
    ops_proj = obp_proj + slg_proj
    iso_proj = max(0.080, min(0.230, slg_proj - avg_proj))
    hr_rate_proj = max(0.012, min(0.085, hr_w * 0.65))
    tb_per_game_proj = max(0.70, min(1.55, tb_per_game_w * 0.78))

    return {
        "season_avg": avg_proj,
        "season_obp": obp_proj,
        "season_slg": slg_proj,
        "season_ops": ops_proj,
        "xBA": avg_proj,
        "xSLG": slg_proj,
        "xwOBA": obp_proj,
        "xISO": iso_proj,
        "xOBP": obp_proj,
        "vs_lhp_avg": avg_proj,
        "vs_rhp_avg": avg_proj,
        "vs_lhp_ops": ops_proj,
        "vs_rhp_ops": ops_proj,
        "last_30_avg": avg_proj,
        "last_30_obp": obp_proj,
        "last_30_slg": slg_proj,
        "last_30_ops": ops_proj,
        "last_7_ops": ops_proj,
        "last_15_ops": ops_proj,
        "historical_sample_games": float(min(120.0, total_games)),
        "historical_hr_game_rate": hr_rate_proj,
        "historical_tb_per_game": tb_per_game_proj,
        "historical_power_ops": ops_proj,
        "historical_xslg": slg_proj,
        "historical_xiso": iso_proj,
        "historical_official_pa": float(total_pa),
        "historical_prior_source": "auto_callup_backfill_milb_yearbyyear",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Conservative defaults
# ─────────────────────────────────────────────────────────────────────────────

def _league_average_rookie_row(hitter_name: str, hitter_id: int) -> Dict[str, Any]:
    """Conservative league-average baseline for a prospect with no MiLB
    yearByYear signal. Values are deliberately below-league-average so the
    projection model cannot generate elite output from them.
    """
    return {
        "hitter_name": hitter_name,
        "hitter_id": int(hitter_id),
        "historical_sample_games": 0.0,
        "historical_hr_game_rate": 0.025,
        "historical_tb_per_game": 0.95,
        "historical_power_ops": 0.660,
        "historical_xslg": 0.370,
        "historical_xiso": 0.130,
        "historical_barrel_rate": 5.5,
        "historical_hard_hit_rate": 36.0,
        "historical_avg_ev": 87.5,
        "historical_max_ev": 106.0,
        "historical_sweet_spot_rate": 31.0,
        "season_pa": 0.0,
        "season_ab": 0.0,
        "season_avg": 0.230,
        "season_obp": 0.295,
        "season_slg": 0.370,
        "season_ops": 0.665,
        "xBA": 0.230,
        "xSLG": 0.370,
        "xwOBA": 0.295,
        "xISO": 0.140,
        "xOBP": 0.295,
        "season_k_pct": 0.25,
        "season_bb_pct": 0.07,
        "stolen_bases": 2.0,
        "caught_stealing": 1.0,
        "stolen_base_attempt_rate": 0.012,
        "oswing_percent": 31.0,
        "zswing_percent": 64.0,
        "contact_percent": 73.0,
        "whiff_percent": 27.0,
        "chase_percent": 30.0,
        "vs_lhp_avg": 0.225,
        "vs_rhp_avg": 0.230,
        "vs_lhp_ops": 0.660,
        "vs_rhp_ops": 0.665,
        "barrel_rate": 5.5,
        "hard_hit_rate": 36.0,
        "avg_ev": 87.5,
        "max_ev": 106.0,
        "sweet_spot_rate": 31.0,
        "last_30_avg": 0.230,
        "last_30_pa": 0.0,
        "last_30_obp": 0.295,
        "last_30_slg": 0.370,
        "last_30_ops": 0.665,
        "last_7_ops": 0.665,
        "last_7_pa": 0.0,
        "last_15_ops": 0.665,
        "last_15_pa": 0.0,
        "data_quality": "rookie_baseline",
        "data_source": "auto_callup_backfill",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Cache + audit I/O
# ─────────────────────────────────────────────────────────────────────────────


def _existing_cache_ids() -> set:
    if not HITTER_CACHE_DIR.exists():
        return set()
    out = set()
    for p in HITTER_CACHE_DIR.glob("*.json"):
        try:
            out.add(int(p.stem))
        except Exception:
            continue
    return out


def _normalize_name(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _load_pool_keys() -> Tuple[set, set]:
    """Return (ids, normalized_names) of every hitter that appears in any
    recent projection output. A lineup hitter who matches NEITHER set is
    considered missing from the projection / history pool.
    """
    ids: set = set()
    names: set = set()
    for path in POOL_SOURCES:
        try:
            if not path.exists() or path.stat().st_size <= 0:
                continue
            with path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    raw_id = (row.get("hitter_id") or "").strip()
                    raw_name = (row.get("hitter_name") or "").strip()
                    try:
                        if raw_id:
                            ids.add(int(float(raw_id)))
                    except Exception:
                        pass
                    norm = _normalize_name(raw_name)
                    if norm:
                        names.add(norm)
        except Exception as exc:
            _log(f"WARNING: could not read pool source {path}: {exc}")
            continue
    return ids, names


def _build_baseline_row(
    hitter_name: str,
    hitter_id: int,
    milb_baseline: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], str, str]:
    base = _league_average_rookie_row(hitter_name, hitter_id)
    if milb_baseline:
        base.update(milb_baseline)
        method = "milb_yearbyyear"
        confidence = "low"
    else:
        method = "league_average_rookie_baseline"
        confidence = "very_low"

    base["hitter_name"] = hitter_name
    base["hitter_id"] = int(hitter_id)
    base["data_quality"] = "rookie_baseline"
    base["data_source"] = "auto_callup_backfill"
    return base, method, confidence


def _write_cache_entry(hitter_id: int, row: Dict[str, Any]) -> bool:
    try:
        HITTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = HITTER_CACHE_DIR / f"{int(hitter_id)}.json"
        if path.exists():
            return False
        payload = {
            "hitter_id": int(hitter_id),
            "season": int(datetime.now().year),
            "row": row,
            "_meta": {
                "source": "auto_callup_backfill",
                "written_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        }
        path.write_text(json.dumps(payload, separators=(",", ":")))
        return True
    except Exception as exc:
        _log(f"WARNING: failed to write cache for hitter_id={hitter_id}: {exc}")
        return False


def _read_cache_entry(hitter_id: int) -> Optional[Dict[str, Any]]:
    try:
        p = HITTER_CACHE_DIR / f"{int(hitter_id)}.json"
        if not p.exists():
            return None
        payload = json.loads(p.read_text())
        row = payload.get("row")
        return row if isinstance(row, dict) else None
    except Exception:
        return None


def _reset_audit_for_today(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(AUDIT_COLUMNS)


def _ensure_audit_header(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(AUDIT_COLUMNS)


def _append_audit_rows(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    try:
        _ensure_audit_header(AUDIT_CSV)
        with AUDIT_CSV.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=AUDIT_COLUMNS)
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in AUDIT_COLUMNS})
    except Exception as exc:
        _log(f"WARNING: failed to write audit CSV at {AUDIT_CSV}: {exc}")


def _dedupe_lineup_hitters(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        try:
            hid = int(r.get("hitter_id") or 0)
        except Exception:
            hid = 0
        hname = str(r.get("hitter_name") or "").strip()
        if hid <= 0 or not hname:
            continue
        key = (hid, hname)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Main backfill flow
# ─────────────────────────────────────────────────────────────────────────────


def run_backfill(test_date: Optional[str] = None) -> Dict[str, Any]:
    today_iso = test_date or datetime.now().strftime("%Y-%m-%d")
    summary: Dict[str, Any] = {
        "date": today_iso,
        "lineup_hitters": 0,
        "missing_count": 0,
        "backfilled_count": 0,
        "errors": [],
        "backfilled": [],
    }

    try:
        lineup_rows = _collect_today_lineups(today_iso)
    except Exception as exc:
        _log(f"WARNING: lineup fetch failed: {exc}")
        summary["errors"].append(f"fetch_failed: {exc}")
        try:
            _reset_audit_for_today(AUDIT_CSV)
        except Exception:
            pass
        return summary

    if not lineup_rows:
        _log("No lineup rows returned; nothing to backfill.")
        try:
            _reset_audit_for_today(AUDIT_CSV)
        except Exception:
            pass
        return summary

    hitters = _dedupe_lineup_hitters(lineup_rows)
    summary["lineup_hitters"] = len(hitters)
    _log(f"Lineup hitters collected: {len(hitters)}")

    _reset_audit_for_today(AUDIT_CSV)

    cached_ids = _existing_cache_ids()
    pool_ids, pool_names = _load_pool_keys()
    _log(
        f"Pool snapshot: ids={len(pool_ids)} names={len(pool_names)}; "
        f"backfill cache entries: {len(cached_ids)}"
    )

    audit_rows: List[Dict[str, Any]] = []
    backfilled: List[Dict[str, Any]] = []

    for r in hitters:
        try:
            hid = int(r.get("hitter_id") or 0)
        except Exception:
            hid = 0
        hname = str(r.get("hitter_name") or "").strip()
        if hid <= 0 or not hname:
            continue

        in_pool = (hid in pool_ids) or (_normalize_name(hname) in pool_names)

        is_existing_backfill = False
        if hid in cached_ids:
            cached_row = _read_cache_entry(hid) or {}
            cached_source = str(cached_row.get("data_source") or "")
            cached_quality = str(cached_row.get("data_quality") or "")
            if cached_source == "auto_callup_backfill" or cached_quality == "rookie_baseline":
                is_existing_backfill = True

        # A lineup hitter is treated as "missing from the projection /
        # history pool" if either:
        #   - they are not in any recent projection output, OR
        #   - we previously backfilled them with a rookie baseline.
        if in_pool and not is_existing_backfill:
            continue

        summary["missing_count"] += 1

        team = str(r.get("team") or "")
        opponent = str(r.get("opponent") or "")
        position = ""
        try:
            position = _fetch_player_position(hid)
        except Exception:
            position = ""

        if is_existing_backfill:
            method = "preexisting_rookie_baseline"
            confidence = "low"
            wrote = False
            milb_baseline = None
        else:
            milb_baseline = None
            try:
                milb_baseline = _fetch_milb_baseline(hid)
            except Exception:
                milb_baseline = None

            baseline_row, method, confidence = _build_baseline_row(
                hname, hid, milb_baseline,
            )
            wrote = _write_cache_entry(hid, baseline_row)
            if wrote:
                summary["backfilled_count"] += 1

        notes_parts = []
        if is_existing_backfill:
            notes_parts.append("preexisting_auto_backfill_cache_entry")
        else:
            notes_parts.append("missing_from_hitter_cache")
        if not wrote and not is_existing_backfill:
            notes_parts.append("cache_write_skipped_or_existing")
        if milb_baseline:
            notes_parts.append("milb_or_year_by_year_signal")
        elif not is_existing_backfill:
            notes_parts.append("no_prior_yearbyyear_signal")

        audit_row = {
            "date": today_iso,
            "player_name": hname,
            "team": team,
            "opponent": opponent,
            "position": position,
            "baseline_method": method,
            "confidence": confidence,
            "notes": "|".join(notes_parts),
        }
        audit_rows.append(audit_row)
        backfilled.append({
            "hitter_id": hid,
            "hitter_name": hname,
            "team": team,
            "opponent": opponent,
            "position": position,
            "baseline_method": method,
            "confidence": confidence,
            "wrote_cache": wrote,
        })

    if audit_rows:
        _append_audit_rows(audit_rows)
        _log(
            f"Backfilled {summary['backfilled_count']} new missing hitter(s); "
            f"audit rows: {len(audit_rows)}"
        )
    else:
        _log("No missing hitters detected — pool is complete.")

    summary["backfilled"] = backfilled
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv or sys.argv[1:]
    test_date: Optional[str] = None
    if "--date" in argv:
        try:
            i = argv.index("--date")
            test_date = argv[i + 1]
        except Exception:
            test_date = None

    started = time.time()
    try:
        summary = run_backfill(test_date=test_date)
    except Exception as exc:
        _log(f"UNCAUGHT ERROR: {exc}")
        _log(traceback.format_exc())
        return 0

    dur = time.time() - started
    _log(
        "Done. "
        f"date={summary['date']} "
        f"lineup_hitters={summary['lineup_hitters']} "
        f"missing={summary['missing_count']} "
        f"backfilled={summary['backfilled_count']} "
        f"duration={dur:.2f}s"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
