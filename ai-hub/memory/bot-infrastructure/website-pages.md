# Website Pages Architecture

Documentation of the Staff Hub website pages (`website/` folder). Each page is a self-contained HTML file that fetches data from `/api/<key>` endpoints and renders leaderboards, dashboards, or dashboards.

## Page Structure

All pages follow the same pattern:

1. **HTML markup** — layout, styling (inline CSS), navigation
2. **Data URLs** — defined at the top of the `<script>` section (e.g., `const DATA_URLS = { loot: '/api/loot', ... }`)
3. **Fetch on load** — `fetchAll()` runs on page load, fetches all URLs in parallel
4. **Render** — JavaScript populates the page with the fetched data

**Key constraint:** Every page has a **unique filename** (kept from the original wave-leaderboard repo) so that cross-links between pages work.

---

## Pages Inventory

| Page | File | Lines | Purpose |
|---|---|---|---|
| **Profile** | `profile.html` | 66,926 | Player profile: lifetime stats, weekly performance, WP history, activity tabs |
| **Loot Routes Leaderboard** | `loot_routes_leaderboard.html` | 224,459 | Live rotation queue, rank deltas, lucky map history, MVP |
| **Surge Routes Leaderboard** | `surge_routes_leaderboard.html` | 199,535 | Parallel to loot; surge-specific rotation and leaderboard |
| **Tips & Tricks Leaderboard** | `tips_tricks_leaderboard.html` | 53,395 | Completed tasks, points earned, difficulty tiers |
| **Activity Leaderboard** | `activity_leaderboard.html` | 31,624 | Full-week Req performance ranks per guild (Great, Very Good, Good, Okay, Bad) |
| **Economy** | `economy.html` | 81,235 | Shop (roles, perks, rewards), buy prices, inventory, transaction history |
| **Events** | `events.html` | 69,200 | Bot activity log (daily, weekly events, announcements) |
| **Rules** | `rules.html` | 33,675 | Game rules, duty descriptions, economy guide, strike thresholds |
| **Wave Guide** | `wave-guide.js` | 59,962 | Game mechanics reference (read-only) — **co-edit requirement** with economy changes |
| **Team** | `team.html` | 33,841 | Org chart (staff hierarchy, team structure) |
| **Admin** | `admin.html` | 4,806 | Head of Staff panel (add members, train users, manage duty roles) |
| **Duty Needs** | `duty_needs.html` | 10,738 | Current open positions, staffing gaps per duty |
| **Index** | `index.html` | 13,479 | Home page (nav, latest news, quick stats) |

---

## Data Flow

### From Bot to Page

1. **Bot runs a task** (e.g., `tasks/loot_routes.py`)
2. **Task builds a data object** (users, ranks, stats, trends)
3. **Task writes JSON** to `website/data/<key>.json` (e.g., `website/data/loot.json`)
4. **`web_api.py` serves it** at `/api/<key>` (e.g., `/api/loot`)
5. **Page fetches it** with `fetch('/api/loot')`
6. **Page renders** the data into the DOM

### Example: Loot Routes Leaderboard

```javascript
const DATA_URLS = {
  loot: '/api/loot',
  surge: '/api/surge',
  lifetime: '/api/lifetime',
  economy: '/api/economy',
  // ...
};

async function fetchAll() {
  const results = await Promise.all(
    Object.entries(DATA_URLS).map(async ([key, url]) => {
      const r = await fetch(url);
      return r.ok ? r.json() : null;
    })
  );
  // results[0] = loot data, results[1] = surge data, etc.
  render(results);
}
```

---

## How to Edit Each Part

### Editing Page Markup or Styling

**File:** `website/<page>.html`

1. Edit the HTML structure or CSS inside the `<style>` block
2. Save
3. **No deploy needed** — Flask serves it live from `website/`
4. Hard-refresh browser to clear cache

**Do NOT edit the data JSON files directly** — they're overwritten by the bot on next update.

### Editing What Data a Page Shows

