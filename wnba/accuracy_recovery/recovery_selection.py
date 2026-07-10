"""Accuracy-recovery selection layer (shadow-validated 2026-07-10).

Flag: WNBA_ACCURACY_RECOVERY = off | shadow (default) | on
  off    — no behavior at all.
  shadow — published board UNCHANGED; recovery board written to a sidecar
           (accuracy_recovery/shadow_boards/) for forward grading.
  on     — recovery board replaces the published board (only after shadow
           verdict; see reports/PHASE4_DEPLOYMENT.md).

The three validated components (Phase 3 replay, Jun 11 - Jul 9, +4.9pp vs
production baseline, day-clustered bootstrap 95% CI [+1.3, +8.7]pp):
  C1 variance-honesty — recompute hit_rate from Normal(mean, STDDEV * factor)
     with per-market factors measured from realized board-vs-actual z-scores.
  C2 singles-only — combo markets (pra/pr/pa/ra) excluded; their sim variance
     is doubly understated (marginals ~2x too narrow + near-independent
     sampling vs realized corr(PTS,REB)=0.30).
  C6 role-guard — exclude players with a starter-status flip in the last 10
     days or <8 games of current-season history.

This layer only ever REMOVES candidates or LOWERS hit rates before the
existing MIN_EDGE / MIN_HIT_RATE gates — it cannot weaken production gates.
Every failure falls back to the untouched production board.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
WNBA_ROOT = HERE.parent
INFLATION_PATH = HERE / "variance_inflation.json"
SHADOW_DIR = HERE / "shadow_boards"
PLAYER_GAMES_PATH = WNBA_ROOT / "data" / "raw" / "wnba_player_games.csv"

COMBO_STATS = {"pra", "pr", "pa", "ra"}
ROLE_LOOKBACK_DAYS = 10
MIN_SEASON_GAMES = 8
DEFAULT_INFLATION = 1.8


def recovery_mode() -> str:
    raw = os.environ.get("WNBA_ACCURACY_RECOVERY", "shadow").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return "on"
    if raw in {"0", "false", "no", "off"}:
        return "off"
    return "shadow"


def _load_inflation() -> tuple[dict, float]:
    try:
        with open(INFLATION_PATH) as fh:
            data = json.load(fh)
        return data.get("factors", {}), float(data.get("fallback", DEFAULT_INFLATION))
    except Exception:
        return {}, DEFAULT_INFLATION


def _role_guard_players(as_of: date) -> set:
    """Players with a recent starter-status flip or thin current-season history."""
    try:
        pg = pd.read_csv(PLAYER_GAMES_PATH, parse_dates=["game_date"])
    except Exception:
        return set()
    as_of_ts = pd.Timestamp(as_of)
    hist = pg[pg.game_date < as_of_ts]
    season = hist[hist.game_date >= as_of_ts - timedelta(days=140)]
    flagged: set = set()

    recent = hist[hist.game_date >= as_of_ts - timedelta(days=ROLE_LOOKBACK_DAYS)]
    for pk, g in recent.groupby("player_key"):
        if g.starter.nunique() > 1:
            prior = hist[(hist.player_key == pk) & (hist.game_date < g.game_date.min())].tail(5)
            if len(prior) and abs(g.sort_values("game_date").starter.iloc[-1] - prior.starter.mean()) > 0.5:
                flagged.add(pk)

    counts = season.groupby("player_key").size()
    flagged |= set(counts[counts < MIN_SEASON_GAMES].index)
    return flagged


def _adjusted_hit_rate(row: pd.Series, factors: dict, fallback: float) -> float:
    stat = str(row.get("stat", "")).lower()
    mean = float(row.get("projection_mean", np.nan))
    sd = float(row.get("STDDEV", np.nan))
    line = float(row.get("line", np.nan))
    if not np.isfinite(mean) or not np.isfinite(sd) or not np.isfinite(line):
        return np.nan
    factor = float(factors.get(stat, fallback))
    sd_adj = max(sd * factor, 0.25)
    p_over = 1.0 - norm.cdf((line - mean) / sd_adj)
    return p_over if str(row.get("side", "")).lower() == "over" else 1.0 - p_over


def build_recovery_board(
    candidates: pd.DataFrame,
    *,
    min_edge: float,
    min_hit_rate: float,
    max_bets_total: int,
    max_bets_per_player: int,
    max_bets_per_stat: int,
    as_of: date | None = None,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """Apply C1+C2+C6 to the pre-threshold candidate pool, then re-apply the
    production gates (same or stricter — never weaker)."""
    log = logger or logging.getLogger(__name__)
    d = candidates.copy()
    if d.empty:
        return d

    # C2 — singles only
    d = d[~d["stat"].astype(str).str.lower().isin(COMBO_STATS)]

    # C6 — role guard
    guard = _role_guard_players(as_of or date.today())
    if guard and "player_name" in d.columns:
        keys = d["player_name"].astype(str).str.lower().str.strip()
        d = d[~keys.isin(guard)]

    # C1 — variance-honest hit rate (only ever shrinks confident tails)
    factors, fallback = _load_inflation()
    adj = d.apply(_adjusted_hit_rate, axis=1, args=(factors, fallback))
    d = d[adj.notna()].copy()
    d["hit_rate"] = adj[adj.notna()].astype(float)
    d["edge"] = d["hit_rate"] - 0.5
    if "HIT_RATE" in d.columns:
        d["HIT_RATE"] = d["hit_rate"].round(4)

    # production gates, unchanged
    d = d[(d["edge"] >= min_edge) & (d["hit_rate"] >= min_hit_rate)].copy()
    if d.empty:
        return d
    d["bet_quality_score"] = (
        100 * d["edge"]
        + 25 * (d["hit_rate"] - 0.5)
        + 2.0 * d["confidence_score"].fillna(0)
        + 0.03 * d["projected_minutes"].clip(lower=0).fillna(0)
        + d["line_delta"].abs().fillna(0)
    )
    d = d.sort_values(["bet_quality_score", "edge", "hit_rate"], ascending=False)
    d = d.groupby("player_name", group_keys=False).head(max_bets_per_player)
    d = d.groupby("stat", group_keys=False).head(max_bets_per_stat)
    d = d.head(max_bets_total).reset_index(drop=True)
    log.info("accuracy-recovery board: %s picks (singles-only, variance-honest, role-guarded)", len(d))
    return d


def maybe_apply_accuracy_recovery(
    candidates: pd.DataFrame,
    production_board: pd.DataFrame,
    *,
    min_edge: float,
    min_hit_rate: float,
    max_bets_total: int,
    max_bets_per_player: int,
    max_bets_per_stat: int,
    bet_date: str | None = None,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """Entry point called from build_wnba_best_bets. Fail-safe: any exception
    returns the untouched production board."""
    log = logger or logging.getLogger(__name__)
    mode = recovery_mode()
    if mode == "off":
        return production_board
    try:
        as_of = pd.Timestamp(bet_date).date() if bet_date else date.today()
        board = build_recovery_board(
            candidates,
            min_edge=min_edge,
            min_hit_rate=min_hit_rate,
            max_bets_total=max_bets_total,
            max_bets_per_player=max_bets_per_player,
            max_bets_per_stat=max_bets_per_stat,
            as_of=as_of,
            logger=log,
        )
        if mode == "shadow":
            SHADOW_DIR.mkdir(parents=True, exist_ok=True)
            out = SHADOW_DIR / f"recovery_board_{as_of.strftime('%Y%m%d')}.csv"
            board.to_csv(out, index=False)
            log.info("accuracy-recovery SHADOW board saved to %s (published board unchanged)", out)
            return production_board
        if board.empty and not production_board.empty:
            log.warning("accuracy-recovery produced an empty board while production has %s picks; "
                        "falling back to production board", len(production_board))
            return production_board
        log.info("accuracy-recovery mode ON: publishing recovery board (%s picks)", len(board))
        return board
    except Exception:
        log.exception("accuracy-recovery failed; falling back to production board")
        return production_board
