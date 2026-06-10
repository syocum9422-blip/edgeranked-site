"""Public Accuracy Center — read-only trust and validation reporting.

Read-only. This module never runs models, simulations, grading, or
calibration. It only *consumes* already-published, verified artifacts:

  MLB  (computed at render time from current tracking CSVs)
    * ``hitter_tracking.csv``              -> hit_prob projections + actual_hits
    * ``pitcher_tracking.csv``             -> predicted vs actual strikeouts/outs
    * ``learning/tracking_freshness.json`` -> staleness / last-updated badge only

  NBA
    * ``nba_walkforward_audit_summary.json`` -> walk-forward validation summary
    * ``nba_walkforward_audit.csv``          -> per-window validation detail

  WNBA
    * ``wnba_monitoring_summary.json``           -> graded-prediction accuracy
    * ``Best_Bets/graded_bets.csv``              -> verified result counts
    * ``wnba_production_status.json``            -> daily pipeline validation
    * ``wnba_slate_validation_manifest.json``    -> slate verification status

Stale pick-record files (MLB ``bet_history.csv``, NBA ``nba_bets_history.csv``)
are intentionally NOT read here: their grading is dormant and publishing them
would misrepresent results. Metrics without current verified tracking render
as "Not currently published" — never estimated or synthesized.

It builds ``/accuracy`` plus ``/accuracy/mlb``, ``/accuracy/nba`` and
``/accuracy/wnba``. All page chrome comes from the host app's
``render_layout``. Every loader fails safe: a missing or unreadable artifact
yields an "Unavailable" section, never an exception.
"""

from __future__ import annotations

import json
import os
import threading
from html import escape
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPORTS_ROOT = PROJECT_ROOT.parent / "sports"

NBA_WALKFORWARD_SUMMARY_PATH = PROJECT_ROOT / "nba_walkforward_audit_summary.json"
NBA_WALKFORWARD_DETAIL_PATH = PROJECT_ROOT / "nba_walkforward_audit.csv"

REQUIRED_DISCLAIMER = (
    "Some sports have deeper historical grading than others. "
    "We only publish metrics where current verified tracking is available."
)

NOT_PUBLISHED = "Not currently published"

NBA_TARGET_LABELS = {
    "PTS": "Points",
    "REB": "Rebounds",
    "AST": "Assists",
    "STL": "Steals",
    "BLK": "Blocks",
    "FG3M": "Three-pointers made",
    "MIN": "Minutes",
}


