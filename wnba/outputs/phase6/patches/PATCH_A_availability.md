# Patch A — Availability Fix (ESPN injuries User-Agent)

**Status:** APPROVED for deployment after Phase 6B validation.
**File:** `sports/wnba/fetch_wnba_data.py`
**Risk:** Low. Restores a currently-dead feed; failure mode falls back to today's behavior.
**Rollback:** restore from `backups/wnba_phase6_<TS>/fetch_wnba_data.py`.

## Root cause
ESPN serves a 1,987-byte bot-protection stub to the detailed Mac-Chrome User-Agent the scraper
sends, so `fetch_espn_injuries` parses 0 rows and `wnba_player_status.csv` is empty. A plain
`Mozilla/5.0` receives the full 298 KB page; the existing parser then works unchanged.

## Change 1 — User-Agent (line 335)

**Before:**
```python
ESPN_INJURIES_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
```
**After:**
```python
ESPN_INJURIES_HEADERS = {
    # NOTE: ESPN serves a ~2KB bot-protection stub to detailed desktop-Chrome UA strings.
    # A generic Mozilla/5.0 receives the full page. Do not "modernize" this UA. See Phase 6.
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
```

## Change 2 — Response-size guard (after line 375, inside `fetch_espn_injuries`)

**Before:**
```python
    logger.info("Fetched ESPN injuries page (%d bytes)", len(html))

    soup = BeautifulSoup(html, "html.parser")
```
**After:**
```python
    logger.info("Fetched ESPN injuries page (%d bytes)", len(html))
    if len(html) < 5000:
        # A <5KB body is a bot-protection stub, not a real (empty) injury report. Raise so
        # resolve_player_status() logs a fetch failure and falls back, instead of silently
        # recording "no injuries". See Phase 6.
        raise RuntimeError(
            f"ESPN injuries page returned only {len(html)} bytes (<5KB) — bot-protection stub; "
            "refusing to parse as 'no injuries'"
        )

    soup = BeautifulSoup(html, "html.parser")
```

The raise is caught by `resolve_player_status()`'s existing `except` (≈line 575), which logs
`"ESPN injuries fetch failed"` and falls back to the manual CSV / empty source — i.e. exactly
today's behavior, but now *visible* in logs rather than silent.

## Schema impact
None. Output columns of `fetch_espn_injuries` / `normalize_player_status` are unchanged
(`player_name, team, status, player_key, _data_source`). Downstream `apply_status_filter`
already handles `out/doubtful/inactive/suspended`. When the feed is empty (fallback), behavior
is identical to today.

## Validation commands (Phase 6B)
```bash
cd /home/ubuntu/EdgeRanked/sports/wnba
# current (pre-patch) scrape result:
.venv/bin/python -c "import logging,fetch_wnba_data as f; print('rows', len(f.fetch_espn_injuries(logging.getLogger())))"
# after applying patch — expect rows>0 and a >5KB fetch in logs:
.venv/bin/python -c "import logging,fetch_wnba_data as f; logging.basicConfig(level=logging.INFO); df=f.fetch_espn_injuries(logging.getLogger()); print('rows',len(df)); print(df.head().to_string())"
# end-to-end: confirm canonical status file populates and schema unchanged:
.venv/bin/python fetch_wnba_data.py && head -1 data/raw/wnba_player_status.csv
```

## Rollback commands
```bash
cp backups/wnba_phase6_<TS>/fetch_wnba_data.py sports/wnba/fetch_wnba_data.py
# verify reverted:
grep -n 'Chrome/124.0' sports/wnba/fetch_wnba_data.py   # present again == rolled back
```
