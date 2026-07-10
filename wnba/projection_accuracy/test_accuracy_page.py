#!/usr/bin/env python3
"""Regression tests for the WNBA projection-accuracy page redesign.

Enforces the core contract: projection-accuracy metrics are computed only from
archived projections vs box scores and can never accidentally use best-bet
artifacts (graded_bets.csv / bet_result / sportsbook lines / over-under sides).

Run: python3 projection_accuracy/test_accuracy_page.py
"""
import ast
import importlib.util
import json
import os
import re
import sys

WNBA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWS = "/home/ubuntu/EdgeRanked/site/nba_model/webapp/accuracy_views.py"
REPORT = os.path.join(WNBA, "projection_accuracy/reports/projection_accuracy_report.json")
PROD_ERRORS = os.path.join(WNBA, "learning/errors/projection_errors.csv")

FORBIDDEN_IN_PROJECTION = ["graded_bets", "bet_result", "hit_rate", "WNBA_GRADED_PATH",
                           "sportsbook", "over_odds", "under_odds", '"side"', "'side'"]
PROJECTION_FUNCS = {"load_wnba_projection_accuracy", "_projection_cards", "_projection_analytics"}


def _load_views():
    os.environ.setdefault("EDGERANKED_WNBA_BASE_DIR", WNBA)
    spec = importlib.util.spec_from_file_location("accuracy_views_test", VIEWS)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_projection_funcs_never_touch_bet_artifacts():
    """Static AST scan: the projection loader/cards/analytics functions must not
    reference any best-bet token."""
    src = open(VIEWS).read()
    tree = ast.parse(src)
    fails = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in PROJECTION_FUNCS:
            seg = ast.get_source_segment(src, node) or ""
            for tok in FORBIDDEN_IN_PROJECTION:
                if tok in seg:
                    fails.append(f"{node.name} references forbidden token {tok!r}")
    return fails


def _strip_docstrings_and_comments(src: str) -> str:
    """Return executable source only — module/func/class docstrings and # comments
    removed — so a token mentioned in prose isn't mistaken for a data reference."""
    tree = ast.parse(src)
    doc_spans = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                d = body[0].value
                doc_spans.add((d.lineno, d.end_lineno))
    out = []
    for i, line in enumerate(src.splitlines(), start=1):
        if any(lo <= i <= hi for lo, hi in doc_spans):
            continue
        code = line.split("#", 1)[0]
        out.append(code)
    return "\n".join(out)


def test_grader_reads_only_archives():
    raw = open(os.path.join(WNBA, "projection_accuracy/grade_projection_accuracy.py")).read()
    src = _strip_docstrings_and_comments(raw)
    fails = []
    for tok in ["graded_bets", "bet_result", "wnba_bets_history", "sportsbook_lines", "best_bets"]:
        if tok in src:
            fails.append(f"grader references best-bet artifact {tok!r} in executable code")
    if "outputs/archive/projections" not in raw:
        fails.append("grader does not read the archived projections directory")
    return fails


def test_singles_parity_with_production():
    """Grader's per-stat MAE must match production projection_errors.csv (proves the
    join/grading is correct and lookahead-free)."""
    import pandas as pd
    fails = []
    if not (os.path.exists(REPORT) and os.path.exists(PROD_ERRORS)):
        return ["report or production errors csv missing"]
    rep = json.load(open(REPORT))
    pe = pd.read_csv(PROD_ERRORS)
    for cat in ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]:
        prod = pe[pe.stat == cat].absolute_error.mean()
        mine = rep["season"]["by_category"][cat]["mae"]
        if abs(prod - mine) > 0.05:
            fails.append(f"{cat}: grader MAE {mine} vs prod {prod:.4f} diff>{0.05}")
    return fails


def test_turnovers_excluded_with_reason():
    rep = json.load(open(REPORT))
    if "turnovers" not in rep.get("categories_excluded", {}):
        return ["turnovers not documented as excluded"]
    if "turnovers" in rep["season"]["by_category"]:
        return ["turnovers should not be graded (no projection published)"]
    return []


def test_flag_off_preserves_legacy_page():
    os.environ["WNBA_PROJECTION_ACCURACY_PAGE"] = "off"
    av = _load_views()
    html = av.build_accuracy_wnba(lambda t, s, b, *a, **k: b)
    return [] if "Verified accuracy" in html else ["flag OFF did not preserve legacy page"]


def test_flag_on_shows_projection_page_and_separates_bets():
    os.environ["WNBA_PROJECTION_ACCURACY_PAGE"] = "on"
    av = _load_views()
    html = av.build_accuracy_wnba(lambda t, s, b, *a, **k: b)
    fails = []
    for token in ["Projection accuracy — last 30 days", "Season projection results",
                  "Category-by-category", "Best Bet Performance", "Daily pipeline validation"]:
        if token not in html:
            fails.append(f"new page missing section {token!r}")
    # projection section (before the Best Bet header) must not present a bet hit rate
    idx = html.find("Best Bet Performance")
    proj_section = html[:idx].lower()
    if "hit rate" in proj_section:
        fails.append("projection section leaks a best-bet 'hit rate'")
    if re.search(r"\d+&#8211;\d+|\d+–\d+", html[:idx]):
        fails.append("projection section shows a win-loss record")
    return fails


def test_season_card_has_no_hit_rate_label():
    rep = json.load(open(REPORT))
    season = rep["season"]["overall"]
    # the season card must be MAE-based, not a win/loss accuracy
    if "hit_rate" in season or "wins" in season:
        return ["season overall block contains betting fields"]
    return []


def main():
    tests = [
        ("projection funcs never touch bet artifacts", test_projection_funcs_never_touch_bet_artifacts),
        ("grader reads only archives", test_grader_reads_only_archives),
        ("singles parity with production", test_singles_parity_with_production),
        ("turnovers excluded with reason", test_turnovers_excluded_with_reason),
        ("flag OFF preserves legacy page", test_flag_off_preserves_legacy_page),
        ("flag ON shows projection page + separates bets", test_flag_on_shows_projection_page_and_separates_bets),
        ("season card has no hit-rate label", test_season_card_has_no_hit_rate_label),
    ]
    any_fail = False
    for name, fn in tests:
        try:
            fails = fn()
        except Exception as exc:  # noqa
            fails = [f"raised {type(exc).__name__}: {exc}"]
        if fails:
            any_fail = True
            print(f"FAIL  {name}")
            for f in fails:
                print(f"      - {f}")
        else:
            print(f"PASS  {name}")
    os.environ.pop("WNBA_PROJECTION_ACCURACY_PAGE", None)
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
