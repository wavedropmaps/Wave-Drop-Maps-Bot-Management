# Economy Simplification Plan

**Goal:** Remove LRP, SRP, TTP as currencies. Tasks pay **Wave Points (WP) directly**. Kill the `>ptv` exit tax. Delete all exchange/transfer commands. Delete all non-WP redeem commands. Update the website everywhere.

**Two currencies remaining:** VBucks + Wave Points.

---

## Earn Rates (direct WP payouts after migration)

### Loot Routes (`>done`)
| Speed     | WP     |
|-----------|--------|
| ≤12h      | 10 WP  |
| ≤24h      | 8 WP   |
| ≤48h      | 4 WP   |
| ≤72h      | 2 WP   |
| ≤96h      | 0 WP   |
| >4d       | penalty: −(3 + days_over) WP, floored at 0 |

Role multipliers unchanged (Head 2×, Inspector 1.5×). Lucky map 2×. Penalties not multiplied.

### Surge Routes (`>surgedone`)
| Speed     | WP     |
|-----------|--------|
| ≤12h      | 5 WP   |
| ≤24h      | 4 WP   |
| ≤48h      | 2 WP   |
| ≤72h      | 1 WP   |
| ≤96h      | 0 WP   |
| >4d       | penalty: −(3 + days_over) / 2 WP, floored at 0 |

### Tips & Tricks (task complete)
| Task type          | WP      |
|--------------------|---------|
| Normal task        | 40 WP   |
| Unclaimed 7d+ task | 80 WP   |
| Lucky task (2×)    | 80 WP   |

---

## Migration Script (Phase 0)
File: `migrations/economy_simplification.py` — runs **once** before bot restart.

| Source                              | Conversion         | Destination              |
|-------------------------------------|--------------------|--------------------------|
| User LRP balances                   | × 4                | wave_points balance      |
| User SRP balances                   | × 3                | wave_points balance      |
| User TTP balances                   | × 40               | wave_points balance      |
| Bank `reserves_lrp`                 | × 4                | `reserves_points` (WP)   |
| Bank `reserves_srp`                 | × 3                | `reserves_points` (WP)   |
| `loot_route_points.total_points`    | × 4                | same column (WP now)     |
| `surge_route_points.total_points`   | × 3                | same column (WP now)     |
| `route_converted_wp` table          | wipe               | —                        |

All at baseline exchange rates (LRP 1:4, SRP 1:3, TTP 1:40).

---

## Phase 1 — Task Payout Rewiring

### `>done` — `commands/loot_route_commands.py`
- Remove `add_loot_route_points` call
- Add `add_wave_points(user_id, wp_amount)` with tier amounts above
- Also write WP amount to `loot_route_points` table for leaderboard tracking
- Penalty → negative WP, floored at 0

### `>surgedone` — `commands/surge_route_commands.py`
- Same pattern: award WP directly
- Log to `surge_route_points` for leaderboard

### TT task complete — `commands/tipsandtricks.py`
- Award WP directly at rates above
- Penalties → negative WP floored at 0

---

## Phase 2 — Delete Exchange & Redeem Commands

### `commands/wave_points_commands.py` — DELETE:
- `>lrptowp` / `>wptolrp`
- `>srptowp` / `>wptosrp`

### `commands/tipsandtricks.py` — DELETE:
- `>ttptowp`
- `>ttredeem` + prize select view

### `commands/surge_route_commands.py` — DELETE:
- `>surgeredeem` + `SurgePrizeSelectView`

---

## Phase 3 — Simplify `>pointstovbucks` (ptv)

File: `commands/wave_points_commands.py`

- Remove `ROUTE_TIER_RATES` dict
- Remove `route_converted_wp` split logic (`route_wp`, `clean_wp`, `route_spend`)
- Remove `ptv_tax_pct` lookup — all WP→VBucks now uses standard `fee_rate_pct` (same as `>vtp`)
- Remove `database_economy.add_route_converted_wp` call
- `>ptv` becomes: WP at market rate, standard fee, no tax, no split breakdown embed

---

## Phase 4 — Economy Data Cleanup

### `tasks/economy_sync.py`
- Stop fetching/writing `lrp_wp`, `srp_wp`, `ttp_wp` market data
- Remove `reserves_lrp`, `reserves_srp` from JSON payload
- Remove LRP/SRP/TTP ticker entries from `economy.json`

### `tasks/central_banks.py` + `commands/central_bank_commands.py`
- Remove LRP/SRP reserve injection/withdrawal
- Remove `>ptvtax` admin command
- Remove `ptv_tax_pct` from central bank config

