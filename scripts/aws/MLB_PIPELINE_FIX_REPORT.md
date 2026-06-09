# MLB Pipeline Fix - Summary Report
# Generated: 2026-05-03 12:08 UTC

## ROOT CAUSE ANALYSIS

### The Problem
The MLB data pipeline had **multiple conflicting publish paths** causing stale data:

1. **Conflicting source directories:**
   - `/home/ubuntu/mlb_model/mlb/outputs` (canonical model output)
   - `/home/ubuntu/edgeranked-sportsai/mlb/outputs` (was being used as live site output)
   - `/home/ubuntu/data/mlb` (legacy path)
   - `/home/ubuntu/data/normalized` (legacy path)

2. **App.py path resolution logic:**
   - App looks for `lines_today.csv` at `MLB_DATA_DIR / "lines_today.csv"`
   - `MLB_DATA_DIR` resolves to first existing directory from candidates:
     - `$EDGERANKED_MLB_BASE_DIR/data/mlb` (if env var set)
     - `/home/ubuntu/mlb_model/data/mlb`
     - `/home/ubuntu/mlb_model_v2_working/mlb_model/data/mlb`
     - `/home/ubuntu/EdgeRanked/site/data/mlb`

3. **Previous fixes created duplicate copy logic:**
   - Old `run_mlb_day.sh` had multiple publish blocks
   - No single source of truth
   - Files copied to multiple locations with no synchronization
   - Service restarted before validation could complete

