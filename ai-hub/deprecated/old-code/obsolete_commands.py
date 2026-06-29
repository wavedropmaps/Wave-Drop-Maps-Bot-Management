"""
Archive of obsolete commands removed due to Staff Hub website integration.
"""

# ==================== FROM commands/wave_points_commands.py ====================

# --- wavepointshop ---
    @commands.command(name='wavepointshop', aliases=['wpshop', 'wavepoints_shop', 'wavepointsredeem', 'wpr', 'wpredeem'])
    @commands.has_any_role('Staff', 'Trial Staff', 'Loot Route Maker')
    async def wave_point_shop(self, ctx):
        """Redirects to the Staff Hub web shop. Usage: >wpshop"""
        balance = await get_wave_points(ctx.author.id)
        embed = discord.Embed(
            title="🛒 Wave Points Shop",
            description=(
                f"You have **{balance:,} Wave Points**.\n\n"
                "Prizes are now claimed on the **Staff Hub website** — no bot commands needed.\n\n"
                "**[Open the Shop](https://wavedropmaps.pages.dev/economy.html)**\n"
                "Go to the 🛒 **Shop** tab and click **Claim** on any prize."
            ),
            color=0xffaa00,
        )
        embed.set_footer(text="wavedropmaps.pages.dev/economy.html")
        await ctx.send(embed=embed)


# --- wavepoints ---
    @commands.command(name='wavepoints', aliases=['wp', 'mypoints'])
    @commands.has_any_role('Staff', 'Trial Staff', 'Loot Route Maker')
    async def wave_points_balance(self, ctx, user: discord.Member = None):
        """
        Check Wave Points balance, including interest accrual info.
        Usage: >wavepoints [user]
        """
        try:
            target  = user or ctx.author
            balance = await get_wave_points(target.id)
            info    = await _get_interest_info(target.id, balance)

            embed = discord.Embed(
                title=f"🌊 Wave Points — {target.display_name}",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.add_field(
                name="💎 Balance",
                value=f"**{balance:,} Wave Points**",
                inline=True
            )

            if info['total_earned'] > 0:
                embed.add_field(
                    name="📈 Total Interest Earned",
                    value=f"**{info['total_earned']:,} pts** (all time)",
                    inline=True
                )

            if info['eligible']:
                daily_str   = f"{info['daily_rate_pts']:.4f}"
                accrued_str = f"{info['accrued_fraction']:.4f}"
                next_str    = (
                    f"~{info['days_until_next']} day(s)"
                    if info['days_until_next'] is not None
                    else "calculating…"
                )
                embed.add_field(
                    name=f"💰 Interest ({info['apr']:.0f}% APR)",
                    value=(
                        f"~**{daily_str} pts/day** at current balance\n"
                        f"Accrued so far: `{accrued_str} pts`\n"
                        f"Next payment: **{next_str}**"
                    ),
                    inline=False
                )
            else:
                needed = INTEREST_MIN_BALANCE - balance
                embed.add_field(
                    name="💰 Interest (Tiered APR)",
                    value=(
                        f"Hold **{INTEREST_MIN_BALANCE}+ pts** to earn daily interest.\n"
                        f"You need **{needed:,} more pts** to qualify.\n\n"
                        f"{INTEREST_TIERS_TEXT}"
                    ),
                    inline=False
                )

            _bank = await database.get_central_bank()
            embed.add_field(
                name="💱 Conversions",
                value=(
                    "`>pointstovbucks` — WP → VBucks (main wallet) at the live market rate\n"
                    "`>vbuckstopoints` — VBucks → WP at the live market rate\n\n"
                    f"WP → VBucks pays a **{_bank['fee_rate_pct']:.0f}% fee**; "
                    f"VBucks → WP pays a **{_bank['fee_rate_pct']:.0f}% fee** — both go to Central Bank reserves"
                ),
                inline=False
            )

            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"❌ Error in wavepoints: {e}")
            await ctx.send(embed=create_error_embed("Wave Points Error", str(e)))



# --- wpleaderboard ---
    @commands.command(name='wpleaderboard', aliases=['wplb', 'waveleaderboard'])
    @commands.has_any_role('Staff', 'Trial Staff', 'Loot Route Maker')
    async def wp_leaderboard(self, ctx):
        """
        Show the top 20 Wave Points leaderboard with interest tier information.
        Usage: >wpleaderboard
        """
        try:
            # Fetch leaderboard data from wave_points database
            rows = await get_wave_points_leaderboard(limit=20)

            if not rows:
                await ctx.send(embed=create_error_embed(
                    "No Data",
                    "No Wave Points have been earned yet."
                ))
                return

            embed = discord.Embed(
                title="🏆 Wave Points Leaderboard",
                description="Top 20 Wave Points earners",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )

            # Medal system for top 3
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            lines  = []
            
            for i, row in enumerate(rows, start=1):
                user_id, points = row[0], row[1]
                member  = ctx.guild.get_member(user_id)
                
                # Use member display name if available, otherwise show mention
                if member:
                    name = member.display_name
                else:
                    name = f"<@{user_id}>"
                
                # Get medal or number
                medal = medals.get(i, f"`{i:>2}.`")
                
                # Format points with commas
                lines.append(f"{medal} **{name}** — `{points:,}` pts")

            embed.add_field(
                name="📊 Rankings",
                value="\n".join(lines),
                inline=False
            )
            
            # Interest tier information
            embed.add_field(
                name="💰 Daily Interest (Tiered APR)",
                value=(
                    f"Hold **{INTEREST_MIN_BALANCE}+ Wave Points** to earn daily interest.\n\n"
                    f"{INTEREST_TIERS_TEXT}\n\n"
                    "Interest accrues each day and is paid once the next whole number is reached."
                ),
                inline=False
            )
            
            embed.set_footer(
                text=f"Requested by {ctx.author} • Tiered APR interest on {INTEREST_MIN_BALANCE}+ pt balances"
            )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"❌ Error in wpleaderboard: {e}")
            await ctx.send(embed=create_error_embed(
                "Leaderboard Error",
                f"Failed to load leaderboard: {str(e)}"
            ))



