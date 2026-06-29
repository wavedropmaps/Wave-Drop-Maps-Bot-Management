# VBucks → Wave Points Unification Plan

**Status:** Planning complete — ready to build.
**Created:** 2026-06-20.
**Supersedes/extends:** [`economy-simplification-plan.md`](economy-simplification-plan.md) (that plan folded LRP/SRP/TTP into WP but **kept** the WP↔VBucks market alive — this plan kills it).

---

## 🎯 Main Goal

**Wave Points become the single currency.** VBucks stops being something you *earn and hold* and becomes a **fixed-price prize you buy with WP**. The whole floating exchange/market, exit tax, and conversion fees are deleted. There is no "market" because there's only one currency.

End state:
- You **earn** Wave Points for everything (routes, reviewing, weekly performance, predictions).
- You **spend** WP in one shop. VBucks is just a prize tier in that shop.
- There is **no WP↔VBucks trading**, no tiers, no exit tax, no conversion fee.

---

## 🔒 Locked Decisions (change here first if you disagree)

| # | Decision | Value |
|---|---|---|
| 1 | **Buy price** for VBucks prizes | **50 WP = 100 VBucks** → cards cost **800→400, 1,000→500, 1,500→750, 2,000→1,000, 5,000→2,500, 10,000→5,000 WP** |
| 2 | **Existing balance migration** rate | **15 WP = 100 VBucks** (1,000 VB → 150 WP). ⚠️ **Deliberately cheaper than buy price** — deflates the VBucks overhang instead of dumping WP into circulation. Do NOT "fix" this asymmetry. |
| 3 | **Weekly Req award** (was 300/200 VBucks) | **150 / 100 WP** (preserves value at buy price). Tunable. |
| 4 | **Predictions** betting currency | **Wave Points** (was VBucks). |
| 5 | **Bad-performance penalty** (was 200-VB-equiv @ 15/100) | **Flat 200 WP**. |
| 6 | **APR interest** on WP balances | **Removed** (a fixed VBucks price + interest faucet = price drift). **Bonds + lottery may stay** (keeps the bank fun). |

**Comms note:** Decision #2 is a ~70% haircut on held VBucks vs buy-back price. Announce to staff before running the migration.

---

## ⚖️ Decision-Framework Summary (why this shape)

- **Core risk is NOT the edits — it's 3 sessions touching the same file.** Solution: strict **file ownership**, zero overlap (table below).
- **Disjoint files still share functions.** The system is only consistent when **all 3 sessions finish AND the migration runs AND the bot restarts** — never half-deploy. (See §Sequencing.)
- **Decoupling rule:** Session C removes only the **market engine**, NOT the core `vbucks` table / `get_vbucks` / `add_vbucks`. Those stay (frozen after migration) so Sessions A & B never depend on C's deletions.

---

## 🧱 Interface Contract (ALL sessions obey)

1. **Read/write WP only** via `database.add_wave_points()` / `get_wave_points()`. Never add new VBucks writes.
2. **Do not delete** `vbucks` table, `get_vbucks`, `add_vbucks`, `set_vbucks` from `database.py`. They stay (frozen post-migration). Only *stop calling* them for new awards.
3. **Buy price constant:** `WP_PER_100_VBUCKS = 50` (fixed). No tier lookups. If you need it in your file, define a local module-level constant — do NOT import a shared market function (those are being deleted).
4. **Touch only files your workstream owns** (table below). If you think you need a file another session owns, STOP and leave a `# TODO(cross-session): …` note instead.
5. **Don't restart the bot or run the migration** — that's the serial finalize step after all 3 land.

---

## 📂 File Ownership — NO OVERLAP

| Session | Owns these files |
|---|---|
| **A — Earning → WP** | `tasks/weekly_checks.py`, `tasks/predictions_engine.py`, `commands/predictions.py`, `tasks/bot_admin_api.py` |
| **B — Redemption + UI** | `web_api.py`, `website/economy.html`, `tasks/web_shop_processor.py`, `tasks/economy_sync.py` |
| **C — Engine teardown + migration** | `database_economy.py`, `commands/central_bank_commands.py`, `tasks/central_banks.py`, `commands/wave_points_commands.py`, `commands/vbucks_system.py`, `tasks/leaderboard_updater.py`, **NEW** `migrations/vbucks_to_wp.py` |
| **SERIAL (after all 3)** | `commands/utilities.py` (help text), `ai-hub/docs/systems.md` (doc), then Phase 0 migration + restart |

