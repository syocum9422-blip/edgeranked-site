import subprocess
import sys
import os
import csv
from pathlib import Path


DEFAULT_LINEUP_FETCH_ENV = {
    "NBA_LINEUP_STINT_MAX_GAMES": "80",
    "NBA_LINEUP_STINT_MAX_NEW_GAMES": "6",
    "NBA_LINEUP_STINT_RETRY_ATTEMPTS": "2",
    "NBA_LINEUP_STINT_RETRY_SLEEP": "1.5",
    "NBA_LINEUP_STINT_SAVE_EVERY": "1",
}
PROJECT_PYTHON = str(Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python")
TEAMS_TODAY_PATH = str(Path(__file__).resolve().parents[2] / "teams_today.csv")
MIN_EXPECTED_SLATE_TEAMS = 4


def run_step(label, command):
    print(f"\n{label}")
    print(f"Running: {command}")

    result = subprocess.run(command, shell=True)

    if result.returncode != 0:
        print(f"\nStopped because this step failed: {label}")
        sys.exit(result.returncode)


def shell_command_with_env(command, env_defaults):
    env_parts = []
    for key, value in env_defaults.items():
        resolved = os.environ.get(key, value)
        env_parts.append(f'{key}="{resolved}"')
    return " ".join(env_parts + [command])


def slate_team_count(path=TEAMS_TODAY_PATH):
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            team_col = None
            if reader.fieldnames:
                upper_names = {name.upper(): name for name in reader.fieldnames}
                team_col = upper_names.get("TEAM_ABBREVIATION") or upper_names.get("TEAM")
            if not team_col:
                return 0
            teams = {
                str(row.get(team_col, "")).strip().upper()
                for row in reader
                if str(row.get(team_col, "")).strip()
            }
            return len(teams)
    except Exception:
        return 0


def ensure_reasonable_slate():
    team_count = slate_team_count()
    if team_count >= MIN_EXPECTED_SLATE_TEAMS:
        print(f"teams_today.csv sanity check passed with {team_count} teams.")
        return

    print(f"teams_today.csv only has {team_count} teams. Retrying fetch_today_teams.py once...")
    run_step("Step 7b: Re-fetching today's teams...", f'"{PROJECT_PYTHON}" fetch_today_teams.py')
    team_count = slate_team_count()
    if team_count >= MIN_EXPECTED_SLATE_TEAMS:
        print(f"teams_today.csv recovered to {team_count} teams after retry.")
        return

    print(
        f"WARNING: teams_today.csv still only has {team_count} teams after retry. "
        "Projection build will ignore the slate-team filter for this run."
    )


def main():
    skip_training = os.environ.get("NBA_SKIP_TRAINING", "").strip().lower() in {"1", "true", "yes", "y"}

    run_step("Step 1: Fetching game data...", f'"{PROJECT_PYTHON}" fetch_games.py')
    try:
        run_step(
            "Step 2: Fetching lineup stints...",
            shell_command_with_env(f'"{PROJECT_PYTHON}" fetch_lineup_stints.py', DEFAULT_LINEUP_FETCH_ENV),
        )
    except SystemExit:
        print("\nStep 2: Lineup-stint fetch failed. Continuing without lineup stints for now.")
    try:
        run_step("Step 3: Building rotation templates...", f'"{PROJECT_PYTHON}" build_rotation_templates.py')
    except SystemExit:
        print("\nStep 3: Rotation-template build failed. Continuing without stint-derived templates for now.")
    run_step("Step 4: Building dataset...", f'"{PROJECT_PYTHON}" build_dataset.py')

    if skip_training:
        print("\nStep 5: Skipping stat-model training for this refresh")
        print("Step 6: Skipping minutes-model training for this refresh")
    else:
        run_step("Step 5: Training stat models...", f'"{PROJECT_PYTHON}" train_models.py')
        run_step("Step 6: Training minutes model...", f'"{PROJECT_PYTHON}" train_minutes_model.py')

    run_step("Step 7: Getting today's teams...", f'"{PROJECT_PYTHON}" fetch_today_teams.py')
    ensure_reasonable_slate()
    run_step("Step 8: Generating projections...", f'"{PROJECT_PYTHON}" predict_today.py')
    print("\nAll steps finished successfully.")


if __name__ == "__main__":
    main()
