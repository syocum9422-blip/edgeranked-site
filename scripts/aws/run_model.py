import sys
import os
import subprocess
import shutil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "mlb" / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MPL_CACHE_DIR = BASE_DIR / ".mplcache"
MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_CACHE_DIR))


def _default_icloud_dir():
    if os.environ.get("EDGERANKED_MLB_ICLOUD_DIR"):
        return Path(os.environ["EDGERANKED_MLB_ICLOUD_DIR"])
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "MLB_Model"
    return None


ICLOUD_DIR = _default_icloud_dir()


def _resolve_first_existing_path(candidates):
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return candidates[0] if candidates else Path()


def _resolve_site_repo_root():
    env_root = os.environ.get("EDGERANKED_SITE_REPO_DIR")
    candidates = []
    if env_root:
        candidates.append(Path(env_root))
    for ancestor in BASE_DIR.parents[:4]:
        candidates.extend([ancestor / "site", ancestor / "NBA_Model"])
    for candidate in candidates:
        if not candidate.exists():
            continue
        if (candidate / "generate_results_page.py").exists():
            return candidate
        if (candidate / "scripts" / "publish_render_site.sh").exists():
            return candidate
    return _resolve_first_existing_path(candidates)


SITE_REPO_ROOT = _resolve_site_repo_root()
SHARED_PAGE_SCRIPT = SITE_REPO_ROOT / "generate_results_page.py"
RENDER_PUBLISH_SCRIPT = SITE_REPO_ROOT / "scripts" / "publish_render_site.sh"


