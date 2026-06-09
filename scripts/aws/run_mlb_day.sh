#!/usr/bin/env bash
set -euo pipefail

# MLB Pipeline - Canonical Single Source of Truth
# SOURCE: /home/ubuntu/mlb_model/mlb/outputs
# DESTINATION: /home/ubuntu/edgeranked-sportsai (served by Flask app)

SRC="/home/ubuntu/mlb_model/mlb/outputs"
LIVE="/home/ubuntu/edgeranked-sportsai"

mkdir -p /home/ubuntu/EdgeRanked/site/logs/cron

cd /home/ubuntu

echo "Starting unified MLB run: $(date)"

# ── Step 1: Fetch lines ──────────────────────────────────────────────────────
python3 mlb_model/fetch_mlb_lines.py || true

# ── Step 1B: Auto-backfill missing MLB call-up / lineup players ─────────────
# Runs BEFORE predict_hitter.py so any new lineup players (call-ups,
# prospects, mid-season trades) get a conservative baseline cache entry and
# never get silently skipped by the hitter projection model. Always exits 0
# — hitter-side issues must not block the run.
#
# Path alignment: predict_hitter.py (Step 2) imports get_hitter_stats.py whose
# CACHE_DIR resolves to ${runtime mlb_model dir}/mlb/data/cache/hitters. The
# backfill writes to the SAME directory so the cache rows it creates are read
# by the runtime hitter model. The env var below is the only place this
# runtime path is referenced from the new feature; the script itself is
# path-pure under /home/ubuntu/EdgeRanked/site/.
echo "[MLB CALLUP-BACKFILL] Running auto_backfill_mlb_live_players..."
EDGERANKED_HITTER_CACHE_DIR=/home/ubuntu/mlb_model/mlb/data/cache/hitters \
EDGERANKED_LIVE_MLB_OUTPUTS_DIR=/home/ubuntu/edgeranked-sportsai/mlb/outputs \
python3 /home/ubuntu/EdgeRanked/site/mlb/auto_backfill_mlb_live_players.py \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_callup_backfill.log 2>&1 \
    || echo "[MLB CALLUP-BACKFILL] WARNING: backfill exited non-zero — continuing"

# ── Step 2: Run predict_hitter.py to generate fresh shared sim JSON ─────────
# This is REQUIRED before unified_output_router - it writes the shared sim artifact
# that unified_output_router reads. Without this, the router uses stale data.
MLB_LAYER4_HITTER_MODE=1 \
MLB_LAYER4_DIRECT_SIM_OUTPUTS=1 \
MLB_LAYER4_PITCHER_MODE=1 \
MLB_LAYER4_SHARED_SIM_ARTIFACT=/home/ubuntu/mlb_model/validation/layer4_shared_sim_outputs.json \
MLB_LAYER4_DIRECT_N_SIMS=300 \
MLB_LAYER4_DIRECT_MIN_N_SIMS=300 \
MLB_LAYER4_DIRECT_MAX_GAMES=30 \
MLB_ENABLE_LEGACY_BIAS_PENALTY=1 \
python3 mlb_model/predict_hitter.py

# ── Step 3: Run unified model router ────────────────────────────────────────
MLB_USE_UNIFIED_LAYER4=1 \
MLB_UNIFIED_FALLBACK_TO_LEGACY=1 \
MLB_LAYER4_DIRECT_N_SIMS=300 \
MLB_LAYER4_DIRECT_MIN_N_SIMS=300 \
MLB_LAYER4_DIRECT_MAX_GAMES=30 \
python3 -m mlb_model.production.unified_output_router

# ── Step 4: Publish site projection exports ───────────────────────────────────
python3 - <<'PY'
from mlb_model.production.unified_output_router import publish_site_projection_exports
print(publish_site_projection_exports())
PY
# ── Step 4B: Rebuild MLB betting/top plays sheet ─────────────────────────────
echo "[MLB BETTING] Rebuilding betting/top plays sheet..."
cd /home/ubuntu/mlb_model
python3 build_betting_sheet.py

# ── Step 4C: Append today's hitter projections to hitter_tracking (non-blocking) ──
# Restores the daily hitter tracking-append that was dropped in the cutover from
# run_model.py to this wrapper (pitchers kept update_live_pitcher_tracking.py;
# hitters were left with no append, freezing hitter_tracking.csv / the learning
# dashboard). Appends today's slate to the CANONICAL hitter_tracking.csv (deduped
# by date+hitter+pitcher) and syncs both tracking copies to the site. Read-only of
# models; backs up before writing; never aborts the wrapper.
echo "[MLB HITTER-TRACK] Appending today's hitter projections to tracking..."
python3 /home/ubuntu/EdgeRanked/site/mlb/learning/repair_tracking.py --mode all \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_hitter_track.log 2>&1 \
    || echo "[MLB HITTER-TRACK] WARNING: append exited non-zero — continuing"