> `database.py` is **read-only** for all sessions (the contract forbids changing the vbucks table). If a schema change is truly needed, it goes in the migration (C), not in `database.py`.

---

## 🅰️ Session A — Move Earning to Wave Points

**Goal:** nothing awards VBucks anymore; everything awards WP.

- [ ] **A1 — Weekly Req award** (`tasks/weekly_checks.py` ~L681-720): change `awards = {1: 300, 2: 200}` to award **WP** (150 / 100) via `add_wave_points`, not `add_vbucks`. Update the DM embed text ("VBucks Awarded" → "Wave Points Awarded", drop the "VBucks Wallet Balance" field).
- [ ] **A2 — Penalty** (`tasks/weekly_checks.py` ~L737-877): replace the 200-VB-equivalent logic + the `15 WP = 100 VBucks` conversion math with a **flat 200 WP deduction** via `add_wave_points(uid, -200)`. Remove the wallet/VBucks deduction branch and the conversion comments.
- [ ] **A3 — Predictions engine** (`tasks/predictions_engine.py` L112,116): bets and payouts move from `add_vbucks(...)` to `add_wave_points(...)`. Audit the whole file for VBucks wording/fields.
- [ ] **A4 — Predictions commands/UI** (`commands/predictions.py`): relabel VBucks → Wave Points in all user-facing text, embeds, and balance checks.
- [ ] **A5 — Predictions admin API** (`tasks/bot_admin_api.py`): switch any predictions balance/pool reads + writes to WP. ⚠️ If you find non-predictions economy endpoints here, leave a `# TODO(cross-session)` and tell the owner — don't fix market endpoints (that's B/C).
- [ ] **A6 — Smoke test:** simulate a Full Week → confirm Req #1/#2 get WP, penalty deducts 200 WP, predictions bet/settle in WP.

## 🅱️ Session B — Redemption + Website

**Goal:** VBucks cards cost WP; the market/exchange is gone from the site.

