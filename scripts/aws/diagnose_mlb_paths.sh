#!/usr/bin/env bash
# MLB Pipeline Diagnostic Script
# Checks paths, timestamps, and reports mismatches

echo "═══════════════════════════════════════════════════════════"
echo "MLB PIPELINE DIAGNOSTIC REPORT"
echo "Generated: $(date -u)"
echo "═══════════════════════════════════════════════════════════"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SRC="/home/ubuntu/mlb_model/mlb/outputs"
LIVE="/home/ubuntu/edgeranked-sportsai"

# ── 1. Service Environment ─────────────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│ SERVICE ENVIRONMENT                                     │"
echo "└─────────────────────────────────────────────────────────┘"
if systemctl is-active --quiet edgerankai 2>/dev/null; then
    echo -e "edgerankai service: ${GREEN}ACTIVE${NC}"
else
    echo -e "edgerankai service: ${RED}INACTIVE${NC}"
fi

if systemctl is-enabled --quiet edgerankai 2>/dev/null; then
    echo -e "edgerankai autostart: ${GREEN}ENABLED${NC}"
else
    echo -e "edgerankai autostart: ${YELLOW}DISABLED${NC}"
fi

echo ""
echo "Environment variables for MLB:"
env | grep -i "MLB\|EDGERANKED" | sort

# ── 2. Cron Jobs ─────────────────────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│ CRON JOBS (MLB related)                                 │"
echo "└─────────────────────────────────────────────────────────┘"
crontab -l 2>/dev/null | grep -i "mlb\|run_mlb" || echo "No MLB cron jobs found"

# ── 3. Path Timestamps ───────────────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│ PATH TIMESTAMPS                                         │"
echo "└─────────────────────────────────────────────────────────┘"

check_path() {
    local path="$1"
    local label="$2"
    
    if [ -d "$path" ]; then
        echo ""
        echo "=== $label ==="
        echo "Path: $path"
        echo "Contents:"
        ls -la "$path" 2>/dev/null | head -20
        
        # Find most recent file
        local newest=$(find "$path" -type f -name "*.csv" -o -name "*.json" 2>/dev/null | xargs stat --format='%Y %n' 2>/dev/null | sort -rn | head -5)
        if [ -n "$newest" ]; then
            echo ""
            echo "Most recent files:"
            echo "$newest" | while read ts fn; do
                local age=$(($(date +%s) - ts))
                local age_str=""
                if [ $age -lt 60 ]; then
                    age_str="seconds ago"
                elif [ $age -lt 3600 ]; then
                    age_str="$((age / 60)) minutes ago"
                elif [ $age -lt 86400 ]; then
                    age_str="$((age / 3600)) hours ago"
                else
                    age_str="$((age / 86400)) days ago"
                fi
                echo "  $(basename $fn) - $age_str"
            done
        fi
    else
        echo -e "${RED}MISSING: $path${NC}"
    fi
}

check_path "$SRC" "SOURCE (mlb_model outputs)"
check_path "$LIVE/mlb/outputs" "LIVE MLB OUTPUTS"
check_path "$LIVE/data/mlb" "LIVE DATA MLB"
check_path "$LIVE/data/normalized" "LIVE DATA NORMALIZED"

# ── 4. Path Mismatch Detection ──────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│ PATH MISMATCH ANALYSIS                                  │"
echo "└─────────────────────────────────────────────────────────┘"

MISMATCH=0

# Check if source files exist
echo ""
echo "Checking SOURCE files..."
for f in lines_today.csv betting_sheet_today.csv hitter_summary_today.csv hitter_predictions_today.csv fantasy_projections_today.csv pitcher_props_today.csv mlb_pitcher_projections_today.csv; do
    if [ -f "$SRC/$f" ]; then
        size=$(stat -c%s "$SRC/$f" 2>/dev/null || echo "0")
        echo -e "  $f: ${GREEN}exists${NC} ($(numfmt --to=iec $size))"
    else
        echo -e "  $f: ${RED}MISSING${NC}"
        MISMATCH=1
    fi
done

echo ""
echo "Checking LIVE mlb/outputs..."
for f in lines_today.csv betting_sheet_today.csv hitter_summary_today.csv hitter_predictions_today.csv fantasy_projections_today.csv pitcher_props_today.csv mlb_pitcher_projections_today.csv; do
    if [ -f "$LIVE/mlb/outputs/$f" ]; then
        size=$(stat -c%s "$LIVE/mlb/outputs/$f" 2>/dev/null || echo "0")
        echo -e "  $f: ${GREEN}exists${NC} ($(numfmt --to=iec $size))"
    else
        echo -e "  $f: ${RED}MISSING${NC}"
        MISMATCH=1
    fi
done

echo ""
echo "Checking LIVE data/mlb (for lines)..."
if [ -f "$LIVE/data/mlb/lines_today.csv" ]; then
    size=$(stat -c%s "$LIVE/data/mlb/lines_today.csv" 2>/dev/null || echo "0")
    echo -e "  lines_today.csv: ${GREEN}exists${NC} ($(numfmt --to=iec $size))"
else
    echo -e "  lines_today.csv: ${RED}MISSING${NC}"
    MISMATCH=1