# ════════════════════════════════════════════════════════════════════════════
# Availability chain (non-blocking, must run AFTER hitter outputs and BEFORE
# downstream intel/public outputs that may consume hitter_predictions_public_safe.csv)
# Order is hard-coded: injury status → availability audit → public-safe builder.
# Each step logs to its own file under logs/cron/ and is wrapped with || echo
# so a failure cannot abort the wrapper.
# ════════════════════════════════════════════════════════════════════════════

# ── Step 4B-1: Fetch official MLB injury / IL status (non-blocking) ──────────
# Writes /home/ubuntu/mlb_model/mlb/outputs/mlb_injury_status_today.json
echo "[MLB INJURY] Fetching official MLB injury / IL status..."
cd /home/ubuntu
python3 -m mlb_model.production.fetch_mlb_injury_status \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_injury_status_fetch.log 2>&1 \
    || echo "[MLB INJURY] WARNING: fetch failed — continuing"

# ── Step 4B-2: Run MLB availability audit (non-blocking) ─────────────────────
# Reads injury status JSON + hitter_predictions_full.csv + live boxscore
# lineups, and writes /home/ubuntu/mlb_model/mlb/outputs/mlb_availability_audit_today.json
echo "[MLB AVAIL AUDIT] Running availability audit..."
python3 -m mlb_model.production.audit_mlb_availability \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_availability_audit.log 2>&1 \
    || echo "[MLB AVAIL AUDIT] WARNING: audit failed — continuing"

# ── HR Threat (non-blocking; fail-closed inside wrapper) ─────────────────────
# Requires fresh injury status + availability audit. Runs after hitter outputs
# (Steps 2–3) and before canonical publish/sync. Failure does not abort MLB day.
echo "[HR Threat] Starting daily HR Threat generation..."

HR_THREAT_WRAPPER="/home/ubuntu/mlb_model/hr_threat/run_hr_threat_day.sh"
export PYTHON_BIN="${PYTHON_BIN:-/home/ubuntu/EdgeRanked/site/venv/bin/python3}"

if [ -x "$HR_THREAT_WRAPPER" ]; then
    if bash "$HR_THREAT_WRAPPER" \
        >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_hr_threat_day.log 2>&1; then
        echo "[HR Threat] Completed successfully."
    else
        echo "[HR Threat] WARNING: HR Threat generation failed. Continuing MLB pipeline without publishing fresh HR Threat outputs."
    fi
else
    echo "[HR Threat] WARNING: wrapper not found or not executable: $HR_THREAT_WRAPPER"
fi

# ── Step 4B-3: Build public-safe hitter board (non-blocking) ─────────────────
# Joins hitter_predictions_full.csv + availability audit; writes
#   hitter_predictions_public_safe.csv and mlb_public_safe_exclusions_today.json.
# Original hitter_predictions_full.csv is NEVER modified by this step.
echo "[MLB PUBLIC-SAFE] Building public-safe hitter board..."
python3 -m mlb_model.production.build_public_safe_hitters \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_public_safe_build.log 2>&1 \
    || echo "[MLB PUBLIC-SAFE] WARNING: build failed — continuing"

# ── Step 4B-4: Build MLB matchup history (BvP) artifact (non-blocking) ───────
# Read-only display/context layer. The builder prefers
# hitter_predictions_public_safe.csv (so IL/Out and Lineup Risk hitters are
# already absent) and falls back to hitter_predictions_full.csv with a warning
# if the public-safe file is missing. This step MUST run AFTER Step 4B-3 so
# the public-safe artifact exists.
echo "[MLB MATCHUP HISTORY] Building MLB matchup history (BvP) artifact..."
python3 -m mlb_model.production.build_mlb_matchup_history \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_matchup_history_build.log 2>&1 \
    || echo "[MLB MATCHUP HISTORY] WARNING: build failed — continuing"
cd /home/ubuntu/mlb_model

# ── Step 4C: Build MLB game-environment intel JSON (non-blocking) ────────────
# Reads layer4_shared_sim_outputs.json + hitter/pitcher outputs + weather (if any)
# and writes /home/ubuntu/mlb_model/mlb/outputs/mlb_game_environment_today.json
echo "[MLB ENVIRONMENT] Building MLB game environment intel JSON..."
cd /home/ubuntu
python3 -m mlb_model.production.build_mlb_game_environment \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_game_environment_build.log 2>&1 \
    || echo "[MLB ENVIRONMENT] WARNING: build failed — continuing"

