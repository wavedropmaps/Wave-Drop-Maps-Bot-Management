"""
tasks/bot_admin_api.py — Internal HTTP server for the Wave Staff Hub admin panel.

Runs on 127.0.0.1:5001 (never exposed externally — only Flask on 5000 proxies
to it after the Cloudflare worker has already verified Discord identity/roles).

Auth: X-API-Key must match STAFF_HUB_SECRET.
Role IDs (Staff Hub guild 1041450125391835186):
  Management        1041582103927726170  -> all sections
  Head Loot Routes  1231187220208025620  -> loot section
  Head Surge Routes 1414071449743921303  -> surge section
  Head Tips & Tricks 1286285354462085182 -> TT section
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

import discord
from aiohttp import web
from discord.ext import commands
from core.helpers import web_avatar_url

MANAGEMENT_ROLE_ID  = 1041582103927726170
HEAD_LOOT_ROLE_ID   = 1231187220208025620
HEAD_SURGE_ROLE_ID  = 1414071449743921303
HEAD_TT_ROLE_ID     = 1286285354462085182  # Head Tips and Tricks (NOT Tips and Tricks Helper)
HEAD_STAFF_ROLE_ID  = 1041582510955561021
STAFF_HUB_GUILD_ID  = 1041450125391835186
GENERAL_AWAY_ROLE_ID = 1231259676457566250  # core.helpers AWAY_ROLE_ID (normal away)


def _calc_points_from_hours(hours: float):
    if hours <= 12:  return 10.0, "⚡ Within 12h"
    if hours <= 24:  return 8.0,  "⚡ Within 24h"
    if hours <= 48:  return 4.0,  "🏃 Within 48h"
    if hours <= 72:  return 2.0,  "🚶 Within 3 days"
    if hours <= 96:  return 0.0,  "🚶 Within 4 days (0 pts)"
    days_over = int((hours - 96) / 24) + 1
    return float(-(3 + days_over)), f"💀 {int(hours/24)}+ days"


def _user_roles(req: web.Request):
    raw = req.headers.get('X-Wave-User-Roles', '')
    return {int(r) for r in raw.split(',') if r.strip().isdigit()}


def _user_id(req: web.Request) -> Optional[int]:
    v = req.headers.get('X-Wave-User-Id', '').strip()
    return int(v) if v.isdigit() else None


def _has_management(roles): return MANAGEMENT_ROLE_ID in roles
def _has_loot(roles):  return bool(roles & {MANAGEMENT_ROLE_ID, HEAD_LOOT_ROLE_ID})
def _has_surge(roles): return bool(roles & {MANAGEMENT_ROLE_ID, HEAD_SURGE_ROLE_ID})
def _has_tt(roles):    return bool(roles & {MANAGEMENT_ROLE_ID, HEAD_TT_ROLE_ID})
def _has_staff(roles): return bool(roles & {MANAGEMENT_ROLE_ID, HEAD_STAFF_ROLE_ID})
def _deny(msg='forbidden', status=403): return web.json_response({'error': msg}, status=status)
def _ok(data): return web.json_response({'ok': True, **data})


class BotAdminAPI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._runner: Optional[web.AppRunner] = None
        self._secret = os.getenv('STAFF_HUB_SECRET', '')

    async def cog_load(self):
        await self._start_server()

    async def cog_unload(self):
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    @web.middleware
    async def _auth(self, req: web.Request, handler):
        if not self._secret or req.headers.get('X-API-Key', '') != self._secret:
            return web.json_response({'error': 'forbidden'}, status=403)
        return await handler(req)

    async def _start_server(self):
        app = web.Application(middlewares=[self._auth])
        app.router.add_get( '/admin/loot/data',          self._loot_data)
        app.router.add_post('/admin/loot/done',           self._loot_done)
        app.router.add_post('/admin/loot/remove_maker',   self._loot_remove_maker)
        app.router.add_post('/admin/loot/set_away',       self._loot_set_away)
        app.router.add_post('/admin/loot/remove_away',    self._loot_remove_away)
        app.router.add_get( '/admin/surge/data',          self._surge_data)
        app.router.add_post('/admin/surge/done',          self._surge_done)
        app.router.add_post('/admin/surge/remove_maker',  self._surge_remove_maker)
        app.router.add_post('/admin/surge/set_away',      self._surge_set_away)
        app.router.add_post('/admin/surge/remove_away',   self._surge_remove_away)
        app.router.add_get( '/admin/tt/data',             self._tt_data)
        app.router.add_post('/admin/tt/create_task',       self._tt_create_task)
        app.router.add_post('/admin/tt/create_super_task', self._tt_create_super_task)
        app.router.add_post('/admin/tt/complete_task',    self._tt_complete_task)
        app.router.add_post('/admin/tt/cancel_task',      self._tt_cancel_task)
        app.router.add_post('/admin/tt/assign_duty',      self._tt_assign_duty)
        app.router.add_post('/admin/tt/remove_duty',      self._tt_remove_duty)
        app.router.add_get( '/admin/staff/data',          self._staff_data)
        app.router.add_post('/admin/staff/set_away',      self._staff_set_away)
        app.router.add_post('/admin/staff/remove_away',   self._staff_remove_away)
        app.router.add_post('/admin/staff/assign',        self._staff_assign)
        app.router.add_post('/admin/staff/train',         self._staff_train)
        app.router.add_post('/admin/staff/promote',       self._staff_promote)
        app.router.add_post('/admin/duty_needs',          self._duty_needs_post)
        # Predictions — read+vote for any staff; create/resolve/cancel = Management
        app.router.add_get( '/admin/predictions/data',     self._pred_data)
        app.router.add_post('/admin/predictions/vote',     self._pred_vote)
        app.router.add_post('/admin/predictions/create',   self._pred_create)
        app.router.add_post('/admin/predictions/resolve',  self._pred_resolve)
        app.router.add_post('/admin/predictions/cancel',   self._pred_cancel)

        app.router.add_get( '/admin/profile/customization', self._profile_custom_get)
        app.router.add_post('/admin/profile/customization', self._profile_custom_set)
        app.router.add_post('/admin/profile/upload',        self._profile_custom_upload)
        app.router.add_get( '/admin/profile/uploads',       self._profile_uploads_list)
        app.router.add_delete('/admin/profile/upload',      self._profile_upload_delete)

        app.router.add_get( '/admin/user/role_names',       self._user_role_names)
        app.router.add_get( '/admin/user/roles',            self._user_roles_live)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, '127.0.0.1', 5001).start()

    async def _duty_needs_post(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_management(roles):
            return _deny()
        
        try:
            data = await req.json()
            if not isinstance(data, list):
                return _deny('payload must be a list of duties', 400)
            
            import json
            from pathlib import Path
            file_path = Path(__file__).resolve().parent.parent / 'website' / 'data' / 'duty_needs.json'
            file_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
            return _ok({'saved': True})
        except Exception as e:
            return _deny(str(e), 500)

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _member_info(self, user_id: int) -> dict:
        guild = self.bot.get_guild(STAFF_HUB_GUILD_ID)
        if not guild:
            return {'user_id': str(user_id), 'display_name': f'User {user_id}', 'avatar_url': None}
        m = guild.get_member(user_id)
        if not m:
            try:
                m = await guild.fetch_member(user_id)
            except Exception:
                return {'user_id': str(user_id), 'display_name': f'User {user_id}', 'avatar_url': None}
        return {'user_id': str(user_id), 'display_name': m.display_name,
                'avatar_url': web_avatar_url(m.display_avatar)}

    def _tt_helpers(self) -> list:
        """All members with the 'Tips and Tricks Helper' role in the staff guild."""
        import core.tipsandtricks_config as ttcfg
        guild = self.bot.get_guild(STAFF_HUB_GUILD_ID)
        if not guild:
            return []
        want = ttcfg.TT_HELPER_ROLE_NAME.lower()
        role = next((r for r in guild.roles if r.name.lower() == want), None)
        if not role:
            return []
        def _av(m):
            return web_avatar_url(m.display_avatar)
        out = [{'user_id': str(m.id), 'display_name': m.display_name,
                'avatar_url': _av(m)}
               for m in role.members]
        out.sort(key=lambda x: x['display_name'].lower())
        return out

    def _member_has_role(self, user_id: int, role_id: int) -> bool:
        guild = self.bot.get_guild(STAFF_HUB_GUILD_ID)
        if not guild:
            return False
        m = guild.get_member(user_id)
        return bool(m and any(r.id == role_id for r in m.roles))

    async def _user_roles_live(self, req: web.Request):
        """Return live role IDs for a user from the Discord guild cache."""
        uid_str = req.rel_url.query.get('user_id', '').strip()
        if not uid_str or not uid_str.isdigit():
            return web.json_response({'error': 'user_id required'}, status=400)
        uid = int(uid_str)
        guild = self.bot.get_guild(STAFF_HUB_GUILD_ID)
        if not guild:
            return web.json_response({'error': 'guild_unavailable'}, status=503)
        member = guild.get_member(uid)
        if not member:
            return web.json_response({'role_ids': []})
        role_ids = [str(r.id) for r in member.roles]
        return web.json_response({'role_ids': role_ids})

    def _parse_dt(self, s: str) -> datetime:
        try:
            dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)

    # ══════════════════════════════════════════════════════════════════════════
    # LOOT ROUTES
    # ══════════════════════════════════════════════════════════════════════════

    async def _loot_data(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_loot(roles):
            return _deny()
        from database import get_all_loot_route_positions, get_all_away_return_dates, get_all_route_assignments
        positions   = await get_all_loot_route_positions()
        assignments = await get_all_route_assignments(STAFF_HUB_GUILD_ID)
        away_list   = await get_all_away_return_dates()
        away_map    = {str(a['user_id']): a.get('return_date') for a in away_list}
        assign_map  = {}
        for a in assignments:
            if a.get('status') in ('pending', 'confirmed'):
                assign_map.setdefault(str(a['user_id']), a)
        now = datetime.now(timezone.utc)
        makers = []
        for rank, user_id in positions:
            info = await self._member_info(user_id)
            uid_s = str(user_id)
            a = assign_map.get(uid_s)
            active = None
            if a:
                assigned_at = self._parse_dt(a.get('assigned_at', ''))
                hours = (now - assigned_at).total_seconds() / 3600
                active = {'assignment_id': a.get('assignment_id'),
                          'assigned_at': a.get('assigned_at', ''),
                          'hours_elapsed': round(hours, 1),
                          'map_details': a.get('map_details') or '',
                          'status': a.get('status', 'pending')}
            makers.append({**info, 'rotation_rank': rank,
                           'is_away': uid_s in away_map,
                           'return_date': away_map.get(uid_s),
                           'active_assignment': active})
        return web.json_response({'makers': makers})

    async def _loot_done(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_loot(roles):
            return _deny()
        body = await req.json()
        aid = body.get('assignment_id')
        if not aid:
            return _deny('missing assignment_id', 400)
        from database import get_route_assignment_by_id, complete_route_assignment, add_loot_route_points
        from tasks.wave_points import add_wave_points as _add_wp
        a = await get_route_assignment_by_id(int(aid))
        if not a:
            return _deny(f'assignment #{aid} not found', 404)
        if a.get('status') == 'completed':
            return _deny('already completed', 409)
        user_id = a['user_id']
        assigned_at = self._parse_dt(a.get('assigned_at', ''))
        hours = (datetime.now(timezone.utc) - assigned_at).total_seconds() / 3600
        base, speed = _calc_points_from_hours(hours)
        has_head = self._member_has_role(user_id, 1231187220208025620)
        has_insp = self._member_has_role(user_id, 1503649126192119839)
        if has_head and base > 0:
            points = base * 2.0
            mult_note = f"👑 2× Head ({base} × 2 = {points})"
        elif has_insp and base > 0:
            points = base * 1.5
            mult_note = f"🕵️ 1.5× Inspector ({base} × 1.5 = {points})"
        else:
            points, mult_note = base, None
        if bool(a.get('is_lucky_map', 0)) and base > 0:
            pre = points; points = points * 2.0
            lucky_note = f"🍀 2× Lucky ({pre} × 2 = {points})"
        else:
            lucky_note = None
        await complete_route_assignment(int(aid), points_awarded=points)
        await add_loot_route_points(user_id, points=points, guild_id=STAFF_HUB_GUILD_ID, bot=self.bot)
        await _add_wp(user_id, int(points), reason="Loot route completed")
        try:
            lr = self.bot.get_cog('LootRoutes')
            if lr and hasattr(lr, 'drain_loot_pending_pool'):
                asyncio.create_task(lr.drain_loot_pending_pool(reason="route_completed"))
        except Exception:
            pass
        try:
            from tasks.loot_routes import auto_update_loot_route_leaderboard
            await auto_update_loot_route_leaderboard(self.bot, triggered_by="route_completed")
        except Exception:
            pass
        return _ok({'assignment_id': aid, 'user': await self._member_info(user_id),
                    'hours': round(hours, 1), 'speed': speed, 'points': points,
                    'mult_note': mult_note, 'lucky_note': lucky_note})

    async def _loot_remove_maker(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_loot(roles):
            return _deny()
        body = await req.json()
        uid = body.get('user_id')
        if not uid:
            return _deny('missing user_id', 400)
        uid = int(uid)
        from database import remove_loot_route_position, get_loot_route_position
        if await get_loot_route_position(uid) is None:
            return _deny('user not in rotation', 404)
        await remove_loot_route_position(uid)
        try:
            lr = self.bot.get_cog('LootRouteCommands')
            if lr and hasattr(lr, 'remove_role_in_guilds'):
                asyncio.create_task(lr.remove_role_in_guilds(uid))
        except Exception:
            pass
        try:
            from tasks.loot_routes import auto_update_loot_route_leaderboard
            await auto_update_loot_route_leaderboard(self.bot, triggered_by="rotation_remove")
        except Exception:
            pass
        return _ok({'removed': await self._member_info(uid)})

    async def _loot_set_away(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_loot(roles):
            return _deny()
        body = await req.json()
        uid = body.get('user_id')
        if not uid:
            return _deny('missing user_id', 400)
        from database import set_away_return_date
        await set_away_return_date(int(uid), body.get('return_date'))
        try:
            from tasks.loot_routes import auto_update_loot_route_leaderboard
            await auto_update_loot_route_leaderboard(self.bot, triggered_by="away_set")
        except Exception:
            pass
        return _ok({'user': await self._member_info(int(uid)), 'return_date': body.get('return_date')})

    async def _loot_remove_away(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_loot(roles):
            return _deny()
        body = await req.json()
        uid = body.get('user_id')
        if not uid:
            return _deny('missing user_id', 400)
        from database import delete_away_return_date
        await delete_away_return_date(int(uid))
        try:
            from tasks.loot_routes import auto_update_loot_route_leaderboard
            await auto_update_loot_route_leaderboard(self.bot, triggered_by="away_removed")
        except Exception:
            pass
        return _ok({'user': await self._member_info(int(uid))})

    # ══════════════════════════════════════════════════════════════════════════
    # SURGE ROUTES
    # ══════════════════════════════════════════════════════════════════════════

    async def _surge_data(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_surge(roles):
            return _deny()
        import database_surge as sdb
        import core.surge_config as cfg
        positions   = await sdb.get_all_surge_route_positions()
        assignments = await sdb.get_all_surge_route_assignments(STAFF_HUB_GUILD_ID)
        away_list   = await sdb.get_all_surge_away_return_dates()
        away_map    = {str(a['user_id']): a.get('return_date') for a in away_list}
        assign_map  = {}
        for a in assignments:
            if a.get('status') in ('pending', 'confirmed'):
                assign_map.setdefault(str(a['user_id']), a)
        now = datetime.now(timezone.utc)
        makers = []
        for rank, user_id in positions:
            info = await self._member_info(user_id)
            uid_s = str(user_id)
            a = assign_map.get(uid_s)
            active = None
            if a:
                assigned_at = self._parse_dt(a.get('assigned_at', ''))
                hours = (now - assigned_at).total_seconds() / 3600
                active = {'assignment_id': a.get('assignment_id'),
                          'assigned_at': a.get('assigned_at', ''),
                          'hours_elapsed': round(hours, 1),
                          'map_details': a.get('map_details') or '',
                          'status': a.get('status', 'pending')}
            makers.append({**info, 'rotation_rank': rank,
                           'is_away': uid_s in away_map,
                           'return_date': away_map.get(uid_s),
                           'active_assignment': active})
        return web.json_response({'makers': makers})

    async def _surge_done(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_surge(roles):
            return _deny()
        body = await req.json()
        aid = body.get('assignment_id')
        if not aid:
            return _deny('missing assignment_id', 400)
        import database_surge as sdb
        import core.surge_config as cfg
        from tasks.wave_points import add_wave_points as _add_wp
        a = await sdb.get_surge_route_assignment_by_id(int(aid))
        if not a:
            return _deny(f'assignment #{aid} not found', 404)
        if a.get('status') == 'completed':
            return _deny('already completed', 409)
        user_id = a['user_id']
        assigned_at = self._parse_dt(a.get('assigned_at', ''))
        hours = (datetime.now(timezone.utc) - assigned_at).total_seconds() / 3600
        base, speed = _calc_points_from_hours(hours)
        has_head = self._member_has_role(user_id, cfg.HEAD_SURGE_ROUTES_ROLE_ID)
        has_insp = self._member_has_role(user_id, cfg.SURGE_INSPECTOR_ROLE_ID)
        if has_head and base > 0:
            points = base * cfg.HEAD_SURGE_MULTIPLIER
            mult_note = f"👑 {cfg.HEAD_SURGE_MULTIPLIER}× Head ({base} × {cfg.HEAD_SURGE_MULTIPLIER} = {points})"
        elif has_insp and base > 0:
            points = base * cfg.SURGE_INSPECTOR_MULTIPLIER
            mult_note = f"🕵️ {cfg.SURGE_INSPECTOR_MULTIPLIER}× Inspector ({base} × {cfg.SURGE_INSPECTOR_MULTIPLIER} = {points})"
        else:
            points, mult_note = base, None
        if bool(a.get('is_lucky_map')) and base > 0:
            pre = points; points = points * cfg.LUCKY_MAP_MULTIPLIER
            lucky_note = f"🍀 {cfg.LUCKY_MAP_MULTIPLIER}× Lucky ({pre} × {cfg.LUCKY_MAP_MULTIPLIER} = {points})"
        else:
            lucky_note = None
        await sdb.complete_surge_route_assignment(int(aid), points_awarded=points)
        await sdb.add_surge_route_points(user_id, points=points, guild_id=STAFF_HUB_GUILD_ID, bot=self.bot)
        await _add_wp(user_id, round(points), reason="Surge route completed")
        try:
            sg = self.bot.get_cog('SurgeRoutes')
            if sg and hasattr(sg, 'drain_pending_pool'):
                asyncio.create_task(sg.drain_pending_pool(reason="route_completed"))
        except Exception:
            pass
        try:
            from tasks.surge_routes import auto_update_surge_route_leaderboard
            await auto_update_surge_route_leaderboard(self.bot, triggered_by="route_completed")
        except Exception:
            pass
        return _ok({'assignment_id': aid, 'user': await self._member_info(user_id),
                    'hours': round(hours, 1), 'speed': speed, 'points': points,
                    'mult_note': mult_note, 'lucky_note': lucky_note})

    async def _surge_remove_maker(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_surge(roles):
            return _deny()
        body = await req.json()
        uid = body.get('user_id')
        if not uid:
            return _deny('missing user_id', 400)
        uid = int(uid)
        import database_surge as sdb
        if await sdb.get_surge_route_position(uid) is None:
            return _deny('user not in surge rotation', 404)
        await sdb.remove_surge_route_position(uid)
        try:
            sg = self.bot.get_cog('SurgeRouteCommands')
            if sg and hasattr(sg, '_role_in_guilds'):
                asyncio.create_task(sg._role_in_guilds(uid, add=False))
        except Exception:
            pass
        try:
            from tasks.surge_routes import auto_update_surge_route_leaderboard
            await auto_update_surge_route_leaderboard(self.bot, triggered_by="rotation_remove")
        except Exception:
            pass
        return _ok({'removed': await self._member_info(uid)})

    async def _surge_set_away(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_surge(roles):
            return _deny()
        body = await req.json()
        uid = body.get('user_id')
        if not uid:
            return _deny('missing user_id', 400)
        import database_surge as sdb
        await sdb.set_surge_away_return_date(int(uid), body.get('return_date'))
        return _ok({'user': await self._member_info(int(uid)), 'return_date': body.get('return_date')})

    async def _surge_remove_away(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_surge(roles):
            return _deny()
        body = await req.json()
        uid = body.get('user_id')
        if not uid:
            return _deny('missing user_id', 400)
        import database_surge as sdb
        await sdb.delete_surge_away_return_date(int(uid))
        return _ok({'user': await self._member_info(int(uid))})

    # ══════════════════════════════════════════════════════════════════════════
    # TIPS & TRICKS
    # ══════════════════════════════════════════════════════════════════════════

    async def _tt_data(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_tt(roles):
            return _deny()
        import database_tipsandtricks as db_tt
        tasks_raw = await db_tt.get_all_tasks()
        duties    = await db_tt.get_duty_assignments()
        tasks = []
        for t in tasks_raw:
            if t.get('status') == 'completed':
                continue
            t2 = dict(t)
            if t2.get('claimed_by'):
                info = await self._member_info(int(t2['claimed_by']))
                t2['claimed_by_name']   = info.get('display_name') or t2.get('claimed_by_name') or f"User {t2['claimed_by']}"
                t2['claimed_by_avatar'] = info.get('avatar_url')
            tasks.append(t2)
        duties_list = []
        for code, assignments in duties.items():
            for d in assignments:
                uid = d.get('user_id')
                info = await self._member_info(int(uid)) if uid else {}
                duties_list.append({'code': code,
                                    'user_id': str(uid) if uid else None,
                                    'display_name': info.get('display_name') or f"User {uid}",
                                    'avatar_url': info.get('avatar_url'),
                                    'assigned_at': d.get('assigned_at')})
        import core.tipsandtricks_config as ttcfg
        duty_codes = [{'code': c, 'name': ttcfg.DUTY_NAMES.get(c, c)} for c in ttcfg.DUTY_CODES]
        helpers = self._tt_helpers()
        return web.json_response({'tasks': tasks, 'duties': duties_list,
                                  'duty_codes': duty_codes, 'helpers': helpers})

    async def _tt_create_task(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_tt(roles):
            return _deny()
        body = await req.json()
        desc = (body.get('description') or body.get('raw') or '').strip()
        if not desc:
            return _deny('description required', 400)

        # Resolve any Discord channel URLs to real channel names
        import re
        attachments = []
        for m in re.finditer(r'https://discord\.com/channels/(\d+)/(\d+)(?:/\d+)?', desc):
            channel_id = int(m.group(2))
            ch = self.bot.get_channel(channel_id)
            label = f'#{ch.name}' if ch else 'Channel Link'
            attachments.append({'type': 'channel', 'url': m.group(0), 'label': label})

        import database_tipsandtricks as db_tt
        result = await db_tt.create_task(desc, _user_id(req) or 0, attachments)
        from tasks.tipsandtricks import push_leaderboard
        asyncio.create_task(push_leaderboard(self.bot))
        return _ok({'task_id': result['task_id'], 'is_lucky': result['is_lucky']})

    async def _tt_create_super_task(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_tt(roles):
            return _deny()
        body = await req.json()
        parent_desc = (body.get('parent_desc') or '').strip()
        subtasks = [s.strip() for s in (body.get('subtasks') or []) if s and s.strip()]
        if not parent_desc:
            return _deny('parent_desc required', 400)
        if len(subtasks) < 2:
            return _deny('at least 2 subtasks required', 400)
        if len(subtasks) > 20:
            return _deny('max 20 subtasks', 400)
        import database_tipsandtricks as db_tt
        result = await db_tt.create_super_task(parent_desc, subtasks, _user_id(req) or 0)
        from tasks.tipsandtricks import push_leaderboard
        asyncio.create_task(push_leaderboard(self.bot))
        return _ok({'parent_task_id': result['parent_task_id'], 'subtask_ids': result['subtask_ids'], 'completion_bonus': result['completion_bonus']})

    async def _tt_complete_task(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_tt(roles):
            return _deny()
        body = await req.json()
        task_id    = body.get('task_id')
        for_user   = body.get('user_id')
        if not task_id or not for_user:
            return _deny('task_id and user_id required', 400)
        import database_tipsandtricks as db_tt
        pts = await db_tt.admin_complete_task(int(task_id), int(for_user), bot=self.bot)
        if pts is None:
            return _deny('task not found or already completed', 404)
        from tasks.tipsandtricks import push_leaderboard
        asyncio.create_task(push_leaderboard(self.bot))
        return _ok({'task_id': task_id, 'points_awarded': pts, 'user': await self._member_info(int(for_user))})

    async def _tt_cancel_task(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_tt(roles):
            return _deny()
        body = await req.json()
        task_id = body.get('task_id')
        if task_id is None or str(task_id).strip() == '':
            return _deny('task_id required', 400)
        try:
            task_id_int = int(task_id)
        except (TypeError, ValueError):
            return _deny('invalid task_id', 400)
        import database_tipsandtricks as db_tt
        success = await db_tt.delete_task(task_id_int)
        if not success:
            return _deny('task not found', 404)
        from tasks.tipsandtricks import push_leaderboard
        asyncio.create_task(push_leaderboard(self.bot))
        return _ok({'task_id': task_id_int, 'status': 'deleted'})

    async def _tt_assign_duty(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_tt(roles):
            return _deny()
        body = await req.json()
        code = (body.get('code') or '').strip()
        uid  = body.get('user_id')
        if not code or not uid:
            return _deny('code and user_id required', 400)
        import database_tipsandtricks as db_tt
        await db_tt.assign_duty(code, int(uid), _user_id(req) or 0)
        from tasks.tipsandtricks import push_leaderboard
        asyncio.create_task(push_leaderboard(self.bot))
        return _ok({'code': code, 'user': await self._member_info(int(uid))})

    async def _tt_remove_duty(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_tt(roles):
            return _deny()
        body = await req.json()
        code = (body.get('code') or '').strip()
        uid_str = body.get('user_id')
        uid = int(uid_str) if uid_str else None
        
        if not code:
            return _deny('code required', 400)
        import database_tipsandtricks as db_tt
        if not await db_tt.remove_duty(code, uid):
            return _deny('assignment not found', 404)
        from tasks.tipsandtricks import push_leaderboard
        asyncio.create_task(push_leaderboard(self.bot))
        return web.json_response({"ok": True})

    # ══════════════════════════════════════════════════════════════════════════
    # GENERAL STAFF (away management — Head Staff + Management)
    # ══════════════════════════════════════════════════════════════════════════

    def _general_staff_role_names(self) -> list:
        """General-staff role names from config.json (default Trial Staff/Staff)."""
        try:
            import json as _json, os as _os
            if _os.path.exists('config.json'):
                with open('config.json', 'r', encoding='utf-8') as f:
                    cfg = _json.load(f)
                names = cfg.get('staff_roles_config', {}).get('general_staff')
                if names:
                    return names
        except Exception:
            pass
        return ['Trial Staff', 'Staff']

    def _general_staff_members(self) -> dict:
        """{user_id: {member, role_name}} for everyone holding a general-staff role
        across all of the bot's guilds (deduped, bots excluded)."""
        want = {n.lower() for n in self._general_staff_role_names()}
        found = {}
        for guild in self.bot.guilds:
            for role in guild.roles:
                if role.name.lower() in want:
                    for m in role.members:
                        if not m.bot and m.id not in found:
                            found[m.id] = {'member': m, 'role_name': role.name}
        return found

    async def _staff_data(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_staff(roles):
            return _deny()
        from database import get_all_staff_away_return_dates

        away_list = await get_all_staff_away_return_dates()
        away_map  = {str(a['user_id']): {'return_date': a.get('return_date'), 'set_at': a.get('set_at')} for a in away_list}

        members = self._general_staff_members()
        staff = []
        for uid, info in members.items():
            m = info['member']
            uid_s = str(uid)
            has_away_role = any(r.id == GENERAL_AWAY_ROLE_ID for r in m.roles)
            is_away = has_away_role or uid_s in away_map
            away_info = away_map.get(uid_s, {})

            staff.append({
                'user_id': uid_s,
                'display_name': m.display_name,
                'avatar_url': web_avatar_url(m.display_avatar),
                'role_name': info['role_name'],
                'is_away': is_away,
                'away_return': away_info.get('return_date'),
            })
        staff.sort(key=lambda x: (not x['is_away'], x['display_name'].lower()))
        return web.json_response({'staff': staff})

    async def _apply_away_role(self, user_id: int, add: bool):
        """Add/remove the general away role wherever it exists across guilds."""
        for guild in self.bot.guilds:
            role = guild.get_role(GENERAL_AWAY_ROLE_ID)
            if not role:
                continue
            m = guild.get_member(user_id)
            if not m:
                continue
            try:
                if add and role not in m.roles:
                    await m.add_roles(role, reason="Staff away (admin panel)")
                elif not add and role in m.roles:
                    await m.remove_roles(role, reason="Staff back (admin panel)")
            except Exception:
                pass

    async def _staff_set_away(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_staff(roles):
            return _deny()
        body = await req.json()
        uid = body.get('user_id')
        if not uid:
            return _deny('missing user_id', 400)
        uid = int(uid)
        await self._apply_away_role(uid, add=True)
        from database import set_staff_away_return_date
        if body.get('return_date'):
            await set_staff_away_return_date(uid, body.get('return_date'))
        return _ok({'user': await self._member_info(uid), 'return_date': body.get('return_date')})

    async def _staff_remove_away(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_staff(roles):
            return _deny()
        body = await req.json()
        uid = body.get('user_id')
        if not uid:
            return _deny('missing user_id', 400)
        uid = int(uid)
        await self._apply_away_role(uid, add=False)
        from database import delete_staff_away_return_date
        await delete_staff_away_return_date(uid)
        return _ok({'user': await self._member_info(uid)})

    class _DummyMessage:
        async def edit(self, *args, **kwargs): pass
        async def delete(self): pass

    class _DummyCtx:
        def __init__(self, bot):
            self.bot = bot
            self.guild = bot.get_guild(STAFF_HUB_GUILD_ID)
            self.author = bot.user
        async def send(self, *args, **kwargs):
            return BotAdminAPI._DummyMessage()

    async def _staff_assign(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_staff(roles):
            return _deny()
        body = await req.json()
        duty = body.get('duty')
        uid = body.get('user_id')
        if not duty or not uid:
            return _deny('duty and user_id required', 400)
        
        uid = int(uid)
        ctx = self._DummyCtx(self.bot)
        
        # Helper to find member across guilds
        m = None
        for guild in self.bot.guilds:
            m = guild.get_member(uid)
            if m: break
            
        if not m:
            return _deny('User not found in any guild', 404)

        try:
            if duty == 'add_loot':
                cog = self.bot.get_cog('LootRouteCommands')
                if cog:
                    await cog.add_loot_route_maker.callback(cog, ctx, user=m)
            elif duty == 'add_surge':
                cog = self.bot.get_cog('SurgeRouteCommands')
                if cog:
                    await cog.add_surge_route_maker.callback(cog, ctx, user=m)
            elif duty == 'add_tips':
                cog = self.bot.get_cog('TipsAndTricksCog')
                if cog:
                    await cog.add_tips_helper.callback(cog, ctx, user=m) # signature might require user=m or user_input=str(m.id)
            elif duty == 'add_map':
                assigned = []
                for guild in self.bot.guilds:
                    role = discord.utils.find(lambda r: r.name.lower() == 'map request helper', guild.roles)
                    if role:
                        guild_member = guild.get_member(m.id)
                        if guild_member:
                            try:
                                await guild_member.add_roles(role)
                                assigned.append(guild.name)
                            except Exception as role_err:
                                from core.global_logger import log_event
                                log_event("Map Role Assign Error", f"Failed to assign map request helper in {guild.name} to {uid}: {role_err}", color=0xFF0000)
                if not assigned:
                    return _deny('Could not assign map request helper role in any guild', 500)
        except Exception as e:
            from core.global_logger import log_event
            log_event("Staff Assign Error", f"Failed to assign duty {duty} to {uid}: {e}", color=0xFF0000)
            return _deny(str(e), 500)

        return _ok({'duty': duty, 'user': await self._member_info(uid)})

    async def _staff_train(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_staff(roles):
            return _deny()
        body = await req.json()
        duty = body.get('duty')
        uid = body.get('user_id')
        if not duty or not uid:
            return _deny('duty and user_id required', 400)
            
        uid = int(uid)

        # Find the member across guilds
        member = None
        for guild in self.bot.guilds:
            member = guild.get_member(uid)
            if member:
                break

        # Send DM to the trainee
        if member:
            invite_links = {
                'train_surge': 'https://discord.gg/pEPJt9braz',
                'train_tips':  'https://discord.gg/Rq44NtnqDU',
                'train_map':   'https://discord.gg/JrQAxkFyCM',
                'train_loot':  'https://discord.gg/8KZ7WSxAXC',
            }
            duty_labels = {
                'train_surge': 'Surge Routes',
                'train_tips':  'Tips & Tricks',
                'train_map':   'Map Request',
                'train_loot':  'Loot Routes',
            }
            invite_link = invite_links.get(duty)
            duty_label = duty_labels.get(duty, duty)
            try:
                if invite_link:
                    msg = (
                        f"\U0001f44b Hey! You've been selected for training in **{duty_label}**.\n\n"
                        f"Please join our training server so a Head of Staff can guide you through your duties:\n"
                        f"\U0001f517 {invite_link}\n\n"
                        f"See you there!"
                    )
                else:
                    msg = (
                        f"\U0001f44b Hey! You've been selected for training in **{duty_label}**.\n\n"
                        f"A Head of Staff will guide you through your duties shortly."
                    )
                await member.send(msg)
            except Exception as dm_err:
                from core.global_logger import log_event
                log_event("Training DM Error", f"Failed to DM {uid} for training {duty}: {dm_err}", color=0xFF0000)

        from core.global_logger import log_event
        log_event(
            "User Training Assigned",
            f"User <@{uid}> has been assigned to training for: **{duty}** via the Admin Panel.",
            color=0x3498DB
        )
        
        return _ok({'duty': duty, 'user': await self._member_info(uid)})

    # Role promotion ladder (Support → Senior Support → Admin → Senior Admin → Head Admin)
    _PROMOTION_LADDER = [
        'Support',
        'Senior Support',
        'Admin',
        'Senior Admin',
        'Head Admin',
    ]

    async def _staff_promote(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_staff(roles):
            return _deny()
        body = await req.json()
        uid = body.get('user_id')
        if not uid:
            return _deny('user_id required', 400)
        uid = int(uid)

        ladder = self._PROMOTION_LADDER
        ladder_lower = [r.lower() for r in ladder]

        results = {}
        for guild in self.bot.guilds:
            member = guild.get_member(uid)
            if not member:
                results[guild.name] = 'not in guild'
                continue

            member_role_names_lower = [r.name.lower() for r in member.roles]

            # Find highest ladder role the member currently has
            current_idx = -1
            for i, rname in enumerate(ladder_lower):
                if rname in member_role_names_lower:
                    current_idx = i

            if current_idx == -1:
                results[guild.name] = 'no ladder role found'
                continue
            if current_idx >= len(ladder) - 1:
                results[guild.name] = 'already at top of ladder'
                continue

            # All ladder roles up to and including the new rank that the member is missing
            new_idx = current_idx + 1
            roles_to_add = []
            for i in range(new_idx + 1):
                if ladder_lower[i] not in member_role_names_lower:
                    r = discord.utils.find(lambda r, n=ladder[i]: r.name.lower() == n.lower(), guild.roles)
                    if r:
                        roles_to_add.append(r)

            if not roles_to_add:
                results[guild.name] = f'role "{ladder[new_idx]}" not found in guild'
                continue

            try:
                await member.add_roles(*roles_to_add, reason='Admin panel promotion')
                added_names = [r.name for r in roles_to_add]
                results[guild.name] = f'promoted to {ladder[new_idx]} (added: {", ".join(added_names)})'
            except Exception as e:
                results[guild.name] = f'error: {e}'

        from core.global_logger import log_event
        log_event("Staff Promote", f"User {uid} promoted via admin panel. Results: {results}", color=0x00FF88)

        successes = [g for g, v in results.items() if v.startswith('promoted')]
        if not successes:
            return _deny('Could not promote in any guild: ' + str(results), 500)

        return _ok({'user_id': uid, 'results': results, 'user': await self._member_info(uid)})


    # ══════════════════════════════════════════════════════════════════════════
    # PREDICTIONS  (member voting + Management admin — single `main` wallet)
    # ══════════════════════════════════════════════════════════════════════════

    async def _pred_data(self, req: web.Request):
        """Live predictions for the Events tab. Any logged-in staff can read."""
        import database
        uid = _user_id(req)
        roles = _user_roles(req)
        preds = await database.get_recent_predictions_db(limit=30)
        out = []
        for p in preds:
            summary = await database.get_vote_summary_db(p['id'])
            votes = await database.get_votes_db(p['id'])
            mine = votes.get(uid) if uid else None
            out.append({
                'id': p['id'], 'title': p['title'], 'description': p['description'],
                'end_date': p['end_date'], 'status': p['status'],
                'outcomes': p['outcomes'], 'result': p['result'],
                'pool': summary.get('total_pool', 0),
                'summary': summary.get('outcomes', {}),
                'your_bet': ({'choice': mine['choice'], 'amount': mine['amount']} if mine else None),
            })
        from tasks.wave_points import get_wave_points as _get_wp
        balance = await _get_wp(uid) if uid else 0
        return web.json_response({
            'predictions': out,
            'your_available': balance,  # no WP reservation system; available = total balance
            'your_balance': balance,
            'is_management': _has_management(roles),
        })

    async def _pred_vote(self, req: web.Request):
        """Place/raise a bet — any logged-in staff."""
        from tasks import predictions_engine as eng
        uid = _user_id(req)
        if not uid:
            return _deny('not signed in', 401)
        body = await req.json()
        try:
            pid = int(body.get('prediction_id'))
            amount = int(body.get('amount'))
        except (TypeError, ValueError):
            return _deny('prediction_id and amount required', 400)
        choice = (body.get('choice') or '').strip()
        if not choice:
            return _deny('choice required', 400)
        result = await eng.place_web_vote(self.bot, pid, uid, choice, amount)
        return web.json_response(result, status=200 if result.get('success') else 400)

    async def _pred_create(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_management(roles):
            return _deny()
        import database
        body = await req.json()
        title = (body.get('title') or '').strip()
        description = (body.get('description') or '').strip()
        end_date = (body.get('end_date') or '').strip()
        outcomes = [o.strip() for o in (body.get('outcomes') or []) if o and o.strip()]
        if not title or len(outcomes) < 2:
            return _deny('title and at least 2 outcomes required', 400)
        pid = await database.create_prediction_db(_user_id(req) or 0, title, description, end_date, outcomes)
        return _ok({'prediction_id': pid})

    async def _pred_resolve(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_management(roles):
            return _deny()
        from tasks import predictions_engine as eng
        body = await req.json()
        try:
            pid = int(body.get('prediction_id'))
        except (TypeError, ValueError):
            return _deny('prediction_id required', 400)
        winning = (body.get('winning_choice') or '').strip()
        if not winning:
            return _deny('winning_choice required', 400)
        result = await eng.resolve_prediction(self.bot, pid, winning)
        return web.json_response(result, status=200 if result.get('success') else 400)

    async def _pred_cancel(self, req: web.Request):
        roles = _user_roles(req)
        if not _has_management(roles):
            return _deny()
        from tasks import predictions_engine as eng
        body = await req.json()
        try:
            pid = int(body.get('prediction_id'))
        except (TypeError, ValueError):
            return _deny('prediction_id required', 400)
        result = await eng.cancel_prediction(self.bot, pid)
        return web.json_response(result, status=200 if result.get('success') else 400)

    # ── Profile card customization (owner-only, persisted) ────────────────────

    async def _profile_custom_get(self, req: web.Request):
        """Public-read: anyone signed in can fetch a profile's saved card theme.
        Returns is_owner so the page only shows edit controls to the owner."""
        import json as _json
        import database
        pid = (req.rel_url.query.get('id') or '').strip()
        if not pid.isdigit():
            return _deny('id required', 400)
        raw = await database.get_profile_customization(pid)
        try:
            settings = _json.loads(raw)
            if not isinstance(settings, dict):
                settings = {}
        except Exception:
            settings = {}
        uid = _user_id(req)
        return web.json_response({'settings': settings,
                                  'is_owner': uid is not None and str(uid) == pid})

    async def _profile_custom_set(self, req: web.Request):
        """Owner-only write. The owner is ALWAYS the verified X-Wave-User-Id —
        never an id from the body — so a user can only ever edit their own card."""
        import json as _json
        import database
        uid = _user_id(req)
        if not uid:
            return _deny('not signed in', 401)
        try:
            body = await req.json()
        except Exception:
            return _deny('invalid body', 400)
        settings = body.get('settings')
        if not isinstance(settings, dict):
            return _deny('settings object required', 400)
        allowed = {'color', 'bg', 'crt', 'glitch'}
        clean = {}
        for cid, prefs in list(settings.items())[:24]:
            if not isinstance(cid, str) or len(cid) > 32 or not isinstance(prefs, dict):
                continue
            entry = {}
            for k, v in prefs.items():
                if k not in allowed:
                    continue
                if k in ('crt', 'glitch'):
                    entry[k] = bool(v)
                elif isinstance(v, str) and len(v) <= 512:
                    entry[k] = v
            clean[cid] = entry
        raw = _json.dumps(clean)
        if len(raw) > 8000:
            return _deny('payload too large', 413)
        await database.set_profile_customization(uid, raw)
        return _ok({'saved': True})


    async def _profile_custom_upload(self, req: web.Request):
        """Owner-only: Upload a custom banner image to the local filesystem."""
        import os
        import time
        from pathlib import Path
        uid = _user_id(req)
        if not uid:
            return _deny('not signed in', 401)
            
        try:
            reader = await req.multipart()
            field = await reader.next()
            if not field or field.name != 'file':
                return _deny('missing file field', 400)
                
            filename = field.filename
            if not filename:
                return _deny('missing filename', 400)
                
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ('.png', '.jpg', '.jpeg', '.webp'):
                return _deny('invalid file type', 400)
                
            # Create uploads directory if it doesn't exist
            uploads_dir = Path(__file__).parent.parent / "website" / "assets" / "uploads"
            os.makedirs(uploads_dir, exist_ok=True)
            
            # Generate unique filename using uid and timestamp
            safe_name = f"{uid}_{int(time.time())}{ext}"
            filepath = uploads_dir / safe_name
            
            size = 0
            with open(filepath, 'wb') as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 2 * 1024 * 1024: # 2MB limit
                        os.remove(filepath)
                        return _deny('file too large (max 2MB)', 413)
                    f.write(chunk)
                    
            return _ok({'url': f'/assets/uploads/{safe_name}'})
        except Exception as e:
            return _deny(f'upload failed: {str(e)}', 500)


    async def _profile_uploads_list(self, req: web.Request):
        """Return all past banner uploads for the requesting user."""
        uid = _user_id(req)
        if not uid:
            return _deny('not signed in', 401)
        uploads_dir = Path(__file__).parent.parent / "website" / "assets" / "uploads"
        urls = []
        if uploads_dir.exists():
            for f in sorted(uploads_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if f.name.startswith(f"{uid}_") and f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                    urls.append(f'/assets/uploads/{f.name}')
        return _ok({'urls': urls})

    async def _profile_upload_delete(self, req: web.Request):
        """Delete a specific uploaded banner belonging to the requesting user."""
        uid = _user_id(req)
        if not uid:
            return _deny('not signed in', 401)
        filename = req.rel_url.query.get('file', '')
        if not filename:
            return _deny('missing file param', 400)
        from pathlib import Path as _Path
        # Safety: must start with uid_ and have a safe extension, no path traversal
        if '/' in filename or '\\' in filename or not filename.startswith(f"{uid}_"):
            return _deny('forbidden', 403)
        uploads_dir = _Path(__file__).parent.parent / "website" / "assets" / "uploads"
        target = uploads_dir / filename
        if not target.exists():
            return _deny('not found', 404)
        target.unlink()
        return _ok({'deleted': filename})

    async def _user_role_names(self, req: web.Request):
        """Return the role names for the requesting user from the Staff Hub guild cache."""
        uid = _user_id(req)
        if not uid:
            return web.json_response({'role_names': []})
        guild = self.bot.get_guild(STAFF_HUB_GUILD_ID)
        if not guild:
            return web.json_response({'role_names': []})
        member = guild.get_member(uid)
        if not member:
            return web.json_response({'role_names': []})
        names = [r.name for r in member.roles if r.name != '@everyone']
        return web.json_response({'role_names': names})


async def setup(bot):
    await bot.add_cog(BotAdminAPI(bot))
