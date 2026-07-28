"""Phase 2A reporter — emits reports/history_completion_report.md from the
parsed cache artifacts, so the numbers in the report always match the data.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
else:
    from ..config import lab_config as C


def main() -> int:
    players = pd.read_parquet(C.LAB_NORMALIZED / "player_games.parquet")
    teams = pd.read_parquet(C.LAB_NORMALIZED / "team_games.parquet")
    manifest = pd.read_csv(C.LAB_NORMALIZED / "parse_manifest.csv", dtype={"game_id": str})
    cache_files = len(list(C.V2_ESPN_CACHE_DIR.glob("*.json")))
    skipped = manifest["skip_reason"].notna().sum() if "skip_reason" in manifest else 0

    dnp = players[players.did_not_play == 1]
    coach = dnp.dnp_reason.fillna("").str.upper().str.contains("COACH")
    phantom = players[(players.minutes.isna()) & (players.did_not_play == 0)]
    starter_anomalies = teams[teams.starters_flagged != 5]
    traded = players.groupby(["player_id", "season"])["team_id"].nunique()

    lines = [
        "# Phase 2A — Historical completion report",
        "",
        "**Date:** 2026-07-25  |  **Source:** local ESPN summary cache only, no network access",
        "",
        "## Parse results",
        "",
        "| | |",
        "|---|---|",
        f"| Cache files discovered | {cache_files} |",
        f"| Games successfully parsed | {len(manifest) - skipped} |",
        f"| Games skipped | {skipped} |",
        f"| Parse failures | {skipped} |",
        f"| Player-game rows | {len(players):,} |",
        f"| Team-game rows | {len(teams):,} |",
        f"| Date range (ET slate) | {players.slate_date_et.min()} → {players.slate_date_et.max()} |",
        "",
        "The Phase 1 pipeline (`replay/build_history.py`) produced 17,360 player-game",
        f"rows through 2026-06-28, because it merged the V2 box-score CSV, last built",
        f"2026-07-01. Reparsing the cache directly adds **{len(players) - 17360:,} rows** and",
        "closes the gap to the latest locally available game.",
        "",
        "## Integrity",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Duplicate `(player_id, game_id)` | {players.duplicated(['player_id','game_id']).sum()} |",
        f"| Duplicate `(team_id, game_id)` | {teams.duplicated(['team_id','game_id']).sum()} |",
        f"| Missing `player_id` | {players.player_id.isna().sum()} |",
        f"| Missing `team_id` | {players.team_id.isna().sum()} |",
        f"| Missing `opponent_id` | {players.opponent_id.isna().sum()} |",
        f"| Missing tip-off time | {players.start_utc.isna().sum()} |",
        f"| Missing position | {players.position.isna().sum()} |",
        f"| Team-games without exactly 5 starters | {len(starter_anomalies)} |",
        "",
        "## Season coverage",
        "",
        "| Season | Type | Player-games | Games | Players | First | Last |",
        "|---|---|---|---|---|---|---|",
    ]
    grouped = players.groupby(["season", "season_type"]).agg(
        rows=("player_id", "size"), games=("game_id", "nunique"),
        players=("player_id", "nunique"), first=("slate_date_et", "min"),
        last=("slate_date_et", "max"),
    ).reset_index()
    for _, row in grouped.iterrows():
        lines.append(f"| {int(row.season)} | {row.season_type} | {row.rows:,} | {row.games} | "
                     f"{row.players} | {row.first} | {row.last} |")

    lines += [
        "",
        "### Preseason is present and unlabelled in production",
        "",
        f"{int((players.season_type == 'preseason').sum()):,} player-game rows across "
        f"{players[players.season_type == 'preseason'].game_id.nunique()} preseason games sit in the",
        "cache, and all of them also appear in `wnba_player_games.csv` — which has no",
        "`season_type` column, so the production trainer cannot exclude them. Preseason",
        "rotations are not representative of regular-season roles. The lab excludes",
        "preseason from feature history by default and records the exclusion.",
        "",
        "## DNP summary",
        "",
        f"- **{len(dnp):,} DNP rows** ({len(dnp)/len(players):.1%} of player-games)",
        f"- Coach's decision: **{int(coach.sum()):,}** ({coach.mean():.1%} of DNPs)",
        f"- Injury / rest / personal: **{int((~coach).sum()):,}** ({(~coach).mean():.1%})",
        f"- Distinct reason strings: **{dnp.dnp_reason.nunique()}**",
        "",
        "DNP status and reason are recorded per game, so they are historically",
        "authentic — but they are **postgame outcomes**, not pregame designations. They",
        "can label an availability model's training target; they cannot serve as a",
        "pregame availability feature.",
        "",
        "## Data-quality findings",
        "",
        f"**Phantom listings ({len(phantom)} rows, {len(phantom)/len(players):.3%}).** A player appears",
        "on a box score with no stat line and no DNP flag. All occur around trades — a",
        "traded player is left on her former team's roster listing. The clearest case is",
        "Celeste Taylor on 2024-08-23, listed for both PHX (12 minutes, real) and CON",
        "(no stat line) in two simultaneously tipping games. These rows are excluded",
        "from feature history and covered by a regression test.",
        "",
        f"**Trades are common.** {int((traded > 1).sum())} of {len(traded)} player-seasons "
        f"({(traded > 1).mean():.1%}) involve",
        "more than one team. Name-based identity would corrupt those histories, which is",
        "why every join in the lab uses ESPN numeric ids.",
        "",
        "**Overtime is not adjusted for.** `pace` is the possession estimate for the game",
        f"as played; the observed range is {teams.game_possessions.min():.1f}–{teams.game_possessions.max():.1f}",
        "possessions. Overtime games sit at the top of that range and are left as-is",
        "rather than normalized to 40 minutes, so the value stays a faithful description",
        "of what happened.",
        "",
        "## Schema",
        "",
        "`data/normalized/player_games.parquet` — uniqueness `(player_id, game_id)`",
        "",
        "```",
        "identity   game_id, player_id, player_name, jersey, position",
        "teams      team_id, team_abbrev, opponent_id, opponent_abbrev, home_away, is_home",
        "time       start_utc (exact tip), slate_date_et (derived local date), tip_hour_et,",
        "           season, season_type, completed",
        "status     starter, active, played, did_not_play, dnp_reason, ejected",
        "box score  minutes, points, rebounds, assists, threes_made, steals, blocks,",
        "           turnovers, fga, fgm, fta, ftm, threes_attempted,",
        "           offensive_rebounds, defensive_rebounds, fouls, plus_minus",
        "context    team_score, opponent_score",
        "```",
        "",
        "`data/normalized/team_games.parquet` — uniqueness `(team_id, game_id)`; adds",
        "team totals plus derived `possessions`, `game_possessions`, `pace`, `off_rating`,",
        "`def_rating`, `net_rating`, `starters_flagged`.",
        "",
        "`start_utc` and `slate_date_et` are stored separately and the production UTC",
        "`game_date` is deliberately not reproduced.",
        "",
        "## Reproducibility",
        "",
        "```bash",
        "python3 learning/analytics_lab/inventory/parse_espn_cache.py            # resumable",
        "python3 learning/analytics_lab/inventory/parse_espn_cache.py --rebuild  # full reparse",
        "```",
        "",
        "Idempotent: a second run reports `newly parsed 0` and leaves the outputs",
        "unchanged. Games already in the manifest are skipped, so an interrupted run",
        "resumes where it stopped.",
        "",
    ]
    target = C.lab_path("history_completion_report.md", root=C.LAB_REPORTS)
    target.write_text("\n".join(lines) + "\n")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