# ── Step 4D: Build MLB attack-context intel JSON (non-blocking) ──────────────
# Reads mlb_game_environment_today.json + hitter/pitcher CSVs and writes
# /home/ubuntu/mlb_model/mlb/outputs/mlb_attack_context_today.json
echo "[MLB ATTACK CONTEXT] Building MLB attack context intel JSON..."
python3 -m mlb_model.production.build_mlb_attack_context \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_attack_context_build.log 2>&1 \
    || echo "[MLB ATTACK CONTEXT] WARNING: build failed — continuing"

# ── Step 4E: Build MLB intel explanations JSON (non-blocking) ────────────────
# Reads mlb_game_environment_today.json + mlb_attack_context_today.json + weather
# and writes /home/ubuntu/mlb_model/mlb/outputs/mlb_intel_explanations_today.json.
# Must run AFTER Steps 4C (game environment) and 4D (attack context).
echo "[MLB INTEL EXPLANATIONS] Building MLB intel explanations JSON..."
python3 -m mlb_model.production.build_mlb_intel_explanations \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_intel_explanations_build.log 2>&1 \
    || echo "[MLB INTEL EXPLANATIONS] WARNING: build failed — continuing"
cd /home/ubuntu/mlb_model

# ── Step 5: MLB Weather (non-blocking) ───────────────────────────────────────
echo "[MLB WEATHER] Building MLB weather board..."
python3 /home/ubuntu/EdgeRanked/site/scripts/mlb_weather/build_mlb_weather_today.py \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_weather_build.log 2>&1 \
    || echo "[MLB WEATHER] WARNING: build failed — continuing"
# ── Step 5B: Publish MLB weather to live site ────────────────────────────────
echo "[MLB WEATHER] Publishing weather board to live site..."

WEATHER_SRC="/home/ubuntu/EdgeRanked/site/mlb/outputs/mlb_weather_today.json"
WEATHER_DEST="/home/ubuntu/edgeranked-sportsai/mlb/outputs/mlb_weather_today.json"

if [ -f "$WEATHER_SRC" ]; then
    mkdir -p "$(dirname "$WEATHER_DEST")"
    cp -f "$WEATHER_SRC" "$WEATHER_DEST"
    echo "[MLB WEATHER] Published: $WEATHER_DEST"
else
    echo "[MLB WEATHER] WARNING: Weather file missing at $WEATHER_SRC"
fi
echo "[MLB WEATHER] Validating MLB weather board..."
python3 /home/ubuntu/EdgeRanked/site/scripts/mlb_weather/validate_mlb_weather_today.py \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_weather_validate.log 2>&1 \
    || echo "[MLB WEATHER] WARNING: validation failed — continuing"

# ── Step 5C: Refresh authoritative team batting K% snapshot (non-blocking) ───
# Keeps the Ks Threat board's Opponent K Rate display current using each club's
# ACTUAL season batting K% (FanGraphs). Runs AFTER data refresh and BEFORE the
# publish/sync block so the freshest snapshot reaches the live read dirs in this
# same run. The script validates in a temp file and atomically replaces only on
# success; on any fetch/validation failure it leaves the existing file untouched
# and exits nonzero, so this step is wrapped non-blocking and the page keeps
# rendering last-good values. Writes to the live runtime read dir
# ($LIVE/data/mlb, selected by EDGERANKED_MLB_BASE_DIR) and the repo copy.
echo "[MLB TEAM-K] Refreshing team batting K% snapshot..."
python3 /home/ubuntu/EdgeRanked/site/scripts/mlb/refresh_team_batting_k.py \
    --dest "$LIVE/data/mlb/team_batting_k_pct_season.csv" \
    --dest /home/ubuntu/EdgeRanked/site/data/mlb/team_batting_k_pct_season.csv \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_team_batting_k_refresh.log 2>&1 \
    || echo "[MLB TEAM-K] WARNING: refresh failed — keeping last-good snapshot, continuing"

# ════════════════════════════════════════════════════════════════════════════
# CANONICAL PUBLISH BLOCK - Single source of truth
# Source: /home/ubuntu/mlb_model/mlb/outputs
# Target: /home/ubuntu/edgeranked-sportsai
# ════════════════════════════════════════════════════════════════════════════

echo "[MLB PUBLISH] Starting canonical publish..."