fi

echo ""
echo "Checking LIVE data/normalized..."
if [ -d "$LIVE/data/normalized" ]; then
    for f in lines_today.csv lines_today_audit.json; do
        if [ -f "$LIVE/data/normalized/$f" ]; then
            size=$(stat -c%s "$LIVE/data/normalized/$f" 2>/dev/null || echo "0")
            echo -e "  $f: ${GREEN}exists${NC} ($(numfmt --to=iec $size))"
        else
            echo -e "  $f: ${YELLOW}missing${NC}"
        fi
    done
else
    echo -e "${RED}Directory does not exist: $LIVE/data/normalized${NC}"
    MISMATCH=1
fi

# Compare timestamps between source and live
echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│ TIMESTAMP COMPARISON (Source vs Live)                   │"
echo "└─────────────────────────────────────────────────────────┘"

for f in lines_today.csv betting_sheet_today.csv hitter_summary_today.csv; do
    if [ -f "$SRC/$f" ] && [ -f "$LIVE/mlb/outputs/$f" ]; then
        src_mtime=$(stat -c %Y "$SRC/$f" 2>/dev/null)
        live_mtime=$(stat -c %Y "$LIVE/mlb/outputs/$f" 2>/dev/null)
        
        if [ "$src_mtime" -eq "$live_mtime" ]; then
            echo -e "  $f: ${GREEN}SYNCED${NC}"
        else
            src_age=$(($(date +%s) - src_mtime))
            live_age=$(($(date +%s) - live_mtime))
            echo -e "  $f: ${YELLOW}OUT OF SYNC${NC} (source: $((src_age/60))m ago, live: $((live_age/60))m ago)"
            MISMATCH=1
        fi
    fi
done

# ── 5. API Endpoint Checks ───────────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│ API ENDPOINT CHECKS                                     │"
echo "└─────────────────────────────────────────────────────────┘"

# Get the localhost URL from the service
PORT=$(systemctl show edgerankai --property=Environment 2>/dev/null | grep -oP 'PORT=\K\d+' || echo "5000")
BASE_URL="http://localhost:$PORT"

echo ""
echo "Testing endpoints (this may take a moment)..."

# Test /api/mlb/lines
echo ""
echo "GET /api/mlb/lines"
response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$BASE_URL/api/mlb/lines" 2>/dev/null || echo "000")
if [ "$response" = "200" ]; then
    echo -e "  Status: ${GREEN}OK (200)${NC}"
    # Show sample of data timestamp
    data_time=$(curl -s --max-time 10 "$BASE_URL/api/mlb/lines" 2>/dev/null | head -c 500)
    echo "  Sample data: $(echo "$data_time" | tr -d '\n' | head -c 200)..."
else
    echo -e "  Status: ${RED}FAIL ($response)${NC}"
    MISMATCH=1
fi

# Test /api/mlb/projections
echo ""
echo "GET /api/mlb/projections"
response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$BASE_URL/api/mlb/projections" 2>/dev/null || echo "000")
if [ "$response" = "200" ]; then
    echo -e "  Status: ${GREEN}OK (200)${NC}"
else
    echo -e "  Status: ${RED}FAIL ($response)${NC}"
    MISMATCH=1
fi

# Test /api/mlb/best-bets
echo ""
echo "GET /api/mlb/best-bets"
response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$BASE_URL/api/mlb/best-bets" 2>/dev/null || echo "000")
if [ "$response" = "200" ]; then
    echo -e "  Status: ${GREEN}OK (200)${NC}"
else
    echo -e "  Status: ${RED}FAIL ($response)${NC}"
    MISMATCH=1
fi

# ── 6. Summary ───────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "SUMMARY"
echo "═══════════════════════════════════════════════════════════"

if [ $MISMATCH -eq 1 ]; then
    echo -e "${RED}⚠️  PATH MISMATCHES DETECTED${NC}"
    echo ""
    echo "The following issues were found:"
    echo "  - Some files are missing from live destination"
    echo "  - Some files may be stale (not modified today)"
    echo "  - Source and live may be out of sync"
    echo ""
    echo "Recommended action:"
    echo "  Run: bash /home/ubuntu/EdgeRanked/site/scripts/aws/run_mlb_day.sh"
else
    echo -e "${GREEN}✓ ALL PATHS SYNCED${NC}"
    echo ""
    echo "All required files exist in both source and live locations."
fi

echo ""
echo "Last model run timestamps:"
if [ -f "$SRC/lines_today.csv" ]; then
    echo "  Source lines_today.csv: $(stat -c %y "$SRC/lines_today.csv" 2>/dev/null | cut -d. -f1)"
fi
if [ -f "$LIVE/mlb/outputs/lines_today.csv" ]; then
    echo "  Live lines_today.csv: $(stat -c %y "$LIVE/mlb/outputs/lines_today.csv" 2>/dev/null | cut -d. -f1)"
fi
if [ -f "$LIVE/data/mlb/lines_today.csv" ]; then
    echo "  Live data/mlb/lines_today.csv: $(stat -c %y "$LIVE/data/mlb/lines_today.csv" 2>/dev/null | cut -d. -f1)"
fi

echo ""
echo "Diagnostic complete."