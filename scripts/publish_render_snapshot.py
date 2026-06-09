#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SITE_ROOT = SCRIPT_DIR.parent
if str(SITE_ROOT) not in sys.path:
    sys.path.insert(0, str(SITE_ROOT))
import os
import shutil
import sys
import pandas as pd


DEPLOY_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MLB_SOURCE_ROOT = PROJECT_ROOT / "sports" / "mlb"
MLB_SOURCE_ROOT = Path(
    os.environ.get(
        "EDGERANKED_MLB_SOURCE_DIR",
        os.environ.get("EDGERANKED_MLB_BASE_DIR", str(DEFAULT_MLB_SOURCE_ROOT)),
    )
)
MLB_MODEL_ROOT = PROJECT_ROOT / "sports" / "mlb" / "mlb_model"
if str(MLB_MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(MLB_MODEL_ROOT))

from reporting_validation import validate_mlb_best_bets_artifacts

SPORTS_ROOT = PROJECT_ROOT / "sports"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from sports.mlb.pipelines.validate_outputs import validate_mlb_outputs
except Exception:
    validate_mlb_outputs = None

MLB_PUBLISH_MODE = os.environ.get("MLB_PUBLISH_MODE", "legacy").strip().lower()
PUBLISH_SPORTS = {
    part.strip().lower()
    for part in os.environ.get("EDGERANKED_PUBLISH_SPORTS", "all").split(",")
    if part.strip()
}


def should_publish_mlb() -> bool:
    return "all" in PUBLISH_SPORTS or "mlb" in PUBLISH_SPORTS


def should_publish_wnba() -> bool:
    return "all" in PUBLISH_SPORTS or "wnba" in PUBLISH_SPORTS


def _mode_path(legacy: Path, canonical: Path) -> Path:
    if MLB_PUBLISH_MODE == "canonical" and canonical.exists():
        return canonical
    return legacy


RAW_LINES_SOURCE = MLB_SOURCE_ROOT / "mlb_model" / "mlb" / "outputs" / "lines_today_raw.csv"
SANITIZED_LINES_SOURCE = _mode_path(
    MLB_SOURCE_ROOT / "mlb_model" / "data" / "mlb" / "lines_today.csv",
    MLB_SOURCE_ROOT / "data" / "normalized" / "lines_today.csv",
)
FINAL_BOARD_SOURCE = MLB_SOURCE_ROOT / "mlb_model" / "mlb" / "outputs" / "betting_sheet_today.csv"
SITE_BOARD_TARGET = DEPLOY_ROOT / "mlb" / "outputs" / "betting_sheet_today.csv"
SITE_LINES_TARGET = DEPLOY_ROOT / "data" / "mlb" / "lines_today.csv"

CANO_HITTER_SUMMARY = MLB_SOURCE_ROOT / "outputs" / "site" / "hitter_summary_today.csv"
LEGACY_HITTER_SUMMARY = MLB_SOURCE_ROOT / "mlb_model" / "mlb" / "outputs" / "hitter_summary_today.csv"
CANO_FULL_HITTER = MLB_SOURCE_ROOT / "outputs" / "canonical" / "hitter_predictions_full.csv"

WNBA_SOURCE_ROOT = Path(os.environ.get("EDGERANKED_WNBA_BASE_DIR", str(SPORTS_ROOT / "wnba")))
WNBA_SNAPSHOT_TARGET = DEPLOY_ROOT / "wnba"
WNBA_EXCLUDE_NAMES = {".venv", "__pycache__", ".git"}