# Create required directories
mkdir -p "$LIVE/mlb/outputs"
mkdir -p "$LIVE/data/mlb"
mkdir -p "$LIVE/data/normalized"

# List of files to publish from model outputs
PUBLISH_FILES=(
    "betting_sheet_today.csv"
    "betting_sheet_mobile_today.csv"
    "hitter_summary_today.csv"
    "hitter_predictions_full.csv"
    "hitter_predictions_today.csv"
    "fantasy_projections_today.csv"
    "mlb_pitcher_projections_today.csv"
    "pitcher_props_today.csv"
    "lines_today.csv"
    "lines_today_audit.json"
    "lines_today_raw.csv"
)

FAILED=0

# Copy files to live destination
for f in "${PUBLISH_FILES[@]}"; do
    src_file="$SRC/$f"
    if [ -f "$src_file" ]; then
        size=$(stat -c%s "$src_file" 2>/dev/null || echo "0")
        if [ "$size" -gt 0 ]; then
            # Publish-time validation gate for the pitcher props file.
            # FAIL PATH: publish today's slate with the ceiling/probability
            # columns BLANKED rather than reverting to yesterday's file. This
            # keeps projected K / opponent K / expected outs current and lets
            # the frontend hide the broken Strikeout Ceiling section
            # gracefully. Never republishes stale yesterday matchups.
            if [ "$f" = "pitcher_props_today.csv" ]; then
                if (cd /home/ubuntu && python3 -m mlb_model.production.validate_pitcher_props_publish "$src_file"); then
                    cp -f "$src_file" "$LIVE/mlb/outputs/$f"
                    echo "[MLB PUBLISH] Copied: $f ($(numfmt --to=iec $size))"
                else
                    echo "[MLB PUBLISH] CRITICAL: ceiling probabilities disabled for today's slate (validator FAIL) — publishing today's projections with ceiling columns blanked"
                    SANITIZED_TMP="/tmp/pitcher_props_sanitized_$$.csv"
                    if (cd /home/ubuntu && python3 -m mlb_model.production.sanitize_pitcher_props "$src_file" "$SANITIZED_TMP"); then
                        cp -f "$SANITIZED_TMP" "$LIVE/mlb/outputs/$f"
                        rm -f "$SANITIZED_TMP"
                        echo "[MLB PUBLISH] Published sanitized $f (today's slate kept current; only ceiling columns blanked)"
                    else
                        echo "[MLB PUBLISH] CRITICAL: sanitize failed; cannot publish — leaving previous live file"
                    fi
                    FAILED=1
                fi
            else
                cp -f "$src_file" "$LIVE/mlb/outputs/$f"
                echo "[MLB PUBLISH] Copied: $f ($(numfmt --to=iec $size))"
            fi
        else
            echo "[MLB PUBLISH] ERROR: $f exists but is empty"
            FAILED=1
        fi
    else
        echo "[MLB PUBLISH] ERROR: Missing required file: $src_file"
        FAILED=1
    fi
done

# Special copies for app.py's MLB_DATA_DIR (lines_today.csv)
if [ -f "$SRC/lines_today.csv" ]; then
    cp -f "$SRC/lines_today.csv" "$LIVE/data/mlb/lines_today.csv"
    cp -f "$SRC/lines_today.csv" "$LIVE/data/normalized/lines_today.csv"
    echo "[MLB PUBLISH] Copied lines_today.csv to data/mlb and data/normalized"
fi

# Special copy for audit JSON
if [ -f "$SRC/lines_today_audit.json" ]; then
    cp -f "$SRC/lines_today_audit.json" "$LIVE/data/normalized/lines_today_audit.json"
    echo "[MLB PUBLISH] Copied lines_today_audit.json to data/normalized"
fi

# Publish MLB game environment intel JSON (optional, non-blocking)
ENV_SRC="$SRC/mlb_game_environment_today.json"
ENV_DEST="$LIVE/mlb/outputs/mlb_game_environment_today.json"
if [ -f "$ENV_SRC" ]; then
    cp -f "$ENV_SRC" "$ENV_DEST"
    echo "[MLB PUBLISH] Copied mlb_game_environment_today.json to live outputs"
else
    echo "[MLB PUBLISH] NOTE: mlb_game_environment_today.json missing — skipping (non-blocking)"
fi

# Publish MLB attack context intel JSON (optional, non-blocking)
ATK_SRC="$SRC/mlb_attack_context_today.json"
ATK_DEST="$LIVE/mlb/outputs/mlb_attack_context_today.json"
if [ -f "$ATK_SRC" ]; then
    cp -f "$ATK_SRC" "$ATK_DEST"
    echo "[MLB PUBLISH] Copied mlb_attack_context_today.json to live outputs"
