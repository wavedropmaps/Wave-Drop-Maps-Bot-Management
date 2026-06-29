"""
Staff Sheet Export System - FIXED TO SCAN ONLY GENERAL_STAFF
Scans message activity and modlogs ONLY for general_staff roles (Trial Staff, Staff)
Uses ROLE_HIERARCHY only to determine which role to display in the sheet

✅ FIXED: 
- Scans ONLY members with general_staff roles from config
- Uses ROLE_HIERARCHY only for role display priority
- Fixed double task creation bug
- Added execution lock to prevent double execution at 168.5 hour mark
"""

import discord
from discord.ext import tasks, commands
import gspread
import asyncio
from asyncio import Lock
import os
import json
import math
import traceback
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Import core functions
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.helpers import (
    get_start_datetime, 
    get_end_datetime,
    extract_embed_content,
    get_readable_text_channels,
    safe_history_fetch
)
from core.cache import config_cache
import database
from tasks.wave_points import bulk_credit_wave_points

logger = logging.getLogger('discord')

# ==================== CONSTANTS ====================
CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# ==================== GLOBAL LOCK FOR EXECUTION ====================
_staff_sheet_execution_lock = Lock()
_last_execution_key = None

# Staff role hierarchy (highest to lowest priority)
# ✅ USED ONLY FOR DISPLAY - determines which role shows in the sheet
# Mirrors the live Discord role list under #roles-explained.
# Keep in sync with ROLE_HIERARCHY in wave-leaderboard/staff_sheet.html.
ROLE_HIERARCHY = [
    # ── Board Of Directors ──
    'Fruss',
    'Founder',
    'Owner',
    'Executive Director',
    # ── Head Of Key Server Functions ──
    'Head Operations | Management',
    'Head Staff | Management',
    'Head Marketing | Management',
    # ── Operations Branch (under Head Operations) ──
    'Head Drop Map Reviewing',
    'Head Drop Map Testing',
    'Head Drop Map Creation',
    'Head Loot Routes',
    'Head Tips and Tricks',
    'Head Surge Routes',
    'Head Logistics',
    # ── Marketing Branch (under Head Marketing) ──
    'Head Promotions',
    # ── Human Resources Branch (under Head Staff) ──
    'Staff Insights',
    'Head Staff Insights',
    'Head Recruiter',
    'Head of Learning & Development',
    # ── Staff Team Roles ──
    'Management',
    'Head Admin',
    'Senior Admin',
    'Admin',
    'Senior Support',
    'Support',
    'Staff',
    'Trial Staff'
]

# ==================== COLUMN WIDTH CONSTANTS ====================
# Used to size the real Google Sheet columns (A–I).
COLUMN_WIDTHS = {
    'A': 150,  # Staff Name
    'B': 120,  # Role
    'C': 180,  # Messages sent since [Date]
    'D': 150,  # Days of week active
    'E': 140,  # Rank (Messages)
    'F': 130,  # Rank (D of W)
    'G': 130,  # Mod Commands
    'H': 110,  # Rank Total
    'I': 250   # Points added from improvement cord (PINK - LAST COLUMN)
}

