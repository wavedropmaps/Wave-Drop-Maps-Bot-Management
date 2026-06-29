"""Multi-Guild Role Sync Commands.

Interactive wizard commands to add or remove a role across all 3 servers.

Commands:
    >dutyrolegive     -> add a duty role (allowlisted) in all 3 guilds
    >dutyroleremove   -> remove a duty role in all 3 guilds
    >staffrolegive    -> add a staff role (allowlisted) in all 3 guilds
    >staffroleremove  -> remove a staff role in all 3 guilds

Permission gates:
    Duty commands  -> Administrator perm OR a role named "Head Admin"
    Staff commands -> Administrator perm only

Allowlists are enforced per command: >dutyrolegive cannot grant a staff role
and vice versa. Roles are matched by case-insensitive name across guilds
(role IDs differ per server).
"""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import discord
from discord.ext import commands


# ==================== CONFIGURATION ====================

GUILD_IDS = [
    988564962802810961,
    1041450125391835186,
    971731167621574666,
]

DUTY_ROLES = [
    "Drop Map Tester",
    "Drop Map Maker",
    "Promoters",
    "Loot Route Maker",
    "Tips and Tricks Helper",
    "Surge Route Maker",
    "Role Giver",
    "Map Request Helper",
]

STAFF_ROLES = [
    "Management",
    "Head Admin",
    "Senior Admin",
    "Admin",
    "Senior Support",
    "Support",
    "Staff",
    "Trial Staff",
]

HEAD_ADMIN_ROLE_NAME = "Head Admin"
WIZARD_TIMEOUT = 60
MAX_INVALID_RETRIES = 3
MAX_USERS_PER_WIZARD = 25
COMPACT_RESULTS_THRESHOLD = 6  # show compact summary if more than this many users

# Rate limit: Head Admin role users (without Admin perm) get 1 use per command per 24h
RATE_LIMIT_HOURS = 24
RATE_LIMIT_FILE_NAME = "head_admin_role_sync_rate_limit.json"

ACTION_ADD = "add"
ACTION_REMOVE = "remove"

SPECIALTY_LOOT_ROUTE_MAKER = "Loot Route Maker"
SPECIALTY_SURGE_ROUTE_MAKER = "Surge Route Maker"
SPECIALTY_TT_HELPER = "Tips and Tricks Helper"
SPECIALTY_ROLES = {SPECIALTY_LOOT_ROUTE_MAKER, SPECIALTY_SURGE_ROUTE_MAKER, SPECIALTY_TT_HELPER}

LOOT_ROUTE_COG_NAME = "LootRouteCommands"
LOOT_ROUTE_ADD_CMD = "addlootroutemaker"
LOOT_ROUTE_REMOVE_CMD = "removelootroutemaker"

TT_COG_NAME = "TipsAndTricksCog"
TT_ADD_CMD = "addtipshelper"
TT_REMOVE_CMD = "removetipshelper"

SURGE_ROUTE_COG_NAME = "SurgeRouteCommands"
SURGE_ROUTE_ADD_CMD = "addsurgeroutemaker"
SURGE_ROUTE_REMOVE_CMD = "removesurgeroutemaker"

TT_COG_NAME = "TipsAndTricksCog"
TT_ADD_CMD = "addtipshelper"
TT_REMOVE_CMD = "removetipshelper"

COLOR_PROMPT = 0x3498DB
COLOR_PROMPT_REMOVE = 0xE67E22
COLOR_ERROR = 0xE74C3C
COLOR_WORKING = 0xF1C40F
COLOR_SUCCESS = 0x2ECC71
COLOR_PARTIAL = 0xF1C40F
COLOR_FAIL = 0xE74C3C
COLOR_CANCELLED = 0x95A5A6


# ==================== HELPERS ====================

def _has_admin(member: discord.Member) -> bool:
    return bool(member.guild_permissions.administrator)


def _has_head_admin_role(member: discord.Member) -> bool:
    target = HEAD_ADMIN_ROLE_NAME.lower()
    return any(r.name.lower() == target for r in member.roles)


def _find_role_in_guild(guild: discord.Guild, role_name: str) -> Optional[discord.Role]:
    target = role_name.lower()
    for r in guild.roles:
        if r.name.lower() == target:
            return r
    return None


def _is_skippable_status(status: str) -> bool:
    """Return True if a per-guild status represents 'no action possible here' rather than a failure.

    Skippable cases are guild-level no-ops we shouldn't count against success:
      - Role missing from this guild      (guild-specific role)
      - User isn't a member of this guild
      - Bot isn't a member of this guild

    Recognized by either the older ⚠️ wording or the newer ℹ️ "— skipped" wording.
    Everything else (Missing perms, top role conflict, restricted, API errors, etc.)
    is still treated as a real outcome (good or bad).
    """
    s = str(status)
    # Role doesn't exist in this guild (old: "Role 'X' not found", new: "Role 'X' doesn't exist here")
    if "Role '" in s and ("not found" in s or "doesn't exist here" in s):
        return True
    if "User not in this server" in s:
        return True
    if "Bot not in this server" in s:
        return True
    return False


def _canonicalize_role(name: str, allowed: list) -> Optional[str]:
    target = name.strip().lower()
    for canonical in allowed:
        if canonical.lower() == target:
            return canonical
    return None


def _parse_user_ids(text: str) -> tuple:
    """Split text on whitespace/commas/newlines, return (valid_int_ids, invalid_tokens, deduped).

    Returns:
        valid: list[int] of digit-only tokens parsed to int, in order, deduped
        invalid: list[str] of tokens that weren't all digits
        had_duplicates: bool — True if duplicates were removed
    """
    import re
    raw_tokens = [t for t in re.split(r"[\s,]+", text.strip()) if t]
    valid_ordered = []
    invalid = []
    seen = set()
    had_duplicates = False
    for tok in raw_tokens:
        if tok.isdigit():
            id_int = int(tok)
            if id_int in seen:
                had_duplicates = True
                continue
            seen.add(id_int)
            valid_ordered.append(id_int)
        else:
            invalid.append(tok)
    return valid_ordered, invalid, had_duplicates


# ==================== RATE LIMIT (Head Admin: 1 per command per 24h, persistent) ====================

def _rate_limit_file_path() -> str:
    """Absolute path to the rate-limit JSON file in workspace root/json_data/."""
    workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(workspace_root, 'json_data', RATE_LIMIT_FILE_NAME)


def _load_rate_limits() -> dict:
    """Load {command_name: {user_id_str: iso_timestamp}} from disk. Returns {} on error/missing."""
    path = _rate_limit_file_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data
    except Exception as e:
        print(f"[ROLE SYNC] ⚠️ Failed to load rate-limit file ({path}): {type(e).__name__}: {e}")
        return {}


