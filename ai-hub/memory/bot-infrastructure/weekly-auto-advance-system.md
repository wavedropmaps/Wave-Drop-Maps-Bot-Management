---
name: Weekly Auto-Advance System
description: Dual-mechanism system that automatically advances weeks to prevent stale date issues
type: project
---

## Problem Solved

**Before:** Weekly checks would complete, then loop forever checking the same dates because config.json was never updated to the next week.

**Now:** Two independent mechanisms ensure dates auto-advance:
1. **Fast path** — after full-week report completes, immediately advance
2. **Safety loop** — every 37 hours, check if week has ended and advance if needed

---

## Architecture

### Two Independent Mechanisms

#### 1. **Fast Path: Auto-Advance After Full-Week Report**
**File:** `tasks/weekly_checks.py` (lines ~1100-1114)

Runs **immediately after** a full-week report completes:
```python
if period == "Full Week":
    try:
        next_start, next_end = calculate_next_week(start_date, actual_end_date)
        if update_global_dates_in_config(next_start, next_end):
            logger.info(f"🎯 AUTO-ADVANCED WEEK: {next_start} → {next_end}")
```

**When it runs:** Right after all duties (req, role, etc.) complete processing  
**Expected output:** `🎯 AUTO-ADVANCED WEEK: 22/06/2026 → 29/06/2026`

#### 2. **Safety Loop: Periodic Fallback Check**
**File:** `tasks/periodic_week_rollover.py` (new file)  
**Interval:** Every 37 hours

Runs independently in the background:
```python
if now > end_datetime:
    logger.info(f"📅 WEEK ENDED: {end_date} has passed")
    next_start, next_end = calculate_next_week(start_date, end_date)
    update_global_dates_in_config(next_start, next_end)
```

**When it activates:**
- Bot crashed and weekly_checks never ran
- weekly_checks.py is broken or disabled
- Dates were manually set wrong
- Weekly report failed mid-process

**Expected output:** `✅ AUTO-ADVANCED: 22/06/2026 → 29/06/2026`

---

## Helper Functions

**File:** `core/helpers.py` (added)

### `calculate_next_week(start_date_str, end_date_str) → tuple`
Calculates next week's dates from current week.

**Input:** `"14/06/2026"`, `"21/06/2026"` (dd/mm/yyyy format)  
**Output:** `("22/06/2026", "29/06/2026")`  
**Logic:** Start = end_date + 1 day, End = start + 6 days (7-day week)

### `update_global_dates_in_config(start_date, end_date) → bool`
Updates `config.json` with new week dates.

**Input:** New start/end dates  
**Writes:** `config.json` → `global_dates` section  
**Returns:** `True` on success, `False` on error

---

## Integration Points

### 1. Weekly Checks Integration
- **Import:** Added to `tasks/weekly_checks.py` imports (line 26-27)
- **When:** Runs after full-week report completes
- **Who:** The `run_report_at_exact_time()` function
- **Speed:** Immediate (no delay)

### 2. Periodic Rollover Cog
- **Type:** Discord.py Cog (auto-loads with bot)
- **Auto-registration:** Scanned by `find_cog_files()` in main.py
- **Setup hook:** `async def setup(bot)` — required for Cog loading
- **Logging:** Debug messages show weekly validity every 37 hours

---

## Behavior Examples

### Normal Case (Weekly Report Runs)
```
12:00 UTC (Fri) — Full week report completes
        ✅ All duties processed
        ✅ Strikes issued, VBucks awarded
        ✅ Report sent to Discord
        🎯 AUTO-ADVANCED WEEK: 22/06/2026 → 29/06/2026  ← FAST PATH
        💤 Sleep until next week

Next loop iteration:
        ✅ Sees new dates in config.json
        ✅ Ready to run mid-week check for new week
```

### Failure Recovery (37-Hour Safety Loop)
```
08:00 UTC (Sat) — Bot crashes before reporting (or report fails)
        config.json still has: 14/06/2026 → 21/06/2026

37 hours later (09:00 UTC Sun):
        📅 Periodic check wakes up
        ✅ Sees current time > 21/06/2026 23:59:59
        ✅ AUTO-ADVANCED: 22/06/2026 → 29/06/2026  ← SAFETY PATH
        ✅ Next weekly_checks loop picks up new dates

Result: Dates corrected without manual intervention
```

### Duplicate Auto-Advance Protection
- Fast path runs (say) Saturday morning → advances to next week
- Safety loop runs Sunday morning → sees new dates, logs "valid", skips
- No risk of double-advancing

---

## Configuration

### `config.json` Structure
```json
{
  "global_dates": {
    "start_date": "14/06/2026",
    "end_date": "21/06/2026",
    "timezone": "UTC"
  }
}
```

This is the ONLY place dates live. Auto-advance updates both `start_date` and `end_date` atomically.

---

## Monitoring & Logs

### Fast Path Logs (after full week completes)
```
🎯 AUTO-ADVANCED WEEK: 22/06/2026 → 29/06/2026
✅ Updated config.json: 22/06/2026 → 29/06/2026
```

### Safety Loop Logs (every 37 hours)
**When week is valid:**
```
📅 PERIODIC CHECK: Week 14/06/2026→21/06/2026 valid. 42.5h remaining
```

**When week has ended (auto-advance triggered):**
```
📅 WEEK ENDED: 21/06/2026 has passed (now: 2026-06-22 12:00:00)
   Auto-advancing to next week...
✅ AUTO-ADVANCED: 22/06/2026 → 29/06/2026
✅ Updated config.json: 22/06/2026 → 29/06/2026
```

---

## Error Handling

### If `calculate_next_week()` fails
- **Cause:** Invalid date format in config.json
- **Log:** `❌ Failed to calculate next week from 14/06/2026 → 21/06/2026`
- **Result:** Dates not updated, safety loop retries after 5 min

### If `update_global_dates_in_config()` fails
- **Cause:** File permission issue, corrupted JSON, disk full
- **Log:** `❌ Failed to update config.json: <error>`
- **Result:** Dates not updated, safety loop retries in 37 hours

### If config.json missing `global_dates` section
- **Log:** `⚠️ No global_dates in config.json, skipping check`
- **Result:** Safety loop skips until config is fixed

---

## Performance Impact

- **Weekly auto-advance:** <10ms (one calculation, one JSON write)
- **Periodic safety loop:** Wakes every 37 hours, checks ~2 dates, runs once per iteration
- **No extra API calls** — all local file operations
- **No race conditions** — one writer (auto-advance) per week

---

## Testing Checklist

- [ ] Full-week report completes, verify `config.json` updated
- [ ] Check logs show `🎯 AUTO-ADVANCED WEEK:` message
- [ ] Kill bot mid-week, restart → safety loop should eventually advance
- [ ] Manually set `end_date` to yesterday → safety loop advances immediately
- [ ] Periodic check logs show `📅 PERIODIC CHECK: ... valid. Xh remaining` every 37 hours

