"""
hierarchy_cache.py — Hourly role hierarchy cache for Staff Hub guild.

Scans Staff Hub guild only (canonical role names). Writes:
  json_data/role_hierarchy_cache.json  — all staff, keyed by user ID
  website/data/team_hierarchy.json     — leadership slice (replaces >refreshteam)

Public API:
  get_cached_role(uid) -> (top_role_name, tier_key)
  force_rebuild(bot)   -> bool
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands

from core.helpers import web_avatar_url

logger = logging.getLogger('discord')

STAFF_HUB_GUILD_ID = 1041450125391835186

_BASE       = Path(__file__).resolve().parent.parent
_CACHE_FILE = _BASE / 'json_data' / 'role_hierarchy_cache.json'
_TEAM_FILE  = _BASE / 'website' / 'data' / 'team_hierarchy.json'

# In-memory cache: uid (int) -> entry dict
_cache: dict = {}

# ==================== TIER ORDER ====================
# (rank, tier_key, match_mode, role_name_list)
# match_mode 'exact'     -> role.name == name  (case-insensitive)
# match_mode 'substring' -> name in role.name  (case-insensitive)
# Roles sorted by Discord position descending; first match wins.

TIER_ORDER = [
    (0,  'board',     'exact',     ['Founder', 'Owner']),
    (1,  'executive', 'substring', ['Executive Director']),
    (2,  'head_func', 'substring', ['Head Staff', 'Head Operations', 'Head Marketing']),
    (3,  'sub_head',  'substring', ['Head Recruiter', 'Head of Learning', 'Head L&D',
                                    'Head Loot Routes', 'Head Tips', 'Head Surge Routes',
                                    'Head Logistics', 'Head Promot']),
    (4,  'mgmt',      'exact',     ['Management']),
    (5,  'head_admin','exact',     ['Head Admin']),
    (6,  'sradmin',   'exact',     ['Senior Admin']),
    (7,  'admin',     'exact',     ['Admin']),
    (8,  'srsup',     'exact',     ['Senior Support']),
    (9,  'sup',       'exact',     ['Support']),
    (10, 'helper',    'exact',     ['Loot Route Maker', 'Tips & Tricks Helper',
                                    'Surge Route Maker', 'Promoters']),
    (11, 'staff',     'exact',     ['Staff', '@Map Request Helper']),
    (12, 'trial',     'exact',     ['Trial Staff']),
]

# ==================== TEAM SLOTS ====================
# Leadership-only slots for team_hierarchy.json (team page).
# (match_mode, role_name_list)

_TEAM_SLOTS = {
    'founder':            ('exact',     ['Founder', 'Owner']),
    'executive_director': ('substring', ['Executive Director']),
    'head_staff':         ('substring', ['Head Staff']),
    'head_operations':    ('substring', ['Head Operations']),
    'head_marketing':     ('substring', ['Head Marketing']),
    'head_recruiter':     ('substring', ['Head Recruiter']),
    'head_ld':            ('substring', ['Head of Learning', 'Head L&D', 'Head Learning']),
    'head_loot_routes':   ('substring', ['Head Loot']),
    'head_tips_tricks':   ('substring', ['Head Tips']),
    'head_surge_routes':  ('substring', ['Head Surge']),
    'head_logistics':     ('substring', ['Head Logistics']),
    'head_promoting':     ('substring', ['Head Promot']),
    'management':         ('exact',     ['Management']),
    'head_admin':         ('exact',     ['Head Admin']),
}


# ==================== CORE LOGIC ====================

def _role_matches(role_name: str, mode: str, names: list) -> bool:
    rn = role_name.lower()
    if mode == 'exact':
        return any(rn == n.lower() for n in names)
    return any(n.lower() in rn for n in names)


_STAFF_ROLE_NAMES = {'staff', 'trial staff'}

def _resolve_tier(member: discord.Member) -> tuple:
    """Return (top_role_name, tier_key, tier_rank, has_staff_role) for a member."""
    best_rank = len(TIER_ORDER)
    best_name = 'Trial Staff'
    best_key  = 'trial'
    has_staff = False
    for role in sorted(member.roles, key=lambda r: r.position, reverse=True):
        if role.name.lower() in _STAFF_ROLE_NAMES:
            has_staff = True
        for rank, key, mode, names in TIER_ORDER:
            if rank >= best_rank:
                break
            if _role_matches(role.name, mode, names):
                best_rank, best_name, best_key = rank, role.name, key
                break
    return best_name, best_key, best_rank, has_staff


def _build_team_hierarchy(cache: dict) -> dict:
    """Filter cache entries to leadership slots for team_hierarchy.json.

    Checks ALL stored role names (not just top_role) so a member with
    Management + Head Surge Routes still appears in the head_surge_routes slot.
    A member may appear in multiple slots if they genuinely hold multiple
    leadership roles (e.g. Management + Head Loot Routes).
    """
    payload = {slot: [] for slot in _TEAM_SLOTS}
    for uid_str, entry in cache.items():
        if uid_str == '_meta':
            continue
        role_names = entry.get('all_roles') or [entry.get('top_role', '')]
        for slot, (mode, names) in _TEAM_SLOTS.items():
            if any(_role_matches(rn, mode, names) for rn in role_names):
                payload[slot].append({
                    'name':       entry['name'],
                    'avatar_url': entry.get('avatar_url'),
                    'user_id':    uid_str,
                })
    return payload


def _write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        tmp.replace(path)
    except Exception as e:
        logger.warning(f"[HierarchyCache] Failed to write {path.name}: {e}")


# ==================== PUBLIC API ====================

def get_cached_role(uid: int) -> tuple:
    """Return (top_role_name, tier_key, has_staff_role). Fallback: ('Trial Staff', 'trial', False)."""
    entry = _cache.get(int(uid))
    if entry:
        return entry['top_role'], entry['tier'], entry.get('has_staff_role', False)
    return 'Trial Staff', 'trial', False


def _get_display_role_for_activity_page(bot, uid: int) -> tuple:
    """Return (display_role_name, display_tier) - highest role EXCLUDING helper & sub_head.
    If top role is helper/sub_head, find next best from all_roles. Fallback: Staff."""
    entry = _cache.get(int(uid))
    if not entry:
        return 'Staff', 'staff'

    hide_tiers = {'helper', 'sub_head'}
    best_rank = len(TIER_ORDER)
    best_name = 'Staff'
    best_key = 'staff'

    # Scan all_roles to find highest non-helper/sub_head tier
    all_roles = entry.get('all_roles', [])
    for role_name in all_roles:
        if role_name == '@everyone':
            continue
        for rank, key, mode, names in TIER_ORDER:
            if key in hide_tiers:  # Skip helper and sub_head
                continue
            if _role_matches(role_name, mode, names):
                if rank < best_rank:
                    best_rank, best_name, best_key = rank, role_name, key
                break

    return best_name, best_key


async def force_rebuild(bot) -> bool:
    """Trigger a full rescan immediately. Called by >refreshteam."""
    return await _full_scan(bot)


# ==================== SCAN ====================

async def _full_scan(bot) -> bool:
    guild = bot.get_guild(STAFF_HUB_GUILD_ID)
    if guild is None:
        logger.warning("[HierarchyCache] Staff Hub guild not cached — skipping scan")
        return False

    new_cache: dict = {}
    for member in guild.members:
        if member.bot:
            continue
        top_role, tier_key, tier_rank, has_staff = _resolve_tier(member)
        new_cache[str(member.id)] = {
            'name':           member.display_name,
            'top_role':       top_role,
            'tier':           tier_key,
            'tier_rank':      tier_rank,
            'has_staff_role': has_staff,
            'all_roles':      [r.name for r in member.roles if r.name != '@everyone'],
            'avatar_url':     web_avatar_url(member.display_avatar),
        }

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    cache_payload = {
        '_meta': {
            'updated_at':   now,
            'guild_id':     STAFF_HUB_GUILD_ID,
            'member_count': len(new_cache),
        },
        **new_cache,
    }

    _write_json(_CACHE_FILE, cache_payload)
    _write_json(_TEAM_FILE, _build_team_hierarchy(cache_payload))

    _cache.clear()
    for uid_str, entry in new_cache.items():
        _cache[int(uid_str)] = entry

    logger.info(f"[HierarchyCache] Full scan complete — {len(new_cache)} members")
    return True


def _update_single(member: discord.Member) -> None:
    """Patch cache for one member after a role change (no full rescan needed)."""
    top_role, tier_key, tier_rank, has_staff = _resolve_tier(member)
    entry = {
        'name':           member.display_name,
        'top_role':       top_role,
        'tier':           tier_key,
        'tier_rank':      tier_rank,
        'has_staff_role': has_staff,
        'all_roles':      [r.name for r in member.roles if r.name != '@everyone'],
        'avatar_url':     web_avatar_url(member.display_avatar),
    }
    _cache[member.id] = entry

    try:
        if _CACHE_FILE.exists():
            existing = json.loads(_CACHE_FILE.read_text(encoding='utf-8'))
        else:
            existing = {'_meta': {}}
        existing[str(member.id)] = entry
        existing.setdefault('_meta', {})['updated_at'] = (
            datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        )
        _write_json(_CACHE_FILE, existing)
        _write_json(_TEAM_FILE, _build_team_hierarchy(existing))
    except Exception as e:
        logger.warning(f"[HierarchyCache] Patch write failed for {member.id}: {e}")


# ==================== HOURLY LOOP ====================

async def _hierarchy_loop(bot):
    await bot.wait_until_ready()
    await asyncio.sleep(5)  # let other cogs settle after startup
    await _full_scan(bot)
    while True:
        await asyncio.sleep(3600)
        try:
            await _full_scan(bot)
        except asyncio.CancelledError:
            logger.info("[HierarchyCache] Hourly loop cancelled")
            raise
        except Exception as e:
            logger.error(f"[HierarchyCache] Hourly scan error: {e}")


# ==================== COG ====================

class HierarchyCache(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.task = None

    async def cog_load(self):
        self.task = asyncio.create_task(_hierarchy_loop(self.bot))
        logger.info("[HierarchyCache] Cog loaded — hourly loop started")

    def cog_unload(self):
        if self.task:
            self.task.cancel()
        logger.info("[HierarchyCache] Cog unloaded")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.guild.id != STAFF_HUB_GUILD_ID:
            return
        if before.roles == after.roles:
            return
        _update_single(after)
        logger.debug(
            f"[HierarchyCache] Role update: {after.display_name} → {get_cached_role(after.id)}"
        )


async def setup(bot):
    await bot.add_cog(HierarchyCache(bot))
    logger.info("[HierarchyCache] Setup complete")
