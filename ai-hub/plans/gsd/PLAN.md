# Milestone: Weekly Challenge Completion Modes (11–26, A–H)

## Goal
Expand `tasks/random_challenges.py` beyond `first_to_target` / `most_in_24h` with 16 completion modes, rotated generation, baseline deltas, and dead `activity_streaks` removal (mode #24 = delete, not build).

## Definition of done
- [x] F0: `mode_params` column, `COMPLETION_MODE_CHECKERS` registry, `compute_rank_total`, `scan_reviews_extended`
- [x] R24: `activity_streaks` dead code removed; memory updated
- [x] All mode checkers implemented (not stubs)
- [x] Week-start / mid-week generation rotates modes
- [x] Fire-time `mode_params` (eligibility, personal targets, multi-duty baselines)
- [x] Hourly enrich: PH active, route counts, reviews extended
- [x] Tiered podium multi-award path
- [x] `closest_without_bust` week-end resolution in `expire_unwon_challenges`
- [x] `py_compile` on `random_challenges.py` + `unified_weekly_loop.py`
- [ ] `python ai-hub/gates/validate.py` exit 0 (run after bot restart / when shell available)
- [ ] Bot restart to apply DB migration + live test one hourly scan

## Tasks (completed in-repo)

| ID | Task | Output |
|----|------|--------|
| F0 | Foundation schema + dispatch | `mode_params`, registry, helpers |
| R24 | Streak cleanup | No live `activity_streaks` callers; `systems.md` note |
| M1 | Mode checkers 11–26 + letters | `_check_*` functions in `random_challenges.py` |
| M2 | Generation INTEG | `generate_week_start_challenges`, `generate_midweek_challenges` |
| M3 | Fire wiring | `_enrich_mode_params_at_fire`, `save_challenge(mode_params=…)` |
| M4 | Hourly wiring | `_enrich_all_stats_for_modes`, tiered + closest paths |
| M5 | Reviews extended | `unified_weekly_loop` uses `scan_reviews_extended` for hub + scans |

## Non-goals (this milestone)
- New challenge **duties** (loot routes, surge, tips as duties) — separate future work
- `tiered_podium` / `seasonal_scramble` in default rotation — implemented but rare/manual
- Git commit (user must ask)

## Mode alias map
| Letter | Number | Slug |
|--------|--------|------|
| A | 18 | catchup_bracket |
| B | 26 | proof_pipeline |
| C | 14 | engagement_combo |
| D | 15 | balanced_staff |
| E | 11 | active_week / consistency_gate |
| F | — | underdog_24h |
| G | 13 | beat_last_week |
| H | 21 | route_runner |