def refresh_wnba_snapshot() -> int:
    if not should_publish_wnba():
        return 0
    if not WNBA_SOURCE_ROOT.exists():
        print(f"SKIP WNBA snapshot: missing source {WNBA_SOURCE_ROOT}")
        return 0
    WNBA_SNAPSHOT_TARGET.mkdir(parents=True, exist_ok=True)
    updated = 0
    for source in WNBA_SOURCE_ROOT.iterdir():
        if source.name in WNBA_EXCLUDE_NAMES:
            continue
        target = WNBA_SNAPSHOT_TARGET / source.name
        if source.is_dir():
            shutil.copytree(
                source,
                target,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            shutil.copy2(source, target)
        updated += 1
    print(f"UPDATED WNBA snapshot: {WNBA_SNAPSHOT_TARGET} from {WNBA_SOURCE_ROOT} ({updated} top-level item(s))")
    return updated


COPIES = [
    (
        _mode_path(LEGACY_HITTER_SUMMARY, CANO_HITTER_SUMMARY),
        DEPLOY_ROOT / "mlb" / "outputs" / "hitter_summary_today.csv",
        "MLB hitter summary",
    ),
    (
        MLB_SOURCE_ROOT / "mlb_model" / "mlb" / "outputs" / "fantasy_projections_today.csv",
        DEPLOY_ROOT / "mlb" / "outputs" / "fantasy_projections_today.csv",
        "MLB fantasy projections",
    ),
    (
        MLB_SOURCE_ROOT / "mlb_model" / "mlb" / "outputs" / "pitcher_props_today.csv",
        DEPLOY_ROOT / "mlb" / "outputs" / "pitcher_props_today.csv",
        "MLB pitcher props",
    ),
    (
        MLB_SOURCE_ROOT / "mlb_model" / "mlb" / "outputs" / "mlb_pitcher_projections_today.csv",
        DEPLOY_ROOT / "mlb" / "outputs" / "mlb_pitcher_projections_today.csv",
        "MLB pitcher projections",
    ),
    (
        MLB_SOURCE_ROOT / "mlb_model" / "mlb" / "outputs" / "betting_sheet_today.csv",
        DEPLOY_ROOT / "mlb" / "outputs" / "betting_sheet_today.csv",
        "MLB betting sheet",
    ),
    (
        MLB_SOURCE_ROOT / "mlb_model" / "mlb" / "outputs" / "daily_betting_summary.csv",
        DEPLOY_ROOT / "mlb" / "outputs" / "daily_betting_summary.csv",
        "MLB daily betting summary",
    ),
    (
        MLB_SOURCE_ROOT / "mlb_model" / "mlb" / "outputs" / "bet_history.csv",
        DEPLOY_ROOT / "mlb" / "outputs" / "bet_history.csv",
        "MLB bet history",
    ),
    (
        MLB_SOURCE_ROOT / "mlb_model" / "mlb" / "outputs" / "hitter_tracking.csv",
        DEPLOY_ROOT / "mlb" / "outputs" / "hitter_tracking.csv",
        "MLB hitter tracking",
    ),
    (
        MLB_SOURCE_ROOT / "mlb_model" / "mlb" / "outputs" / "pitcher_tracking.csv",
        DEPLOY_ROOT / "mlb" / "outputs" / "pitcher_tracking.csv",
        "MLB pitcher tracking",
    ),
    (
        _mode_path(
            MLB_SOURCE_ROOT / "mlb_model" / "data" / "mlb" / "lines_today.csv",
            MLB_SOURCE_ROOT / "data" / "normalized" / "lines_today.csv",
        ),
        DEPLOY_ROOT / "data" / "mlb" / "lines_today.csv",
        "MLB lines",
    ),
    (
        CANO_FULL_HITTER,
        DEPLOY_ROOT / "mlb" / "outputs" / "hitter_predictions_full.csv",
        "MLB canonical hitter full board",
    ),
    (
        MLB_SOURCE_ROOT / "outputs" / "site" / "validation_manifest.json",
        DEPLOY_ROOT / "mlb" / "outputs" / "validation_manifest.json",
        "MLB validation manifest",
    ),
]


def _print_df_sample(label: str, path: Path, columns: list[str], limit: int = 8) -> None:
    print(f"\n=== {label} ===")
    print(f"path: {path}")
    if not path.exists():
        print("(missing)")
        return
    df = pd.read_csv(path)
    if df.empty:
        print("(empty)")
        return
    keep = [col for col in columns if col in df.columns]
    if not keep:
        print(df.head(limit).to_string(index=False))
        return
    print(df[keep].head(limit).to_string(index=False))


def _print_existing_site_leak_samples() -> None:
    _print_df_sample(
        "CURRENT SITE MLB BOARD SAMPLE BEFORE REFRESH",
        SITE_BOARD_TARGET,
        ["date", "market", "player_name", "line", "play", "matchup_pitcher", "opponent"],
    )
    _print_df_sample(
        "CURRENT SITE LINES SAMPLE BEFORE REFRESH",
        SITE_LINES_TARGET,
        ["PLAYER_NAME", "PLAYER_TYPE", "STAT", "LINE", "ODDS_TYPE", "RAW_STAT_TYPE"],
    )
    if not SITE_BOARD_TARGET.exists():
        return
    site_df = pd.read_csv(SITE_BOARD_TARGET)
    if site_df.empty:
        return
    market_col = "market" if "market" in site_df.columns else None
    line_col = "line" if "line" in site_df.columns else None
    play_col = "play" if "play" in site_df.columns else None
    if market_col and line_col:
        hitter_k_under_alt = site_df[
            site_df[market_col].astype(str).str.upper().eq("HITTER_K")
            & (
                site_df[play_col].astype(str).str.upper().eq("UNDER")
                if play_col
                else False
            )
            & pd.to_numeric(site_df[line_col], errors="coerce").gt(1.5)
        ]
        print(f"[mlb_site_publish] current site suspicious hitter-K alt-line rows: {len(hitter_k_under_alt)}")
        if not hitter_k_under_alt.empty:
            print(
                hitter_k_under_alt[
                    ["date", "market", "player_name", "line", "play", "matchup_pitcher"]
                ].head(10).to_string(index=False)
            )


def validate_mlb_site_source() -> None:
    print(f"[mlb_site_publish] publish mode: {MLB_PUBLISH_MODE}")
    print(f"[mlb_site_publish] live site board target path: {SITE_BOARD_TARGET}")
    print(f"[mlb_site_publish] live site lines target path: {SITE_LINES_TARGET}")
    print(f"[mlb_site_publish] email image / site source board path: {FINAL_BOARD_SOURCE}")
    print(f"[mlb_site_publish] sanitized source lines path: {SANITIZED_LINES_SOURCE}")
    if validate_mlb_outputs is None:
        print("Skipping MLB output validation: validate_mlb_outputs unavailable.")
        return 0

    validation_manifest = validate_mlb_outputs(
        projections_source_path=str(CANO_FULL_HITTER)
    )
    print(f"[mlb_site_publish] validation manifest: {validation_manifest}")

    if (MLB_SOURCE_ROOT / "mlb_model").resolve() == DEPLOY_ROOT.resolve():
        raise RuntimeError(
            "Refusing to refresh the site snapshot from itself. "
            f"Set EDGERANKED_MLB_SOURCE_DIR or use the default model root {DEFAULT_MLB_SOURCE_ROOT}."
        )

    _print_existing_site_leak_samples()
    validate_mlb_best_bets_artifacts(
        raw_lines_path=RAW_LINES_SOURCE,
        sanitized_lines_path=SANITIZED_LINES_SOURCE,
        final_board_path=FINAL_BOARD_SOURCE,
        logger=print,
    )
    _print_df_sample(
        "CORRECTED SOURCE BOARD SAMPLE",
        FINAL_BOARD_SOURCE,
        ["date", "market", "player_name", "line", "play", "matchup_pitcher", "opponent"],
    )
    _print_df_sample(
        "CORRECTED SANITIZED LINES SAMPLE",
        SANITIZED_LINES_SOURCE,
        ["PLAYER_NAME", "PLAYER_TYPE", "STAT", "LINE", "ODDS_TYPE", "RAW_STAT_TYPE"],
    )
    print("[mlb_site_publish] validated MLB source board is safe to publish to the live site snapshot")


def copy_one(source: Path, target: Path, label: str) -> bool:
    if not source.exists():
        print(f"SKIP {label}: missing source {source}")
        return False

    try:
        same_file = source.resolve() == target.resolve()
    except FileNotFoundError:
        same_file = False

    if same_file:
        print(f"SKIP {label}: source already matches target {target}")
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, target)
    except shutil.SameFileError:
        print(f"SKIP {label}: source already matches target {target}")
        return False
    print(f"UPDATED {label}: {target}")
    return True


def main() -> int:
    updated = 0

    if should_publish_mlb():
        validate_mlb_site_source()
        for source, target, label in COPIES:
            updated += int(copy_one(source, target, label))
    else:
        print(
            "[site_publish] EDGERANKED_PUBLISH_SPORTS="
            f"{','.join(sorted(PUBLISH_SPORTS))}; skipping MLB validation/copy"
        )

    updated += refresh_wnba_snapshot()

    print("")
    print(f"Snapshot refresh complete. Updated {updated} file(s).")
    print("Next step:")
    print("  run scripts/publish_render_site.sh to sync the refreshed snapshot into the live site")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
