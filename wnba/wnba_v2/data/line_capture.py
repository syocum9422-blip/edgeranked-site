"""Phase 2 prerequisite — line capture & open/close consolidation.

Two jobs:
  1. consolidate_prop_snapshots(): turn the intraday PrizePicks snapshots the live
     pipeline already writes (data/raw/line_snapshots/*.csv) into a CLV-ready
     open/close history per (date, player, stat). This is pure value from data we
     ALREADY collect but never consolidated — it unblocks real CLV going forward.
  2. GameLinesFetcher: a pluggable interface to start capturing GAME spreads/totals
     (currently NOT collected). Wire any odds source to it; until then it no-ops so
     the rebuild is never blocked. Captured game lines append to the same history
     store and become an OPTIONAL Vegas feature for the Phase 2 pace engine.

Run (backfill from existing snapshots): .venv/bin/python -m wnba_v2.data.line_capture
"""
from __future__ import annotations

import glob
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_v2 import config as C

SNAPSHOT_DIR = C.PROD_ROOT / "data" / "raw" / "line_snapshots"
HISTORY_DIR = C.V2_ROOT / "data" / "line_history"
PROP_OPEN_CLOSE = HISTORY_DIR / "prop_open_close.csv"
GAME_LINES_SNAPSHOTS = HISTORY_DIR / "game_lines_snapshots.csv"
GAME_LINES_OPEN_CLOSE = HISTORY_DIR / "game_open_close.csv"


# --------------------------------------------------------------------------- #
# 1. Prop snapshot -> open/close consolidation (CLV)
# --------------------------------------------------------------------------- #
def _consolidate_frame(snap: pd.DataFrame, date_str: str) -> pd.DataFrame:
    snap = snap.copy()
    snap["snapshot_at"] = pd.to_datetime(snap["snapshot_at"], errors="coerce", utc=True)
    snap = snap.dropna(subset=["snapshot_at"])
    key = ["player_name", "team", "opponent", "stat"]
    snap = snap.sort_values("snapshot_at")
    g = snap.groupby(key, dropna=False)
    out = g.agg(
        open_line=("line", "first"),
        close_line=("line", "last"),
        open_at=("snapshot_at", "first"),
        close_at=("snapshot_at", "last"),
        n_snapshots=("line", "size"),
        min_line=("line", "min"),
        max_line=("line", "max"),
        sportsbook=("sportsbook", "last"),
    ).reset_index()
    out["line_move"] = out["close_line"] - out["open_line"]
    out["date"] = date_str
    return out


def consolidate_prop_snapshots(date_str: str | None = None) -> pd.DataFrame:
    """Consolidate one day's snapshot file (default: latest) into open/close rows."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if date_str:
        files = [SNAPSHOT_DIR / f"wnba_lines_snapshots_{date_str}.csv"]
    else:
        files = sorted(glob.glob(str(SNAPSHOT_DIR / "wnba_lines_snapshots_*.csv")))[-1:]
        files = [Path(f) for f in files]
    frames = []
    for f in files:
        if not f.exists():
            continue
        ds = f.stem.replace("wnba_lines_snapshots_", "")
        snap = pd.read_csv(f)
        if "snapshot_at" not in snap or "line" not in snap:
            continue
        frames.append(_consolidate_frame(snap, ds))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    _append_dedup(PROP_OPEN_CLOSE, out, ["date", "player_name", "stat"])
    return out


def backfill_all_props() -> pd.DataFrame:
    """One-time: consolidate EVERY existing snapshot file into open/close history."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    for f in sorted(glob.glob(str(SNAPSHOT_DIR / "wnba_lines_snapshots_*.csv"))):
        ds = Path(f).stem.replace("wnba_lines_snapshots_", "")
        snap = pd.read_csv(f)
        if "snapshot_at" in snap and "line" in snap:
            frames.append(_consolidate_frame(snap, ds))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(["date", "player_name", "stat"], keep="last")
    out.to_csv(PROP_OPEN_CLOSE, index=False)
    return out


# --------------------------------------------------------------------------- #
# 2. Game spread/total capture (pluggable; not collected yet)
# --------------------------------------------------------------------------- #
class GameLinesFetcher:
    """Interface for capturing game spreads/totals. Subclass and implement fetch()
    to wire an odds source (The Odds API, Pinnacle, sportsbook scrape, etc.).
    The default no-ops so the pipeline never breaks without a source configured."""

    COLUMNS = ["game_date", "home", "away", "spread", "total", "sportsbook"]

    def fetch(self) -> pd.DataFrame:
        """Return rows: game_date, home, away, spread, total, sportsbook. Empty = no source."""
        return pd.DataFrame(columns=self.COLUMNS)