else
    echo "[MLB PUBLISH] NOTE: mlb_attack_context_today.json missing — skipping (non-blocking)"
fi

# Publish MLB intel explanations JSON (optional, non-blocking)
EXPL_SRC="$SRC/mlb_intel_explanations_today.json"
EXPL_DEST="$LIVE/mlb/outputs/mlb_intel_explanations_today.json"
if [ -f "$EXPL_SRC" ]; then
    cp -f "$EXPL_SRC" "$EXPL_DEST"
    echo "[MLB PUBLISH] Copied mlb_intel_explanations_today.json to live outputs"
else
    echo "[MLB PUBLISH] NOTE: mlb_intel_explanations_today.json missing — skipping (non-blocking)"
fi

# Publish public-safe hitter CSV (optional, non-blocking)
PSC_SRC="$SRC/hitter_predictions_public_safe.csv"
PSC_DEST="$LIVE/mlb/outputs/hitter_predictions_public_safe.csv"
if [ -f "$PSC_SRC" ]; then
    cp -f "$PSC_SRC" "$PSC_DEST"
    echo "[MLB PUBLISH] Copied hitter_predictions_public_safe.csv to live outputs"
else
    echo "[MLB PUBLISH] NOTE: hitter_predictions_public_safe.csv missing — skipping (non-blocking)"
fi

# Publish public-safe exclusions JSON (optional, non-blocking)
PSX_SRC="$SRC/mlb_public_safe_exclusions_today.json"
PSX_DEST="$LIVE/mlb/outputs/mlb_public_safe_exclusions_today.json"
if [ -f "$PSX_SRC" ]; then
    cp -f "$PSX_SRC" "$PSX_DEST"
    echo "[MLB PUBLISH] Copied mlb_public_safe_exclusions_today.json to live outputs"
else
    echo "[MLB PUBLISH] NOTE: mlb_public_safe_exclusions_today.json missing — skipping (non-blocking)"
fi

# Publish MLB matchup history (BvP) JSON (optional, non-blocking)
MH_SRC="$SRC/mlb_matchup_history_today.json"
MH_DEST="$LIVE/mlb/outputs/mlb_matchup_history_today.json"
if [ -f "$MH_SRC" ]; then
    cp -f "$MH_SRC" "$MH_DEST"
    echo "[MLB PUBLISH] Copied mlb_matchup_history_today.json to live outputs"
else
    echo "[MLB PUBLISH] NOTE: mlb_matchup_history_today.json missing — skipping (non-blocking)"
fi

# ════════════════════════════════════════════════════════════════════════════
# VALIDATION - Verify required files exist, not empty, modified today
# ════════════════════════════════════════════════════════════════════════════

echo "[MLB VALIDATE] Starting validation..."

TODAY=$(date -u +%Y-%m-%d)
VALIDATION_FAILED=0

validate_file() {
    local filepath="$1"
    local filename=$(basename "$filepath")
    
    if [ ! -f "$filepath" ]; then
        echo "[MLB VALIDATE] FAIL: $filename does not exist at $filepath"
        return 1
    fi
    
    local size=$(stat -c%s "$filepath" 2>/dev/null || echo "0")
    if [ "$size" -eq 0 ]; then
        echo "[MLB VALIDATE] FAIL: $filename is empty"
        return 1
    fi
    
    local mtime=$(stat -c %Y "$filepath" 2>/dev/null || echo "0")
    local today_start=$(date -d "$TODAY" +%s 2>/dev/null || echo "0")
    
    if [ "$mtime" -lt "$today_start" ]; then
        echo "[MLB VALIDATE] WARN: $filename was NOT modified today (may be stale)"
    else
        echo "[MLB VALIDATE] OK: $filename is current ($(numfmt --to=iec $size))"
    fi
    
    # Count CSV rows if applicable
    if [[ "$filename" == *.csv ]]; then
        local rows=$(wc -l < "$filepath" 2>/dev/null || echo "0")
        echo "         Rows: $rows"
    fi
    
    return 0
}