4. **Data normalized path was missing:**
   - `/home/ubuntu/edgeranked-sportsai/data/normalized/` did not exist
   - App was reading from `/home/ubuntu/edgeranked-sportsai/data/mlb/lines_today.csv` (44K, stale from April 21)
   - Source had fresh data at `/home/ubuntu/mlb_model/mlb/outputs/lines_today.csv` (49K, today's run)

### The Solution
Single canonical pipeline with ONE source of truth:

**Source:** `/home/ubuntu/mlb_model/mlb/outputs`
**Destination:** `/home/ubuntu/edgeranked-sportsai` (served by Flask app)

---

## FILES CHANGED

### 1. `/home/ubuntu/EdgeRanked/site/scripts/aws/run_mlb_day.sh` (rewritten)

**What it does:**
- Fetches MLB lines from PrizePicks API
- Runs unified model via `unified_output_router`
- Publishes site projection exports
- Runs MLB weather board build/validation (non-blocking)
- **NEW: Canonical publish block** - copies model outputs to live destination
- **NEW: Validation block** - verifies required files exist, not empty, modified today
- **NEW: Service restart** - only after successful validation

**Key changes:**
- Removed duplicate publish logic
- Removed references to `/home/ubuntu/data`
- Removed old loop-based copy logic
- Added explicit file-by-file copy with size validation
- Added `lines_today.csv` copies to `data/mlb` and `data/normalized`
- Added `lines_today_audit.json` copy to `data/normalized`
- Added timestamp validation (must be modified today)
- Added row count reporting for CSV files
- Service restart happens ONLY after validation passes

### 2. `/home/ubuntu/EdgeRanked/site/scripts/aws/diagnose_mlb_paths.sh` (new)

**What it does:**
- Checks service status and environment
- Lists cron jobs
- Reports timestamps from all key paths
- Compares source vs live file timestamps
- Tests API endpoints
- Reports path mismatches with recommendations

---

## BACKUP LOCATIONS

Previous versions of `run_mlb_day.sh` backed up:
- `/home/ubuntu/EdgeRanked/site/scripts/aws/run_mlb_day.sh.backup_20260430_020416`
- `/home/ubuntu/EdgeRanked/site/scripts/aws/run_mlb_day.sh.backup_20260430_102001`
- `/home/ubuntu/EdgeRanked/site/scripts/aws/run_mlb_day.sh.backup_20260503_113242`
- `/home/ubuntu/EdgeRanked/site/scripts/aws/run_mlb_day.sh.backup_20260503_120316` (latest backup)

---

## VERIFICATION RESULTS

### Pipeline run completed at 12:07:39 UTC:
```
[MLB PUBLISH] Copied: betting_sheet_today.csv (1.2K)
[MLB PUBLISH] Copied: betting_sheet_mobile_today.csv (551)
[MLB PUBLISH] Copied: hitter_summary_today.csv (12K)
[MLB PUBLISH] Copied: hitter_predictions_full.csv (58K)
[MLB PUBLISH] Copied: hitter_predictions_today.csv (273K)
[MLB PUBLISH] Copied: fantasy_projections_today.csv (25K)
[MLB PUBLISH] Copied: mlb_pitcher_projections_today.csv (5.9K)
[MLB PUBLISH] Copied: pitcher_props_today.csv (4.4K)
[MLB PUBLISH] Copied: lines_today.csv (49K)
[MLB PUBLISH] Copied: lines_today_audit.json (15K)
[MLB PUBLISH] Copied: lines_today_raw.csv (1.7M)
[MLB PUBLISH] Copied lines_today.csv to data/mlb and data/normalized
[MLB PUBLISH] Copied lines_today_audit.json to data/normalized
[MLB VALIDATE] All required files validated successfully
[MLB RESTART] Service restarted
```

### API Endpoints verified (all show 2026-05-03T08:07:39 - today's run):
- `/api/mlb/lines` - 50 records, last_updated: 2026-05-03T08:07:39
- `/api/mlb/projections` - 391 records, last_updated: 2026-05-03T08:07:39
- `/api/mlb/best-bets` - 9 records, last_updated: 2026-05-03T08:07:39

---

## ROLLBACK INSTRUCTIONS

If issues occur, rollback by:

### Option 1: Restore previous script version
```bash
cp /home/ubuntu/EdgeRanked/site/scripts/aws/run_mlb_day.sh.backup_20260503_120316 \
   /home/ubuntu/EdgeRanked/site/scripts/aws/run_mlb_day.sh
sudo systemctl restart edgerankai
```

### Option 2: Manual file restoration (if data becomes stale)
```bash
# Re-copy from source to live
SRC="/home/ubuntu/mlb_model/mlb/outputs"
LIVE="/home/ubuntu/edgeranked-sportsai"

for f in lines_today.csv betting_sheet_today.csv hitter_summary_today.csv hitter_predictions_today.csv fantasy_projections_today.csv pitcher_props_today.csv mlb_pitcher_projections_today.csv; do
    cp -f "$SRC/$f" "$LIVE/mlb/outputs/$f"
done

# Copy lines to data directories
cp -f "$SRC/lines_today.csv" "$LIVE/data/mlb/lines_today.csv"
cp -f "$SRC/lines_today.csv" "$LIVE/data/normalized/lines_today.csv"

sudo systemctl restart edgerankai
```

### Option 3: Run diagnostic to identify specific issues
```bash
bash /home/ubuntu/EdgeRanked/site/scripts/aws/diagnose_mlb_paths.sh
```

---

## CANONICAL PIPELINE SUMMARY

```
┌─────────────────────────────────────────────────────────────────────┐
│                      MLB PIPELINE (AFTER FIX)                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  SOURCE (Model Outputs)                                            │
│  /home/ubuntu/mlb_model/mlb/outputs                                 │
│                                                                     │
│       │                                                              │
│       ▼                                                              │
│  ┌──────────────────────────────────────────┐                      │
│  │  Canonical Publish Block (run_mlb_day.sh) │                      │
│  │  - Explicit file-by-file copy             │                      │
│  │  - Size validation (reject empty files)   │                      │
│  │  - Timestamp validation (must be today)   │                      │
│  │  - Row count reporting for CSVs          │                      │
│  └──────────────────────────────────────────┘                      │
│       │                                                              │
│       ▼                                                              │
│  LIVE DESTINATION                                                   │
│  /home/ubuntu/edgeranked-sportsai/                                  │
│                                                                     │
│  Subdirectories updated:                                            │
│  - mlb/outputs/ (all output files)                                  │
│  - data/mlb/ (lines_today.csv)                                     │
│  - data/normalized/ (lines_today.csv, audit JSON)                    │
│                                                                     │
│       │                                                              │
│       ▼                                                              │
│  Flask app reads from:                                              │
│  - MLB_OUTPUT_DIR = /home/ubuntu/edgeranked-sportsai/mlb/outputs    │
│  - MLB_DATA_DIR = /home/ubuntu/edgeranked-sportsai/data/mlb         │
│                                                                     │
│       │                                                              │
│       ▼                                                              │
│  Service restart only after validation passes                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## KEY FILES AND THEIR PURPOSES

| File | Purpose |
|------|---------|
| `/home/ubuntu/mlb_model/mlb/outputs/lines_today.csv` | Model input lines |
| `/home/ubuntu/edgeranked-sportsai/mlb/outputs/` | Live site outputs |
| `/home/ubuntu/edgeranked-sportsai/data/mlb/lines_today.csv` | App's MLB_DATA_DIR |
| `/home/ubuntu/edgeranked-sportsai/data/normalized/` | Audit files location |

---

## CRON SCHEDULE

MLB cron jobs (unchanged):
- 09:00 UTC - Morning run
- 14:00 UTC - Afternoon run
- 18:15 UTC - Evening run

All cron jobs run: `bash /home/ubuntu/EdgeRanked/site/scripts/aws/run_mlb_day.sh`

---

## NOTES

1. **No rsync used** - explicit file-by-file copy as required
2. **No model formula changes** - only publishing logic modified
3. **NBA/PGA/UFC unchanged** - only MLB pipeline touched
4. **Service restart timing** - now happens only after validation passes
5. **Diagnostic script** - created for ongoing monitoring
6. **Path ambiguity eliminated** - single source of truth established