def _save_rate_limits(data: dict) -> bool:
    """Save the rate-limit dict to disk. Returns True on success."""
    path = _rate_limit_file_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        return True
    except Exception as e:
        print(f"[ROLE SYNC] ⚠️ Failed to save rate-limit file ({path}): {type(e).__name__}: {e}")
        return False


def _check_rate_limit(user_id: int, cmd_name: str) -> Tuple[bool, Optional[datetime]]:
    """Returns (is_rate_limited, next_available_utc).

    is_rate_limited=True means the user has used this command within the last RATE_LIMIT_HOURS hours.
    next_available_utc is when the user can use this command again.
    """
    data = _load_rate_limits()
    cmd_data = data.get(cmd_name, {})
    last_use_str = cmd_data.get(str(user_id))
    if not last_use_str:
        return (False, None)
    try:
        last_use = datetime.fromisoformat(last_use_str)
        if last_use.tzinfo is None:
            last_use = last_use.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return (False, None)
    next_avail = last_use + timedelta(hours=RATE_LIMIT_HOURS)
    now = datetime.now(timezone.utc)
    if now >= next_avail:
        return (False, None)
    return (True, next_avail)


def _record_rate_limit_use(user_id: int, cmd_name: str) -> bool:
    """Record a use of `cmd_name` by `user_id` at the current UTC time. Returns True on save success."""
    data = _load_rate_limits()
    if cmd_name not in data or not isinstance(data.get(cmd_name), dict):
        data[cmd_name] = {}
    data[cmd_name][str(user_id)] = datetime.now(timezone.utc).isoformat()
    return _save_rate_limits(data)


# ==================== CONFIRM VIEW ====================

class ConfirmView(discord.ui.View):
    """Submit/Cancel buttons locked to the wizard's author."""

    def __init__(self, author_id: int, timeout: float = WIZARD_TIMEOUT):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the staff member who started this wizard can use these buttons.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Submit", style=discord.ButtonStyle.success, emoji="✅")
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass


# ==================== COG ====================

