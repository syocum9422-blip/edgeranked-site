# Phase 4C — Injury / Availability Audit (proposal only, not integrated)

## Root cause: the feed is not dead — it is bot-blocked by its User-Agent

`data/raw/wnba_player_status.csv` is empty (header only). The pipeline wiring is **correct**:
`fetch_wnba_data.main()` → `resolve_player_status()` → `fetch_espn_injuries()` →
writes `CANONICAL_PLAYER_STATUS_PATH`. The scrape itself returns nothing.

Live diagnosis (`https://www.espn.com/wnba/injuries`):

| Request headers | Bytes returned | Injury data present |
|---|---|---|
| **Current scraper** (`ESPN_INJURIES_HEADERS`, Mac-Chrome 124 UA + Accept + Accept-Language) | **1,987** | ❌ no |
| `Mozilla/5.0` (minimal) | **298,114** | ✅ yes |
| `Mozilla/5.0` + Accept | 298,114 | ✅ yes |
| `Mozilla/5.0` + Accept-Language | 298,114 | ✅ yes |
| Scraper UA only (no Accept) | 0 | ❌ no |

ESPN's bot mitigation serves a **1,987-byte stub** to the specific detailed Mac-Chrome UA
string the scraper uses, but the **full page to a plain `Mozilla/5.0`**. With the full page,
the existing parser works unchanged: **7 team sections, 9 current injury entries** (all
"Day-To-Day" right now). The HTML classes the parser targets (`Table__league-injuries`,
`injuries__teamName`, `TextStatus`) are all still present.

### Fix (one line, proposal — DO NOT integrate per Phase 4 rules)
Change `ESPN_INJURIES_HEADERS["User-Agent"]` in `fetch_wnba_data.py:334` from the detailed
Chrome string to a generic `"Mozilla/5.0"` (or rotate UAs / add a retry that falls back to
the generic UA when the response is < ~5 KB). This restores the feed with zero parser change.
Recommend a guard: if the page is < 5 KB or yields 0 sections, log a hard warning and retry,
so silent stubbing can never recur unnoticed.

## Can ESPN provide availability? Yes.
The ESPN injuries page is a viable primary source (Out / Doubtful / Questionable /
Day-To-Day, per team, pre-game). It is already coded for; it only needs the UA fix.

## Derivation alternatives (ranked)
1. **ESPN injuries page (primary)** — pre-game status, already parsed. Fix = 1 line. **Best.**
2. **Pre-game starting lineups** (ESPN/stats boxscore "starters" ~30 min pre-tip) — confirms
   actual availability and starter/bench, the strongest signal; needs a new fetch but is the
   highest-fidelity. Good secondary.
3. **DNP / absence patterns from the game log** (`wnba_player_games.csv`) — a player absent
   from a team's game = was unavailable. Useful to build a *retrospective* availability
   history and to backfill training labels, but **not predictive** (known only post-game).
4. **Status reports** — same data as (1).

## Expected accuracy impact (quantified on the 588 graded minutes rows)
- Over-projection collapses (projected ≥18 min, actual ≤8 — the injury/early-hook tail):
  **7 rows (1.2% of graded) but 3.9% of total minutes-error mass**, mean miss 18.2 min.
- Perfectly catching them would move minutes MAE **5.61 → 5.40 (−4%)** — a *ceiling*, since
  several are in-game injuries a pre-game "Day-To-Day" flag only partially de-risks.
- There are **0** severe DNPs (actual ≤2) in the graded set, because truly-OUT players are
  already excluded upstream — so the **larger value is bet-quality**: with a live feed we can
  (a) drop OUT players from the slate before they are ever projected/bet, and (b) cap
  confidence on Questionable/Day-To-Day players. This directly attacks Phase 3A Root Cause #2
  and removes a class of bad bets the graded set cannot even measure today.

## Recommendation
Treat the UA fix as a **standalone, high-value, low-risk change** (independent of the Variant
C promotion question). Stand up the feed, backfill a retrospective availability history from
the game log for training, then add a pre-game lineup source as a second signal. Only after
the feed is live should availability features be added to the minutes/selection models.