# ==================== MAIN EXPORT FUNCTION ====================
async def export_to_google_sheets(bot, start_date: str, end_date: str, ctx=None, is_soft: bool = False):
    """
    Export weekly staff data to Google Sheets
    
    ✅ SCANS ONLY members with general_staff roles (Trial Staff, Staff)
    ✅ USES ROLE_HIERARCHY only to determine which role to display
    """
    try:
        from googleapiclient.discovery import build
        
        logger.info(f"📊 Starting Google Sheets export for {start_date} to {end_date}")
        
        # Discord output is fully disabled — the staff sheet now lives on the
        # web hub (staff_sheet.html) and Google Sheets, so we never post here.
        # progress_msg stays None so all the legacy `if progress_msg:` blocks
        # below are inert no-ops.
        progress_msg = None

        # ==================== STEP 1: GET GUILD INFO ====================
        logger.info("🔄 STEP 1: Getting guild information...")
        
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        auto_config = config.get('automated_checks', {})
        source_guilds = auto_config.get('source_guilds', [])
        
        # ✅ GET GENERAL_STAFF ROLES TO SCAN
        staff_roles_config = config.get('staff_roles_config', {})
        general_staff_role_names = staff_roles_config.get('general_staff', [])
        
        logger.info(f"📋 General staff roles to scan: {general_staff_role_names}")
        
        if not general_staff_role_names:
            logger.error("❌ No general_staff roles configured in staff_roles_config!")
            if progress_msg:
                await progress_msg.edit(embed=discord.Embed(
                    title="❌ Export Failed",
                    description="No general_staff roles configured in config.json",
                    color=discord.Color.red()
                ))
            return None
        
        if len(source_guilds) < 2:
            logger.error("❌ Need at least 2 source guilds configured")
            if progress_msg:
                await progress_msg.edit(embed=discord.Embed(
                    title="❌ Export Failed",
                    description="Need at least 2 source guilds configured",
                    color=discord.Color.red()
                ))
            return None
        
        main_guild_id = source_guilds[0]
        improvement_guild_id = source_guilds[1]
        
        main_guild = bot.get_guild(main_guild_id)
        improvement_guild = bot.get_guild(improvement_guild_id)
        
        if not main_guild or not improvement_guild:
            logger.error("❌ Could not find source guilds")
            if progress_msg:
                await progress_msg.edit(embed=discord.Embed(
                    title="❌ Export Failed",
                    description="Could not find source guilds",
                    color=discord.Color.red()
                ))
            return None
        
        logger.info(f"📍 Main guild: {main_guild.name}")
        logger.info(f"📍 Improvement guild: {improvement_guild.name}")
        
        # ==================== STEP 2: FIND/CREATE GOOGLE SHEET ====================
        if progress_msg:
            await progress_msg.edit(embed=discord.Embed(
                title="📊 Exporting Staff Sheet",
                description=f"🔄 **Step 2/5:** Finding Google Sheet...\n\n✅ Guilds: {main_guild.name}, {improvement_guild.name}",
                color=discord.Color.blue()
            ))
        
        logger.info("📋 STEP 2: Finding or creating Google Sheet...")
        
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        
        start_dt = datetime.strptime(start_date, '%d/%m/%Y')
        end_dt = datetime.strptime(end_date, '%d/%m/%Y')
        
        target_year = end_dt.year
        target_month = end_dt.month
        month_name = end_dt.strftime('%B')
        month_abbr = end_dt.strftime('%b')
        
        logger.info(f"📋 Target: {month_name} {target_year}")
        logger.info(f"📋 Searching for EDIT sheet in folder: {target_year}/{month_abbr}")
        
        # Find year folder
        query_year = f"name = '{target_year}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        year_results = drive_service.files().list(q=query_year, fields='files(id, name)').execute()
        year_folders = year_results.get('files', [])
        
        if not year_folders:
            logger.error(f"❌ Year folder '{target_year}' not found in Google Drive")
            if progress_msg:
                await progress_msg.edit(embed=discord.Embed(
                    title="❌ Export Failed",
                    description=f"Year folder '{target_year}' not found in Google Drive",
                    color=discord.Color.red()
                ))
            return None
        
        year_folder_id = year_folders[0]['id']
        logger.info(f"✅ Found year folder: {target_year} (ID: {year_folder_id})")
        
        # Find month folder
        query_month = f"(name = '{month_abbr}' or name = '{month_name}') and '{year_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        month_results = drive_service.files().list(q=query_month, fields='files(id, name)').execute()
        month_folders = month_results.get('files', [])
        
        if not month_folders:
            logger.error(f"❌ Month folder '{month_abbr}' or '{month_name}' not found in {target_year}")
            if progress_msg:
                await progress_msg.edit(embed=discord.Embed(
                    title="❌ Export Failed",
                    description=f"Month folder '{month_abbr}' not found in {target_year} folder",
                    color=discord.Color.red()
                ))
            return None
        
        month_folder_id = month_folders[0]['id']
        month_folder_name = month_folders[0]['name']
        logger.info(f"✅ Found month folder: {month_folder_name} (ID: {month_folder_id})")
        
        # Find EDIT sheet
        query_edit = f"'{month_folder_id}' in parents and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
        edit_results = drive_service.files().list(q=query_edit, fields='files(id, name)').execute()
        all_sheets_in_folder = edit_results.get('files', [])
        
        edit_sheets = [f for f in all_sheets_in_folder if 'edit' in f['name'].lower()]
        
        logger.info(f"📋 Found {len(all_sheets_in_folder)} total sheets in {month_folder_name} folder")
        logger.info(f"📋 Found {len(edit_sheets)} sheets with 'EDIT' in name:")
        for sheet in edit_sheets:
            logger.info(f"  ✓ {sheet['name']}")
        
        if not edit_sheets:
            logger.error(f"❌ No EDIT sheet found in {month_folder_name} {target_year} folder")
            if progress_msg:
                await progress_msg.edit(embed=discord.Embed(
                    title="❌ Export Failed",
                    description=f"No EDIT sheet found in {month_folder_name} {target_year} folder",
                    color=discord.Color.red()
                ))
            return None
        
        matching_sheet = edit_sheets[0]
        new_sheet = client.open_by_key(matching_sheet['id'])
        logger.info(f"✅ Using EDIT sheet: {matching_sheet['name']} from {target_year}/{month_folder_name}")
        
        # Generate sheet name
        def ordinal(n):
            if 10 <= n % 100 <= 20:
                suffix = 'th'
            else:
                suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
            return f"{n}{suffix}"
        
        start_month = start_dt.strftime('%B')
        start_day = ordinal(start_dt.day)
        end_month = end_dt.strftime('%B')
        end_day = ordinal(end_dt.day)
        year = end_dt.year
        
        if start_month == end_month:
            new_sheet_name = f"Staff Sheet {start_month} {start_day} - {end_day} {year}"
        else:
            new_sheet_name = f"Staff Sheet {start_month} {start_day} - {end_month} {end_day} {year}"
        
        try:
            drive_service.files().update(
                fileId=matching_sheet['id'],
                body={'name': new_sheet_name}
            ).execute()
            logger.info(f"✅ Renamed sheet to: {new_sheet_name}")
        except Exception as e:
            logger.error(f"⚠️ Failed to rename sheet: {e}")
        
        sheet_name = new_sheet_name
        worksheet = new_sheet.get_worksheet(0)
        
        # Set up headers
        headers = [
            'Staff Name', 'Role', 'Messages sent since [Date]', 'Days of week active',
            'Rank (Messages)', 'Rank (D of W)', 'Mod Commands', 'Rank Total',
            'Points added from improvement cord'
        ]
        worksheet.update(values=[headers], range_name='A1:I1')
        
        # Set column widths
        sheets_service = build('sheets', 'v4', credentials=creds)
        
        requests = []
        column_widths_list = [
            COLUMN_WIDTHS['A'], COLUMN_WIDTHS['B'], COLUMN_WIDTHS['C'],
            COLUMN_WIDTHS['D'], COLUMN_WIDTHS['E'], COLUMN_WIDTHS['F'],
            COLUMN_WIDTHS['G'], COLUMN_WIDTHS['H'], COLUMN_WIDTHS['I']
        ]
        
        logger.info(f"📏 Setting column widths: {column_widths_list}")
        
        for idx, width in enumerate(column_widths_list):
            requests.append({
                'updateDimensionProperties': {
                    'range': {
                        'sheetId': worksheet.id,
                        'dimension': 'COLUMNS',
                        'startIndex': idx,
                        'endIndex': idx + 1
                    },
                    'properties': {
                        'pixelSize': width
                    },
                    'fields': 'pixelSize'
                }
            })
        
        batch_update_request = {'requests': requests}
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=new_sheet.id,
            body=batch_update_request
        ).execute()
        
        logger.info("✅ Column widths adjusted")
        
        # Apply colors
        worksheet.format('A1:I1', {
            'backgroundColor': {'red': 0.78, 'green': 0.78, 'blue': 0.78},
            'textFormat': {'bold': True}
        })
        
        worksheet.format('A:A', {'backgroundColor': {'red': 0.82, 'green': 0.89, 'blue': 0.95}})
        worksheet.format('B:B', {'backgroundColor': {'red': 0.82, 'green': 0.89, 'blue': 0.95}})
        worksheet.format('C:C', {'backgroundColor': {'red': 0.776, 'green': 0.843, 'blue': 0.659}})
        worksheet.format('D:D', {'backgroundColor': {'red': 0.706, 'green': 0.655, 'blue': 0.839}})
        worksheet.format('E:E', {'backgroundColor': {'red': 0.714, 'green': 0.843, 'blue': 0.659}})
        worksheet.format('F:F', {'backgroundColor': {'red': 0.706, 'green': 0.655, 'blue': 0.839}})
        worksheet.format('G:G', {'backgroundColor': {'red': 0.957, 'green': 0.800, 'blue': 0.800}})
        worksheet.format('H:H', {'backgroundColor': {'red': 0.996, 'green': 0.569, 'blue': 0.220}})
        worksheet.format('I:I', {'backgroundColor': {'red': 0.835, 'green': 0.651, 'blue': 0.741}})
        
        # ==================== STEP 3: SCAN DATA ====================
        start_datetime = get_start_datetime(start_date)
        end_datetime = get_end_datetime(end_date)
        
        main_config = await config_cache.get_guild_config(main_guild_id)
        improvement_config = await config_cache.get_guild_config(improvement_guild_id)
        
        # Role priority for display (case-insensitive keys)
        role_priority = {role.lower(): idx for idx, role in enumerate(ROLE_HIERARCHY)}
        
        # ✅ GET STAFF MEMBERS - ONLY FROM GENERAL_STAFF ROLES
        all_staff_members = set()
        for role_name in general_staff_role_names:
            role = discord.utils.find(lambda r, n=role_name: r.name.lower() == n.lower(), main_guild.roles)
            if role:
                staff_with_role = [m for m in role.members if not m.bot]
                all_staff_members.update(staff_with_role)
                logger.info(f"✅ Found {len(staff_with_role)} members with '{role_name}' role")
            else:
                logger.warning(f"⚠️ Role '{role_name}' not found in {main_guild.name}")
        
        all_staff_members = list(all_staff_members)
        logger.info(f"👥 Found {len(all_staff_members)} total general staff members to scan")
        
        if not all_staff_members:
            logger.warning("⚠️ No general staff members found!")
            if progress_msg:
                await progress_msg.edit(embed=discord.Embed(
                    title="❌ Export Failed",
                    description="No general staff members found!",
                    color=discord.Color.red()
                ))
            return None
        
        # Scan messages
        if progress_msg:
            await progress_msg.edit(embed=discord.Embed(
                title="📊 Exporting Staff Sheet",
                description=(
                    f"🔄 **Step 3/5:** Scanning message activity...\n\n"
                    f"✅ Sheet: {sheet_name}\n"
                    f"✅ General staff found: {len(all_staff_members)}\n"
                    f"📨 Scanning messages in {main_guild.name}..."
                ),
                color=discord.Color.blue()
            ))
        
        logger.info("📨 Scanning message activity...")
        main_message_stats = {}
        improvement_message_stats = {}
        
        # Scan main guild
        main_text_channels = get_readable_text_channels(main_guild)
        logger.info(f"📖 Scanning {len(main_text_channels)} channels in {main_guild.name}")
        
        for channel in main_text_channels:
            try:
                messages = await safe_history_fetch(channel, limit=5000, after=start_datetime, before=end_datetime)
                
                for message in messages:
                    if message.author in all_staff_members and not message.author.bot:
                        if message.author not in main_message_stats:
                            main_message_stats[message.author] = {'count': 0, 'days': set()}
                        main_message_stats[message.author]['count'] += 1
                        main_message_stats[message.author]['days'].add(message.created_at.date())
            except Exception as e:
                logger.error(f"Error scanning {channel.name}: {e}")
        
        # Scan improvement guild
        if progress_msg:
            await progress_msg.edit(embed=discord.Embed(
                title="📊 Exporting Staff Sheet",
                description=(
                    f"🔄 **Step 3/5:** Scanning message activity...\n\n"
                    f"✅ Sheet: {sheet_name}\n"
                    f"✅ General staff found: {len(all_staff_members)}\n"
                    f"✅ {main_guild.name}: {len(main_text_channels)} channels scanned\n"
                    f"📨 Scanning {improvement_guild.name}..."
                ),
                color=discord.Color.blue()
            ))
        
        improvement_text_channels = get_readable_text_channels(improvement_guild)
        logger.info(f"📖 Scanning {len(improvement_text_channels)} channels in {improvement_guild.name}")
        
        for channel in improvement_text_channels:
            try:
                messages = await safe_history_fetch(channel, limit=5000, after=start_datetime, before=end_datetime)
                
                for message in messages:
                    if message.author in all_staff_members and not message.author.bot:
                        if message.author not in improvement_message_stats:
                            improvement_message_stats[message.author] = {'count': 0, 'days': set()}
                        improvement_message_stats[message.author]['count'] += 1
                        improvement_message_stats[message.author]['days'].add(message.created_at.date())
            except Exception as e:
                logger.error(f"Error scanning {channel.name}: {e}")
        
        logger.info(f"✅ Message scan complete")
        
        # Scan modlogs
        if progress_msg:
            await progress_msg.edit(embed=discord.Embed(
                title="📊 Exporting Staff Sheet",
                description=(
                    f"🔄 **Step 3/5:** Scanning moderation logs...\n\n"
                    f"✅ Sheet: {sheet_name}\n"
                    f"✅ General staff found: {len(all_staff_members)}\n"
                    f"✅ Message channels scanned\n"
                    f"🔨 Scanning modlogs..."
                ),
                color=discord.Color.blue()
            ))
        
        logger.info("🔨 Scanning modlog activity...")
        main_modlog_stats = {}
        improvement_modlog_stats = {}
        
        # Scan main guild modlogs
        if main_config.get('modlogs_channel_id'):
            modlogs_channel = main_guild.get_channel(main_config['modlogs_channel_id'])
            if modlogs_channel:
                messages = await safe_history_fetch(modlogs_channel, limit=5000, after=start_datetime, before=end_datetime)
                
                for message in messages:
                    for embed in message.embeds:
                        content = extract_embed_content(embed)
                        for member in all_staff_members:
                            if str(member.id) in content:
                                if member not in main_modlog_stats:
                                    main_modlog_stats[member] = 0
                                main_modlog_stats[member] += 1
                                break
        
        # Scan improvement guild modlogs
        if improvement_config.get('modlogs_channel_id'):
            modlogs_channel = improvement_guild.get_channel(improvement_config['modlogs_channel_id'])
            if modlogs_channel:
                messages = await safe_history_fetch(modlogs_channel, limit=5000, after=start_datetime, before=end_datetime)
                
                for message in messages:
                    for embed in message.embeds:
                        content = extract_embed_content(embed)
                        for member in all_staff_members:
                            if str(member.id) in content:
                                if member not in improvement_modlog_stats:
                                    improvement_modlog_stats[member] = 0
                                improvement_modlog_stats[member] += 1
                                break
        
        logger.info(f"✅ Modlog scan complete")
        
        # ==================== STEP 4: PROCESS DATA AND WRITE ====================
        if progress_msg:
            await progress_msg.edit(embed=discord.Embed(
                title="📊 Exporting Staff Sheet",
                description=(
                    f"🔄 **Step 4/5:** Writing data to sheet...\n\n"
                    f"✅ All scanning complete\n"
                    f"📝 Processing {len(all_staff_members)} general staff members..."
                ),
                color=discord.Color.blue()
            ))
        
        logger.info("📊 STEP 4: Processing data and writing to sheet...")
        
        staff_data_rows = []
        
        for member in all_staff_members:
            try:
                # ✅ Find highest role FROM ROLE_HIERARCHY for display
                top_role = None
                highest_priority = 999
                
                for role in member.roles:
                    if role.name.lower() in role_priority:
                        priority = role_priority[role.name.lower()]
                        if priority < highest_priority:
                            highest_priority = priority
                            top_role = role.name
                
                if not top_role:
                    # If no role from hierarchy, use their highest visible role
                    top_role = member.top_role.name if member.top_role else "Member"
                
                # Get message data
                main_data = main_message_stats.get(member, {'count': 0, 'days': set()})
                improvement_data = improvement_message_stats.get(member, {'count': 0, 'days': set()})
                
                total_messages = main_data['count'] + improvement_data['count']
                all_days = main_data['days'].union(improvement_data['days'])
                days_active = len(all_days)
                
                # Rank calculations (capped at 100)
                # 70 messages = rank 100 (lowered from 100 to de-emphasize message grinding)
                rank_messages = min(math.ceil((total_messages / 70) * 100), 100)
                rank_days = min(math.ceil((days_active / 7) * 100), 100)
                
                # Get modlog data
                main_mods = main_modlog_stats.get(member, 0)
                improvement_mods = improvement_modlog_stats.get(member, 0)
                total_mod_commands = main_mods + improvement_mods
                
                # Calculate rank total
                rank_total_base = math.ceil((rank_messages + rank_days) / 2)
                improvement_points = improvement_data['count']
                rank_total = min(math.ceil(rank_total_base + improvement_points + total_mod_commands), 100)
                
                # Discord's display_avatar returns the user's animated/static avatar
                # if set, otherwise the default embed avatar — so this always works.
                try:
                    avatar_url = str(member.display_avatar.url)
                except Exception:
                    avatar_url = None

                staff_data_rows.append({
                    'name': member.name,
                    'role': top_role,
                    'role_priority': highest_priority,
                    'user_id': member.id,
                    'avatar_url': avatar_url,
                    'data': [
                        member.name,
                        top_role,
                        total_messages,
                        days_active,
                        rank_messages,
                        rank_days,
                        total_mod_commands,
                        rank_total,
                        improvement_points
                    ]
                })
                
            except Exception as e:
                logger.error(f"❌ Error processing {member.name}: {e}")
                continue
        
        # Sort by role then rank total
        staff_data_rows.sort(key=lambda x: (x['role_priority'], -x['data'][7]))
        
        logger.info(f"📊 Prepared {len(staff_data_rows)} staff records")
        
        # Write to sheet
        final_data = [row['data'] for row in staff_data_rows]
        
        if final_data:
            range_to_update = f'A2:I{len(final_data) + 1}'
            worksheet.update(values=final_data, range_name=range_to_update)
            logger.info(f"✅ Wrote {len(final_data)} staff records to sheet")

            # ============================================================
            # PUSH JSON TO WAVE STAFF HUB (wave-leaderboard repo)
            # Fires alongside the Google Sheets write so the public hub at
            # wavedropmaps.github.io/wave-leaderboard/wave_staff_hub.html
            # always has the same data as the Discord screenshot.
            # ============================================================
            try:
                from tasks.staff_hub_writer import push_staff_sheet_to_github
                iso_year, iso_week, _ = end_dt.isocalendar()
                week_id = f"{iso_year}-W{iso_week:02d}"
                staff_payload = {
                    "_meta": {
                        "start_date":   start_date,
                        "end_date":     end_date,
                        "last_updated": datetime.now(timezone.utc).isoformat(),
                        "sheet_name":   new_sheet_name,
                    },
                    "staff": [
                        {
                            "name":               r['data'][0],
                            "role":               r['data'][1],
                            "messages":           r['data'][2],
                            "days_active":        r['data'][3],
                            "rank_messages":      r['data'][4],
                            "rank_days":          r['data'][5],
                            "mod_commands":       r['data'][6],
                            "rank_total":         r['data'][7],
                            "improvement_points": r['data'][8],
                            "user_id":            r['user_id'],
                            "avatar_url":         r.get('avatar_url'),
                        }
                        for r in staff_data_rows
                    ]
                }
                logger.info(f"🌐 Pushing staff sheet JSON to wave-leaderboard ({week_id})...")
                await push_staff_sheet_to_github(staff_payload, week_id)
            except Exception as e:
                # Never let a hub push failure block the Google Sheets export
                logger.error(f"⚠️ Failed to push staff sheet JSON to GitHub: {e}", exc_info=True)

            # Add average row
            avg_row_num = len(final_data) + 2
            
            avg_formulas = [
                'Average',
                '',
                f'=ROUND(AVERAGE(C2:C{avg_row_num - 1}), 0)',
                f'=ROUND(AVERAGE(D2:D{avg_row_num - 1}), 0)',
                f'=ROUND(AVERAGE(E2:E{avg_row_num - 1}), 0)',
                f'=ROUND(AVERAGE(F2:F{avg_row_num - 1}), 0)',
                f'=ROUND(AVERAGE(G2:G{avg_row_num - 1}), 0)',
                f'=ROUND(AVERAGE(H2:H{avg_row_num - 1}), 0)',
                f'=ROUND(AVERAGE(I2:I{avg_row_num - 1}), 0)'
            ]
            
            worksheet.update(
                range_name=f'A{avg_row_num}:I{avg_row_num}',
                values=[avg_formulas],
                value_input_option='USER_ENTERED'
            )

            from tasks.wave_points import bulk_credit_wave_points
            wp_records = [{'user_id': r['user_id'], 'rank_total': r['data'][7]} for r in staff_data_rows]
            await bulk_credit_wave_points(wp_records, bot=bot)
            
            # 🎉 DM users who reached Rank 100 (earned 10 Wave Points)
            rank_100_user_ids = [rec['user_id'] for rec in wp_records if rec['rank_total'] >= 100]
            if rank_100_user_ids:
                logger.info(f"[Staff Sheet] 🎉 Preparing DM for {len(rank_100_user_ids)} rank‑100 users")
                for uid in rank_100_user_ids:
                    try:
                        user = bot.get_user(uid) or await bot.fetch_user(uid)
                        dm_text = (
                            "🎉 **Congratulations!**\n"
                            "You have earned **10 Wave Points** for reaching **Rank 100** in the staff sheet.\n"
                            "Thank you for your dedication to the community!\n"
                            "Keep on supporting the free drop maps cause!"
                        )
                        await user.send(dm_text)
                        logger.info(f"[Staff Sheet] ✅ Sent rank‑100 DM to user {uid}")
                    except discord.Forbidden:
                        logger.warning(f"[Staff Sheet] ⚠️ Could not DM user {uid} – DMs are disabled")
                    except Exception as e:
                        logger.error(f"[Staff Sheet] ❌ Error DMing user {uid}: {e}", exc_info=True)
                    await asyncio.sleep(0.5)
                        
            # Format average row (yellow/gold)
            worksheet.format(f'A{avg_row_num}:I{avg_row_num}', {
                'backgroundColor': {'red': 1.0, 'green': 0.851, 'blue': 0.400},
                'textFormat': {'bold': True}
            })
            
            logger.info(f"✅ Added average row at row {avg_row_num}")
        else:
            logger.warning("⚠️ No staff data to write!")
        
        sheet_url = new_sheet.url
        logger.info(f"✅ Google Sheets export complete: {sheet_url}")

        # ── Discord posting removed ──────────────────────────────────────────
        # The staff sheet is now published to the web hub (staff_sheet.html via
        # push_staff_sheet_to_github) and Google Sheets. We no longer screenshot
        # the sheet or post images / @everyone pings into Discord channels.

        return sheet_url
        
    except Exception as e:
        logger.error(f"❌ Google Sheets export failed: {e}")
        logger.error(traceback.format_exc())
        
        if progress_msg:
            await progress_msg.edit(embed=discord.Embed(
                title="❌ Export Failed",
                description=f"Error: {str(e)[:200]}",
                color=discord.Color.red()
            ))
        
        return None