# ==================== FROM commands/tipsandtricks.py ====================

# --- mytttasks ---
    @commands.command(name='mytttasks')
    async def my_tt_tasks(self, ctx):
        """Show your currently claimed T&T tasks."""
        if not _is_tt_helper(ctx):
            return await ctx.send("❌ You need the **Tips & Tricks Helper** role.")

        tasks = await db_tt.get_user_tasks(ctx.author.id)
        if not tasks:
            return await ctx.send("You have no claimed T&T tasks. Use `>tttasks` to see what's available.")

        embed = discord.Embed(
            title=f"Your Claimed Tasks ({len(tasks)})",
            color=0xFF8C1A,
            description="\n\n".join(_task_line(t) for t in tasks),
        )
        embed.set_footer(text=">completetask <id> to mark one done")
        await ctx.send(embed=embed)



# --- ttleaderboard ---
    @commands.command(name='ttleaderboard')
    async def tt_leaderboard(self, ctx):
        """Show the T&T helpers leaderboard (top 10)."""
        rows = await db_tt.get_leaderboard()
        if not rows:
            return await ctx.send("No helpers on the leaderboard yet.")

        lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, row in enumerate(rows[:10], 1):
            medal = medals.get(i, f"#{i}")
            member = ctx.guild.get_member(row['user_id'])
            name = member.display_name if member else f"User {row['user_id']}"
            pts = row['total_points']
            completed = row['tasks_completed']
            lucky = row['lucky_tasks_completed']
            lucky_str = f" ⚡{lucky}" if lucky else ""
            lines.append(f"{medal} **{name}** — {pts:g} pts · {completed} tasks{lucky_str}")

        embed = discord.Embed(
            title="🏆 Tips & Tricks Helpers Leaderboard",
            color=0xFF8C1A,
            description="\n".join(lines),
        )
        await ctx.send(embed=embed)



# ==================== FROM commands/loot_route_commands.py ====================

# --- lootroutedashboard ---
    @commands.command(name="lootroutedashboard", aliases=["lrdashboard", "lrdash"])
    @commands.has_any_role('007', '+', 'Management', 'Head Loot Routes', LOOT_ROUTE_PERMS_ROLE_ID)
    async def loot_route_dashboard(self, ctx: commands.Context):
        """📊 Snapshot: active routes, overdue, away, weekly stats"""
        if ctx.guild.id != GUILD_ID:
            await ctx.send("❌ This command only works in the main server.")
            return

        try:
            import database as _db
            pool = await _db.get_pool()
            async with pool.acquire() as db:
                # Active routes
                async with db.execute(
                    "SELECT assignment_id, user_id, assigned_at, status, reminder_count "
                    "FROM route_assignments WHERE status IN ('pending','confirmed') ORDER BY assigned_at ASC"
                ) as cur:
                    active_rows = await cur.fetchall()

                # Weekly completions & points
                async with db.execute(
                    "SELECT COUNT(*), SUM(points_awarded) FROM route_assignments "
                    "WHERE status='completed' AND completed_at >= datetime('now','-7 days') AND points_awarded > 0"
                ) as cur:
                    wk = await cur.fetchone()
                    weekly_routes = wk[0] or 0
                    weekly_points = round(wk[1] or 0, 1)

                # All-time totals
                async with db.execute(
                    "SELECT COUNT(*), SUM(points_awarded) FROM route_assignments "
                    "WHERE status='completed' AND points_awarded > 0"
                ) as cur:
                    tot = await cur.fetchone()
                    total_routes = tot[0] or 0
                    total_points = round(tot[1] or 0, 1)

            # Away users
            away_role = ctx.guild.get_role(AWAY_ROLE_ID)
            away_members = [m for m in (away_role.members if away_role else []) if not m.bot]

            now = datetime.now(timezone.utc)

            # Build active route lines — flag overdue (>4 days = penalty territory)
            active_lines = []
            overdue_lines = []
            for row in active_rows:
                a_id, u_id, assigned_str, status, reminder_count = row
                member = ctx.guild.get_member(u_id)
                name = member.display_name if member else f"<@{u_id}>"
                try:
                    assigned_dt = datetime.fromisoformat(assigned_str.replace('Z', '+00:00'))
                    if assigned_dt.tzinfo is None:
                        assigned_dt = assigned_dt.replace(tzinfo=timezone.utc)
                    hours = (now - assigned_dt).total_seconds() / 3600
                    age_str = f"{int(hours)}h" if hours < 48 else f"{hours/24:.1f}d"
                except Exception:
                    hours = 0
                    age_str = "?"

                status_icon = "🟡" if status == "pending" else "🟢"
                reminder_str = f" ·{reminder_count}🔔" if reminder_count else ""
                line = f"{status_icon} `#{a_id}` {name} — {age_str}{reminder_str}"

                if hours > 96:  # past 4-day zero-point threshold → penalty
                    overdue_lines.append(f"💀 `#{a_id}` **{name}** — {age_str}{reminder_str}")
                else:
                    active_lines.append(line)

            embed = discord.Embed(
                title="📊 Loot Route Dashboard",
                color=0xFF0080,
                timestamp=now,
            )

            # Weekly + all-time stats
            embed.add_field(
                name="📅 This Week",
                value=f"**{weekly_routes}** routes · **{weekly_points} pts** awarded",
                inline=True,
            )
            embed.add_field(
                name="🏆 All Time",
                value=f"**{total_routes}** routes · **{total_points} pts** total",
                inline=True,
            )
            embed.add_field(name="​", value="​", inline=True)

            # Active routes
            if active_lines:
                embed.add_field(
                    name=f"⏳ Active Routes ({len(active_rows) - len(overdue_lines)})",
                    value="\n".join(active_lines[:15]) or "None",
                    inline=False,
                )
            else:
                embed.add_field(name="⏳ Active Routes", value="None right now ✅", inline=False)

            # Overdue
            if overdue_lines:
                embed.add_field(
                    name=f"💀 Overdue — Penalty Accumulating ({len(overdue_lines)})",
                    value="\n".join(overdue_lines[:10]),
                    inline=False,
                )

            # Away
            if away_members:
                away_str = " · ".join(m.display_name for m in away_members[:15])
                embed.add_field(
                    name=f"🏖️ Away ({len(away_members)})",
                    value=away_str,
                    inline=False,
                )
            else:
                embed.add_field(name="🏖️ Away", value="Nobody away ✅", inline=False)

            embed.set_footer(text="🟡 pending  🟢 confirmed  🔔 reminders sent")
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Dashboard error: {e}")
            import traceback
            traceback.print_exc()



