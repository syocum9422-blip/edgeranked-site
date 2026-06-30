"""EdgeRanked WNBA Engine V2 — global config.

V2 is built in isolation from the live production tree. Nothing here writes to
production paths. Phase 0 (evaluation) is strictly read-only on historical data.
"""
from __future__ import annotations

from pathlib import Path

# --- Paths -----------------------------------------------------------------
V2_ROOT = Path(__file__).resolve().parent
PROD_ROOT = V2_ROOT.parent                      # sports/wnba
OUTPUTS = V2_ROOT / "outputs"
BASELINE_DIR = OUTPUTS / "baseline"

# Historical sources (read-only) produced by the live pipeline.
GRADED_BETS_PATH = PROD_ROOT / "Best_Bets" / "graded_bets.csv"
LEDGER_PATH = PROD_ROOT / "learning" / "graded_predictions_ledger.csv"
BETS_HISTORY_PATH = PROD_ROOT / "Best_Bets" / "wnba_bets_history.csv"

# --- Betting economics ------------------------------------------------------
# The live book is PrizePicks (pick'em, no per-leg American odds were captured).
# We benchmark realized win rate against two references and report ROI under a
# standard -110 sportsbook proxy so results are comparable to industry norms.
# NOTE: PrizePicks payouts are parlay-structured; per-leg ROI here is a PROXY.
BREAKEVEN_EVEN_MONEY = 0.50        # flat even-money reference
BREAKEVEN_MINUS_110 = 0.5238       # standard -110 vig breakeven
DEFAULT_ODDS_AMERICAN = -110       # ROI proxy odds

# --- Calibration ------------------------------------------------------------
CALIB_BINS = 10                    # reliability-curve bins
MIN_BUCKET_N = 25                  # min samples for a bucket to be trusted

# --- Markets ----------------------------------------------------------------
CORE_MARKETS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
COMBO_MARKETS = ["pa", "pr", "ra", "pra"]
ALL_MARKETS = CORE_MARKETS + COMBO_MARKETS

RANDOM_SEED = 42
