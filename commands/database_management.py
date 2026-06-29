"""
Database Management Commands
Generic >dbtable and >dbclear commands work on any DB table automatically.
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
import logging
import asyncio

logger = logging.getLogger('discord')

# Singleton tables: must be reset via UPDATE, not DELETE (bot expects the row to exist)
_SINGLETON_RESETS = {
    'central_bank': (
        "UPDATE central_bank SET reserves_vbucks=0, reserves_points=0, "
        "fee_rate_pct=5.0, ptv_tax_pct=50.0, last_updated=? WHERE id=1"
    ),
    'rotation_state': (
        "UPDATE rotation_state SET rotation_message_id=NULL, sticky_message_id=NULL, "
        "leaderboard_message_id=NULL, last_assigned_position=0, "
        "last_assigned_user_id=NULL, total_assignments=0, last_updated=? WHERE id=1"
    ),
}

# FK dependencies: clear these child tables before their parent
_CLEAR_DEPS = {
    'predictions': ['prediction_votes'],
}


class GenericTableView(discord.ui.View):
    """Paginated viewer for any database table."""

    PER_PAGE = 8

    def __init__(self, author, table_name: str):
        super().__init__(timeout=300)
        self.author = author
        self.table_name = table_name
        self.page = 0
        self.total_pages = 1
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Not your menu!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        try:
            for item in self.children:
                item.disabled = True
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

    def _sync_buttons(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "gt_prev":
                    item.disabled = (self.page == 0)
                elif item.custom_id == "gt_next":
                    item.disabled = (self.page >= self.total_pages - 1)

    async def build_embed(self) -> discord.Embed:
        import database
        pool = await database.get_pool()
        async with pool.acquire() as db:
            async with db.execute(f"PRAGMA table_info({self.table_name})") as c:
                cols = await c.fetchall()
            col_names = [col[1] for col in cols]

            async with db.execute(f"SELECT COUNT(*) FROM {self.table_name}") as c:
                total = (await c.fetchone())[0]

            self.total_pages = max(1, (total + self.PER_PAGE - 1) // self.PER_PAGE)

            async with db.execute(
                f"SELECT * FROM {self.table_name} LIMIT ? OFFSET ?",
                (self.PER_PAGE, self.page * self.PER_PAGE)
            ) as c:
                rows = await c.fetchall()

        e = discord.Embed(
            title=f"🗄️ {self.table_name}",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )
        e.add_field(
            name="📊 Summary",
            value=f"```\n{'Total Rows':<20} {total:>8,}\n{'Columns':<20} {len(col_names):>8,}\n```",
            inline=False
        )
        col_header = " | ".join(f"`{c}`" for c in col_names)
        if len(col_header) > 1020:
            col_header = col_header[:1017] + "…"
        e.add_field(name="📋 Columns", value=col_header, inline=False)

        if rows:
            lines = []
            for row in rows:
                parts = []
                for val in row:
                    v = str(val) if val is not None else "NULL"
                    parts.append(v[:18] + "…" if len(v) > 18 else v)
                lines.append("• " + " | ".join(parts))
            value = "\n".join(lines)
            if len(value) > 1020:
                value = value[:1017] + "…"
            e.add_field(
                name=f"📄 Rows — Page {self.page + 1}/{self.total_pages}",
                value=value,
                inline=False
            )
        else:
            e.add_field(name="📄 Rows", value="*Table is empty*", inline=False)

        e.set_footer(text=f"Page {self.page + 1}/{self.total_pages}  •  {self.table_name}  •  ◀ ▶ to paginate")
        return e

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0, disabled=True, custom_id="gt_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        embed = await self.build_embed()
        self._sync_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=0, custom_id="gt_next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
        embed = await self.build_embed()
        self._sync_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="✖ Close", style=discord.ButtonStyle.danger, row=0)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


class DatabaseManagement(commands.Cog):
    """Commands for database management"""

    def __init__(self, bot):
        self.bot = bot

    async def _get_tables(self, db) -> set:
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as c:
            return {r[0] for r in await c.fetchall()}

    # ── >dbinfo ───────────────────────────────────────────────────────────────

    @commands.command(name='dbinfo', help='Overview of all database tables and row counts')
    @commands.has_any_role('007', '+', 'Management')
    async def dbinfo(self, ctx):
        """
        Display row counts for every table in the database dynamically.
        Usage: >dbinfo
        """
        try:
            import database
            pool = await database.get_pool()
            async with pool.acquire() as db:
                async with db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ) as c:
                    tables = [r[0] for r in await c.fetchall()]

                counts = {}
                for t in tables:
                    async with db.execute(f"SELECT COUNT(*) FROM {t}") as c:
                        counts[t] = (await c.fetchone())[0]

            grand = sum(counts.values())
            active = len([t for t in tables if counts[t] > 0])

            embed = discord.Embed(
                title="📊 Database Overview",
                description=(
                    f"**{grand:,} total records** across **{len(tables)}** tables "
                    f"({active} active)\n"
                    "Use `>dbtable <name>` to inspect any table."
                ),
                color=0x5865F2,
                timestamp=datetime.now(timezone.utc)
            )

            lines = "\n".join(f"  {t:<38} {counts[t]:>8,}" for t in tables)
            # Split into chunks if too long for one field
            if len(lines) <= 980:
                embed.add_field(name="📋 All Tables", value=f"```\n{lines}\n```", inline=False)
            else:
                chunks, current = [], []
                for line in lines.split("\n"):
                    current.append(line)
                    if len("\n".join(current)) > 900:
                        chunks.append("\n".join(current[:-1]))
                        current = [line]
                if current:
                    chunks.append("\n".join(current))
                for i, chunk in enumerate(chunks):
                    embed.add_field(
                        name=f"📋 All Tables {'(cont.)' if i else ''}",
                        value=f"```\n{chunk}\n```",
                        inline=False
                    )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in dbinfo: {e}")
            await ctx.send(embed=discord.Embed(
                title="❌ Error", description=str(e), color=0xED4245
            ))

    # ── >dbtable ──────────────────────────────────────────────────────────────

    @commands.command(name='dbtable', help='Inspect any database table with pagination')
    @commands.has_any_role('007', '+', 'Management')
    async def dbtable(self, ctx, table_name: str = None):
        """
        View any database table with paginated rows and column info.
        Usage: >dbtable <table_name>
        Run >dbinfo to see all available table names.
        """
        if not table_name:
            await ctx.send(embed=discord.Embed(
                title="❌ Usage",
                description="`>dbtable <table_name>`\nRun `>dbinfo` to see all table names.",
                color=0xED4245
            ))
            return

        try:
            import database
            pool = await database.get_pool()
            async with pool.acquire() as db:
                tables = await self._get_tables(db)

            if table_name not in tables:
                close = [t for t in sorted(tables) if table_name.lower() in t.lower()]
                hint = f"\n**Did you mean:** {', '.join(f'`{t}`' for t in close[:5])}" if close else ""
                await ctx.send(embed=discord.Embed(
                    title="❌ Table Not Found",
                    description=f"`{table_name}` does not exist.{hint}\nRun `>dbinfo` for the full list.",
                    color=0xED4245
                ))
                return

            view = GenericTableView(ctx.author, table_name)
            embed = await view.build_embed()
            view._sync_buttons()
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg

        except Exception as e:
            logger.error(f"Error in dbtable: {e}")
            await ctx.send(embed=discord.Embed(
                title="❌ Error", description=str(e), color=0xED4245
            ))

    # ── >dbclear ──────────────────────────────────────────────────────────────

    @commands.command(name='dbclear', help='Clear any database table with confirmation')
    @commands.has_any_role('007', '+', 'Management')
    async def dbclear(self, ctx, table_name: str = None):
        """
        Clear (DELETE FROM) any database table, with reaction confirmation.
        Singleton tables (central_bank, rotation_state) are reset to defaults instead of deleted.
        Usage: >dbclear <table_name>
        Run >dbinfo to see all available table names.
        """
        if not table_name:
            await ctx.send(embed=discord.Embed(
                title="❌ Usage",
                description="`>dbclear <table_name>`\nRun `>dbinfo` to see all table names.",
                color=0xED4245
            ))
            return

        try:
            import database
            pool = await database.get_pool()
            async with pool.acquire() as db:
                tables = await self._get_tables(db)

            if table_name not in tables:
                close = [t for t in sorted(tables) if table_name.lower() in t.lower()]
                hint = f"\n**Did you mean:** {', '.join(f'`{t}`' for t in close[:5])}" if close else ""
                await ctx.send(embed=discord.Embed(
                    title="❌ Table Not Found",
                    description=f"`{table_name}` does not exist.{hint}\nRun `>dbinfo` for the full list.",
                    color=0xED4245
                ))
                return

            is_singleton = table_name in _SINGLETON_RESETS
            deps = _CLEAR_DEPS.get(table_name, [])

            async with pool.acquire() as db:
                async with db.execute(f"SELECT COUNT(*) FROM {table_name}") as c:
                    count = (await c.fetchone())[0]

            action_desc = "reset to defaults" if is_singleton else "permanently deleted"
            embed = discord.Embed(
                title=f"⚠️ Clear `{table_name}`",
                description=(
                    f"This will **{action_desc}** `{table_name}` — **{count:,} rows** affected."
                ),
                color=0xF4900C
            )
            if is_singleton:
                embed.add_field(
                    name="ℹ️ Singleton table",
                    value="Rows will be reset to zero/defaults (not deleted — bot requires the row to exist).",
                    inline=False
                )
            if deps:
                embed.add_field(
                    name="Also clears (FK dependencies):",
                    value="\n".join(f"• `{d}`" for d in deps),
                    inline=False
                )
            embed.add_field(name="Confirmation", value="React ✅ to confirm or ❌ to cancel", inline=False)

            msg = await ctx.send(embed=embed)
            await msg.add_reaction('✅')
            await msg.add_reaction('❌')

            def check(reaction, user):
                return (
                    user == ctx.author
                    and str(reaction.emoji) in ['✅', '❌']
                    and reaction.message.id == msg.id
                )

            try:
                reaction, _ = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
            except asyncio.TimeoutError:
                return await msg.edit(embed=discord.Embed(
                    title="⏱️ Timeout", description="Operation cancelled", color=0xED4245
                ))

            if str(reaction.emoji) != '✅':
                return await msg.edit(embed=discord.Embed(
                    title="❌ Cancelled", description=f"`{table_name}` was not cleared.", color=0xED4245
                ))

            now = datetime.now(timezone.utc).isoformat()
            async with pool.acquire() as db:
                # Clear FK deps first
                for dep in deps:
                    if dep in tables:
                        await db.execute(f"DELETE FROM {dep}")

                if is_singleton:
                    await db.execute(_SINGLETON_RESETS[table_name], (now,))
                    action_word = "Reset"
                else:
                    await db.execute(f"DELETE FROM {table_name}")
                    action_word = "Cleared"

                await db.commit()

            result_embed = discord.Embed(
                title=f"✅ {action_word} `{table_name}`",
                description=(
                    f"**{count:,} rows** {'reset to defaults' if is_singleton else 'deleted'} "
                    f"from `{table_name}`."
                ),
                color=0x57F287,
                timestamp=datetime.now(timezone.utc)
            )
            if deps:
                result_embed.add_field(
                    name="Also cleared:",
                    value="\n".join(f"• `{d}`" for d in deps if d in tables),
                    inline=False
                )
            result_embed.set_footer(text=f"Cleared by {ctx.author}")
            await msg.edit(embed=result_embed)
            logger.warning(f"dbclear: {table_name} cleared by {ctx.author} ({count} rows)")

        except Exception as e:
            logger.error(f"Error in dbclear: {e}")
            await ctx.send(embed=discord.Embed(
                title="❌ Error", description=str(e), color=0xED4245
            ))

    # ── >clearcache ───────────────────────────────────────────────────────────

    @commands.command(name='clearcache', help='Clear guild config cache and reload from disk')
    @commands.has_any_role('007', '+', 'Management')
    async def clearcache(self, ctx):
        """
        Clear the in-memory config cache and force reload from config.json.
        Usage: >clearcache
        """
        try:
            from core.cache import config_cache
            async with config_cache._lock:
                config_cache._cache.clear()
                config_cache._last_modified = 0
                await config_cache._reload_config()

            embed = discord.Embed(
                title="🗑️ Config Cache Cleared",
                description="Cache cleared and reloaded from `config.json`.",
                color=0x57F287,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"Cleared by {ctx.author}")
            await ctx.send(embed=embed)
            logger.info(f"Config cache cleared by {ctx.author}")

        except Exception as e:
            logger.error(f"Error in clearcache: {e}")
            await ctx.send(embed=discord.Embed(
                title="❌ Error", description=str(e), color=0xED4245
            ))

    # ── >cleardatabase ────────────────────────────────────────────────────────

    @commands.command(name='cleardatabase', help='☢️ Nuclear option — wipe entire database')
    @commands.has_any_role('007', '+', 'Management')
    async def cleardatabase(self, ctx):
        """
        Nuclear option — DELETE every row from every table. Double confirmation required.
        Singleton tables are reset to defaults. FK dependents are cleared in correct order.
        Usage: >cleardatabase
        """
        embed = discord.Embed(
            title="🚨 NUCLEAR OPTION — CLEAR ENTIRE DATABASE 🚨",
            description=(
                "This will **DELETE EVERYTHING** from every table in the database.\n"
                "Singleton tables (`central_bank`, `rotation_state`) will be reset to defaults."
            ),
            color=discord.Color.dark_red()
        )
        embed.add_field(
            name="⚠️ CANNOT BE UNDONE",
            value="React ✅ to proceed to final confirmation, or ❌ to cancel.",
            inline=False
        )

        msg = await ctx.send(embed=embed)
        await msg.add_reaction('✅')
        await msg.add_reaction('❌')

        def check(reaction, user):
            return (
                user == ctx.author
                and str(reaction.emoji) in ['✅', '❌']
                and reaction.message.id == msg.id
            )

        try:
            reaction, _ = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
            if str(reaction.emoji) != '✅':
                return await msg.edit(embed=discord.Embed(
                    title="❌ Cancelled", description="Database is safe.", color=0x57F287
                ))

            embed2 = discord.Embed(
                title="🚨 FINAL CONFIRMATION 🚨",
                description="**ABSOLUTELY SURE?**\nReact ✅ to **DELETE EVERYTHING** or ❌ to cancel.",
                color=discord.Color.dark_red()
            )
            await msg.clear_reactions()
            await msg.edit(embed=embed2)
            await msg.add_reaction('✅')
            await msg.add_reaction('❌')

            reaction2, _ = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
            if str(reaction2.emoji) != '✅':
                return await msg.edit(embed=discord.Embed(
                    title="❌ Cancelled", description="Database is safe.", color=0x57F287
                ))

            import database
            pool = await database.get_pool()
            now = datetime.now(timezone.utc).isoformat()
            total_deleted = 0

            async with pool.acquire() as db:
                tables = await self._get_tables(db)

                # 1. Clear all FK child tables first
                all_deps = {dep for deps in _CLEAR_DEPS.values() for dep in deps}
                for dep in all_deps:
                    if dep in tables:
                        async with db.execute(f"SELECT COUNT(*) FROM {dep}") as c:
                            total_deleted += (await c.fetchone())[0]
                        await db.execute(f"DELETE FROM {dep}")

                # 2. Clear all normal tables (skip singletons and already-cleared deps)
                for t in tables:
                    if t in _SINGLETON_RESETS or t in all_deps:
                        continue
                    async with db.execute(f"SELECT COUNT(*) FROM {t}") as c:
                        total_deleted += (await c.fetchone())[0]
                    await db.execute(f"DELETE FROM {t}")

                # 3. Reset singletons
                for t, sql in _SINGLETON_RESETS.items():
                    if t in tables:
                        await db.execute(sql, (now,))

                await db.commit()

            await msg.edit(embed=discord.Embed(
                title="💥 DATABASE WIPED",
                description=(
                    f"Deleted **{total_deleted:,}** records from all tables.\n"
                    "Singleton tables reset to defaults."
                ),
                color=discord.Color.dark_red(),
                timestamp=datetime.now(timezone.utc)
            ))
            logger.critical(f"ENTIRE DATABASE CLEARED by {ctx.author} — {total_deleted} records deleted")

        except asyncio.TimeoutError:
            await msg.edit(embed=discord.Embed(
                title="⏱️ Timeout", description="Database is safe.", color=0x57F287
            ))
        except Exception as e:
            logger.error(f"Error in cleardatabase: {e}")
            await ctx.send(embed=discord.Embed(
                title="❌ Error", description=str(e), color=0xED4245
            ))


async def setup(bot):
    await bot.add_cog(DatabaseManagement(bot))