### `database_economy.py`
- Remove `get_route_converted_wp`, `add_route_converted_wp` functions
- Remove `route_converted_wp` table creation from `init_database`

---

## Phase 5 — Help Text

File: `commands/utilities.py`

Remove all references to:
- `>lrptowp`, `>wptolrp`, `>srptowp`, `>wptosrp`, `>ttptowp`
- `>surgeredeem`, `>ttredeem`
- `>ptvtax`, exit tax descriptions

Update economy description: earn WP from tasks → spend at `>wpshop` / `>wavepointsredeem`.

---

## Phase 6 — Website: `economy.html`

- **Market tab**: remove LRP/WP, SRP/WP, TTP/WP market cards + tier tables
- **Bank tab**: remove `reserves_lrp`, `reserves_srp` reserve cards; remove `ptv_tax` from fees; update text to standard fee only
- **Shop tab**: unchanged (WP shop already here)
- **Bottom ticker**: remove LRP/SRP/TTP market lines
- Add earning guide: loot routes = up to 10 WP, surge = up to 5 WP, tips = 40 WP per task

---

## Phase 7 — Website: Leaderboard Pages

### `loot_routes_leaderboard.html`
- Rename "LRP" / points column → "WP Earned"
- Replace loot shop section with redirect card: *"Spend your WP in the shop → Economy Page"*
- Remove all redeem/exchange references

### `surge_routes_leaderboard.html`
- Rename "SRP" → "WP Earned"
- Same shop redirect card

### `tips_tricks_leaderboard.html`
- Rename "TTP" → "WP Earned"
- Same shop redirect card

---

## Phase 8 — `economy.json` Schema

The bot's `economy_sync.py` writer removes:
- `market.lrp_wp`
- `market.srp_wp`
- `market.ttp_wp`
- `central_bank.reserves_lrp`
- `central_bank.reserves_srp`
- `central_bank.ptv_tax`

Website reads this at runtime so it automatically reflects the cleanup.

---

## Where to Work

### ✅ External PC (no database or live bot needed)
Pure code edits — can be done anywhere, committed and pushed:

| Phase | Files |
|-------|-------|
| Phase 1 | `commands/loot_route_commands.py`, `commands/surge_route_commands.py`, `commands/tipsandtricks.py` |
| Phase 2 | `commands/wave_points_commands.py`, `commands/tipsandtricks.py`, `commands/surge_route_commands.py` |
| Phase 3 | `commands/wave_points_commands.py` |
| Phase 4 | `tasks/economy_sync.py`, `tasks/central_banks.py`, `commands/central_bank_commands.py`, `database_economy.py` |
| Phase 5 | `commands/utilities.py` |
| Phase 6 | `website/economy.html` |
| Phase 7 | `website/loot_routes_leaderboard.html`, `website/surge_routes_leaderboard.html`, `website/tips_tricks_leaderboard.html` |

### 🖥️ Main machine only (needs live DB + bot)
| Phase | Why |
|-------|-----|
| Phase 0 | Migration script must run against the real `bot_database.db` |
| Phase 8 | Verify `economy.json` is writing correctly after bot restarts |
| Testing | Confirm `>done`, `>surgedone`, `>ptv` behave correctly in Discord |

**Workflow:** Do all code edits on external PC → push to master → run Phase 0 migration on main machine → restart bot.

---

## Files Changed Summary

| File | Change |
|------|--------|
| `migrations/economy_simplification.py` | NEW — one-time migration |
| `commands/loot_route_commands.py` | Rewire `>done` to pay WP |
| `commands/surge_route_commands.py` | Rewire `>surgedone` to pay WP; delete `>surgeredeem` |
| `commands/tipsandtricks.py` | Rewire task complete to pay WP; delete `>ttredeem`, `>ttptowp` |
| `commands/wave_points_commands.py` | Delete 4 exchange commands; simplify `>ptv` |
| `commands/central_bank_commands.py` | Remove LRP/SRP reserve cmds; remove `>ptvtax` |
| `commands/utilities.py` | Update all help strings |
| `tasks/economy_sync.py` | Stop writing LRP/SRP/TTP market data |
| `tasks/central_banks.py` | Remove LRP/SRP reserve management |
| `database_economy.py` | Remove `route_converted_wp` table + functions |
| `website/economy.html` | Remove LRP/SRP/TTP market, reserves, tax; add earning guide |
| `website/loot_routes_leaderboard.html` | Rename column; replace shop with WP redirect |
| `website/surge_routes_leaderboard.html` | Same |
| `website/tips_tricks_leaderboard.html` | Same |

---

*Created: 2026-06-14. Updated: 2026-06-15 — added external PC vs main machine split. See conversation context for full discussion.*