- [ ] **B1 — VBucks redemption deducts WP** (`tasks/web_shop_processor.py` `_process_vbucks_redemption` ~L147): instead of checking/deducting the VBucks balance, compute `cost_wp = amount * 50 / 100`, check `get_wave_points`, deduct via `add_wave_points(-cost_wp)`. Keep the "real V-Bucks fulfilment" DM/log (it's still a manual payout).
- [ ] **B2 — Web API VBucks shop** (`web_api.py` `shop_vbucks_*` ~L392-487): price the 6 VBucks prizes in **WP** at 50/100 (400/500/750/1,000/2,500/5,000). Validate against WP balance, not VBucks balance.
- [ ] **B3 — Delete exchange endpoints** (`web_api.py` ~L490-530+): remove `_exchange_preview`, `_WP_TIER_RATES`, the `wp_vb`/`vb_wp` routes — the market is gone.
- [ ] **B4 — economy.html VBucks cards** (~L1086-1096): change `currency: "vbucks"` block so the 6 cards show **WP cost** (400/500/750/1,000/2,500/5,000) and spend WP. Fix the stale note ("Deducted from your VBucks wallets (Main → Req → Role)") → WP wording.
- [ ] **B5 — economy.html Market tab** (~L1700+): remove the WP↔VBucks market UI, tier tables, and the "Trade your points on the open market" section. Remove APR-interest displays (decision #6). Keep bonds/lottery UI if those stay.
- [ ] **B6 — economy_sync.py** (`tasks/economy_sync.py`): stop fetching/writing market tier + exchange data + VBucks supply to `economy.json`; remove the WP→VBucks conversion write (~L274).
- [ ] **B7 — Smoke test:** load the shop page, redeem a VBucks card → confirm WP deducted at 50/100, no market tab, page renders.

## 🅲 Session C — Engine Teardown + Migration

**Goal:** delete the market machinery; write the one-time balance migration.

- [ ] **C1 — Market engine** (`database_economy.py`): remove `get_market_tier`, `update_market_volume`, `update_market_tier`, `get_market_with_history`, rate-history fns, `_RATE_VALUES_WP_VB`. **Keep** bonds + lottery sections (decision #6). Do NOT touch the `vbucks` table helpers in `database.py`.
- [ ] **C2 — Central bank commands** (`commands/central_bank_commands.py`): remove `>ptvtax`, conversion-fee admin, and **interest** commands (`>bankinterest`, `>bankinterestlog`, `>bankinterestinfo`, `get_tiered_apr` usage). Keep bonds/lottery/reserves/broadcast.
- [ ] **C3 — Central bank task** (`tasks/central_banks.py`): remove `apply_conversion_fee` and the interest payout loop. Keep bond resolution if bonds stay.
- [ ] **C4 — Delete disabled exchange cmds** (`commands/wave_points_commands.py`): delete the commented-out `>ptv`/`>vtp` method bodies and the `WP_TIER_RATES` constants. **Leave the `SHOP_PRIZES` block alone** (it has today's fresh pricing). Remove the `INTEREST_TIERS`/`get_tiered_apr` helpers (decision #6).
- [ ] **C5 — VBucks command surface** (`commands/vbucks_system.py`): remove the dead `>vbucksredeem`/`>vbuckstransfer` stubs; repurpose `>vbucks set` → it should set **WP** (or delete in favor of `>wpset`). Keep `>vbucks` (balance view) only if VBucks balances still display post-migration; otherwise remove.
- [ ] **C6 — Leaderboard hooks** (`tasks/leaderboard_updater.py`): remove `auto_update_vbucks_leaderboard` hooks (no VBucks leaderboard in a one-currency world).
- [ ] **C7 — Migration script** (NEW `migrations/vbucks_to_wp.py`): model it on `economy_simplification.py` (idempotent, sentinel row, dry-run + `--commit`, atomic txn). It must:
  1. Credit each user `ROUND(vbucks.total_vbucks * 15 / 100)` WP.
  2. Zero the `vbucks` table balances.
  3. Fold/zero central-bank VBucks reserves (convert at 15/100 into WP reserves, or zero).
  4. Settle/convert any **open prediction pools** at 15/100 (or assert none open).
  5. Write sentinel `vbucks_to_wp_v1`.
- [ ] **C8 — Dry-run** the migration against a DB copy and paste the preview into the PR.

## 🏁 SERIAL Finalize (one session, after A+B+C merged)

- [ ] **F1 — Help text** (`commands/utilities.py`): strip all `>ptv`/`>vtp`/`>vbucksredeem`/`>vbuckstransfer`/exit-tax/market mentions; rewrite economy help as "earn WP → spend in `>wpshop`; VBucks is a prize."
- [ ] **F2 — Docs** (`ai-hub/docs/systems.md`): rewrite the Wave Points + VBucks sections to the one-currency model.
- [ ] **F3 — Announce** the 15/100 haircut to staff (decision #2 comms note).
- [ ] **F4 — Run Phase 0 migration** (`python migrations/vbucks_to_wp.py` dry-run → `--commit`) on the main machine with the bot **stopped**.
- [ ] **F5 — Restart bot**, verify: shop redeems VBucks at WP cost, weekly award pays WP, predictions in WP, no market tab, `economy.json` clean.

---

## 🔀 Sequencing & Safety

1. **Before spawning sessions:** commit + push the current pricing work (clean base for all 3).
2. **Run A, B, C in parallel** — each on its own files, each opens its own PR/branch or commits to master in turn (master-only repo → coordinate pushes, or use worktrees).
3. **HARD RULE — no half-deploy:** the bot is NOT restarted and the migration is NOT run until A, B, and C are all merged. Intermediate states break (e.g. C deletes `get_market_tier` while B still imports it).
4. **Finalize (F1–F5)** last, serially.

## ✅ Definition of Done
- No code path calls `add_vbucks` for a *new* award (predictions/weekly/penalty all WP).
- The website has no market tab and VBucks cards cost WP at 50/100.
- `database_economy.get_market_tier` and the exchange endpoints no longer exist.
- Migration ran: every held VBuck became WP at 15/100; `vbucks` balances zeroed.
- Bot restarts clean; `economy.json` has no market/exchange/interest fields.
