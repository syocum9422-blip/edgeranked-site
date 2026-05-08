# WNBA Model Pipeline

This project is set up to follow a practical daily workflow and now mirrors your NBA layout more closely:

- top-level `projections.csv`
- top-level `wnba_best_bets_today.csv`
- `Best_Bets/` folder for history and grading artifacts

1. `fetch_wnba_data.py`
2. `import_wnba_csv.py` if you downloaded a historical CSV manually
2. `build_wnba_dataset.py`
3. `train_wnba_models.py`
4. `train_wnba_minutes_model.py`
5. `build_wnba_features_today.py`
6. `simulate_wnba_today.py`
7. `build_wnba_best_bets.py`
8. `fill_wnba_actuals.py`
9. `grade_wnba_best_bets.py`
10. `calibrate_wnba_model.py`

## Quick start

From Terminal:

```bash
cd "/Users/steveyocum/Library/Mobile Documents/com~apple~CloudDocs/WNBA"
python3 run_wnba_model.py
```

Or:

```bash
cd "/Users/steveyocum/WNBA_Model"
./run_wnba_model.sh
```

## Quick bootstrap with a downloaded dataset

1. Download a WNBA historical player-game dataset.
2. Save it as:
   `data/raw/source_wnba_dataset.csv`
3. Run:

```bash
python3 import_wnba_csv.py
python3 run_wnba_model.py
```

## Data sources

`fetch_wnba_data.py` supports three modes at the top of the file:

- `SOURCE_MODE = "auto"`: tries official WNBA stats endpoints first, then local CSV files.
- `SOURCE_MODE = "api"`: requires official WNBA stats endpoints to succeed.
- `SOURCE_MODE = "csv"`: only uses local files.

### Practical default

Before the 2026 season opens, the best bootstrap path is to train on completed historical seasons:

- `2023`
- `2024`
- `2025`

That is already the default in `HISTORICAL_SEASONS`.

## Raw files you can maintain manually

Files live in `data/raw/`:

- `wnba_player_games_raw.csv`
- `wnba_team_context_raw.csv`
- `wnba_schedule_today_raw.csv`
- `wnba_sportsbook_lines_raw.csv`
- `wnba_player_positions_raw.csv`
- `wnba_player_status_raw.csv`

### Sportsbook lines

Populate:

- `data/raw/wnba_sportsbook_lines_raw.csv`

Columns:

- `player_name`
- `team`
- `opponent`
- `stat`
- `line`
- `over_odds`
- `under_odds`
- `sportsbook`

Accepted stat names:

- `points`
- `rebounds`
- `assists`
- `threes_made`
- `steals`
- `blocks`

Aliases like `pts`, `reb`, `ast`, `fg3m`, `stl`, and `blk` are normalized automatically.

## Known upgrade points

- Player positions are still best handled by a maintained CSV until a stronger roster source is wired in.
- Player status / injuries are also best maintained with a daily CSV.
- Official stats endpoints can change without notice, so the CSV fallback remains important.
- If you later want market automation, the clean insert point is `data/raw/wnba_sportsbook_lines_raw.csv`.

## New production helpers

- `archive_wnba_outputs.py` stores dated snapshots of projections and best bets.
- `calibrate_wnba_model.py` summarizes whether simulated hit rates are over or under actual outcomes once bets are graded.