def _resolve_wnba_base() -> Path:
    # Mirrors wnba_views._resolve_wnba_base so accuracy pages read the same
    # artifacts the live WNBA pages serve.
    candidates = []
    env_base = os.environ.get("EDGERANKED_WNBA_BASE_DIR")
    if env_base:
        candidates.append(Path(env_base).expanduser())
    candidates.extend(
        [
            SPORTS_ROOT / "wnba",
            PROJECT_ROOT / "wnba",
            PROJECT_ROOT / "data" / "wnba",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


WNBA_BASE_DIR = _resolve_wnba_base()
WNBA_GRADED_PATH = WNBA_BASE_DIR / "Best_Bets" / "graded_bets.csv"
WNBA_MONITORING_PATH = WNBA_BASE_DIR / "data" / "processed" / "wnba_monitoring_summary.json"
WNBA_PRODUCTION_STATUS_PATH = WNBA_BASE_DIR / "data" / "processed" / "wnba_production_status.json"
WNBA_SLATE_MANIFEST_PATH = WNBA_BASE_DIR / "data" / "processed" / "wnba_slate_validation_manifest.json"

# --- cached reads (keyed on path + mtime) -----------------------------------

_CACHE: dict[str, tuple[float, object]] = {}
_LOCK = threading.Lock()


def _cached_load(path: Path, loader):
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = str(path)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
    try:
        value = loader(path)
    except Exception:
        value = None
    with _LOCK:
        _CACHE[key] = (mtime, value)
    return value


def _read_csv(path: Path):
    return _cached_load(path, pd.read_csv)


def _read_json(path: Path):
    return _cached_load(path, lambda p: json.loads(p.read_text()))


# --- formatting helpers ------------------------------------------------------


def _fmt_num(value, digits: int = 2) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "—"
    if f != f:  # NaN
        return "—"
    return f"{f:.{digits}f}"


def _fmt_pct(value, digits: int = 1) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "—"
    if f != f:
        return "—"
    return f"{f * 100:.{digits}f}%"


def _fmt_count(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_date(value) -> str:
    text = str(value or "").strip()
    return text[:10] if text else "—"


# --- metric loaders (each returns dict or None; never raises) ----------------


def load_mlb_metrics():
    """Aggregate MLB projection-vs-actual tracking. Computed at render time."""
    mlb_dir = _MLB_OUTPUT_DIR
    if mlb_dir is None:
        return None
    hitters = _read_csv(mlb_dir / "hitter_tracking.csv")
    pitchers = _read_csv(mlb_dir / "pitcher_tracking.csv")
    if hitters is None and pitchers is None:
        return None
    out = {}

    if hitters is not None and "date" in hitters.columns:
        dates = hitters["date"].astype(str).str.slice(0, 10)
        out["hitter_total"] = int(len(hitters))
        out["hitter_first_date"] = dates.min()
        out["hitter_last_date"] = dates.max()
        actual = pd.to_numeric(hitters.get("actual_hits"), errors="coerce")
        prob = pd.to_numeric(hitters.get("hit_prob"), errors="coerce")
        # hit_prob is stored as a percentage (e.g. 54.3); normalize to 0-1.
        if prob.max() is not None and prob.max() > 1.5:
            prob = prob / 100.0
        graded = hitters[actual.notna()]
        out["hitter_graded"] = int(len(graded))
        if len(graded):
            out["hitter_last_graded_date"] = (
                graded["date"].astype(str).str.slice(0, 10).max()
            )
        mask = actual.notna() & prob.notna()
        if mask.sum() >= 100:
            buckets = [
                ("Under 40%", 0.0, 0.40),
                ("40–50%", 0.40, 0.50),
                ("50–60%", 0.50, 0.60),
                ("60%+", 0.60, 1.01),
            ]
            rows = []
            for label, lo, hi in buckets:
                in_bucket = mask & (prob >= lo) & (prob < hi)
                n = int(in_bucket.sum())
                if n == 0:
                    continue
                rows.append(
                    {
                        "label": label,
                        "n": n,
                        "predicted": float(prob[in_bucket].mean()),
                        "observed": float((actual[in_bucket] >= 1).mean()),
                    }
                )
            if rows:
                out["hit_calibration"] = rows

    if pitchers is not None and "date" in pitchers.columns:
        pred_k = pd.to_numeric(pitchers.get("predicted_strikeouts"), errors="coerce")
        act_k = pd.to_numeric(pitchers.get("actual_strikeouts"), errors="coerce")
        mask = pred_k.notna() & act_k.notna()
        out["pitcher_graded"] = int(mask.sum())
        if mask.sum() > 0:
            out["pitcher_k_mae"] = float((pred_k[mask] - act_k[mask]).abs().mean())
            out["pitcher_last_graded_date"] = (
                pitchers.loc[mask, "date"].astype(str).str.slice(0, 10).max()
            )
        pred_outs = pd.to_numeric(pitchers.get("predicted_outs"), errors="coerce")
        act_outs = pd.to_numeric(pitchers.get("actual_outs"), errors="coerce")
        outs_mask = pred_outs.notna() & act_outs.notna()
        if outs_mask.sum() > 0:
            out["pitcher_outs_mae"] = float(
                (pred_outs[outs_mask] - act_outs[outs_mask]).abs().mean()
            )
            out["pitcher_outs_graded"] = int(outs_mask.sum())

    # Freshness badge only — never used for counts (the tracking files are
    # rewritten intraday, so row counts here can drift from the JSON).
    # The legacy MLB base dir has no learning/ folder, so fall back to the
    # repo copy; both describe the same canonical tracking files.
    freshness = _read_json(mlb_dir / "learning" / "tracking_freshness.json")
    if freshness is None:
        freshness = _read_json(
            PROJECT_ROOT / "mlb" / "outputs" / "learning" / "tracking_freshness.json"
        )
    if isinstance(freshness, dict):
        site_hitter = freshness.get("site_hitter") or freshness.get("canonical_hitter")
        if isinstance(site_hitter, dict):
            out["freshness_date"] = site_hitter.get("max_tracking_date")
            out["freshness_days_stale"] = site_hitter.get("days_stale")

    return out or None


def load_nba_metrics():
    summary = _read_json(NBA_WALKFORWARD_SUMMARY_PATH)
    if not isinstance(summary, dict) or not summary.get("by_target"):
        return None
    return summary


def load_nba_detail():
    detail = _read_csv(NBA_WALKFORWARD_DETAIL_PATH)
    if detail is None or detail.empty:
        return None
    needed = {"target", "cutoff", "test_rows", "mae"}
    if not needed.issubset(set(detail.columns)):
        return None
    return detail


def load_wnba_metrics():
    out = {}

    monitoring = _read_json(WNBA_MONITORING_PATH)
    if isinstance(monitoring, dict):
        learning = monitoring.get("learning")
        if isinstance(learning, dict):
            out["accuracy"] = learning.get("accuracy")
            out["predictions_graded"] = learning.get("predictions_graded")
            out["games_graded"] = learning.get("games_graded")
            out["window_days"] = learning.get("backtest_window_days")
            out["last_graded_date"] = learning.get("last_graded_date")

    graded = _read_csv(WNBA_GRADED_PATH)
    if graded is not None and "bet_result" in graded.columns:
        results = graded["bet_result"].astype(str).str.strip().str.lower()
        wins = int((results == "win").sum())
        losses = int((results == "loss").sum())
        pushes = int((results == "push").sum())
        if wins + losses + pushes > 0:
            out["alltime_correct"] = wins
            out["alltime_incorrect"] = losses
            out["alltime_exact"] = pushes
            if wins + losses > 0:
                out["alltime_accuracy"] = wins / (wins + losses)
            date_col = "bet_date" if "bet_date" in graded.columns else None
            if date_col:
                dates = graded[date_col].astype(str).str.slice(0, 10)
                out["alltime_first_date"] = dates.min()
                out["alltime_last_date"] = dates.max()

    status = _read_json(WNBA_PRODUCTION_STATUS_PATH)
    if isinstance(status, dict):
        out["production_status"] = status.get("WNBA_PRODUCTION_STATUS") or status.get("status")
        out["slate_date"] = status.get("slate_date")
        out["included_players"] = status.get("included_players")

    manifest = _read_json(WNBA_SLATE_MANIFEST_PATH)
    if isinstance(manifest, dict):
        out["slate_status"] = manifest.get("status")
        out["slate_expected_games"] = manifest.get("expected_game_count")
        out["slate_generated_games"] = manifest.get("generated_game_count")

    return out or None


# --- shared page fragments ----------------------------------------------------


def _disclaimer_html() -> str:
    return (
        "<div class='notice-banner' style='margin:18px 0;'>"
        f"{escape(REQUIRED_DISCLAIMER)}"
        "</div>"
    )


def _methodology_note(text: str) -> str:
    return f"<p class='muted' style='margin-top:14px;'>{escape(text)}</p>"


def _not_published(label: str) -> str:
    return (
        "<article class='metric-card'>"
        f"<div class='metric-label'>{escape(label)}</div>"
        f"<div class='metric-value'>{escape(NOT_PUBLISHED)}</div>"
        "<p class='metric-caption'>This metric is published only when current "
        "verified tracking is available.</p>"
        "</article>"
    )


def _metric_card(label: str, value: str, caption: str) -> str:
    return (
        "<article class='metric-card'>"
        f"<div class='metric-label'>{escape(label)}</div>"
        f"<div class='metric-value'>{escape(value)}</div>"
        f"<p class='metric-caption'>{escape(caption)}</p>"
        "</article>"
    )


def _metric_grid(cards_html: list[str]) -> str:
    return "<div class='metric-grid compact'>" + "".join(cards_html) + "</div>"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return (
        "<div class='table-shell'><table><thead><tr>"
        + head
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></div>"
    )


def _cta_row(links: list[tuple[str, str]]) -> str:
    out = "".join(
        f"<a class='cta-btn secondary' href='{escape(href)}'>{escape(label)}</a>"
        for label, href in links
    )
    return f"<div class='cta-row' style='margin-top:18px;'>{out}</div>"


def _panel(eyebrow: str, heading: str, sub: str, inner: str) -> str:
    return (
        "<section class='panel' style='margin-bottom:22px;'>"
        "<div class='panel-head'><div>"
        f"<div class='eyebrow'>{escape(eyebrow)}</div>"
        f"<h2>{escape(heading)}</h2></div></div>"
        f"<p class='muted'>{escape(sub)}</p>"
        + inner
        + "</section>"
    )


# --- sport card builders (shared by overview + sport pages) -------------------


def _mlb_cards(metrics, overview: bool):
    if not metrics:
        return [_not_published("MLB projection tracking")]
    cards = []
    graded = metrics.get("hitter_graded")
    total = metrics.get("hitter_total")
    if graded:
        cards.append(
            _metric_card(
                "Hitter projections graded",
                _fmt_count(graded),
                f"Of {_fmt_count(total)} archived since {_fmt_date(metrics.get('hitter_first_date'))}; "
                f"last graded {_fmt_date(metrics.get('hitter_last_graded_date'))}.",
            )
        )
    else:
        cards.append(_not_published("Hitter projections graded"))
    if metrics.get("pitcher_k_mae") is not None:
        cards.append(
            _metric_card(
                "Pitcher strikeout projection error",
                f"±{_fmt_num(metrics['pitcher_k_mae'], 2)} Ks",
                f"Average miss vs final box score across {_fmt_count(metrics.get('pitcher_graded'))} "
                f"graded starts; last graded {_fmt_date(metrics.get('pitcher_last_graded_date'))}.",
            )
        )
    else:
        cards.append(_not_published("Pitcher strikeout projection error"))
    if not overview and metrics.get("pitcher_outs_mae") is not None:
        cards.append(
            _metric_card(
                "Pitcher innings-depth projection error",
                f"±{_fmt_num(metrics['pitcher_outs_mae'], 2)} outs",
                f"Average miss on recorded outs across {_fmt_count(metrics.get('pitcher_outs_graded'))} graded starts.",
            )
        )
    if metrics.get("freshness_date"):
        stale = metrics.get("freshness_days_stale")
        stale_text = (
            "current as of the latest completed slate"
            if stale in (0, "0")
            else f"{stale} day(s) behind the latest slate"
        )
        cards.append(
            _metric_card(
                "Tracking freshness",
                _fmt_date(metrics["freshness_date"]),
                f"Most recent tracked date; {stale_text}.",
            )
        )
    return cards


def _nba_cards(summary, overview: bool):
    if not summary:
        return [_not_published("NBA walk-forward validation")]
    by_target = summary.get("by_target") or {}
    cards = [
        _metric_card(
            "Validation status",
            str(summary.get("status", "—")),
            f"Walk-forward audit generated {_fmt_date(summary.get('generated_at_utc'))} across "
            f"{_fmt_count(summary.get('windows_evaluated'))} held-out windows.",
        ),
        _metric_card(
            "Player-games evaluated",
            _fmt_count(summary.get("dataset_rows")),
            f"Season dataset from {_fmt_date(summary.get('dataset_start'))} to "
            f"{_fmt_date(summary.get('dataset_end'))}.",
        ),
    ]
    pts = by_target.get("PTS") or {}
    if pts.get("latest_mae") is not None:
        cards.append(
            _metric_card(
                "Points projection error",
                f"±{_fmt_num(pts['latest_mae'], 2)} pts",
                "Average miss per player on the most recent held-out window the model never trained on.",
            )
        )
    if not overview:
        reb = by_target.get("REB") or {}
        if reb.get("latest_mae") is not None:
            cards.append(
                _metric_card(
                    "Rebounds projection error",
                    f"±{_fmt_num(reb['latest_mae'], 2)} reb",
                    "Average miss per player on the most recent held-out window.",
                )
            )
    return cards


def _wnba_cards(metrics, overview: bool):
    if not metrics:
        return [_not_published("WNBA validation")]
    cards = []
    if metrics.get("accuracy") is not None and metrics.get("predictions_graded"):
        cards.append(
            _metric_card(
                f"Verified accuracy, last {metrics.get('window_days', 30)} days",
                _fmt_pct(metrics["accuracy"]),
                f"{_fmt_count(metrics['predictions_graded'])} stat-line predictions graded against final "
                f"box scores; last graded {_fmt_date(metrics.get('last_graded_date'))}.",
            )
        )
    else:
        cards.append(_not_published("Verified accuracy"))
    if metrics.get("alltime_correct") is not None:
        total = (
            metrics["alltime_correct"]
            + metrics["alltime_incorrect"]
            + metrics["alltime_exact"]
        )
        cards.append(
            _metric_card(
                "Season verified results",
                f"{_fmt_count(metrics['alltime_correct'])}–{_fmt_count(metrics['alltime_incorrect'])}",
                f"Correct–incorrect across {_fmt_count(total)} graded predictions "
                f"({_fmt_count(metrics['alltime_exact'])} landed exactly on the line and are excluded), "
                f"{_fmt_date(metrics.get('alltime_first_date'))} to {_fmt_date(metrics.get('alltime_last_date'))}.",
            )
        )
    if metrics.get("production_status"):
        cards.append(
            _metric_card(
                "Daily pipeline validation",
                str(metrics["production_status"]),
                f"Slate {_fmt_date(metrics.get('slate_date'))}: outputs publish only after slate and "
                "freshness checks pass.",
            )
        )
    if not overview and metrics.get("slate_status"):
        cards.append(
            _metric_card(
                "Slate verification",
                str(metrics["slate_status"]),
                f"{_fmt_count(metrics.get('slate_generated_games'))} of "
                f"{_fmt_count(metrics.get('slate_expected_games'))} games matched the official league "
                "scoreboard before publishing.",
            )
        )
    return cards


# --- page builders -------------------------------------------------------------


def build_accuracy_overview(render_layout):
    mlb = load_mlb_metrics()
    nba = load_nba_metrics()
    wnba = load_wnba_metrics()

    intro = (
        "<section class='panel' style='margin-bottom:22px;'>"
        "<div class='panel-head'><div><div class='eyebrow'>Accuracy Center</div>"
        "<h2>How we verify our projections</h2></div></div>"
        "<p>Every tracked prediction is archived before games begin, then compared "
        "against final results after games complete.</p>"
        "<p class='muted'>The numbers below are read directly from our tracking and "
        "validation files — the same artifacts our internal monitoring uses. Nothing "
        "on this page is estimated or back-filled.</p>"
        + _disclaimer_html()
        + "</section>"
    )

    mlb_panel = _panel(
        "MLB",
        "MLB Accuracy",
        "Daily hitter and pitcher projections graded against final box scores.",
        _metric_grid(_mlb_cards(mlb, overview=True))
        + _cta_row([("MLB accuracy detail", "/accuracy/mlb"), ("MLB projections", "/mlb")]),
    )
    nba_panel = _panel(
        "NBA",
        "NBA Walk-Forward Validation",
        "The projection model is tested on past dates it never trained on — no look-ahead.",
        _metric_grid(_nba_cards(nba, overview=True))
        + _cta_row([("NBA validation detail", "/accuracy/nba"), ("NBA projections", "/nba")]),
    )
    wnba_panel = _panel(
        "WNBA",
        "WNBA Validation Status",
        "Graded predictions, plus the daily pipeline checks that gate publishing.",
        _metric_grid(_wnba_cards(wnba, overview=True))
        + _cta_row([("WNBA validation detail", "/accuracy/wnba"), ("WNBA projections", "/wnba")]),
    )

    membership = (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Membership</div>"
        "<h2>See the full boards behind these numbers</h2></div></div>"
        "<p class='muted'>Pro members get the complete daily projection boards across "
        "MLB, NBA, WNBA, PGA, and UFC.</p>"
        + _cta_row([("View membership", "/pricing")])
        + "</section>"
    )

    body = intro + mlb_panel + nba_panel + wnba_panel + membership
    return render_layout(
        "Accuracy Center",
        "Projection accuracy, validation, and verified results — read straight from our tracking files.",
        body,
        "/accuracy",
        hero_kicker="Accuracy Center",
        meta_description="EdgeRanked Accuracy Center: projection accuracy, walk-forward validation, and verified results for MLB, NBA, and WNBA.",
        canonical_path="/accuracy",
    )


def build_accuracy_mlb(render_layout):
    metrics = load_mlb_metrics()
    inner = _metric_grid(_mlb_cards(metrics, overview=False))

    calibration = metrics.get("hit_calibration") if metrics else None
    if calibration:
        rows = [
            [
                bucket["label"],
                _fmt_count(bucket["n"]),
                _fmt_pct(bucket["predicted"]),
                _fmt_pct(bucket["observed"]),
            ]
            for bucket in calibration
        ]
        inner += (
            "<h3 style='margin:22px 0 8px;'>Hit probability vs. observed outcomes</h3>"
            "<p class='muted'>Each graded hitter projection carries a pre-game hit "
            "probability. Grouping graded projections by that probability shows how "
            "often players in each band actually recorded a hit.</p>"
            + _table(
                ["Pre-game hit probability", "Graded projections", "Average projected", "Actually hit"],
                rows,
            )
        )
    else:
        inner += _metric_grid([_not_published("Hit probability vs. observed outcomes")])

    inner += _methodology_note(
        "Method: projections are archived to tracking files before first pitch. After "
        "games complete, final box-score stats are written next to each archived "
        "projection. All figures on this page are computed from those files at page "
        "load — no re-modeling, no adjustments."
    )
    inner += _disclaimer_html()
    inner += _cta_row(
        [
            ("Back to Accuracy Center", "/accuracy"),
            ("MLB projections", "/mlb"),
            ("Membership", "/pricing"),
        ]
    )

    body = _panel(
        "MLB",
        "MLB Projection Accuracy",
        "Hitter and pitcher projections graded against final box scores, updated daily.",
        inner,
    )
    return render_layout(
        "MLB Projection Accuracy",
        "Hitter and pitcher projections graded against final box scores.",
        body,
        "/accuracy",
        hero_kicker="Accuracy Center",
        meta_description="MLB projection accuracy: graded hitter and pitcher projections verified against final box scores.",
        canonical_path="/accuracy/mlb",
    )


def build_accuracy_nba(render_layout):
    summary = load_nba_metrics()
    inner = _metric_grid(_nba_cards(summary, overview=False))

    if summary:
        by_target = summary.get("by_target") or {}
        rows = []
        for key, label in NBA_TARGET_LABELS.items():
            stats = by_target.get(key)
            if not isinstance(stats, dict):
                continue
            rows.append(
                [
                    label,
                    f"±{_fmt_num(stats.get('latest_mae'), 2)}",
                    f"±{_fmt_num(stats.get('avg_mae'), 2)}",
                    _fmt_count(stats.get("windows")),
                ]
            )
        if rows:
            inner += (
                "<h3 style='margin:22px 0 8px;'>Typical projection miss by stat</h3>"
                "<p class='muted'>Average absolute error per player-game on held-out "
                "validation windows — dates the model never saw in training.</p>"
                + _table(
                    ["Stat", "Latest window", "All windows", "Windows evaluated"],
                    rows,
                )
            )
        detail = load_nba_detail()
        if detail is not None:
            detail_rows = [
                [
                    NBA_TARGET_LABELS.get(str(r.get("target")), str(r.get("target"))),
                    _fmt_date(r.get("cutoff")),
                    _fmt_count(r.get("test_rows")),
                    f"±{_fmt_num(r.get('mae'), 2)}",
                ]
                for r in detail.to_dict("records")
            ]
            inner += (
                "<h3 style='margin:22px 0 8px;'>Every validation window</h3>"
                "<p class='muted'>Each row is one walk-forward test: the model is "
                "trained only on games before the cutoff date, then scored on games "
                "after it.</p>"
                + _table(
                    ["Stat", "Trained through", "Held-out player-games", "Average miss"],
                    detail_rows,
                )
            )
    else:
        inner += _metric_grid([_not_published("Walk-forward validation detail")])

    inner += _methodology_note(
        "Method: walk-forward validation re-trains the projection model using only "
        "games played before a cutoff date, then measures error on games after that "
        "date. Because the test games are always in the model's future, these "
        "numbers cannot benefit from hindsight."
    )
    inner += _disclaimer_html()
    inner += _cta_row(
        [
            ("Back to Accuracy Center", "/accuracy"),
            ("NBA projections", "/nba"),
            ("Membership", "/pricing"),
        ]
    )

    body = _panel(
        "NBA",
        "NBA Walk-Forward Validation",
        "Projection error measured on held-out dates the model never trained on.",
        inner,
    )
    return render_layout(
        "NBA Walk-Forward Validation",
        "Projection error measured on held-out dates the model never trained on.",
        body,
        "/accuracy",
        hero_kicker="Accuracy Center",
        meta_description="NBA walk-forward validation: projection error per stat measured on held-out dates with no look-ahead.",
        canonical_path="/accuracy/nba",
    )


def build_accuracy_wnba(render_layout):
    metrics = load_wnba_metrics()
    inner = _metric_grid(_wnba_cards(metrics, overview=False))

    inner += _methodology_note(
        "Method: every published WNBA stat-line prediction is graded against the "
        "final box score. Daily outputs publish only after the slate is verified "
        "against the official league scoreboard and freshness checks pass; stale "
        "outputs are blocked rather than published."
    )
    inner += _disclaimer_html()
    inner += _cta_row(
        [
            ("Back to Accuracy Center", "/accuracy"),
            ("WNBA projections", "/wnba"),
            ("Membership", "/pricing"),
        ]
    )

    body = _panel(
        "WNBA",
        "WNBA Validation Status",
        "Graded predictions and the daily pipeline checks that gate publishing.",
        inner,
    )
    return render_layout(
        "WNBA Validation Status",
        "Graded predictions and the daily pipeline checks that gate publishing.",
        body,
        "/accuracy",
        hero_kicker="Accuracy Center",
        meta_description="WNBA validation status: graded prediction accuracy and the daily slate verification checks that gate publishing.",
        canonical_path="/accuracy/wnba",
    )


# --- registration --------------------------------------------------------------

_MLB_OUTPUT_DIR: Path | None = None


def register_accuracy_routes(flask_app, render_layout, mlb_output_dir):
    global _MLB_OUTPUT_DIR
    _MLB_OUTPUT_DIR = Path(mlb_output_dir) if mlb_output_dir else None

    @flask_app.get("/accuracy")
    def accuracy_overview():
        return build_accuracy_overview(render_layout)

    @flask_app.get("/accuracy/mlb")
    def accuracy_mlb():
        return build_accuracy_mlb(render_layout)

    @flask_app.get("/accuracy/nba")
    def accuracy_nba():
        return build_accuracy_nba(render_layout)

    @flask_app.get("/accuracy/wnba")
    def accuracy_wnba():
        return build_accuracy_wnba(render_layout)