def resolve_python():
    candidates = []
    env_python = os.environ.get("MLB_PYTHON_BIN")
    if env_python:
        candidates.append(Path(env_python))
    candidates.extend(
        [
            BASE_DIR / ".venv" / "bin" / "python",
            BASE_DIR.parent / ".venv" / "bin" / "python",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "python3"


PYTHON = resolve_python()

# Run in the order you want the full pipeline to happen.
# required=True means stop the whole pipeline if that step fails.
# required=False means print a warning and continue.
STEPS = []

if (BASE_DIR / "refresh_mlb_results.py").exists() and not (Path.cwd() / ".skip_results_refresh").exists():
    STEPS.append({"name": "Morning results refresh", "script": "refresh_mlb_results.py", "required": False})

STEPS += [
    {"name": "Hitter projections", "script": "predict_hitter.py", "required": True},
    {"name": "Hitter strikeout projections", "script": "predict_hitter_strikeouts.py", "required": False},
    {"name": "Hitter summary report", "script": "build_hitter_summary_report.py", "required": False},
    {"name": "Pitcher projections", "script": "predict_pitchers.py", "required": True},
    {"name": "Pitcher props report", "script": "build_pitcher_props_report.py", "required": False},
    {"name": "Build projection images", "script": "build_predictions_image.py", "required": True},

    # Optional extras — these only run if the file exists.
    {"name": "Top plays", "script": "top_plays.py", "required": False},
    {"name": "Betting sheet", "script": "build_betting_sheet.py", "required": False},
    {"name": "Track hitter predictions", "script": "track_hitter_predictions.py", "required": False},
    {"name": "Track pitcher predictions", "script": "track_pitcher_predictions.py", "required": False},
    {"name": "Mobile image", "script": "build_mobile_image.py", "required": False},
    {"name": "Display projections", "script": "display_projections.py", "required": False},
]

ICLOUD_FILES = [
    "hitter_predictions_today.csv",
    "hitter_strikeouts_today.csv",
    "hitter_summary_today.csv",
    "fantasy_projections_today.csv",
    "mlb_pitcher_projections_today.csv",
    "pitcher_props_today.csv",
    "pitcher_best_bets_today.csv",
    "betting_sheet_today.csv",
    "top_plays_today.csv",
    "hitter_tracking.csv",
    "pitcher_tracking.csv",
    "bet_history.csv",
    "daily_betting_summary.csv",
    "betting_record.png",
    "hitter_predictions_today.png",
    "pitcher_predictions_today.png",
    "betting_sheet_mobile_today.png",
]


def run_step(step):
    script_path = BASE_DIR / step["script"]

    print("\n" + "=" * 40)
    print(f"RUNNING: {step['name']}")
    print("=" * 40)

    if not script_path.exists():
        message = f"Script not found: {script_path}"
        if step["required"]:
            print(f"ERROR: {message}")
            return False
        print(f"SKIPPING OPTIONAL STEP: {message}")
        return True

    cmd = [PYTHON, str(script_path)]

    result = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        text=True,
    )

    if result.returncode != 0:
        if step["required"]:
            print(f"ERROR: Step failed -> {step['name']}")
            return False
        print(f"WARNING: Optional step failed -> {step['name']}")
        return True

    print(f"DONE: {step['name']}")
    return True


def show_outputs():
    print("\n" + "=" * 40)
    print("OUTPUT FILES")
    print("=" * 40)

    if not OUTPUT_DIR.exists():
        print(f"Output directory not found: {OUTPUT_DIR}")
        return

    files = sorted(
        [p for p in OUTPUT_DIR.iterdir() if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not files:
        print(f"No files found in: {OUTPUT_DIR}")
        return

    print(f"Output directory: {OUTPUT_DIR}\n")
    for f in files[:25]:
        print(f"{f.name}")


def sync_to_icloud():
    print("\n" + "=" * 40)
    print("SYNC TO ICLOUD")
    print("=" * 40)

    if ICLOUD_DIR is None:
        print("SKIPPING ICLOUD SYNC: No EDGERANKED_MLB_ICLOUD_DIR set for this environment.")
        return

    try:
        ICLOUD_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"WARNING: Could not create iCloud folder: {exc}")
        return

    copied = []
    skipped = []

    for filename in ICLOUD_FILES:
        src = OUTPUT_DIR / filename
        dst = ICLOUD_DIR / filename

        if not src.exists():
            skipped.append(filename)
            continue

        try:
            shutil.copy2(src, dst)
            copied.append(filename)
        except Exception as exc:
            print(f"WARNING: Could not copy {filename}: {exc}")

    print(f"iCloud folder: {ICLOUD_DIR}")
    if copied:
        print("\nCopied:")
        for name in copied:
            print(name)

    if skipped:
        print("\nSkipped (not found):")
        for name in skipped:
            print(name)


def run_follow_up_email():
    if (Path.cwd() / ".skip_mlb_email").exists():
        print("SKIPPING EMAIL: Later day run requested no email send.")
        return

    script_path = BASE_DIR / "send_mlb_results_email.py"
    if not script_path.exists():
        print("SKIPPING EMAIL: send_mlb_results_email.py not found.")
        return

    print("\n" + "=" * 40)
    print("SEND MLB EMAIL")
    print("=" * 40)

    result = subprocess.run([PYTHON, str(script_path)], cwd=str(BASE_DIR), text=True)
    if result.returncode != 0:
        print("WARNING: MLB email step failed.")
        return

    print("DONE: MLB email step")


def refresh_shared_page():
    if not SHARED_PAGE_SCRIPT.exists():
        print("SKIPPING SHARED PAGE: generate_results_page.py not found.")
        return

    print("\n" + "=" * 40)
    print("REFRESH SHARED PAGE")
    print("=" * 40)

    result = subprocess.run([PYTHON, str(SHARED_PAGE_SCRIPT)], cwd=str(SHARED_PAGE_SCRIPT.parent), text=True)
    if result.returncode != 0:
        print("WARNING: Shared page refresh failed.")
        return

    print("DONE: Shared page refresh")


def publish_render_site():
    if not RENDER_PUBLISH_SCRIPT.exists():
        print("SKIPPING RENDER PUBLISH: publish_render_site.sh not found.")
        return

    print("\n" + "=" * 40)
    print("PUBLISH RENDER SITE")
    print("=" * 40)

    result = subprocess.run([str(RENDER_PUBLISH_SCRIPT)], cwd=str(RENDER_PUBLISH_SCRIPT.parent), text=True)
    if result.returncode != 0:
        print("WARNING: Render publish step failed.")
        return

    print("DONE: Render publish step")


def main():
    print("\n" + "=" * 40)
    print("STARTING FULL MLB PIPELINE")
    print("=" * 40)
    print(f"Project folder: {BASE_DIR}")
    print(f"Python: {PYTHON}")

    for step in STEPS:
        ok = run_step(step)
        if not ok:
            print("\nPIPELINE STOPPED.")
            show_outputs()
            sys.exit(1)

    print("\n" + "=" * 40)
    print("FULL MLB PIPELINE COMPLETE")
    print("=" * 40)

    show_outputs()
    sync_to_icloud()
    refresh_shared_page()
    publish_render_site()
    run_follow_up_email()


if __name__ == "__main__":
    main()