# Validate required files at live destination
REQUIRED_FILES=(
    "$LIVE/mlb/outputs/lines_today.csv"
    "$LIVE/mlb/outputs/betting_sheet_today.csv"
    "$LIVE/mlb/outputs/hitter_summary_today.csv"
    "$LIVE/mlb/outputs/hitter_predictions_today.csv"
    "$LIVE/mlb/outputs/fantasy_projections_today.csv"
    "$LIVE/mlb/outputs/pitcher_props_today.csv"
    "$LIVE/mlb/outputs/mlb_pitcher_projections_today.csv"
    "$LIVE/data/mlb/lines_today.csv"
    "$LIVE/data/normalized/lines_today.csv"
)

for filepath in "${REQUIRED_FILES[@]}"; do
    if ! validate_file "$filepath"; then
        VALIDATION_FAILED=1
    fi
done

if [ $VALIDATION_FAILED -eq 1 ]; then
    echo "[MLB VALIDATE] ERROR: Validation failed - some required files missing or empty"
    exit 1
fi

echo "[MLB VALIDATE] All required files validated successfully"

# ════════════════════════════════════════════════════════════════════════════
# PITCHER MATCH VALIDATION - Verify pitcher names match between data sources
# This catches stale shared sim JSON that causes wrong pitcher identities
# ════════════════════════════════════════════════════════════════════════════

echo "[MLB PITCHER VALIDATE] Checking pitcher name alignment..."

python3 - <<'PY'
import csv
import sys

def get_pitcher_names(filepath):
    """Extract unique pitcher names from a CSV file."""
    pitchers = set()
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Try common pitcher name columns
                name = (
                    row.get('pitcher_name')
                    or row.get('Pitcher')
                    or row.get('player_name')
                    or row.get('name')
                    or row.get('pitcher')
                    or row.get('player')
                )
                if name and name.strip():
                    pitchers.add(name.strip().lower())
    except Exception as e:
        print(f"[MLB PITCHER VALIDATE] WARNING: Could not read {filepath}: {e}")
        return set()
    return pitchers

# Check lines_today.csv (source of truth for today's slate)
lines_path = "/home/ubuntu/mlb_model/mlb/outputs/lines_today.csv"
pitcher_props_path = "/home/ubuntu/mlb_model/mlb/outputs/pitcher_props_today.csv"

lines_pitchers = get_pitcher_names(lines_path)
props_pitchers = get_pitcher_names(pitcher_props_path)

print(f"[MLB PITCHER VALIDATE] Lines API pitchers: {len(lines_pitchers)}")
print(f"[MLB PITCHER VALIDATE] Pitcher props pitchers: {len(props_pitchers)}")

if lines_pitchers and props_pitchers:
    overlap = lines_pitchers & props_pitchers
    print(f"[MLB PITCHER VALIDATE] Overlap: {len(overlap)} pitchers")
    
    if len(overlap) == 0:
        print("[MLB PITCHER VALIDATE] ERROR: ZERO overlap - pitcher names DO NOT MATCH!")
        print("[MLB PITCHER VALIDATE] This indicates stale shared sim JSON or wrong date data.")
        print("[MLB PITCHER VALIDATE] lines_today.csv sample:", list(lines_pitchers)[:5])
        print("[MLB PITCHER VALIDATE] pitcher_props_today.csv sample:", list(props_pitchers)[:5])
        sys.exit(1)
    elif len(overlap) < len(lines_pitchers) * 0.5:
        print(f"[MLB PITCHER VALIDATE] WARN: Only {len(overlap)}/{len(lines_pitchers)} pitchers match")
        print("[MLB PITCHER VALIDATE] This may indicate partially stale data")
    else:
        print(f"[MLB PITCHER VALIDATE] OK: {len(overlap)} pitchers match between sources")
else:
    print("[MLB PITCHER VALIDATE] WARN: Could not extract pitcher names from one or both files")
PY

PITCHER_VALIDATE_RESULT=$?
if [ $PITCHER_VALIDATE_RESULT -ne 0 ]; then
    echo "[MLB PITCHER VALIDATE] ERROR: Pitcher validation failed - names don't match"
    echo "[MLB PITCHER VALIDATE] This usually means the shared sim JSON is stale."
    echo "[MLB PITCHER VALIDATE] Check if predict_hitter.py ran successfully and wrote fresh data."
    exit 1
fi

echo "[MLB PITCHER VALIDATE] Pitcher names validated successfully"

# ════════════════════════════════════════════════════════════════════════════
# FINAL SYNC - Mirror source outputs to BOTH live MLB read directories
# Runs only after all upstream validations pass. Aborts before service restart
# if any critical file is missing/empty in its source location, so the website
# never gets a partial sync.
#
# Primary source: /home/ubuntu/mlb_model/mlb/outputs/
# Weather source: /home/ubuntu/EdgeRanked/site/mlb/outputs/  (built by Step 5)
# Destinations:   /home/ubuntu/EdgeRanked/site/mlb/outputs/
#                 /home/ubuntu/edgeranked-sportsai/mlb/outputs/
# ════════════════════════════════════════════════════════════════════════════