**Involved files:**
- `website/<page>.html` — the render code (where data is displayed)
- `tasks/<system>.py` — the payload builder (what data gets written)

**Flow:**
1. Edit the **render code** in the page (how data is displayed)
2. Edit the **payload builder** in the bot task (what data gets sent)
3. Both must agree on the JSON schema
4. On next bot data update, the new format is written and page renders it

**Example:** If you want loot leaderboard to show "last_completed_date" alongside rank:
- Edit `website/loot_routes_leaderboard.html` to render `player.last_completed_date`
- Edit `tasks/loot_routes.py` to include `last_completed_date` in the JSON payload
- On next `push_loot_route_leaderboard_to_github()` run, the new data flows to the page

### Adding a New Data Endpoint

1. **Add to `_API_PAGES` in `web_api.py`** — register the new endpoint name
2. **Have the bot task write `website/data/<key>.json`** — e.g., `website/data/my_new_data.json`
3. **Page fetches it** with `fetch('/api/<key>')`

**Restart required:** Edit `web_api.py`, then run `restart_staff_hub.ps1` (full restart).

---

## Critical Rules

### Do NOT write to `bot_database.db` from the website

- Flask has no `_bot_instance`, so direct writes skip bot side-effects
- **All mutations must route through the bot** (this is the gate for any future "website actions")

### Do NOT commit `.env`

- Holds `BOT_TOKEN`, `CLOUDFLARE_API_TOKEN`, `STAFF_HUB_SECRET`
- Gitignored; keep it out of version control

### Co-edit Rule: Economy Changes

**Any change to economy mechanics (earning rates, commands, awards, currency, shop items, penalties):**
- Edit the code (commands, tasks, database helpers)
- **Also update `website/wave-guide.js`** in the SAME commit
- The guide is a static doc with zero connection to bot code — it will silently drift if not touched

**Historical gotcha:** VBucks→WP unification left the guide stale with LRP/SRP/APR copy until a follow-up pass.

---

## Local Dev Preview

**Run the website locally** (for testing before deploy):

```bash
python website/mock_server.py
```

- Starts Flask at `http://127.0.0.1:5000`
- Serves static files from `website/`
- Mocks `/api/` endpoints with data from `website/data/*.json` files
- Useful for testing front-end changes before the live supervisor takes over

---

## Page-Specific Gotchas

### Profile Page
- Fetches per-user data: `wp_history`, `wp_transactions`, lifetime stats
- User lookup is case-insensitive (search UI)
- Avatar images cached; Discord updates may lag

### Leaderboard Pages (Loot, Surge, Tips, Duties)
- Rank calculations are live (ORDER BY in the bot task, not cached)
- Daily streaks, weekly MVPs update on their schedule (see background tasks)
- Deltas show rank change vs last snapshot (stored in `json_data/`)

### Economy Page
- Buy prices are FIXED (set in bot code, not fetched)
- Shop inventory refreshes when new roles are added to bot
- Transaction history is user-filtered (bot writes filtered JSON per user request)

### Admin Page
- Requires Discord login + Staff role
- Head of Staff only (role-gated in Flask)
- Actions (add member, train user) call backend endpoints; responses poll for success

---

## File Locations & Ownership

| Component | File | Owner | Notes |
|---|---|---|---|
| Live website code | `website/` | Flask + pages | Edit here for changes |
| Live data (JSON) | `website/data/` | Bot tasks | Never edit directly; bot overwrites on update |
| Bot payload builders | `tasks/loot_routes.py`, `tasks/surge_routes.py`, etc. | Bot code | Controls what data is written |
| API server | `web_api.py` | Flask | Routes `/api/<key>` to `website/data/<key>.json` |
| Supervisor | `staff_hub_serve.py` | Windows (PC) | Starts Flask + cloudflared tunnel; auto-restarts on fail |

---

*Referenced from `AGENTS.md` → Codebase Map. Read this before touching `website/`, `web_api.py`, or editing page layouts/data endpoints.*
