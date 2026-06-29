"""
Surge Route System — single source of truth for all IDs and tunables.

Mirrors the Loot Route system but is a fully separate product:
  • separate DB tables (surge_route_*)
  • separate staff/roles
  • separate points balance + shop + leaderboard
  • NEW: hold-and-auto-assign-when-free pending pool

All Discord role matching is case-insensitive NAME match across the 3 guilds
(IDs below are the staff-hub fast path / multiplier checks). See database_surge.py.
"""

# ──────────────────────────── Guilds ────────────────────────────
GUILD_ID = 1041450125391835186  # staff hub (where rotation/points/leaderboard run)
GUILD_IDS = [
    1041450125391835186,  # staff hub
    988564962802810961,   # source guild 2
    971731167621574666,   # source guild 3 (also the surge customer-queue guild)
]

# ──────────────────────────── Roles ─────────────────────────────
# Maker is matched purely by NAME across all 3 guilds (IDs differ per guild).
SURGE_MAKER_ROLE_NAME = "Surge Route Maker"

# Head / Inspector / Away are staff-hub roles → ID fast path + name fallback.
HEAD_SURGE_ROUTES_ROLE_ID = 1414071449743921303
HEAD_SURGE_ROUTES_ROLE_NAME = "Head Surge Routes"
HEAD_SURGE_MULTIPLIER = 2.0

SURGE_INSPECTOR_ROLE_ID = 1513082132602552330
SURGE_INSPECTOR_ROLE_NAME = "Surge Route Inspector"
SURGE_INSPECTOR_MULTIPLIER = 1.5

SURGE_AWAY_ROLE_ID = 1513082353986306048
SURGE_AWAY_ROLE_NAME = "Surge Away"  # name fallback; away is checked by ID in staff hub

# ──────────────────────── Functional channels ───────────────────
# (staff hub) — NO log/rotation/leaderboard channels: those live on the website.
SURGE_MAP_REQUEST_CHANNEL_ID = 1416770574042140804   # trigger ("surge maps not taken")
SURGE_NOTIFICATION_CHANNEL_ID = 1513082739908153354  # claim/notify (assignment card + confirm)
SURGE_SUBMISSION_CHANNEL_ID = 1417091772810526760    # makers post fn.gg link; >surgedone scans here
SURGE_MEMBER_UPDATES_CHANNEL_ID = 1414072054457569322  # member updates (weekly MVP)
SURGE_MAPS_WORKED_ON_CHANNEL_ID = 1515010765235687555           # maps-getting-worked-on-surge (assignment feed)

# Redemption notification (functional management channel; default reuse loot's)
REDEMPTION_LOG_CHANNEL_ID = 1041584423264596009

# ──────────────────────────── Economy ───────────────────────────
# Time-to-complete → base points (same tiers as loot routes).
# HALF of the loot tiers on purpose: a surge route is worth HALF a loot route, but
# each surge POINT is worth the same as a loot point (prizes cost the same), so the
# value vs Wave Points stays identical to loot. "2x weaker" = half the earnings.
# hours <= 12 → 5 | <= 24 → 4 | <= 48 → 2 | <= 72 → 1 | <= 96 → 0 | > 96 → penalty
SURGE_POINT_TIERS = [
    (12, 5.0),
    (24, 4.0),
    (48, 2.0),
    (72, 1.0),
    (96, 0.0),
]
# > 4 days: half the loot penalty → -(3 + days_over) / 2.

LUCKY_MAP_CHANCE = 0.06   # 6% chance of a Lucky Map per surge assignment
LUCKY_MAP_MULTIPLIER = 2.0

# ──────────────────────── Cross-bot bridge ──────────────────────
SURGE_QUEUE_GUILD_ID = 971731167621574666          # where the Logistics surge queue lives
LOGISTICS_MAP_QUEUE_CHANNEL_ID = 1131190892707979284  # removequeue target (allowlist it)
WAVE_MANAGEMENT_BOT_ID = 1269188273201352768       # confirm == live Management bot.user.id

# ──────────────────────────── Shop ──────────────────────────────
# Mirrors the loot shop catalog/prices, but spends the separate SURGE balance.
# Same prices as the loot-route shop — a surge POINT is worth the same as a loot
# point (and the same vs Wave Points). Surge is "2x weaker" purely via half earnings.
SURGE_SHOP_PRIZES = {
    "surge_route":      {"name": "⚡ Free Pro Surge Route!",        "cost": 48,   "emoji": "⚡", "color": 0x00D9FF},
    "loot_route":       {"name": "💰 Free Pro Loot Route!",         "cost": 95,   "emoji": "💰", "color": 0xFFD700},
    "paid_priority":    {"name": "⭐ Paid Priority Role!",          "cost": 95,   "emoji": "⭐", "color": 0xF1C40F},
    "wave_contributor": {"name": "🌊 Wave Contributor Role!",       "cost": 107,  "emoji": "🌊", "color": 0x1ABC9C},
    "drop_map":         {"name": "🎯 Free Pro Drop Map!",           "cost": 166,  "emoji": "🎯", "color": 0xFF6B35},
    "vip":              {"name": "👑 VIP Role!",                    "cost": 1188, "emoji": "👑", "color": 0xE91E63},
    "announcement_ping":{"name": "📢 @everyone Announcement Ping!", "cost": 1781, "emoji": "📢", "color": 0xE67E22},
}
# Prizes that grant a community role (across the perks guilds).
SURGE_ROLE_PRIZES = {"paid_priority": "Paid Priority", "wave_contributor": "Wave Contributor", "vip": "VIP"}
# Prizes requiring manual fulfilment by management (posted to the redemption channel).
SURGE_MANUAL_PRIZES = {"surge_route", "loot_route", "drop_map", "announcement_ping"}
# Guilds the perk roles apply in (NOT the staff hub).
PERKS_GUILD_IDS = [988564962802810961, 971731167621574666]

# ──────────────────────── Files / web ───────────────────────────
SURGE_FILES_DIR = "surge_files"                         # local copies of surge map attachments
SURGE_RANK_SNAPSHOT = "json_data/surge_route_rank_snapshot.json"
SURGE_LEADERBOARD_JSON = "surge_routes_leaderboard.json"  # pushed to wave-leaderboard repo
WAVE_LOG_CATEGORY = "surge_routes"                       # Wave-Logging dashboard tab