# --- updatelootrouteleaderboard ---
    @commands.command(name="updatelootrouteleaderboard")
    @commands.has_any_role('007', '+', 'Management', 'Head Loot Routes', LOOT_ROUTE_PERMS_ROLE_ID)
    async def update_leaderboard_cmd(self, ctx: commands.Context):
        """Update rotation and Loot Route Points leaderboard from database"""
        
        if ctx.guild.id != GUILD_ID:
            await ctx.send("❌ This command only works in the main server.")
            return
        
        try:
            status = await ctx.send("🔄 Syncing GitHub Pages leaderboard...")
            await auto_update_loot_route_leaderboard(self.bot, triggered_by="manual_cmd")
            await status.edit(content="✅ GitHub Pages leaderboard synced!")
        except Exception as e:
            print(f"[Update] ❌ Error: {e}")
            await ctx.send(f"❌ Error: {str(e)}")



# --- myroutes ---
    @commands.command(name="myroutes", aliases=["checkroute"])
    @commands.has_any_role('007', '+', 'Management', 'Head Loot Routes', 'Loot Route Maker', LOOT_ROUTE_PERMS_ROLE_ID)
    async def my_routes(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """
        📊 View your personal Loot Route stats, points, and last 3 assignments.
        Usage: >myroutes [@user]
        Staff can look up other users by mentioning them.
        """
        if ctx.guild.id != GUILD_ID:
            return

        # Determine target user - staff can look up others
        is_self = user is None
        if user is None:
            user = ctx.author
        else:
            # Only staff can look up other users
            allowed_roles = {'007', '+', 'Management', 'Head Loot Routes', 'Loot Route Perms'}
            author_role_names = {role.name for role in ctx.author.roles}
            if not allowed_roles.intersection(author_role_names):
                await ctx.send("❌ You can only check your own stats. Use `>myroutes` with no arguments.")
                return

        user_id = user.id
        print(f"[myroutes] Fetching stats for user {user.name} ({user_id})")

        try:
            loading_msg = await ctx.send(f"🔄 Loading stats for **{user.display_name}**...")

            # ── Fetch all data concurrently ──
            points_data, leaderboard_data, assignments, position_data = await asyncio.gather(
                get_loot_route_user_points(user_id),
                get_loot_route_points_leaderboard(limit=100),
                get_user_route_assignments(user_id, limit=3),
                get_loot_route_position(user_id),
            )

            total_points    = points_data.get('total_points', 0.0)
            routes_done     = points_data.get('routes_completed', 0)
            rotation_pos    = position_data  # int or None

            # Work out leaderboard rank
            rank = None
            for idx, (lb_uid, lb_pts, _) in enumerate(leaderboard_data, start=1):
                if lb_uid == user_id:
                    rank = idx
                    break

            # Next shop prize they're working toward
            next_prize = None
            next_prize_gap = None
            for prize_id, prize_data in SHOP_PRIZES.items():
                if total_points < prize_data['cost']:
                    next_prize = prize_data
                    next_prize_gap = prize_data['cost'] - total_points
                    break

            # ── Build embed ──
            embed = discord.Embed(
                title=f"🗺️ Loot Route Stats — {user.display_name}",
                color=0xFF0080,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_thumbnail(url=user.display_avatar.url)

            # ── Points & rank row ──
            rank_str = f"#{rank}" if rank else "Unranked"
            pos_str  = f"#{rotation_pos}" if rotation_pos else "Not in rotation"

            embed.add_field(
                name="💰 Loot Route Points",
                value=(
                    f"**{total_points} pts**\n"
                    f"Leaderboard: **{rank_str}**"
                ),
                inline=True
            )
            embed.add_field(
                name="✅ Routes Completed",
                value=f"**{routes_done}**",
                inline=True
            )
            embed.add_field(
                name="📋 Rotation Position",
                value=f"**{pos_str}**",
                inline=True
            )

            # ── Next prize progress ──
            if next_prize:
                bar_total = 10
                filled = int((total_points / next_prize['cost']) * bar_total)
                filled = min(filled, bar_total)
                bar = "█" * filled + "░" * (bar_total - filled)
                embed.add_field(
                    name=f"🎯 Next Prize: {next_prize['name']}",
                    value=(
                        f"`{bar}` {total_points}/{next_prize['cost']} pts\n"
                        f"**{next_prize_gap:.1f} pts to go!**"
                    ),
                    inline=False
                )
            else:
                embed.add_field(
                    name="🏆 Prize Status",
                    value="You can redeem **all prizes**! Use `>wpshop`",
                    inline=False
                )

            # ── Last 3 assignments ──
            if assignments:
                # Only show the first 3 assignments (cap the display)
                recent_assignments = assignments[:3]
                history_lines = []
                for a in recent_assignments:
                    status  = a['status']
                    assigned_raw = a['assigned_at']
                    confirmed_raw = a['confirmed_at']
                    reminders = a.get('reminder_count', 0)

                    # Parse assigned_at
                    try:
                        assigned_dt = datetime.fromisoformat(assigned_raw).replace(tzinfo=timezone.utc)
                        assigned_str = assigned_dt.strftime('%d %b %Y')
                    except Exception:
                        assigned_str = assigned_raw[:10] if assigned_raw else "Unknown"

                    # Status icon + speed label
                    if status == 'completed':
                        completed_raw = a.get('completed_at') or confirmed_raw
                        try:
                            completed_dt = datetime.fromisoformat(completed_raw).replace(tzinfo=timezone.utc)
                            hours_taken = (completed_dt - assigned_dt).total_seconds() / 3600

                            if hours_taken <= 12:
                                speed = "⚡ <12h"
                            elif hours_taken <= 24:
                                speed = "⚡ <24h"
                            elif hours_taken <= 48:
                                speed = "🏃 <48h"
                            elif hours_taken <= 72:
                                speed = "🚶 <3d (2 pts)"
                            elif hours_taken <= 96:
                                speed = "🚶 <4d (0 pts)"
                            else:
                                days_over = int((hours_taken - 96) / 24) + 1
                                speed = f"💀 {int(hours_taken/24)}d (-{3 + days_over}pts)"

                            status_label = f"✅ Done ({speed})"
                        except Exception:
                            status_label = "✅ Done"
                    elif status == 'confirmed':
                        status_label = "👀 In Progress (reacted, awaiting staff sign-off)"
                    elif status == 'pending':
                        reminder_note = f" — {reminders} reminder{'s' if reminders != 1 else ''}" if reminders > 0 else ""
                        status_label = f"⏳ Pending{reminder_note}"
                    elif status == 'cancelled':
                        status_label = "❌ Cancelled"
                    else:
                        status_label = f"❓ {status.title()}"

                    history_lines.append(f"`{assigned_str}` — {status_label}")

                embed.add_field(
                    name="📅 Last 3 Assignments",
                    value="\n".join(history_lines),
                    inline=False
                )
            else:
                embed.add_field(
                    name="📅 Last 3 Assignments",
                    value="No assignments yet.",
                    inline=False
                )

            # ── Footer ──
            footer_text = "Your stats" if is_self else f"Stats for {user.name}"
            embed.set_footer(text=f"{footer_text} • Use >wpshop to spend your Wave Points")

            await loading_msg.delete()
            await ctx.send(embed=embed)
            print(f"[myroutes] ✅ Sent stats for {user.name}")

        except Exception as e:
            print(f"[myroutes] ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            await ctx.send(f"[ERROR] Error fetching stats: {str(e)}")



# ==================== FROM commands/surge_route_commands.py ====================

# --- mysurges ---
    @commands.command(name="mysurges", aliases=["surgeprofile"])
    @commands.has_any_role(*SURGE_REDEEM_ROLES)
    async def my_surges(self, ctx: commands.Context, user: discord.Member = None):
        """Show surge points + recent assignments. Usage: >mysurges [@user]"""
        if ctx.guild.id != cfg.GUILD_ID:
            return
        target = user or ctx.author
        data = await sdb.get_surge_route_user_points(target.id)
        rank = await sdb.get_surge_route_position(target.id)
        recent = await sdb.get_user_surge_assignments(target.id, limit=5)
        embed = discord.Embed(title=f"⚡ Surge Profile — {target.display_name}", color=discord.Color.orange())
        embed.add_field(name="Points", value=f"**{data['total_points']:g}**", inline=True)
        embed.add_field(name="Routes", value=f"{data['routes_completed']}", inline=True)
        embed.add_field(name="Rotation Rank", value=f"#{rank}" if rank else "—", inline=True)
        if recent:
            lines = "\n".join(f"#{a['assignment_id']} · {a['status']}"
                              + (f" · {a['points_awarded']:+g}pts" if a.get('points_awarded') is not None else "")
                              for a in recent)
            embed.add_field(name="Recent", value=lines[:1024], inline=False)
        await ctx.send(embed=embed)


# --- surgedashboard ---
    @commands.command(name="surgedashboard", aliases=["surgedash", "srdash"])
    @commands.has_any_role(*SURGE_ADMIN_ROLES)
    async def surge_dashboard(self, ctx: commands.Context):
        """📊 Operational snapshot: active routes, overdue, held maps, away makers."""
        if ctx.guild.id != cfg.GUILD_ID:
            return
        active = (await sdb.get_all_pending_surge_assignments()) + (await sdb.get_all_confirmed_surge_assignments())
        active.sort(key=lambda a: a.get('assigned_at') or '')
        held = await sdb.count_surge_pending_maps()
        makers = len(await sdb.get_all_surge_route_positions())

        from database import get_pool
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(points_awarded),0) FROM surge_route_assignments "
                "WHERE status='completed' AND completed_at >= datetime('now','-7 days') AND points_awarded>0") as cur:
                wk = await cur.fetchone()
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(points_awarded),0) FROM surge_route_assignments "
                "WHERE status='completed' AND points_awarded>0") as cur:
                tot = await cur.fetchone()

        now = datetime.now(timezone.utc)
        active_lines, overdue_lines = [], []
        for a in active:
            name = f"<@{a.get('user_id')}>"
            try:
                dt = datetime.fromisoformat(str(a.get('assigned_at')).replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                hrs = (now - dt).total_seconds() / 3600
                line = f"#{a.get('assignment_id')} · {name} · {hrs:.0f}h · {a.get('status')}"
                (overdue_lines if hrs > 48 else active_lines).append(line)
            except Exception:
                active_lines.append(f"#{a.get('assignment_id')} · {name} · {a.get('status')}")

        away_role = ctx.guild.get_role(cfg.SURGE_AWAY_ROLE_ID)
        away = [m.mention for m in (away_role.members if away_role else []) if not m.bot]

        embed = discord.Embed(title="⚡ Surge Route Dashboard", color=discord.Color.orange(), timestamp=now)
        embed.add_field(name="Rotation", value=f"{makers} makers · {held} held map(s)", inline=False)
        embed.add_field(name=f"🟢 Active ({len(active_lines)})",
                        value=("\n".join(active_lines)[:1024] or "none"), inline=False)
        if overdue_lines:
            embed.add_field(name=f"🔴 Overdue >48h ({len(overdue_lines)})",
                            value="\n".join(overdue_lines)[:1024], inline=False)
        embed.add_field(name="This week", value=f"{wk[0] or 0} routes · {round(wk[1] or 0, 1)} pts", inline=True)
        embed.add_field(name="All-time", value=f"{tot[0] or 0} routes · {round(tot[1] or 0, 1)} pts", inline=True)
        embed.add_field(name=f"🏖️ Away ({len(away)})", value=(", ".join(away)[:1024] or "none"), inline=False)
        await ctx.send(embed=embed)


# ==================== FROM commands/staff_stats.py ====================

# --- staffstats group ---
    @commands.group(name='staffstats', invoke_without_command=True)
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def staffstats(self, ctx):
        """
        View statistics for staff members.
        Usage: >staffstats <subcommand> [member_id]
        """
        embed = discord.Embed(
            title="📊 Staff Stats",
            description=(
                "❌ Please specify a subcommand:\n\n"
                "`>staffstats all [user]` - View ALL stats at once\n"
                "`>staffstats message [user]` - Message activity\n"
                "`>staffstats role [user]` - Role giving stats\n"
                "`>staffstats req [user]` - Request stats\n"
                "`>staffstats modlog [user]` - Mod command stats\n\n"
                "If no member ID is provided, your own stats will be shown."
            ),
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

    # ==================== STAFFSTATS SUBCOMMANDS ====================

    @staffstats.command(name='message', help='View message activity for a staff member.')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def staffstats_message(self, ctx, member_id: int = None):
        cmd_start = time.time()
        # Send loading message
        loading_msg = await ctx.send("⏳ Loading message statistics... (this may take 1-5 minutes)")
        
        member = get_member(ctx, member_id)
        if not member:
            await loading_msg.delete()
            return await ctx.send(embed=create_error_embed(
                "Member Not Found", "The specified member could not be found in this server."
            ))

        config = await check_dates_configured(ctx, config_cache)
        if not config:
            await loading_msg.delete()
            return

        start_date = config['start_date']
        end_date = config['end_date']
        start_datetime = get_start_datetime(start_date)
        end_datetime = get_end_datetime(end_date)

        duties = _read_duties_json()
        if not duties:
            return await ctx.send(embed=create_error_embed(
                "No Data", "duties_totals.json not found or empty — duties_scan hasn't run yet this week."
            ))

        # Get last scan time and perform live scanning
        last_scan_dt = _get_last_scan_datetime(duties)
        live_updates = await self._scan_for_live_updates(ctx, last_scan_dt or start_datetime, datetime.now(timezone.utc))
        merged_duties = self._merge_duty_counts(duties, live_updates)

        meta = duties.get('_meta', {})
        messages_sent = _get_user_count(merged_duties, 'message', member.id)
        active_days_count = merged_duties.get('message', {}).get(str(member.id), {}).get('days_of_week_active', 0)

        await self.send_stat_embed(
            ctx, f"📨 Messages Sent", member, [
                ("Period", f"{meta.get('start_date', '?')} → {meta.get('end_date', '?')}"),
                ("Messages", str(messages_sent)),
                ("Days Active", str(active_days_count)),
                ("Last Synced", _last_updated(duties)),
                ("Live Updates", "✅ Included (since last scan)"),
            ]
        )
        
        # Delete loading message
        try:
            await loading_msg.delete()
        except:
            pass

        global_dates = await config_cache.get_global_dates()
        sd = global_dates.get('start_date')
        ed = global_dates.get('end_date')
        if sd and ed:
            start_dt = get_start_datetime(sd)
            end_dt = get_end_datetime(ed)
            now = datetime.now(timezone.utc)
            elapsed_hours = (now - start_dt).total_seconds() / 3600
            total_hours = (end_dt - start_dt).total_seconds() / 3600
            if elapsed_hours > 0:
                days_elapsed = elapsed_hours / 24
                daily_msg_rate = messages_sent / days_elapsed
                total_days_count = total_hours / 24
                projected_msgs = int(daily_msg_rate * total_days_count)
                await ctx.send(
                    f"\n\n🔮 **End-of-Week Prediction:**\n"
                    f"• **Current Pace:** {daily_msg_rate:.1f} messages per day\n"
                    f"• **Projected Total:** ~{projected_msgs} messages"
                )

        await ctx.send(f"✅ **Time Taken:** {time.time() - cmd_start:.2f}s")

    @staffstats.command(name='role', help='View role giving statistics for a staff member.')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def staffstats_role(self, ctx, member_id: int = None):
        cmd_start = time.time()
        # Send loading message
        loading_msg = await ctx.send("⏳ Loading role statistics... (this may take 1-5 minutes)")
        
        member = get_member(ctx, member_id)
        if not member:
            await loading_msg.delete()
            return await ctx.send(embed=create_error_embed(
                "Member Not Found", "The specified member could not be found in this server."
            ))

        config = await check_dates_configured(ctx, config_cache)
        if not config:
            await loading_msg.delete()
            return

        start_date = config['start_date']
        end_date = config['end_date']
        start_datetime = get_start_datetime(start_date)
        end_datetime = get_end_datetime(end_date)

        duties = _read_duties_json()
        if not duties:
            return await ctx.send(embed=create_error_embed(
                "No Data", "duties_totals.json not found or empty — duties_scan hasn't run yet this week."
            ))

        # Get last scan time and perform live scanning
        last_scan_dt = _get_last_scan_datetime(duties)
        live_updates = await self._scan_for_live_updates(ctx, last_scan_dt or start_datetime, datetime.now(timezone.utc))
        merged_duties = self._merge_duty_counts(duties, live_updates)

        meta = duties.get('_meta', {})
        total_count = _get_user_count(merged_duties, 'role', member.id)

        await self.send_stat_embed(
            ctx, f"Roles Given Stats for {member} (Global)", member, [
                ("Period", f"{meta.get('start_date', '?')} → {meta.get('end_date', '?')}"),
                ("Roles Given", str(total_count)),
                ("Last Synced", _last_updated(duties)),
                ("Live Updates", "✅ Included (since last scan)"),
            ]
        )
        
        # Delete loading message
        try:
            await loading_msg.delete()
        except:
            pass

        global_dates = await config_cache.get_global_dates()
        sd = global_dates.get('start_date')
        ed = global_dates.get('end_date')
        if sd and ed:
            prediction = await predict_end_of_week_performance(member.id, 'role', total_count, sd, ed)
            if prediction:
                await ctx.send(prediction)

        await ctx.send(f"✅ **Time Taken:** {time.time() - cmd_start:.2f}s")

    @staffstats.command(name='req', help='View request completion statistics for a staff member.')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def staffstats_req(self, ctx, member_id: int = None):
        cmd_start = time.time()
        # Send loading message
        loading_msg = await ctx.send("⏳ Loading request statistics... (this may take 1-5 minutes)")
        
        member = get_member(ctx, member_id)
        if not member:
            await loading_msg.delete()
            return await ctx.send(embed=create_error_embed(
                "Member Not Found", "The specified member could not be found in this server."
            ))

        config = await check_dates_configured(ctx, config_cache)
        if not config:
            await loading_msg.delete()
            return

        start_date = config['start_date']
        end_date = config['end_date']
        start_datetime = get_start_datetime(start_date)
        end_datetime = get_end_datetime(end_date)

        duties = _read_duties_json()
        if not duties:
            return await ctx.send(embed=create_error_embed(
                "No Data", "duties_totals.json not found or empty — duties_scan hasn't run yet this week."
            ))

        # Get last scan time and perform live scanning
        last_scan_dt = _get_last_scan_datetime(duties)
        live_updates = await self._scan_for_live_updates(ctx, last_scan_dt or start_datetime, datetime.now(timezone.utc))
        merged_duties = self._merge_duty_counts(duties, live_updates)

        meta = duties.get('_meta', {})
        total_count = _get_user_count(merged_duties, 'req', member.id)

        await self.send_stat_embed(
            ctx, f"Requests Completed Stats for {member} (Global)", member, [
                ("Period", f"{meta.get('start_date', '?')} → {meta.get('end_date', '?')}"),
                ("Requests Completed", str(total_count)),
                ("Last Synced", _last_updated(duties)),
                ("Live Updates", "✅ Included (since last scan)"),
            ]
        )
        
        # Delete loading message
        try:
            await loading_msg.delete()
        except:
            pass

        global_dates = await config_cache.get_global_dates()
        sd = global_dates.get('start_date')
        ed = global_dates.get('end_date')
        if sd and ed:
            prediction = await predict_end_of_week_performance(member.id, 'req', total_count, sd, ed)
            if prediction:
                await ctx.send(prediction)

        await ctx.send(f"✅ **Time Taken:** {time.time() - cmd_start:.2f}s")

    @staffstats.command(name='modlog', help='View moderation command statistics for a staff member.')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def staffstats_modlog(self, ctx, member_id: int = None):
        cmd_start = time.time()
        # Send loading message
        loading_msg = await ctx.send("⏳ Loading modlog statistics... (this may take 1-5 minutes)")
        
        member = get_member(ctx, member_id)
        if not member:
            await loading_msg.delete()
            return await ctx.send(embed=create_error_embed(
                "Member Not Found", "The specified member could not be found in this server."
            ))

        config = await check_dates_configured(ctx, config_cache)
        if not config:
            await loading_msg.delete()
            return

        start_date = config['start_date']
        end_date = config['end_date']
        start_datetime = get_start_datetime(start_date)
        end_datetime = get_end_datetime(end_date)

        duties = _read_duties_json()
        if not duties:
            return await ctx.send(embed=create_error_embed(
                "No Data", "duties_totals.json not found or empty — duties_scan hasn't run yet this week."
            ))

        # Get last scan time and perform live scanning
        last_scan_dt = _get_last_scan_datetime(duties)
        live_updates = await self._scan_for_live_updates(ctx, last_scan_dt or start_datetime, datetime.now(timezone.utc))
        merged_duties = self._merge_duty_counts(duties, live_updates)

        meta = duties.get('_meta', {})
        total_count = _get_user_count(merged_duties, 'modlog', member.id)

        await self.send_stat_embed(
            ctx, f"Moderation Commands Stats for {member} (Global)", member, [
                ("Period", f"{meta.get('start_date', '?')} → {meta.get('end_date', '?')}"),
                ("Moderation Commands", str(total_count)),
                ("Last Synced", _last_updated(duties)),
                ("Live Updates", "✅ Included (since last scan)"),
            ]
        )
        
        # Delete loading message
        try:
            await loading_msg.delete()
        except:
            pass

        global_dates = await config_cache.get_global_dates()
        sd = global_dates.get('start_date')
        ed = global_dates.get('end_date')
        if sd and ed:
            start_dt = get_start_datetime(sd)
            end_dt = get_end_datetime(ed)
            now = datetime.now(timezone.utc)
            elapsed_hours = (now - start_dt).total_seconds() / 3600
            total_hours = (end_dt - start_dt).total_seconds() / 3600
            if elapsed_hours > 0:
                days_elapsed = elapsed_hours / 24
                daily_rate = total_count / days_elapsed
                total_days_count = total_hours / 24
                projected_total = int(daily_rate * total_days_count)
                await ctx.send(
                    f"\n\n🔮 **End-of-Week Prediction:**\n"
                    f"• **Current Pace:** {daily_rate:.1f} commands per day\n"
                    f"• **Projected Total:** ~{projected_total} commands"
                )

        await ctx.send(f"✅ **Time Taken:** {time.time() - cmd_start:.2f}s")

    @staffstats.command(name='all', help='View ALL statistics at once for a staff member.')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def staffstats_all(self, ctx, member_id: int = None):
        cmd_start = time.time()
        # Send loading message
        loading_msg = await ctx.send("⏳ Loading complete statistics... (this may take 1-5 minutes)")
        
        member = get_member(ctx, member_id)
        if not member:
            await loading_msg.delete()
            return await ctx.send(embed=create_error_embed(
                "Member Not Found", "The specified member could not be found in this server."
            ))

        config = await check_dates_configured(ctx, config_cache)
        if not config:
            await loading_msg.delete()
            return

        start_date = config['start_date']
        end_date = config['end_date']
        start_datetime = get_start_datetime(start_date)
        end_datetime = get_end_datetime(end_date)

        duties = _read_duties_json()
        if not duties:
            return await ctx.send(embed=create_error_embed(
                "No Data", "duties_totals.json not found or empty — duties_scan hasn't run yet this week."
            ))

        # Get last scan time and perform live scanning
        last_scan_dt = _get_last_scan_datetime(duties)
        live_updates = await self._scan_for_live_updates(ctx, last_scan_dt or start_datetime, datetime.now(timezone.utc))
        merged_duties = self._merge_duty_counts(duties, live_updates)

        meta = duties.get('_meta', {})
        uid = member.id
        total_messages   = _get_user_count(merged_duties, 'message', uid)
        total_active_days = merged_duties.get('message', {}).get(str(uid), {}).get('days_of_week_active', 0)
        total_roles      = _get_user_count(merged_duties, 'role',    uid)
        total_requests   = _get_user_count(merged_duties, 'req',     uid)
        total_modlogs    = _get_user_count(merged_duties, 'modlog',  uid)

        embed = discord.Embed(
            title=f"📊 Complete Stats for {member.name}",
            description=f"**Period:** {meta.get('start_date','?')} → {meta.get('end_date','?')}\n**Last Synced:** {_last_updated(duties)}\n✅ **Live Updates Included** (since last scan)",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
        embed.add_field(
            name="📨 Messages Sent",
            value=f"**{total_messages}** messages\n**{total_active_days}** days active",
            inline=True
        )
        embed.add_field(name="👤 Roles Given", value=f"**{total_roles}** roles", inline=True)
        embed.add_field(name="🗺️ Map Requests", value=f"**{total_requests}** requests", inline=True)
        embed.add_field(name="🔨 Mod Commands", value=f"**{total_modlogs}** commands", inline=True)

        total_activity = total_messages + total_roles + total_requests + total_modlogs
        embed.add_field(name="📊 Total Activity", value=f"**{total_activity}** total actions", inline=True)

        goals = await database.get_user_goals(member.id)
        if goals:
            goal_lines = []
            current_map = {
                'role': total_roles,
                'req': total_requests, 'modlog': total_modlogs, 'message': total_messages
            }
            for duty, target in goals.items():
                current = current_map.get(duty, 0)
                pct = min(100, int((current / target) * 100)) if target > 0 else 0
                status = "✅" if current >= target else "🔄"
                goal_lines.append(f"{status} **{duty}:** {current}/{target} ({pct}%)")
            embed.add_field(name="🎯 Personal Goals", value="\n".join(goal_lines), inline=False)

        embed.set_footer(text=f"⚡ Fetched in {time.time() - cmd_start:.2f}s")
        
        # Delete loading message
        try:
            await loading_msg.delete()
        except:
            pass
        
        await ctx.send(embed=embed)



# ==================== FROM commands/central_bank_commands.py ====================

# --- buybond ---
    @commands.command(name='buybond')
    @commands.has_any_role('Staff', 'Trial Staff', 'Loot Route Maker')
    async def buy_bond(self, ctx, days: int = None, amount: int = None):
        """Lock Wave Points for a guaranteed return. Usage: >buybond <7|14|30|60> <amount>"""
        BOND_TIERS = {7: 15.0, 14: 30.0, 30: 60.0, 60: 100.0}

        if days is None or amount is None:
            tiers_text = "\n".join(
                f"**{d} days** → **{apr:.0f}% return** (locked {d}d, guaranteed)"
                for d, apr in BOND_TIERS.items()
            )
            embed = discord.Embed(
                title="🏦 Central Bank Bonds",
                description=(
                    "Lock your Wave Points away for a guaranteed return.\n\n"
                    f"{tiers_text}\n\n"
                    "**Usage:** `>buybond <days> <amount>`\n"
                    "**Example:** `>buybond 14 100` — locks 100 WP for 14 days at 30% return"
                ),
                color=0x00ff88
            )
            return await ctx.send(embed=embed)

        if days not in BOND_TIERS:
            return await ctx.send(
                f"❌ Invalid duration. Choose from: **7, 14, 30, or 60** days.\n"
                f"Usage: `>buybond <7|14|30|60> <amount>`"
            )

        if amount <= 0:
            return await ctx.send("❌ Please specify a valid amount of Wave Points to lock.")

        apr = BOND_TIERS[days]

        from tasks.wave_points import get_wave_points, remove_wave_points
        user_points = await get_wave_points(ctx.author.id)
        if user_points < amount:
            return await ctx.send(f"❌ You only have **{user_points}** Wave Points!")

        # Flat per-term return: the tier % is the actual return for locking the full
        # period (7d=15% of locked, 14d=30%, 30d=60%, 60d=100%) — NOT annualized.
        # The duration only sets how long the WP is locked.
        interest = round(amount * (apr / 100))
        payout = amount + interest

        if interest < 1:
            return await ctx.send(
                "❌ That amount is too small to earn any interest at this tier. "
                "Lock a bit more WP, or choose a longer duration for a higher rate."
            )

        # Deduct the locked amount
        await remove_wave_points(ctx.author.id, amount, bot=self.bot)

        # Create bond in DB
        await database_economy.create_bond(ctx.author.id, amount, payout, days=days)

        maturity_date = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%d %b %Y")

        embed = discord.Embed(
            title="🏦 Bank Bond Purchased!",
            description=f"You locked **{amount:,} WP** for **{days} days** at **{apr:.0f}% return**.",
            color=0x00ff88
        )
        embed.add_field(name="💰 Amount Locked",    value=f"**{amount:,} WP**",           inline=True)
        embed.add_field(name="📈 Projected Interest",  value=f"**+{interest:,} WP**",         inline=True)
        embed.add_field(name="🎯 Guaranteed Payout",value=f"**{payout:,} WP**",            inline=True)
        embed.add_field(name="📅 Matures On",       value=f"**{maturity_date}**",           inline=True)
        embed.add_field(name="💎 Return",           value=f"**{apr:.0f}%**",               inline=True)
        embed.set_footer(text="The Central Bank guarantees this return. Use >mybonds to check status.")
        await ctx.send(embed=embed)



# --- mybonds ---
    @commands.command(name='mybonds')
    @commands.has_any_role('Staff', 'Trial Staff', 'Loot Route Maker')
    async def my_bonds(self, ctx):
        """View your active Bank Bonds"""
        BOND_TIERS = {7: 15.0, 14: 30.0, 30: 60.0, 60: 100.0}
        bonds = await database_economy.get_active_bonds(ctx.author.id)
        if not bonds:
            return await ctx.send(
                "🏦 You have no active Bank Bonds.\n"
                "Use `>buybond <7|14|30|60> <amount>` to buy one!"
            )

        embed = discord.Embed(title="🏦 Your Active Bank Bonds", color=0x00ff88)
        now = datetime.now(timezone.utc)

        for idx, bond in enumerate(bonds, 1):
            maturity = datetime.fromisoformat(bond['maturity_date']).replace(tzinfo=timezone.utc)
            days_left = max(0, (maturity - now).days)
            interest = bond['amount_payout'] - bond['amount_locked']

            # Best-guess APR from duration
            total_days = (maturity - datetime.fromisoformat(bond['maturity_date']).replace(tzinfo=timezone.utc) + (maturity - now)).days
            apr_label = ""
            for d, apr in BOND_TIERS.items():
                if abs(days_left - d) <= 2 or days_left <= d:
                    apr_label = f"{apr:.0f}% return"
                    break

            embed.add_field(
                name=f"Bond #{idx} — {bond['amount_locked']:,} WP locked",
                value=(
                    f"**Payout:** {bond['amount_payout']:,} WP (+{interest:,} WP interest)\n"
                    f"**Time Left:** {days_left} day(s)\n"
                    f"**Matures:** {maturity.strftime('%d %b %Y')}"
                ),
                inline=False
            )
        await ctx.send(embed=embed)


# ==================== FROM commands/vbucks_system.py ====================

# --- vbucks (original) ---
    @commands.group(name='vbucks', help='VBucks commands', invoke_without_command=True)
    async def vbucks(self, ctx, user: discord.Member = None):
        """View VBucks balance for a user. Usage: >vbucks [user]"""
        try:
            target = user or ctx.author
            embed = discord.Embed(
                title=f"💰 VBucks Balance - {target.display_name}",
                description="Current VBucks totals",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )
            duty_types = [
                ('main', '💎 Main Wallet'),
                ('req', '🗺️ Map Request Helper'),
                ('role', '👤 Role Giver')
            ]
            total_vbucks = 0
            for duty_type, name in duty_types:
                vbucks = await database.get_vbucks(target.id, duty_type)
                total_vbucks += vbucks
                embed.add_field(name=name, value=f"💰 **{vbucks:,}** VBucks", inline=True)
            embed.add_field(name="Total VBucks", value=f"💎 **{total_vbucks:,}** VBucks", inline=False)
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in vbucks command: {e}")
            await ctx.send(embed=create_error_embed("VBucks Error", f"Failed to retrieve VBucks: {str(e)}"))