class TheOddsAPIFetcher(GameLinesFetcher):
    """Captures WNBA consensus spreads/totals from The Odds API.

    Set the API key via env THE_ODDS_API_KEY (free tier exists). With no key this
    no-ops (returns empty) so cron never breaks — capture simply begins the moment
    a key is provided. Consensus = median across books, robust to a single outlier.
    """
    SPORT = "basketball_wnba"
    URL = ("https://api.the-odds-api.com/v4/sports/{sport}/odds"
           "?apiKey={key}&regions=us&markets=spreads,totals&oddsFormat=american")

    def __init__(self, api_key: str | None = None):
        import os
        # Accept either env name; the box already has ODDS_API_KEY provisioned.
        self.api_key = (api_key or os.environ.get("THE_ODDS_API_KEY")
                        or os.environ.get("ODDS_API_KEY"))

    def fetch(self) -> pd.DataFrame:
        if not self.api_key:
            return pd.DataFrame(columns=self.COLUMNS)
        import json as _json
        import urllib.request
        url = self.URL.format(sport=self.SPORT, key=self.api_key)
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                games = _json.loads(r.read().decode("utf-8"))
        except Exception:
            return pd.DataFrame(columns=self.COLUMNS)
        rows = []
        for g in games:
            home, away = g.get("home_team"), g.get("away_team")
            gdate = str(g.get("commence_time", ""))[:10]
            spreads, totals = [], []
            for bk in g.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    if mk["key"] == "spreads":
                        for o in mk["outcomes"]:
                            if o.get("name") == home and o.get("point") is not None:
                                spreads.append(float(o["point"]))
                    elif mk["key"] == "totals":
                        for o in mk["outcomes"]:
                            if o.get("name") == "Over" and o.get("point") is not None:
                                totals.append(float(o["point"]))
            rows.append({
                "game_date": gdate, "home": home, "away": away,
                "spread": float(np.median(spreads)) if spreads else np.nan,
                "total": float(np.median(totals)) if totals else np.nan,
                "sportsbook": "consensus",
            })
        return pd.DataFrame(rows, columns=self.COLUMNS)


def capture_game_lines(fetcher: GameLinesFetcher) -> int:
    """Append a timestamped snapshot of current game lines. Returns rows captured."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    df = fetcher.fetch()
    if df is None or df.empty:
        return 0
    df = df.copy()
    df["snapshot_at"] = datetime.now(timezone.utc).isoformat()
    _append(GAME_LINES_SNAPSHOTS, df)
    return len(df)


def consolidate_game_lines() -> pd.DataFrame:
    """Open/close per game from accumulated game-line snapshots."""
    if not GAME_LINES_SNAPSHOTS.exists():
        return pd.DataFrame()
    snap = pd.read_csv(GAME_LINES_SNAPSHOTS)
    snap["snapshot_at"] = pd.to_datetime(snap["snapshot_at"], errors="coerce", utc=True)
    snap = snap.dropna(subset=["snapshot_at"]).sort_values("snapshot_at")
    g = snap.groupby(["game_date", "home", "away"], dropna=False)
    out = g.agg(
        open_spread=("spread", "first"), close_spread=("spread", "last"),
        open_total=("total", "first"), close_total=("total", "last"),
        n_snapshots=("spread", "size"),
    ).reset_index()
    out.to_csv(GAME_LINES_OPEN_CLOSE, index=False)
    return out


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _append(path: Path, df: pd.DataFrame) -> None:
    df.to_csv(path, mode="a", header=not path.exists(), index=False)


def _append_dedup(path: Path, df: pd.DataFrame, keys: list[str]) -> None:
    if path.exists():
        prev = pd.read_csv(path)
        df = pd.concat([prev, df], ignore_index=True).drop_duplicates(keys, keep="last")
    df.to_csv(path, index=False)


if __name__ == "__main__":
    hist = backfill_all_props()
    if hist.empty:
        print("No snapshot history found.")
    else:
        moved = hist[hist["line_move"].abs() > 0]
        print(f"Consolidated {len(hist)} prop open/close rows over "
              f"{hist['date'].nunique()} days -> {PROP_OPEN_CLOSE}")
        print(f"  rows with line movement: {len(moved)} ({len(moved)/len(hist)*100:.1f}%)")
        print(f"  mean |move| (moved only): {moved['line_move'].abs().mean():.3f}")
        print(f"  date range: {hist['date'].min()} -> {hist['date'].max()}")
    print("\nGame spread/total capture: scaffold ready (wire a GameLinesFetcher to begin).")