echo "[MLB FINAL SYNC] Starting two-destination sync..."

# Files generated by the MLB model into $SRC.
FINAL_SYNC_MODEL_FILES=(
    "hitter_predictions_full.csv"
    "hitter_predictions_public_safe.csv"
    "hitter_summary_today.csv"
    "hitter_predictions_today.csv"
    "fantasy_projections_today.csv"
    "betting_sheet_today.csv"
    "betting_sheet_mobile_today.csv"
    "pitcher_props_today.csv"
    "mlb_pitcher_projections_today.csv"
    "lines_today.csv"
    "lines_today_raw.csv"
    "lines_today_audit.json"
    "hitter_tracking.csv"
    "pitcher_tracking.csv"
    "bet_history.csv"
)

# Files generated outside $SRC. Weather is built by Step 5 into
# /home/ubuntu/EdgeRanked/site/mlb/outputs/ and must also reach the other
# destination so both live read dirs stay in sync.
FINAL_SYNC_WEATHER_FILE="mlb_weather_today.json"
FINAL_SYNC_WEATHER_SRC_DIR="/home/ubuntu/EdgeRanked/site/mlb/outputs"

FINAL_SYNC_TARGETS=(
    "/home/ubuntu/EdgeRanked/site/mlb/outputs"
    "/home/ubuntu/edgeranked-sportsai/mlb/outputs"
)

# Pre-flight: verify every required file exists and is non-empty in its source
# location BEFORE we touch any destination. This blocks partial syncs.
FINAL_SYNC_MISSING=0
for f in "${FINAL_SYNC_MODEL_FILES[@]}"; do
    src_file="$SRC/$f"
    if [ ! -f "$src_file" ]; then
        echo "[MLB FINAL SYNC] FAIL: missing model source file: $src_file"
        FINAL_SYNC_MISSING=1
        continue
    fi
    size=$(stat -c%s "$src_file" 2>/dev/null || echo "0")
    if [ "$size" -eq 0 ]; then
        echo "[MLB FINAL SYNC] FAIL: empty model source file: $src_file"
        FINAL_SYNC_MISSING=1
    fi
done

weather_src_file="$FINAL_SYNC_WEATHER_SRC_DIR/$FINAL_SYNC_WEATHER_FILE"
if [ ! -f "$weather_src_file" ]; then
    echo "[MLB FINAL SYNC] FAIL: missing weather source file: $weather_src_file"
    FINAL_SYNC_MISSING=1
else
    weather_size=$(stat -c%s "$weather_src_file" 2>/dev/null || echo "0")
    if [ "$weather_size" -eq 0 ]; then
        echo "[MLB FINAL SYNC] FAIL: empty weather source file: $weather_src_file"
        FINAL_SYNC_MISSING=1
    fi
fi

if [ "$FINAL_SYNC_MISSING" -ne 0 ]; then
    echo "[MLB FINAL SYNC] ERROR: one or more critical files missing/empty. Aborting BEFORE service restart to avoid serving stale outputs."
    exit 1
fi