# ==================== EXACT TIMING AUTOMATION ====================

STAFF_SHEET_HOURS = 167.5  # ✅ FIXED: Changed from 168.5 to 167.5 for 1.5-hour buffer before Full Week Insights (169.0h)

def get_global_dates_from_config():
    """Get global dates from config.json"""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        global_dates = config.get('global_dates', {})
        start_date = global_dates.get('start_date')
        end_date = global_dates.get('end_date')
        
        if not start_date or not end_date:
            global_config = config.get('global', {})
            start_date = global_config.get('start_date')
            end_date = global_config.get('end_date')
        
        return start_date, end_date
    except Exception as e:
        logger.error(f"Failed to load config.json: {e}")
        return None, None

async def run_staff_sheet_at_exact_time(bot):
    """Run staff sheet at EXACTLY 168:30:00 after week start"""
    global _last_execution_key
    
    await bot.wait_until_ready()
    logger.info(f"✅ Staff sheet task is now active and waiting for triggers")
    
    while True:
        try:
            start_date, end_date = get_global_dates_from_config()
            
            if not start_date or not end_date:
                logger.debug("⏸️ No global dates configured, waiting...")
                await asyncio.sleep(300)
                continue
            
            # ✅ CREATE UNIQUE KEY FOR THIS WEEK
            execution_key = f"{start_date}_{end_date}"
            
            start_datetime = get_start_datetime(start_date)
            target_time = start_datetime + timedelta(hours=STAFF_SHEET_HOURS)
            now = datetime.now(timezone.utc)
            
            with open('config.json', 'r') as f:
                config = json.load(f)
            
            auto_config = config.get('automated_checks', {})
            report_guild_id = auto_config.get('report_guild_id', 1041450125391835186)
            
            # ✅ CHECK IF ALREADY EXECUTED IN MEMORY (FAST CHECK)
            if _last_execution_key == execution_key:
                logger.info(f"⏭️ Staff sheet already executed for {execution_key} (memory check), waiting for new week...")
                wait_until = start_datetime + timedelta(hours=168 + 24)
                wait_seconds = (wait_until - now).total_seconds()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                else:
                    # ✅ FIX: Sleep for 5 minutes to prevent infinite loop spam
                    await asyncio.sleep(300)
                continue
            
            already_sent = await database.check_report_already_sent(
                report_guild_id,
                'staff_sheet',
                'Staff Sheet',
                start_date,
                end_date
            )
            
            if already_sent:
                logger.info(f"⏭️ Staff sheet already sent for {start_date} (database check), waiting for new week...")
                _last_execution_key = execution_key  # ✅ MARK AS DONE
                wait_until = start_datetime + timedelta(hours=168 + 24)
                wait_seconds = (wait_until - now).total_seconds()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                else:
                    # ✅ FIX: Sleep for 5 minutes to prevent infinite loop spam
                    await asyncio.sleep(300)
                continue
            
            time_diff = (target_time - now).total_seconds()
            
            if time_diff < -7200:
                hours_late = abs(time_diff) / 3600
                logger.warning(f"⚠️ Staff sheet trigger missed by {hours_late:.1f} hours - TOO LATE, skipping")
                wait_until = start_datetime + timedelta(hours=168 + 24)
                wait_seconds = (wait_until - now).total_seconds()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                else:
                    # ✅ FIX: Sleep for 5 minutes to prevent infinite loop spam
                    await asyncio.sleep(300)
                continue
            
            if time_diff > 0:
                logger.info(f"⏰ Staff sheet scheduled for {target_time} (in {time_diff/3600:.1f} hours)")
                logger.info(f"   Waiting {time_diff:.0f} seconds...")
                await asyncio.sleep(time_diff)
                
                now = datetime.now(timezone.utc)
                actual_diff = (now - target_time).total_seconds()
                
                if actual_diff > 7200:
                    logger.warning(f"⚠️ Staff sheet woke up {actual_diff/3600:.1f} hours late - skipping")
                    wait_until = start_datetime + timedelta(hours=168 + 24)
                    wait_seconds = (wait_until - now).total_seconds()
                    if wait_seconds > 0:
                        await asyncio.sleep(wait_seconds)
                    else:
                    # ✅ FIX: Sleep for 5 minutes to prevent infinite loop spam
                        await asyncio.sleep(300)
                    continue  # ✅ CRITICAL FIX: MOVED INSIDE THE IF BLOCK! Now only executes if oversleep detected
            
                    # ✅ If we reach here, we woke up on-time! Fall through to execution code.
            
            # ✅ USE LOCK TO PREVENT DOUBLE EXECUTION
            async with _staff_sheet_execution_lock:
                # ✅ DOUBLE-CHECK AFTER ACQUIRING LOCK
                if _last_execution_key == execution_key:
                    logger.warning(f"⚠️ Another instance already executed {execution_key}, skipping")
                    wait_until = start_datetime + timedelta(hours=168 + 24)
                    wait_seconds = (wait_until - datetime.now(timezone.utc)).total_seconds()
                    if wait_seconds > 0:
                        await asyncio.sleep(wait_seconds)
                    else:
                        # ✅ FIX: Sleep for 5 minutes to prevent infinite loop spam
                        await asyncio.sleep(300)
                    continue  # ✅ FIXED: now correctly inside the if block
                
                # ✅ CHECK DATABASE ONE MORE TIME
                already_sent = await database.check_report_already_sent(
                    report_guild_id,
                    'staff_sheet',
                    'Staff Sheet',
                    start_date,
                    end_date
                )
                
                if already_sent:
                    logger.warning(f"⚠️ Database shows {execution_key} already sent, skipping")
                    _last_execution_key = execution_key
                    wait_until = start_datetime + timedelta(hours=168 + 24)
                    wait_seconds = (wait_until - datetime.now(timezone.utc)).total_seconds()
                    if wait_seconds > 0:
                        await asyncio.sleep(wait_seconds)
                    else:
                        # ✅ FIX: Sleep for 5 minutes to prevent infinite loop spam
                        await asyncio.sleep(300)
                    continue  # ✅ FIXED: now correctly inside the if block
                
                logger.info(f"📋 ========================================")
                logger.info(f"📋 RUNNING STAFF SHEET EXPORT")
                logger.info(f"📋 Period: {start_date} → {end_date}")
                logger.info(f"📋 Execution Key: {execution_key}")
                logger.info(f"📋 ========================================")
                
                sheet_url = await export_to_google_sheets(
                    bot=bot,
                    start_date=start_date,
                    end_date=end_date,
                    ctx=None,
                    is_soft=False
                )
                
                if sheet_url:
                    await database.mark_report_sent(
                        report_guild_id,
                        'staff_sheet',
                        'Staff Sheet',
                        start_date,
                        end_date
                    )
                    
                    # ✅ MARK AS EXECUTED IN MEMORY
                    _last_execution_key = execution_key
                    
                    logger.info("✅ ========================================")
                    logger.info("✅ STAFF SHEET EXPORT COMPLETED")
                    logger.info(f"✅ URL: {sheet_url}")
                    logger.info(f"✅ Marked {execution_key} as complete")
                    logger.info("✅ ========================================")
                else:
                    logger.error("❌ Staff sheet export failed")
            
            wait_until = start_datetime + timedelta(hours=168 + 24)
            wait_seconds = (wait_until - datetime.now(timezone.utc)).total_seconds()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
        
        except Exception as e:
            logger.error(f"❌ Error in staff sheet task: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(300)

# ==================== COG SETUP ====================

class StaffSheetAutomation(discord.ext.commands.Cog):
    """Automated staff sheet export with exact timing"""
    
    def __init__(self, bot):
        self.bot = bot
        self.task = None
    
    async def cog_load(self):
        """Retired — staff sheet now runs as part of weekly_checks at 168h."""
        logger.info("ℹ️ StaffSheetAutomation: 167.5h trigger retired; engagement data flows through duties_scan → weekly_checks.")
    
    def cog_unload(self):
        """Stop task when cog unloads"""
        if self.task:
            self.task.cancel()
        logger.info("🛑 Staff sheet automation stopped")

async def setup(bot):
    await bot.add_cog(StaffSheetAutomation(bot))