class MultiGuildRoleCommands(commands.Cog):
    """Wizard-style commands for syncing roles across all 3 guilds."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- Permission gates ----------

    def _check_duty_gate(self, ctx: commands.Context) -> bool:
        author = ctx.author
        if not isinstance(author, discord.Member):
            return False
        return _has_admin(author) or _has_head_admin_role(author)

    def _check_staff_gate(self, ctx: commands.Context) -> bool:
        author = ctx.author
        if not isinstance(author, discord.Member):
            return False
        return _has_admin(author)

    # ---------- Commands ----------

    async def _enforce_rate_limit_if_head_admin(self, ctx: commands.Context, cmd_name: str) -> bool:
        """If user is Head Admin but NOT Admin, enforce 24h rate limit. Returns True if allowed to proceed."""
        if _has_admin(ctx.author):
            return True  # Admins are unrestricted
        is_limited, next_avail = _check_rate_limit(ctx.author.id, cmd_name)
        if not is_limited:
            return True
        # Build a friendly rejection message
        ts = int(next_avail.timestamp())
        now = datetime.now(timezone.utc)
        wait = next_avail - now
        hours, rem = divmod(int(wait.total_seconds()), 3600)
        minutes = rem // 60
        await ctx.reply(
            f"⏱️ **Rate limited.** Head Admin role holders can use `>{cmd_name}` "
            f"**once per {RATE_LIMIT_HOURS} hours**.\n"
            f"Next available: <t:{ts}:f> (<t:{ts}:R>)\n"
            f"Time remaining: **{hours}h {minutes}m**\n\n"
            f"*Note: Administrators are not rate-limited. Each duty command has its own 24h "
            f"cooldown, so if you've used `>dutyrolegive` recently you can still use "
            f"`>dutyroleremove` (and vice versa).*"
        )
        return False

    @commands.command(name="dutyrolegive")
    @commands.guild_only()
    async def duty_role_give(self, ctx: commands.Context):
        if not self._check_duty_gate(ctx):
            await ctx.reply(
                "❌ You need **Administrator** permission or the **Head Admin** role to use this command."
            )
            return
        if not await self._enforce_rate_limit_if_head_admin(ctx, "dutyrolegive"):
            return
        await self._run_wizard(ctx, ACTION_ADD, DUTY_ROLES, "Duty Role", "dutyrolegive")

    @commands.command(name="dutyroleremove")
    @commands.guild_only()
    async def duty_role_remove(self, ctx: commands.Context):
        if not self._check_duty_gate(ctx):
            await ctx.reply(
                "❌ You need **Administrator** permission or the **Head Admin** role to use this command."
            )
            return
        if not await self._enforce_rate_limit_if_head_admin(ctx, "dutyroleremove"):
            return
        await self._run_wizard(ctx, ACTION_REMOVE, DUTY_ROLES, "Duty Role", "dutyroleremove")

    @commands.command(name="staffrolegive")
    @commands.guild_only()
    async def staff_role_give(self, ctx: commands.Context):
        if not self._check_staff_gate(ctx):
            await ctx.reply("❌ You need **Administrator** permission to use this command.")
            return
        await self._run_wizard(ctx, ACTION_ADD, STAFF_ROLES, "Staff Role", "staffrolegive")

    @commands.command(name="staffroleremove")
    @commands.guild_only()
    async def staff_role_remove(self, ctx: commands.Context):
        if not self._check_staff_gate(ctx):
            await ctx.reply("❌ You need **Administrator** permission to use this command.")
            return
        await self._run_wizard(ctx, ACTION_REMOVE, STAFF_ROLES, "Staff Role", "staffroleremove")

    # ---------- Wizard core ----------

    async def _run_wizard(
        self,
        ctx: commands.Context,
        action: str,
        allowed_roles: list,
        label: str,
        cmd_name: str,
    ):
        action_verb = "GIVE" if action == ACTION_ADD else "REMOVE"
        action_word = "give" if action == ACTION_ADD else "remove"
        preposition = "to" if action == ACTION_ADD else "from"
        accent = COLOR_PROMPT if action == ACTION_ADD else COLOR_PROMPT_REMOVE

        # ----- Step 1: ask for user IDs (1 or many) -----
        step1_embed = discord.Embed(
            title=f"🟦 {label} Sync — Step 1 of 3",
            description=(
                f"Send **one or more user IDs** of the people you want to {action_word} the role {preposition}.\n\n"
                f"**Accepted separators:** spaces, commas, or newlines.\n"
                f"**Examples:**\n"
                f"• `123456789012345678`\n"
                f"• `123456 789012 345678`\n"
                f"• `123, 456, 789`\n\n"
                f"**Max {MAX_USERS_PER_WIZARD} users per run.** Duplicates auto-removed.\n\n"
                f"⏳ Waiting... ({WIZARD_TIMEOUT}s timeout · type `cancel` to abort)"
            ),
            color=accent,
        )
        wizard_msg = await ctx.reply(embed=step1_embed)

        target_user_ids = await self._prompt_user_ids(ctx, wizard_msg, step1_embed)
        if target_user_ids is None:
            return

        target_display = self._format_user_list(target_user_ids, limit=10)

        # ----- Step 2: ask for role name -----
        role_list = "\n".join(f"• {r}" for r in allowed_roles)
        step2_embed = discord.Embed(
            title=f"🟦 {label} Sync — Step 2 of 3",
            description=(
                f"**Target:** {target_display}\n\n"
                f"Type the name of the role to **{action_word}**:\n{role_list}\n\n"
                f"⏳ Waiting... ({WIZARD_TIMEOUT}s timeout · type `cancel` to abort)"
            ),
            color=accent,
        )
        await wizard_msg.edit(embed=step2_embed)

        role_name = await self._prompt_role_name(ctx, wizard_msg, step2_embed, allowed_roles)
        if role_name is None:
            return

        # ----- Step 3: confirm -----
        is_specialty = role_name in SPECIALTY_ROLES
        specialty_note = self._build_specialty_note(role_name, action) if is_specialty else ""
        user_count = len(target_user_ids)
        targets_label = f"**Targets ({user_count}):**" if user_count > 1 else "**Target:**"

        # Time estimate warning for LR Maker × multi
        time_warning = ""
        if role_name == SPECIALTY_LOOT_ROUTE_MAKER and user_count > 1:
            est_seconds = user_count * 15
            est_minutes = est_seconds // 60
            est_secs_rem = est_seconds % 60
            time_str = (
                f"~{est_minutes}m {est_secs_rem}s" if est_minutes
                else f"~{est_seconds}s"
            )
            time_warning = (
                f"\n⏱️ **Time estimate:** {time_str} ({user_count} × ~15s per user). "
                f"Wizard message will show live progress.\n"
            )

        # Pre-flight role availability check — show which of the 3 guilds actually has this role.
        # Skipped for specialty roles since they have their own multi-step handling.
        availability_note = ""
        if not is_specialty:
            availability_note = self._build_role_availability_note(role_name)

        step3_embed = discord.Embed(
            title=f"🟦 {label} Sync — Step 3 of 3 (Confirm)",
            description=(
                f"{targets_label} {target_display}\n"
                f"**Role:** {role_name}\n"
                f"**Action:** {action_verb} in all 3 servers\n"
                f"{availability_note}"
                f"{specialty_note}"
                f"{time_warning}\n"
                f"Click **Submit** to apply, or **Cancel** to abort.\n"
                f"⏳ ({WIZARD_TIMEOUT}s timeout)"
            ),
            color=accent,
        )
        view = ConfirmView(author_id=ctx.author.id, timeout=WIZARD_TIMEOUT)
        await wizard_msg.edit(embed=step3_embed, view=view)

        await view.wait()

        if view.value is None:
            await self._edit_cancelled(wizard_msg, "⏱️ Cancelled — timed out waiting for confirmation.")
            return
        if view.value is False:
            await self._edit_cancelled(wizard_msg, f"❌ Cancelled by {ctx.author.mention}.")
            return

        # ----- Step 4: apply (loop over user list) -----
        per_user_results = {}  # {user_id: per-guild dict OR raw specialty dict OR sentinel}
        total = len(target_user_ids)

        for idx, uid in enumerate(target_user_ids, start=1):
            # Live progress update
            if total > 1:
                progress_embed = discord.Embed(
                    title=f"⏳ {label} Sync — Applying ({idx}/{total})...",
                    description=(
                        f"{targets_label} {target_display}\n"
                        f"**Role:** {role_name}\n"
                        f"**Action:** {action_verb}\n\n"
                        f"Processing user `{uid}` ({idx}/{total})..."
                    ),
                    color=COLOR_WORKING,
                )
                try:
                    await wizard_msg.edit(embed=progress_embed, view=None)
                except discord.HTTPException as e:
                    print(f"[ROLE SYNC] ⚠️ Failed to edit progress embed (uid={uid}, idx={idx}/{total}): {type(e).__name__}: {e}")
            else:
                if role_name == SPECIALTY_LOOT_ROUTE_MAKER:
                    working_desc = (
                        f"Triggering `>{LOOT_ROUTE_ADD_CMD if action == ACTION_ADD else LOOT_ROUTE_REMOVE_CMD}` "
                        "— full DB + rotation + leaderboard sync (~15s)..."
                    )
                elif role_name == SPECIALTY_TT_HELPER:
                    working_desc = (
                        f"Triggering `>{TT_ADD_CMD if action == ACTION_ADD else TT_REMOVE_CMD}` "
                        "— role sync across all 3 servers + announcement..."
                    )
                else:
                    working_desc = "Working across all 3 servers..."
                working_embed = discord.Embed(
                    title=f"⏳ {label} Sync — Applying...",
                    description=(
                        f"**Target:** {target_display}\n"
                        f"**Role:** {role_name}\n"
                        f"**Action:** {action_verb}\n\n"
                        f"{working_desc}"
                    ),
                    color=COLOR_WORKING,
                )
                try:
                    await wizard_msg.edit(embed=working_embed, view=None)
                except discord.HTTPException as e:
                    print(f"[ROLE SYNC] ⚠️ Failed to edit working embed: {type(e).__name__}: {e}")

            # Dispatch per user — wrapped so a single failure can't crash the loop
            try:
                if role_name == SPECIALTY_LOOT_ROUTE_MAKER:
                    per_user_results[uid] = await self._handle_specialty_loot_route_maker_raw(
                        ctx=ctx, action=action, user_id=uid, executor=ctx.author,
                    )
                elif role_name == SPECIALTY_SURGE_ROUTE_MAKER:
                    per_user_results[uid] = await self._handle_specialty_surge_route_maker_raw(
                        ctx=ctx, action=action, user_id=uid, executor=ctx.author,
                    )
                elif role_name == SPECIALTY_TT_HELPER:
                    per_user_results[uid] = await self._handle_specialty_tt_helper_raw(
                        ctx=ctx, action=action, user_id=uid, executor=ctx.author,
                    )
                else:
                    per_user_results[uid] = await self._apply_role_change(
                        user_id=uid, role_name=role_name, action=action,
                        executor=ctx.author, cmd_name=cmd_name,
                    )
            except Exception as e:
                err_str = f"{type(e).__name__}: {str(e)[:200]}"
                print(f"[ROLE SYNC] ❌ Unhandled exception for user {uid}: {err_str}")
                import traceback
                traceback.print_exc()
                per_user_results[uid] = {gid: f"❌ Crashed: {err_str}" for gid in GUILD_IDS}

            # Small breath between users to avoid Discord global rate limits
            if total > 1 and idx < total:
                await asyncio.sleep(0.5)

        # ----- Step 5: build final embed -----
        try:
            final_embed = self._build_multi_results_embed(
                label=label,
                action_verb=action_verb,
                target_user_ids=target_user_ids,
                role_name=role_name,
                per_user_results=per_user_results,
                executor=ctx.author,
                cmd_name=cmd_name,
            )
        except Exception as e:
            err_str = f"{type(e).__name__}: {str(e)[:300]}"
            print(f"[ROLE SYNC] ❌ Failed to build final embed: {err_str}")
            import traceback
            traceback.print_exc()
            final_embed = discord.Embed(
                title=f"❌ {label} Sync — Results Embed Failed",
                description=(
                    f"The role changes were applied (see console log for per-user details), "
                    f"but the results embed could not be built.\n\n**Error:** `{err_str}`"
                ),
                color=COLOR_FAIL,
            )

        # Mark the wizard message as done with a small indicator (so it stops looking "stuck")
        done_indicator = discord.Embed(
            title=f"✅ {label} Sync Complete",
            description=(
                f"**Role:** {role_name}\n"
                f"**Action:** {action_verb}\n"
                f"**Users:** {len(target_user_ids)}\n\n"
                f"📋 **Full per-user results posted below ↓**"
            ),
            color=COLOR_SUCCESS,
        )
        edit_succeeded = False
        try:
            await wizard_msg.edit(embed=done_indicator, view=None)
            edit_succeeded = True
        except discord.HTTPException as e:
            print(f"[ROLE SYNC] ⚠️ Failed to edit wizard 'done' indicator: {type(e).__name__}: {e}")
        except Exception as e:
            print(f"[ROLE SYNC] ⚠️ Unexpected error editing wizard 'done' indicator: {type(e).__name__}: {e}")

        # ALWAYS send fresh message with full results — guaranteed visibility, no edit-propagation lag
        send_succeeded = False
        try:
            await ctx.send(embed=final_embed)
            send_succeeded = True
        except Exception as send_err:
            print(f"[ROLE SYNC] ❌ Failed to send final results message: {type(send_err).__name__}: {send_err}")
            import traceback
            traceback.print_exc()

        # ----- Rate limit consumption (Head Admin only, full success + actual change) -----
        rate_consumed = False
        rate_skipped_reason = None
        if not _has_admin(ctx.author) and len(target_user_ids) > 0:
            all_success = all(
                self._classify_user_result(per_user_results.get(uid)) == "success"
                for uid in target_user_ids
            )
            had_change = self._had_actual_change(per_user_results)
            if all_success and had_change:
                rate_consumed = _record_rate_limit_use(ctx.author.id, cmd_name)
                if rate_consumed:
                    print(
                        f"[ROLE SYNC] ⏱️ Rate limit consumed for {ctx.author} ({ctx.author.id}) "
                        f"on >{cmd_name} — next available in {RATE_LIMIT_HOURS}h"
                    )
            elif all_success and not had_change:
                rate_skipped_reason = "no-op (everyone already had/lacked the role)"
                print(
                    f"[ROLE SYNC] ⏱️ Rate limit NOT consumed for {ctx.author} ({ctx.author.id}) "
                    f"on >{cmd_name} — {rate_skipped_reason}"
                )
            elif not all_success:
                rate_skipped_reason = "wizard did not fully succeed"

        print(
            f"[ROLE SYNC] {ctx.author} ({ctx.author.id}) used >{cmd_name} "
            f"on {len(target_user_ids)} user(s) -> '{role_name}' "
            f"(wizard_edited={edit_succeeded}, results_sent={send_succeeded}, "
            f"rate_consumed={rate_consumed}"
            + (f", rate_skipped={rate_skipped_reason}" if rate_skipped_reason else "")
            + ")"
        )

    # ---------- Wizard prompt helpers ----------

    async def _prompt_user_ids(
        self,
        ctx: commands.Context,
        wizard_msg: discord.Message,
        base_embed: discord.Embed,
    ) -> Optional[list]:
        """Prompt for one or more user IDs. Strict validation — reject the whole list on any error."""
        for attempt in range(MAX_INVALID_RETRIES):
            try:
                msg = await self.bot.wait_for(
                    "message",
                    check=lambda m: m.author.id == ctx.author.id and m.channel.id == ctx.channel.id,
                    timeout=WIZARD_TIMEOUT,
                )
            except asyncio.TimeoutError:
                await self._edit_cancelled(wizard_msg, "⏱️ Cancelled — timed out waiting for user IDs.")
                return None

            content = msg.content.strip()
            tries_left = MAX_INVALID_RETRIES - attempt - 1

            if content.lower() == "cancel":
                await self._edit_cancelled(wizard_msg, f"❌ Cancelled by {ctx.author.mention}.")
                return None

            valid_ids, invalid_tokens, _had_dupes = _parse_user_ids(content)

            if not valid_ids and not invalid_tokens:
                await self._show_retry(
                    wizard_msg, base_embed,
                    f"❌ No IDs detected. Send at least one numeric user ID. "
                    f"Tries left: **{tries_left}**",
                )
                continue

            if invalid_tokens:
                preview = ", ".join(f"`{t[:30]}`" for t in invalid_tokens[:5])
                more = f" (+{len(invalid_tokens) - 5} more)" if len(invalid_tokens) > 5 else ""
                await self._show_retry(
                    wizard_msg, base_embed,
                    f"❌ Invalid (not numeric): {preview}{more}. "
                    f"Reject all and re-enter the list. Tries left: **{tries_left}**",
                )
                continue

            if len(valid_ids) > MAX_USERS_PER_WIZARD:
                await self._show_retry(
                    wizard_msg, base_embed,
                    f"❌ Too many users (`{len(valid_ids)}`). Max is **{MAX_USERS_PER_WIZARD}** per run. "
                    f"Tries left: **{tries_left}**",
                )
                continue

            # Validate each ID resolves to a member in at least one of the 3 guilds
            not_found = [uid for uid in valid_ids if not self._get_member_anywhere(uid)]
            if not_found:
                preview = ", ".join(f"`{uid}`" for uid in not_found[:5])
                more = f" (+{len(not_found) - 5} more)" if len(not_found) > 5 else ""
                await self._show_retry(
                    wizard_msg, base_embed,
                    f"❌ Not found in any of the 3 servers: {preview}{more}. "
                    f"Reject all and re-enter the list. Tries left: **{tries_left}**",
                )
                continue

            return valid_ids

        await self._edit_cancelled(wizard_msg, "❌ Cancelled — too many invalid attempts.")
        return None

    def _format_user_list(self, user_ids: list, limit: int = 10) -> str:
        """Render a user-id list as @mentions for Step 3 display."""
        if not user_ids:
            return "(none)"
        if len(user_ids) == 1:
            uid = user_ids[0]
            member = self._get_member_anywhere(uid)
            return f"<@{uid}> (`{uid}`)" if member else f"`{uid}`"
        shown = user_ids[:limit]
        remainder = len(user_ids) - len(shown)
        mentions = ", ".join(f"<@{uid}>" for uid in shown)
        if remainder > 0:
            mentions += f" *(+{remainder} more)*"
        return mentions

    async def _prompt_role_name(
        self,
        ctx: commands.Context,
        wizard_msg: discord.Message,
        base_embed: discord.Embed,
        allowed_roles: list,
    ) -> Optional[str]:
        for attempt in range(MAX_INVALID_RETRIES):
            try:
                msg = await self.bot.wait_for(
                    "message",
                    check=lambda m: m.author.id == ctx.author.id and m.channel.id == ctx.channel.id,
                    timeout=WIZARD_TIMEOUT,
                )
            except asyncio.TimeoutError:
                await self._edit_cancelled(wizard_msg, "⏱️ Cancelled — timed out waiting for role name.")
                return None

            content = msg.content.strip()
            tries_left = MAX_INVALID_RETRIES - attempt - 1

            if content.lower() == "cancel":
                await self._edit_cancelled(wizard_msg, f"❌ Cancelled by {ctx.author.mention}.")
                return None

            canonical = _canonicalize_role(content, allowed_roles)
            if canonical is None:
                await self._show_retry(
                    wizard_msg, base_embed,
                    f"❌ `{content[:50]}` is not in the allowed list for this command. "
                    f"Tries left: **{tries_left}**",
                )
                continue

            return canonical

        await self._edit_cancelled(wizard_msg, "❌ Cancelled — too many invalid attempts.")
        return None

    async def _show_retry(
        self,
        wizard_msg: discord.Message,
        base_embed: discord.Embed,
        error_msg: str,
    ):
        retry_embed = discord.Embed(
            title=base_embed.title,
            description=f"{error_msg}\n\n{base_embed.description}",
            color=COLOR_ERROR,
        )
        try:
            await wizard_msg.edit(embed=retry_embed)
        except discord.HTTPException:
            pass

    async def _edit_cancelled(self, wizard_msg: discord.Message, reason: str):
        embed = discord.Embed(
            title="Cancelled",
            description=reason,
            color=COLOR_CANCELLED,
        )
        try:
            await wizard_msg.edit(embed=embed, view=None)
        except discord.HTTPException:
            pass

    def _get_member_anywhere(self, user_id: int) -> Optional[discord.Member]:
        for guild_id in GUILD_IDS:
            guild = self.bot.get_guild(guild_id)
            if guild:
                member = guild.get_member(user_id)
                if member:
                    return member
        return None

    def _build_role_availability_note(self, role_name: str) -> str:
        """Scan the 3 guilds for the role and return a confirm-step note.

        Shows the operator which guilds actually have this role *before* they
        click Submit. Guild-specific roles like "Tips and Tricks Helper" may only
        exist in 1 of the 3 servers — that's expected and OK. But if the role
        exists in 0 servers, the role name is likely a typo / has hidden chars
        and we surface a strong warning.
        """
        found = []
        missing = []
        for gid in GUILD_IDS:
            guild = self.bot.get_guild(gid)
            if guild is None:
                missing.append((gid, None, "bot not in server"))
                continue
            role = _find_role_in_guild(guild, role_name)
            if role:
                found.append((gid, guild.name))
            else:
                missing.append((gid, guild.name, "role missing"))

        if len(found) == 3:
            return ""  # All 3 have the role — nothing to flag

        if not found:
            lines = [
                f"\n⚠️ **Heads-up:** `{role_name}` was not found in any of the 3 servers.",
                "Possible causes: the role was renamed, deleted, or has a hidden character "
                "(emoji prefix, smart quote, trailing space). Verify the exact role name "
                "in Discord before submitting — otherwise every guild will be skipped.\n",
            ]
            return "\n".join(lines)

        # Found in some but not all — informational, not blocking
        found_names = ", ".join(name for _, name in found)
        missing_names = ", ".join(
            (name or f"Guild {gid}") for gid, name, _ in missing
        )
        return (
            f"\nℹ️ **Role availability:** found in **{len(found)} of 3** servers "
            f"({found_names}). Missing in: {missing_names} — those guilds will be "
            f"skipped smoothly.\n"
        )

    # ---------- Core role application ----------

    async def _apply_role_change(
        self,
        user_id: int,
        role_name: str,
        action: str,
        executor: discord.Member,
        cmd_name: str,
    ) -> dict:
        results = {}
        reason = f"by {executor} ({executor.id}) via >{cmd_name} wizard"

        for guild_id in GUILD_IDS:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                results[guild_id] = "ℹ️ Bot not in this server — skipped"
                continue

            member = guild.get_member(user_id)
            if not member:
                # Fallback: cache miss but the user might still be a member — fetch from API
                try:
                    member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    results[guild_id] = "ℹ️ User not in this server — skipped"
                    continue
                except discord.HTTPException as e:
                    results[guild_id] = f"⚠️ Lookup failed: {str(e)[:60]}"
                    continue
                if not member:
                    results[guild_id] = "ℹ️ User not in this server — skipped"
                    continue

            role = _find_role_in_guild(guild, role_name)
            if not role:
                results[guild_id] = f"ℹ️ Role '{role_name}' doesn't exist here — skipped"
                continue

            if role.is_default() or role.managed:
                results[guild_id] = "⚠️ Role is restricted (default/managed)"
                continue

            bot_member = guild.me
            if bot_member is None:
                results[guild_id] = "⚠️ Cannot resolve bot member"
                continue

            if role >= bot_member.top_role:
                results[guild_id] = "⚠️ Role is at or above my top role"
                continue

            try:
                if action == ACTION_ADD:
                    if role in member.roles:
                        results[guild_id] = "ℹ️ Already has role"
                    else:
                        await member.add_roles(role, reason=reason)
                        results[guild_id] = "✅ Added role"
                else:
                    if role not in member.roles:
                        results[guild_id] = "ℹ️ Did not have role"
                    else:
                        await member.remove_roles(role, reason=reason)
                        results[guild_id] = "✅ Removed role"
            except discord.Forbidden:
                results[guild_id] = "❌ Missing permissions"
            except discord.HTTPException as e:
                results[guild_id] = f"❌ Error: {str(e)[:80]}"

        return results

    # ---------- Specialty role handling ----------

    def _build_specialty_note(self, role_name: str, action: str) -> str:
        verb_past = "added to" if action == ACTION_ADD else "removed from"
        if role_name == SPECIALTY_LOOT_ROUTE_MAKER:
            cmd = LOOT_ROUTE_ADD_CMD if action == ACTION_ADD else LOOT_ROUTE_REMOVE_CMD
            return (
                f"\n⚠️ **Full Sync** — `{role_name}` has extra setup.\n"
                f"This will trigger `>{cmd}` which handles rotation, points, "
                f"role sync across all 3 servers, and leaderboard updates (~15s).\n"
            )
        if role_name == SPECIALTY_TT_HELPER:
            cmd = TT_ADD_CMD if action == ACTION_ADD else TT_REMOVE_CMD
            return (
                f"\n⚠️ **Full Sync** — `{role_name}` has extra setup.\n"
                f"This will trigger `>{cmd}` which syncs the role across all 3 servers "
                f"and posts a join/leave announcement.\n"
            )
        return ""

    async def _handle_specialty_loot_route_maker_raw(
        self,
        ctx: commands.Context,
        action: str,
        user_id: int,
        executor: discord.Member,
    ) -> dict:
        """Invoke existing loot route command for one user, return outcome marker."""
        cog = self.bot.get_cog(LOOT_ROUTE_COG_NAME)
        cmd_name = LOOT_ROUTE_ADD_CMD if action == ACTION_ADD else LOOT_ROUTE_REMOVE_CMD
        if cog is None:
            return {"_kind": "loot_route", "_cmd": cmd_name, "_error": f"Cog `{LOOT_ROUTE_COG_NAME}` not loaded"}

        try:
            if action == ACTION_ADD:
                member = self._get_member_anywhere(user_id)
                if member is None:
                    return {"_kind": "loot_route", "_cmd": cmd_name, "_error": f"User `{user_id}` not resolvable"}
                main_guild = self.bot.get_guild(1041450125391835186)
                if main_guild:
                    main_member = main_guild.get_member(user_id)
                    if main_member:
                        member = main_member
                await ctx.invoke(cog.add_loot_route_maker, user=member)
            else:
                await ctx.invoke(cog.remove_loot_route_maker, user_input=str(user_id))
        except commands.CommandError as e:
            return {"_kind": "loot_route", "_cmd": cmd_name, "_error": f"Command error: {str(e)[:200]}"}
        except Exception as e:
            return {"_kind": "loot_route", "_cmd": cmd_name, "_error": f"Exception: {str(e)[:200]}"}

        print(
            f"[ROLE SYNC] {executor} ({executor.id}) wizard-delegated "
            f">{cmd_name} for user {user_id}"
        )
        return {"_kind": "loot_route", "_cmd": cmd_name, "_invoked": True}

    async def _handle_specialty_surge_route_maker_raw(
        self,
        ctx: commands.Context,
        action: str,
        user_id: int,
        executor: discord.Member,
    ) -> dict:
        """Invoke the surge route add/remove command for one user, return outcome marker."""
        cog = self.bot.get_cog(SURGE_ROUTE_COG_NAME)
        cmd_name = SURGE_ROUTE_ADD_CMD if action == ACTION_ADD else SURGE_ROUTE_REMOVE_CMD
        if cog is None:
            return {"_kind": "surge_route", "_cmd": cmd_name, "_error": f"Cog `{SURGE_ROUTE_COG_NAME}` not loaded"}

        try:
            if action == ACTION_ADD:
                member = self._get_member_anywhere(user_id)
                if member is None:
                    return {"_kind": "surge_route", "_cmd": cmd_name, "_error": f"User `{user_id}` not resolvable"}
                main_guild = self.bot.get_guild(1041450125391835186)
                if main_guild:
                    main_member = main_guild.get_member(user_id)
                    if main_member:
                        member = main_member
                await ctx.invoke(cog.add_surge_route_maker, user=member)
            else:
                await ctx.invoke(cog.remove_surge_route_maker, user_input=str(user_id))
        except commands.CommandError as e:
            return {"_kind": "surge_route", "_cmd": cmd_name, "_error": f"Command error: {str(e)[:200]}"}
        except Exception as e:
            return {"_kind": "surge_route", "_cmd": cmd_name, "_error": f"Exception: {str(e)[:200]}"}

        print(
            f"[ROLE SYNC] {executor} ({executor.id}) wizard-delegated "
            f">{cmd_name} for user {user_id}"
        )
        return {"_kind": "surge_route", "_cmd": cmd_name, "_invoked": True}

    async def _handle_specialty_tt_helper_raw(
        self,
        ctx: commands.Context,
        action: str,
        user_id: int,
        executor: discord.Member,
    ) -> dict:
        """Invoke the T&T helper add/remove command for one user, return outcome marker."""
        cog = self.bot.get_cog(TT_COG_NAME)
        cmd_name = TT_ADD_CMD if action == ACTION_ADD else TT_REMOVE_CMD
        if cog is None:
            return {"_kind": "tips_tricks", "_cmd": cmd_name, "_error": f"Cog `{TT_COG_NAME}` not loaded"}

        try:
            if action == ACTION_ADD:
                member = self._get_member_anywhere(user_id)
                if member is None:
                    return {"_kind": "tips_tricks", "_cmd": cmd_name, "_error": f"User `{user_id}` not resolvable"}
                main_guild = self.bot.get_guild(1041450125391835186)
                if main_guild:
                    main_member = main_guild.get_member(user_id)
                    if main_member:
                        member = main_member
                await ctx.invoke(cog.add_tips_helper, user=member)
            else:
                await ctx.invoke(cog.remove_tips_helper, user_input=str(user_id))
        except commands.CommandError as e:
            return {"_kind": "tips_tricks", "_cmd": cmd_name, "_error": f"Command error: {str(e)[:200]}"}
        except Exception as e:
            return {"_kind": "tips_tricks", "_cmd": cmd_name, "_error": f"Exception: {str(e)[:200]}"}

        print(
            f"[ROLE SYNC] {executor} ({executor.id}) wizard-delegated "
            f">{cmd_name} for user {user_id}"
        )
        return {"_kind": "tips_tricks", "_cmd": cmd_name, "_invoked": True}

    # ---------- Multi-user results ----------

    def _had_actual_change(self, per_user_results: dict) -> bool:
        """True if at least one user had an actual role change (✅ Added/Removed).

        Returns False if every result was 'Already has role' / 'Did not have role' / failure —
        i.e., a no-op run where the bot didn't actually modify any Discord state.
        Used to decide whether to consume a Head Admin's rate-limit slot.
        """
        for result in per_user_results.values():
            if isinstance(result, dict) and "_kind" in result:
                if "_error" in result:
                    continue
                if result.get("_invoked"):
                    return True
            elif isinstance(result, dict):
                # Standard {guild_id: status_str}
                if any(str(v).startswith("✅") for v in result.values()):
                    return True
        return False

    def _classify_user_result(self, result) -> str:
        """Reduce a per-user result to one of: 'success', 'partial', 'fail'.

        Skippable per-guild statuses (role missing in guild, user/bot not in guild)
        are treated as benign — they don't count toward success or failure. We
        classify based only on the guilds where action was actually possible.
        That way, a guild-specific role like "Tips and Tricks Helper" that only
        exists in 1 of the 3 servers can still report ✅ success when the user
        gets/already has it in the guild where it lives.

        Edge case: if EVERY guild was skipped (e.g. role doesn't exist in any
        server), classify as 'fail' so the operator notices — there's likely a
        typo or the role was renamed.
        """
        if isinstance(result, dict) and "_kind" in result:
            if "_error" in result:
                return "fail"
            if result.get("_invoked"):
                return "success"
            return "fail"
        # Standard {guild_id: status_str}
        if isinstance(result, dict):
            statuses = list(result.values())
            if not statuses:
                return "fail"
            actionable = [s for s in statuses if not _is_skippable_status(s)]
            if not actionable:
                # Every guild was skipped — no role existed anywhere, or user/bot was missing
                # from every server. Surface as failure so the operator can fix the input.
                return "fail"
            good = sum(1 for s in actionable if str(s).startswith("✅") or str(s).startswith("ℹ️"))
            if good == len(actionable):
                return "success"
            if good == 0:
                return "fail"
            return "partial"
        return "fail"

    def _all_failures_are_role_missing(self, target_user_ids: list, per_user_results: dict, classes: dict) -> bool:
        """Return True iff every failing user failed solely because the role was missing from every guild.

        Used to pick a clearer 'role-not-found' headline instead of the generic
        '❌ Sync Failed' when the real cause is a bad role name.
        """
        any_failed = False
        for uid in target_user_ids:
            if classes.get(uid) != "fail":
                continue
            any_failed = True
            result = per_user_results.get(uid)
            # Specialty results (loot/surge route etc.) don't follow the {gid: status} shape
            if isinstance(result, dict) and "_kind" in result:
                return False
            if not isinstance(result, dict):
                return False
            statuses = list(result.values())
            if not statuses:
                return False
            # Every status for this failing user must be a "Role doesn't exist here" skip
            for s in statuses:
                s_str = str(s)
                if "Role '" not in s_str:
                    return False
                if "not found" not in s_str and "doesn't exist here" not in s_str:
                    return False
        return any_failed

    def _format_user_result_lines(self, user_id: int, result) -> list:
        """Return a list of pretty lines describing one user's result, for the full grid view."""
        lines = [f"**<@{user_id}>** (`{user_id}`)"]
        if isinstance(result, dict) and "_kind" in result:
            if "_error" in result:
                lines.append(f"  ❌ `>{result.get('_cmd', '?')}` — {result['_error']}")
            elif result.get("_invoked"):
                lines.append(f"  ✅ Triggered `>{result.get('_cmd', '?')}` (see status messages above)")
            else:
                lines.append(f"  ⚠️ Unknown specialty result")
            return lines
        # Standard {guild_id: status_str}
        if isinstance(result, dict):
            for gid, status in result.items():
                g = self.bot.get_guild(gid) if isinstance(gid, int) else None
                gname = g.name if g else f"Guild {gid}"
                lines.append(f"  • {gname}: {status}")
        return lines

    def _categorize_status(self, status: str) -> str:
        """Map a per-guild status string to a category key for aggregation."""
        s = str(status)
        if "Added role" in s:
            return "added"
        if "Removed role" in s:
            return "removed"
        if "Already has role" in s:
            return "already_had"
        if "Did not have role" in s:
            return "didnt_have"
        if "User not in this server" in s or "Bot not in this server" in s:
            return "not_in_server"
        if "Role" in s and ("not found" in s or "doesn't exist here" in s):
            return "role_not_found"
        if "above my top role" in s:
            return "role_too_high"
        if "Missing permissions" in s:
            return "missing_perms"
        if "Lookup failed" in s:
            return "lookup_failed"
        if "restricted (default/managed)" in s:
            return "role_restricted"
        if "Crashed" in s:
            return "crashed"
        if s.startswith("❌"):
            return "error"
        return "other"

    def _aggregate_per_guild(self, target_user_ids: list, per_user_results: dict) -> dict:
        """Invert per-user results into per-guild breakdown.

        Returns: {guild_id: {category: [user_ids]}} for standard results.
        Specialty results (LR Maker, SR Maker, etc.) are excluded from this aggregation.
        """
        breakdown = {}
        categories = (
            "added", "removed", "already_had", "didnt_have",
            "not_in_server", "role_not_found", "role_too_high",
            "missing_perms", "lookup_failed", "role_restricted",
            "crashed", "error", "other",
        )
        for gid in GUILD_IDS:
            breakdown[gid] = {cat: [] for cat in categories}

        for uid in target_user_ids:
            result = per_user_results.get(uid)
            # Skip specialty-tagged results — they don't follow standard {gid: status} shape
            if isinstance(result, dict) and "_kind" in result:
                continue
            if not isinstance(result, dict):
                continue
            for gid, status in result.items():
                if not isinstance(gid, int) or gid not in breakdown:
                    continue
                cat = self._categorize_status(status)
                breakdown[gid][cat].append(uid)

        return breakdown

    def _format_guild_section(self, guild_id: int, section_data: dict, max_mentions: int = 15) -> str:
        """Build a multi-line string summary of one guild's per-user outcomes."""
        def fmt_mentions(uids: list) -> str:
            if not uids:
                return ""
            shown = uids[:max_mentions]
            more = f" *(+{len(uids) - len(shown)} more)*" if len(uids) > len(shown) else ""
            return " " + ", ".join(f"<@{u}>" for u in shown) + more

        lines = []
        a = section_data
        if a["added"]:
            lines.append(f"✅ **Added:** {len(a['added'])}")
        if a["removed"]:
            lines.append(f"✅ **Removed:** {len(a['removed'])}")
        if a["already_had"]:
            lines.append(f"ℹ️ **Already had role:** {len(a['already_had'])}{fmt_mentions(a['already_had'])}")
        if a["didnt_have"]:
            lines.append(f"ℹ️ **Didn't have role:** {len(a['didnt_have'])}{fmt_mentions(a['didnt_have'])}")
        if a["not_in_server"]:
            lines.append(f"ℹ️ **Not a member here — skipped:** {len(a['not_in_server'])}{fmt_mentions(a['not_in_server'])}")
        if a["role_not_found"]:
            lines.append(f"ℹ️ **Role doesn't exist here — skipped:** {len(a['role_not_found'])} user(s){fmt_mentions(a['role_not_found'])}")
        if a["role_too_high"]:
            lines.append(f"⚠️ **Role above my top role** — affects {len(a['role_too_high'])} user(s)")
        if a["role_restricted"]:
            lines.append(f"⚠️ **Role restricted (default/managed):** {len(a['role_restricted'])}")
        if a["missing_perms"]:
            lines.append(f"❌ **Missing permissions:** {len(a['missing_perms'])}{fmt_mentions(a['missing_perms'])}")
        if a["lookup_failed"]:
            lines.append(f"⚠️ **Member lookup failed:** {len(a['lookup_failed'])}")
        if a["error"]:
            lines.append(f"❌ **Other API errors:** {len(a['error'])}{fmt_mentions(a['error'])}")
        if a["crashed"]:
            lines.append(f"❌ **Crashed:** {len(a['crashed'])}{fmt_mentions(a['crashed'])}")
        if a["other"]:
            lines.append(f"❔ **Other:** {len(a['other'])}")
        if not lines:
            return "*(no actions on this server)*"
        text = "\n".join(lines)
        if len(text) > 1024:
            text = text[:1020] + "\n…"
        return text

    def _build_multi_results_embed(
        self,
        label: str,
        action_verb: str,
        target_user_ids: list,
        role_name: str,
        per_user_results: dict,
        executor: discord.Member,
        cmd_name: str,
    ) -> discord.Embed:
        total = len(target_user_ids)
        # Classify each
        classes = {uid: self._classify_user_result(per_user_results.get(uid)) for uid in target_user_ids}
        succ = sum(1 for c in classes.values() if c == "success")
        part = sum(1 for c in classes.values() if c == "partial")
        fail = sum(1 for c in classes.values() if c == "fail")

        # Detect the common failure mode where the role didn't exist in ANY guild
        # (i.e., every guild status was a skippable "role not found"). That gets a
        # clearer headline so the operator knows it's a role-name problem, not a perms one.
        all_role_missing = self._all_failures_are_role_missing(target_user_ids, per_user_results, classes)

        if total > 0 and succ == total:
            color, head = COLOR_SUCCESS, f"✅ {label} Sync Complete"
        elif succ == 0 and part == 0:
            if all_role_missing:
                color, head = COLOR_FAIL, f"❌ {label} Sync Failed — role not found in any server"
            else:
                color, head = COLOR_FAIL, f"❌ {label} Sync Failed"
        else:
            color, head = COLOR_PARTIAL, f"⚠️ {label} Sync Partial"

        if total > 1:
            head += f" — {total} users"

        embed = discord.Embed(title=head, color=color)
        embed.add_field(name="Role", value=role_name, inline=True)
        embed.add_field(name="Action", value=action_verb, inline=True)
        embed.add_field(name="Users", value=str(total), inline=True)

        if total > 1:
            embed.add_field(
                name="Summary",
                value=f"✅ {succ} succeeded  ·  ⚠️ {part} partial  ·  ❌ {fail} failed",
                inline=False,
            )

        # ----- Per-USER section (only meaningful for ≤6 users; specialty roles always show) -----
        if total <= COMPACT_RESULTS_THRESHOLD:
            for uid in target_user_ids:
                lines = self._format_user_result_lines(uid, per_user_results.get(uid))
                value = "\n".join(lines)
                if len(value) > 1024:
                    value = value[:1020] + "\n…"
                emoji = {"success": "✅", "partial": "⚠️", "fail": "❌"}.get(classes[uid], "•")
                embed.add_field(name=f"{emoji} User {uid}", value=value, inline=False)
        else:
            # Compact per-user (one line each)
            compact_lines = []
            for uid in target_user_ids:
                emoji = {"success": "✅", "partial": "⚠️", "fail": "❌"}.get(classes[uid], "•")
                compact_lines.append(f"{emoji} <@{uid}> (`{uid}`)")
            value = "\n".join(compact_lines)
            if len(value) > 1024:
                value = value[:1020] + "\n…"
            embed.add_field(name=f"👤 Per-User ({total})", value=value, inline=False)

        # ----- Per-GUILD breakdown (always shown when there's standard data; skipped for specialty roles) -----
        per_guild = self._aggregate_per_guild(target_user_ids, per_user_results)
        # Check if there's any aggregated data (specialty roles skip aggregation)
        has_data = any(any(v for v in section.values()) for section in per_guild.values())
        if has_data:
            for gid in GUILD_IDS:
                guild = self.bot.get_guild(gid)
                guild_name = guild.name if guild else f"Guild {gid}"
                section_text = self._format_guild_section(gid, per_guild[gid])
                embed.add_field(
                    name=f"🌐 {guild_name} (`{gid}`)",
                    value=section_text,
                    inline=False,
                )

        footer = f"Executed by {executor} ({executor.id}) · via >{cmd_name}"
        if total > COMPACT_RESULTS_THRESHOLD:
            footer = f"Compact per-user view ({total} users) · " + footer
        embed.set_footer(text=footer)
        return embed

    def _build_results_embed(
        self,
        label: str,
        action_verb: str,
        target_display: str,
        role_name: str,
        results: dict,
        executor: discord.Member,
    ) -> discord.Embed:
        statuses = list(results.values())
        good = sum(1 for s in statuses if s.startswith("✅") or s.startswith("ℹ️"))
        total = len(statuses)

        if total > 0 and good == total:
            color = COLOR_SUCCESS
            title = f"✅ {label} Sync Complete"
        elif good == 0:
            color = COLOR_FAIL
            title = f"❌ {label} Sync Failed"
        else:
            color = COLOR_PARTIAL
            title = f"⚠️ {label} Sync Partial"

        lines = []
        for guild_id, status in results.items():
            guild = self.bot.get_guild(guild_id)
            guild_name = guild.name if guild else f"Guild {guild_id}"
            lines.append(f"**{guild_name}** (`{guild_id}`): {status}")

        embed = discord.Embed(title=title, color=color)
        embed.add_field(name="Target", value=target_display, inline=False)
        embed.add_field(name="Role", value=role_name, inline=True)
        embed.add_field(name="Action", value=action_verb, inline=True)
        embed.add_field(name="Per-Server Results", value="\n".join(lines) or "(no results)", inline=False)
        embed.set_footer(text=f"Executed by {executor} ({executor.id})")
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(MultiGuildRoleCommands(bot))
