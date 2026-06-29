"""
Tips & Tricks Helper System — single source of truth for all IDs and tunables.

Tips & Tricks Helpers manage Fortnite strategy content across the Wave community:
spawns, surge, creative codes, pro notes, game stages, loadouts, mechanics, drop
spots, and lootpools. Fully separate from loot/surge systems.

TODO: fill in role IDs and channel IDs after creating the roles/channels in Discord.
"""

# ──────────────────────────── Guilds ────────────────────────────
GUILD_ID = 1041450125391835186  # staff hub (where commands/points run)
GUILD_IDS = [
    1041450125391835186,  # staff hub
    988564962802810961,   # source guild 2
    971731167621574666,   # source guild 3
]

# ──────────────────────────── Roles ─────────────────────────────
TT_HELPER_ROLE_NAME = "Tips and Tricks Helper"  # matched by name across all guilds
HEAD_TT_ROLE_NAME   = "Head Tips & Tricks"

# Roles allowed to run admin commands (>addtipshelper, >addtttask, etc.)
TT_ADMIN_ROLES = ('Management', '007', '+', HEAD_TT_ROLE_NAME)

# ──────────────────────── Functional channels ───────────────────
TT_LOG_CHANNEL_ID           = 0                    # task creation / completion logs (set if needed)
TT_ANNOUNCEMENTS_CHANNEL_ID = 1261142512093888582   # join/leave announcements + weekly MVP

# ──────────────────────────── Economy ───────────────────────────
LUCKY_TASK_CHANCE      = 0.11   # 11% — assigned at task creation time
LUCKY_TASK_MULTIPLIER  = 2.0    # lucky: earned_pts = base × 2
UNCLAIMED_BONUS_DAYS   = 7      # days until unclaimed task gets base_points bumped
UNCLAIMED_BONUS_POINTS = 80     # new base_points value after 7-day unclaimed period (WP direct)
BASE_TASK_POINTS       = 40     # default points for a freshly created task (WP direct)

# ──────────────────────────── Duty codes ────────────────────────
# Admin supplies these codes to >assignttduty <CODE> <@user>
DUTY_CODES = [
    "SPAWNS",
    "SURGE",
    "CREATIVE",
    "PRONOTES",
    "GAMESTAGES",
    "LOADOUTS",
    "MECHANICS",
    "DROPSPOTS",
    "LOOTPOOLS",
]

DUTY_NAMES = {
    "SPAWNS":     "Managing Spawns Category",
    "SURGE":      "Managing Surge Category",
    "CREATIVE":   "Managing Creative Map Codes Category",
    "PRONOTES":   "Managing Pro Notes & Learn From Pros Category",
    "GAMESTAGES": "Managing Game Stages",
    "LOADOUTS":   "Managing Loadouts Category",
    "MECHANICS":  "Managing Game Mechanics & Meta",
    "DROPSPOTS":  "Managing Dropspots Category",
    "LOOTPOOLS":  "Managing Lootpools Category",
}

# ──────────────────────────── Shop ──────────────────────────────
# Prices = loot/surge shop ÷ 10, rounded to nearest whole number.
TT_SHOP_PRIZES = {
    "surge_route":       {"name": "⚡ Free Pro Surge Route!",        "cost": 5,   "emoji": "⚡", "color": 0x00D9FF},
    "loot_route":        {"name": "💰 Free Pro Loot Route!",         "cost": 10,  "emoji": "💰", "color": 0xFFD700},
    "paid_priority":     {"name": "⭐ Paid Priority Role!",          "cost": 10,  "emoji": "⭐", "color": 0xF1C40F},
    "wave_contributor":  {"name": "🌊 Wave Contributor Role!",       "cost": 11,  "emoji": "🌊", "color": 0x1ABC9C},
    "drop_map":          {"name": "🎯 Free Pro Drop Map!",           "cost": 17,  "emoji": "🎯", "color": 0xFF6B35},
    "vip":               {"name": "👑 VIP Role!",                    "cost": 119, "emoji": "👑", "color": 0xE91E63},
    "announcement_ping": {"name": "📢 @everyone Announcement Ping!", "cost": 178, "emoji": "📢", "color": 0xE67E22},
}
# Prizes auto-granted as Discord roles (same perks guilds as surge/loot).
TT_ROLE_PRIZES   = {"paid_priority": "Paid Priority", "wave_contributor": "Wave Contributor", "vip": "VIP"}
# Prizes requiring manual fulfilment by management.
TT_MANUAL_PRIZES = {"surge_route", "loot_route", "drop_map", "announcement_ping"}
# Guilds where perks roles live (NOT the staff hub).
PERKS_GUILD_IDS         = [988564962802810961, 971731167621574666]
REDEMPTION_LOG_CHANNEL_ID = 1470639550534778882   # shared redemption log

# ─────────────────────── TTP ↔ WP Exchange ──────────────────────
# Baseline (T3): 1 T&T pt = 40 WP.  Tier driven by ratio = total_ttp / total_wp.
# Thresholds are LRP thresholds ÷ 40 (T&T supply is ~40× smaller than LRP supply).
TTP_WP_TIER_RATES = {1: 50, 2: 45, 3: 40, 4: 35, 5: 30}   # WP per 1 TTP
TTP_WP_TIER_LABELS = {
    1: "TTP scarce",
    2: "",
    3: "Baseline",
    4: "",
    5: "TTP abundant",
}
# (upper_exclusive, tier) sorted ascending; last band catches ratio ≥ 0.010
TTP_WP_TIER_THRESHOLDS = [
    (0.002, 1),
    (0.003, 2),
    (0.006, 3),
    (0.010, 4),
]

# ──────────────────────── Files / web ───────────────────────────
TT_LEADERBOARD_JSON = "tips_tricks_leaderboard.json"  # pushed to wave-leaderboard repo
TT_RANK_SNAPSHOT    = "json_data/tt_rank_snapshot.json"
WAVE_LOG_CATEGORY   = "tips_and_tricks"