TOTAL_REQUIRED=$(( ${#FINAL_SYNC_MODEL_FILES[@]} + 1 ))
echo "[MLB FINAL SYNC] Pre-flight passed: all ${TOTAL_REQUIRED} required files present (${#FINAL_SYNC_MODEL_FILES[@]} from $SRC, 1 weather from $FINAL_SYNC_WEATHER_SRC_DIR)"

for dest_dir in "${FINAL_SYNC_TARGETS[@]}"; do
    mkdir -p "$dest_dir"
done

FINAL_SYNC_COPIED=0
FINAL_SYNC_FAILED=0

# 1) Model-generated files: $SRC → both destinations
for f in "${FINAL_SYNC_MODEL_FILES[@]}"; do
    src_file="$SRC/$f"
    src_size=$(stat -c%s "$src_file" 2>/dev/null || echo "0")
    for dest_dir in "${FINAL_SYNC_TARGETS[@]}"; do
        dest_file="$dest_dir/$f"
        if cp -f "$src_file" "$dest_file"; then
            dest_size=$(stat -c%s "$dest_file" 2>/dev/null || echo "0")
            if [ "$src_size" -eq "$dest_size" ]; then
                echo "[MLB FINAL SYNC] OK: $f ($(numfmt --to=iec $src_size)) → $dest_dir"
                FINAL_SYNC_COPIED=$((FINAL_SYNC_COPIED + 1))
            else
                echo "[MLB FINAL SYNC] FAIL: size mismatch after copy: $f (src=$src_size dst=$dest_size) at $dest_file"
                FINAL_SYNC_FAILED=$((FINAL_SYNC_FAILED + 1))
            fi
        else
            echo "[MLB FINAL SYNC] FAIL: cp failed for $f → $dest_file"
            FINAL_SYNC_FAILED=$((FINAL_SYNC_FAILED + 1))
        fi
    done
done

# 2) Weather: $FINAL_SYNC_WEATHER_SRC_DIR → both destinations (self-copy is a
# no-op for the source-equals-destination case, but keeps the post-sync invariant
# "every destination has the freshest weather" explicit).
for dest_dir in "${FINAL_SYNC_TARGETS[@]}"; do
    dest_file="$dest_dir/$FINAL_SYNC_WEATHER_FILE"
    if [ "$weather_src_file" = "$dest_file" ]; then
        echo "[MLB FINAL SYNC] OK (in-place): $FINAL_SYNC_WEATHER_FILE already at $dest_dir"
        FINAL_SYNC_COPIED=$((FINAL_SYNC_COPIED + 1))
        continue
    fi
    if cp -f "$weather_src_file" "$dest_file"; then
        dest_size=$(stat -c%s "$dest_file" 2>/dev/null || echo "0")
        if [ "$weather_size" -eq "$dest_size" ]; then
            echo "[MLB FINAL SYNC] OK: $FINAL_SYNC_WEATHER_FILE ($(numfmt --to=iec $weather_size)) → $dest_dir"
            FINAL_SYNC_COPIED=$((FINAL_SYNC_COPIED + 1))
        else
            echo "[MLB FINAL SYNC] FAIL: weather size mismatch after copy (src=$weather_size dst=$dest_size) at $dest_file"
            FINAL_SYNC_FAILED=$((FINAL_SYNC_FAILED + 1))
        fi
    else
        echo "[MLB FINAL SYNC] FAIL: cp failed for $FINAL_SYNC_WEATHER_FILE → $dest_file"
        FINAL_SYNC_FAILED=$((FINAL_SYNC_FAILED + 1))
    fi
done

EXPECTED_COPIES=$(( TOTAL_REQUIRED * ${#FINAL_SYNC_TARGETS[@]} ))
echo "[MLB FINAL SYNC] Summary: $FINAL_SYNC_COPIED/$EXPECTED_COPIES copies succeeded, $FINAL_SYNC_FAILED failed"
if [ "$FINAL_SYNC_FAILED" -ne 0 ]; then
    echo "[MLB FINAL SYNC] ERROR: at least one copy failed. Aborting BEFORE service restart."
    exit 1
fi
echo "[MLB FINAL SYNC] All ${EXPECTED_COPIES} copies succeeded across ${#FINAL_SYNC_TARGETS[@]} destinations"

# ════════════════════════════════════════════════════════════════════════════
# LIVE PITCHER OBSERVABILITY - Additive, non-blocking
# Archives the exact public-facing pitcher outputs after final sync and attempts
# to append finalized public-card rows to live_pitcher_tracking.csv when
# boxscore actuals are available. These steps must never change displayed
# values or block the service restart.
# ════════════════════════════════════════════════════════════════════════════

echo "[MLB LIVE OBS] Archiving public pitcher outputs..."
python3 /home/ubuntu/mlb_model/validation/live_output_scoring/archive_live_pitcher_outputs.py \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_live_pitcher_observability.log 2>&1 \
    || echo "[MLB LIVE OBS] WARNING: archive step failed — continuing"

echo "[MLB LIVE OBS] Updating append-only public pitcher tracking..."
python3 /home/ubuntu/mlb_model/validation/live_output_scoring/update_live_pitcher_tracking.py \
    >> /home/ubuntu/EdgeRanked/site/logs/cron/mlb_live_pitcher_observability.log 2>&1 \
    || echo "[MLB LIVE OBS] WARNING: tracking step failed — continuing"

# ════════════════════════════════════════════════════════════════════════════
# SERVICE RESTART - Only after successful validation
# ════════════════════════════════════════════════════════════════════════════

echo "[MLB RESTART] Restarting edgerankai service..."
sudo systemctl restart edgerankai

echo "[MLB RESTART] Service restarted"
echo "Finished unified MLB run: $(date)"
echo "[MLB PUBLISH] Canonical publish complete"
