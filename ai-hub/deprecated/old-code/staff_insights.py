"""
Staff Insights Export System - FIXED VERSION
Exports staff activity data to Google Sheets with comprehensive tracking
Includes both Full Week (168h) and Mid-Week (72h) exports

FIXES APPLIED:
- ✅ Smooth gradient: Dark Yellow → White (not multi-color)
- ✅ Formulas updated AFTER reorganization (so they don't get deleted)
- ✅ ONLY scans users with DUTY-SPECIFIC ROLES
- ✅ ALL users with duty role added to sheet (even with 0 activity)
- ✅ ONLY removes users who lost their duty role
- ✅ Reorganization happens EVERY TIME (not just full week)
- ✅ Column B formatting cleared (removes underlines)
"""

import discord
import logging
import traceback
import re
import database
import asyncio
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import gspread
import io

from core.constants import CREDENTIALS_FILE, SCOPES
from core.helpers import (
    get_automation_config,
    parse_date,
    get_start_datetime,
    get_end_datetime,
    check_if_user_is_away,
    extract_embed_content,
    get_readable_text_channels,
    safe_history_fetch,
    is_reply_to_other,
    web_avatar_url,
)
from core.cache import config_cache

logger = logging.getLogger('discord')

# ==================== RETRY HELPER ====================

async def _sheets_execute_with_retry(callable_fn, description: str, max_attempts: int = 3):
    """
    Execute a Google Sheets API call with exponential back-off retry.
    
    callable_fn  — a zero-argument callable that performs .execute() and returns the result
    description  — human-readable label used in log messages
    
    Returns the API result on success, raises the last exception on total failure.
    """
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = callable_fn()
            if attempt > 1:
                logger.info(f"    ✅ {description} succeeded on attempt {attempt}")
            return result
        except Exception as e:
            last_err = e
            if attempt < max_attempts:
                wait = attempt * 5  # 5 s, 10 s
                logger.warning(f"    ⚠️ {description} failed (attempt {attempt}/{max_attempts}): {e}")
                logger.info(f"    ⏳ Retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.error(f"    ❌ {description} failed after {max_attempts} attempts: {e}")
    raise last_err

# ==================== GOOGLE DRIVE FOLDER ====================
STAFF_INSIGHTS_FOLDER_ID = "1wE3GoIsOwfWpfp39Hhn-j6z0regmXbDv"

# ==================== ROLE HIERARCHY ====================

ROLE_HIERARCHY = [
    'Founder',
    'Owner',
    'Executive Director',
    'Head Operations | Management',
    'Head Staff | Management',
    'Head Marketing | Management',
    'Head Dropmaps',
    'Head Staff Insights',
    'Head Recruiter',
    'Head Promotions',
    'Head Logistics',
    'Management',
    'Head Admin',
    'Admin',
    'Senior Support',
    'Support',
    'Staff',
    'Trial Staff'
]


def get_highest_role(member):
    """Get the highest role for a member based on the role hierarchy"""
    if not member:
        return 'Unknown'
    
    member_role_names = [role.name for role in member.roles]
    
    for role_name in ROLE_HIERARCHY:
        if role_name in member_role_names:
            return role_name
    
    return 'Staff'

# ==================== GET STAFF WITH DUTY-SPECIFIC ROLES ====================

async def get_staff_with_duty_roles(bot, source_guilds, duty_type):
    """Get staff members who have a SPECIFIC DUTY ROLE"""
    import json
    import os
    
    config_path = 'config.json'
    if not os.path.exists(config_path):
        logger.error("  ❌ config.json not found, cannot determine staff roles")
        return {}
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    staff_roles_config = config.get('staff_roles_config', {})
    
    duty_to_config_key = {
        'req': 'request_helpers',
        'modlog': 'general_staff',
        'message': 'general_staff'
    }
    
    config_key = duty_to_config_key.get(duty_type)
    
    if not config_key:
        logger.error(f"  ❌ Unknown duty type: {duty_type}")
        return {}
    
    role_names_list = staff_roles_config.get(config_key, [])
    
    if not role_names_list:
        logger.warning(f"  ⚠️ No roles configured for '{config_key}' in config.json")
        return {}
    
    logger.info(f"  👥 Looking for users with roles: {role_names_list}")
    
    staff_with_duty = {}
    
    for guild_id in source_guilds:
        guild = bot.get_guild(guild_id)
        if not guild:
            logger.warning(f"  ⚠️ Guild {guild_id} not found")
            continue
        
        logger.info(f"  🔍 Scanning guild: {guild.name}")
        
        matching_roles = []
        for role in guild.roles:
            for role_name in role_names_list:
                if role_name.lower() in role.name.lower():
                    matching_roles.append(role)
                    logger.info(f"    ✅ Found '{duty_type}' role: {role.name} ({role.id}) with {len(role.members)} members")
                    break
        
        if not matching_roles:
            logger.warning(f"    ⚠️ No roles found for duty '{duty_type}' (looking for: {role_names_list})")
            continue
        
        for role in matching_roles:
            for member in role.members:
                if member.bot:
                    continue
                
                if member.id not in staff_with_duty:
                    staff_with_duty[member.id] = member.name
                    logger.debug(f"    ➕ Added {member.name} (ID: {member.id})")
    
    logger.info(f"  ✅ Found {len(staff_with_duty)} users with '{duty_type}' duty role(s)")
    return staff_with_duty

# ==================== SCANNING FUNCTIONS ====================

async def scan_duty_activity(bot, duty_type: str, source_guilds: list, start_datetime, end_datetime, all_staff_dict: dict):
    """Scan activity for a specific duty type"""
    stats = {}
    for user_id, user_name in all_staff_dict.items():
        stats[user_id] = {'count': 0, 'name': user_name}
    
    logger.info(f"  🔍 Scanning {duty_type} activity from {start_datetime} to {end_datetime}")
    logger.info(f"  👥 Initialized {len(stats)} users with {duty_type} duty (all start at 0)")
    
    for guild_id in source_guilds:
        guild = bot.get_guild(guild_id)
        if not guild:
            logger.warning(f"  ⚠️ Guild {guild_id} not found, skipping")
            continue
        
        guild_config = await config_cache.get_guild_config(guild_id)
        
        if duty_type == 'role':
            logger.info(f"  👤 Scanning role updates in {guild.name}...")
            
            try:
                entries_checked = 0
                async for entry in guild.audit_logs(
                    action=discord.AuditLogAction.member_role_update,
                    after=start_datetime,
                    before=end_datetime,
                    limit=None
                ):
                    entries_checked += 1
                    if entry.user.id in all_staff_dict and not entry.user.bot:
                        user_id = entry.user.id
                        if user_id not in stats:
                            stats[user_id] = {'count': 0, 'name': all_staff_dict[user_id]}
                        stats[user_id]['count'] += 1
                
                logger.info(f"  📋 Checked {entries_checked} audit log entries in {guild.name}")
            except discord.Forbidden:
                logger.warning(f"  ⚠️ No permission to view audit logs in {guild.name}")
            except Exception as e:
                logger.error(f"  ❌ Error scanning roles in guild {guild_id}: {e}")
        
        elif duty_type == 'req':
            channel_id = guild_config.get('request_channel_id')
            if not channel_id:
                logger.debug(f"  ℹ️ No request channel configured for guild {guild_id}")
                continue
            
            channel = guild.get_channel(channel_id)
            if not channel:
                logger.warning(f"  ⚠️ Request channel {channel_id} not found in guild {guild_id}")
                continue
            
            try:
                messages = await safe_history_fetch(channel, limit=5000, after=start_datetime, before=end_datetime)
                logger.info(f"  📨 Fetched {len(messages)} messages from request channel in {guild.name}")
                
                for message in messages:
                    # Only count messages where staff replied to someone else
                    # (an actual help action), not every message they post here.
                    if (message.author.id in all_staff_dict and not message.author.bot
                            and is_reply_to_other(message)):
                        user_id = message.author.id
                        if user_id not in stats:
                            stats[user_id] = {'count': 0, 'name': all_staff_dict[user_id]}
                        stats[user_id]['count'] += 1
                        
            except Exception as e:
                logger.error(f"  ❌ Error scanning requests in guild {guild_id}: {e}")
        
        elif duty_type == 'modlog':
            channel_id = guild_config.get('modlogs_channel_id')
            if not channel_id:
                logger.debug(f"  ℹ️ No modlog channel configured for guild {guild_id}")
                continue
            
            channel = guild.get_channel(channel_id)
            if not channel:
                logger.warning(f"  ⚠️ Modlog channel {channel_id} not found in guild {guild_id}")
                continue
            
            try:
                messages = await safe_history_fetch(channel, limit=10000, after=start_datetime, before=end_datetime)
                logger.info(f"  📨 Fetched {len(messages)} messages from modlog channel in {guild.name}")
                
                for message in messages:
                    for embed in message.embeds:
                        content = extract_embed_content(embed)
                        
                        matched = False
                        for user_id in all_staff_dict.keys():
                            if str(user_id) in content:
                                if user_id not in stats:
                                    stats[user_id] = {'count': 0, 'name': all_staff_dict[user_id]}
                                stats[user_id]['count'] += 1
                                matched = True
                                break
                        
                        if matched:
                            break
                            
            except Exception as e:
                logger.error(f"  ❌ Error scanning modlog in guild {guild_id}: {e}")
        
        elif duty_type == 'message':
            text_channels = get_readable_text_channels(guild)
            logger.info(f"  📨 Scanning {len(text_channels)} text channels in {guild.name}...")
            
            for channel in text_channels:
                try:
                    messages = await safe_history_fetch(channel, limit=5000, after=start_datetime, before=end_datetime)
                    
                    for message in messages:
                        if message.author.id in all_staff_dict and not message.author.bot:
                            user_id = message.author.id
                            if user_id not in stats:
                                stats[user_id] = {'count': 0, 'name': all_staff_dict[user_id]}
                            stats[user_id]['count'] += 1
                
                except Exception as e:
                    logger.error(f"  ⚠️ Error scanning channel {channel.name}: {e}")
    
    logger.info(f"  ✅ Found {len(stats)} users with {duty_type} activity")
    return stats

# ==================== HELPER FUNCTIONS ====================

def col_num_to_letter(n):
    """Convert column number to letter (1=A, 2=B, etc.)"""
    result = ""
    while n > 0:
        n -= 1
        result = chr(n % 26 + 65) + result
        n //= 26
    return result


def extract_user_id_from_cell(value):
    """Extract user ID from "Discord Name (UserID)" format"""
    if not value or not value.strip():
        return None
    
    match = re.search(r'\((\d+)\)', value)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    
    try:
        clean_value = value.strip().lstrip("'")
        return int(clean_value)
    except (ValueError, AttributeError):
        return None


def find_next_empty_column(worksheet):
    """Find the next empty column by checking the header row"""
    try:
        header_row = worksheet.row_values(1)
        
        if not header_row:
            return 2
        
        for i, value in enumerate(header_row, start=1):
            if i == 1:
                continue
            if not value or not value.strip():
                logger.info(f"  📍 Found empty header at column {i} ({col_num_to_letter(i)})")
                return i
        
        next_col = len(header_row) + 1
        logger.info(f"  📍 All columns have headers, using column {next_col} ({col_num_to_letter(next_col)})")
        return next_col
        
    except Exception as e:
        logger.error(f"  ⚠️ Error finding next column: {e}, defaulting to column B")
        return 2


def format_header_date(start_date_str, end_date_str=None, is_midweek=False):
    """Format header as 'MMM DD' (using week END date) or 'Amount on half weekly'"""
    if is_midweek:
        return "Amount on half weekly"

    date_to_use = end_date_str if end_date_str else start_date_str
    try:
        dt = datetime.strptime(date_to_use, '%d/%m/%Y')
        month_abbr = dt.strftime('%b').upper()
        day = dt.strftime('%d')
        return f"{month_abbr} {day}"
    except Exception as e:
        logger.error(f"Error formatting header date: {e}")
        return date_to_use


async def expand_sheet_grid(sheets_service, sheet_id, sheet_metadata_id, required_rows, required_cols):
    """Expand sheet grid to accommodate new data"""
    try:
        metadata = sheets_service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        current_grid = metadata['sheets'][0]['properties']['gridProperties']
        current_rows = current_grid['rowCount']
        current_cols = current_grid['columnCount']
        
        new_row_count = max(required_rows + 100, current_rows)
        new_col_count = max(required_cols, 500, current_cols)
        
        needs_expansion = (new_row_count > current_rows) or (new_col_count > current_cols)
        
        if needs_expansion:
            request_body = {
                'requests': [{
                    'updateSheetProperties': {
                        'properties': {
                            'sheetId': sheet_metadata_id,
                            'gridProperties': {
                                'rowCount': new_row_count,
                                'columnCount': new_col_count
                            }
                        },
                        'fields': 'gridProperties(rowCount,columnCount)'
                    }
                }]
            }
            
            await _sheets_execute_with_retry(
                lambda: sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=sheet_id,
                    body=request_body
                ).execute(),
                "expand sheet grid"
            )
            logger.info(f"  ✅ Grid expanded to {new_row_count} rows × {new_col_count} columns")
            await asyncio.sleep(0.2)
        else:
            logger.info(f"  ℹ️ Grid already sufficient: {current_rows} rows × {current_cols} columns")
            
    except Exception as e:
        logger.error(f"  ⚠️ Error expanding grid: {e}")


async def set_column_a_text_format(sheets_service, sheet_id, sheet_metadata_id):
    """Force Column A to TEXT format"""
    try:
        format_request = {
            'requests': [{
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_metadata_id,
                        'startColumnIndex': 0,
                        'endColumnIndex': 1
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'numberFormat': {
                                'type': 'TEXT'
                            }
                        }
                    },
                    'fields': 'userEnteredFormat.numberFormat'
                }
            }]
        }
        
        await _sheets_execute_with_retry(
            lambda: sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body=format_request
            ).execute(),
            "set column A text format"
        )
        logger.info(f"  ✅ Set Column A to TEXT format")
        
    except Exception as e:
        logger.error(f"  ⚠️ Error setting Column A format: {e}")


async def clear_column_b_formatting(sheets_service, sheet_id, sheet_metadata_id, last_row):
    """Clear all text formatting (underline, bold, etc.) from Column B without touching content"""
    try:
        if last_row <= 1:
            logger.info(f"  ℹ️ No rows to clear formatting for")
            return
        
        # Use updateCells to ONLY modify formatting, not content
        format_request = {
            'requests': [{
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_metadata_id,
                        'startColumnIndex': 1,  # Column B (0-indexed)
                        'endColumnIndex': 2,     # Up to but not including column 2
                        'startRowIndex': 1,       # Row 2 (0-indexed, skipping header)
                        'endRowIndex': last_row   # Up to last row (0-indexed already accounts for this)
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'textFormat': {
                                'underline': False,
                                'bold': False,
                                'italic': False,
                                'strikethrough': False
                            }
                        }
                    },
                    'fields': 'userEnteredFormat.textFormat'  # ONLY update text format, not values
                }
            }]
        }
        
        await _sheets_execute_with_retry(
            lambda: sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body=format_request
            ).execute(),
            "clear column B formatting"
        )
        logger.info(f"  ✅ Cleared text decoration for Column B rows 2-{last_row} (removed underline/bold/italic)")
        await asyncio.sleep(0.2)
        
    except Exception as e:
        logger.error(f"  ⚠️ Error clearing Column B formatting: {e}")
        logger.error(traceback.format_exc())


async def auto_resize_column_to_fit_header(sheets_service, sheet_id, sheet_metadata_id, col_index, header_text):
    """Auto-resize a single column to fit its header text"""
    try:
        if len(header_text) <= 10:
            col_letter = col_num_to_letter(col_index + 1)
            logger.info(f"  ℹ️ Column {col_letter} header '{header_text}' fits in default width, skipping resize")
            return
        
        resize_request = {
            'requests': [{
                'autoResizeDimensions': {
                    'dimensions': {
                        'sheetId': sheet_metadata_id,
                        'dimension': 'COLUMNS',
                        'startIndex': col_index,
                        'endIndex': col_index + 1
                    }
                }
            }]
        }
        
        await _sheets_execute_with_retry(
            lambda: sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body=resize_request
            ).execute(),
            "auto-resize column"
        )
        col_letter = col_num_to_letter(col_index + 1)
        logger.info(f"  ✅ Auto-resized column {col_letter} to fit header text '{header_text}'")
        
    except Exception as e:
        logger.error(f"  ⚠️ Error auto-resizing column: {e}")


async def hide_historical_columns(sheets_service, sheet_id, sheet_metadata_id, newly_added_col_index, is_midweek=False, duty_type=None):
    """Hide historical columns intelligently based on export type"""
    try:
        newly_added_col_0based = newly_added_col_index - 1
        
        start_hide_index = 4
        
        # ✅ Only show "Amount on half weekly" for req and role
        show_half_weekly = duty_type in ['req', 'role']

        if is_midweek:
            end_hide_index = newly_added_col_0based - 2
            logger.info(f"  👁️ MID-WEEK mode: Will show last 2 columns (Amount on half weekly + newest)")
        else:
            if show_half_weekly:
                # FULL WEEK (req/role): Show Amount on half weekly + newest
                end_hide_index = newly_added_col_0based - 2
                logger.info(f"  👁️ FULL WEEK mode ({duty_type}): Will show last 2 columns (Amount on half weekly + newest)")
            else:
                # FULL WEEK (modlog/message): Show ONLY newest
                end_hide_index = newly_added_col_0based - 1
                logger.info(f"  👁️ FULL WEEK mode ({duty_type}): Will show only newest column")
        
        if end_hide_index < start_hide_index:
            logger.info(f"  ℹ️ No columns to hide (newly added column is too early)")
            return
        
        start_col_letter = col_num_to_letter(start_hide_index + 1)
        end_col_letter = col_num_to_letter(end_hide_index + 1)
        newly_added_letter = col_num_to_letter(newly_added_col_index)
        amount_half_weekly_letter = col_num_to_letter(newly_added_col_index - 1)
        
        logger.info(f"  👁️ Hiding columns {start_col_letter} to {end_col_letter} (keeping {amount_half_weekly_letter} and {newly_added_letter} visible)...")
        
        hide_request = {
            'requests': [{
                'updateDimensionProperties': {
                    'range': {
                        'sheetId': sheet_metadata_id,
                        'dimension': 'COLUMNS',
                        'startIndex': start_hide_index,
                        'endIndex': end_hide_index + 1
                    },
                    'properties': {
                        'hiddenByUser': True
                    },
                    'fields': 'hiddenByUser'
                }
            }]
        }
        
        await _sheets_execute_with_retry(
            lambda: sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body=hide_request
            ).execute(),
            "hide historical columns"
        )
        num_hidden = end_hide_index - start_hide_index + 1
        logger.info(f"  ✅ Hidden {num_hidden} columns ({start_col_letter} to {end_col_letter}), columns {amount_half_weekly_letter} and {newly_added_letter} remain visible")
        
    except Exception as e:
        logger.error(f"  ⚠️ Error hiding columns: {e}")


async def reorganize_by_role_hierarchy(sheets_service, sheet_id, sheet_metadata_id, worksheet):
    """Reorganize all rows by role hierarchy"""
    try:
        logger.info(f"  🔄 Reorganizing rows by role hierarchy...")
        
        all_values = worksheet.get_all_values()
        
        if len(all_values) <= 1:
            logger.info(f"  ℹ️ No data rows to reorganize (only header)")
            return
        
        header = all_values[0]
        data_rows = all_values[1:]
        
        logger.info(f"  📊 Found {len(data_rows)} data rows to reorganize")
        
        # DEBUG: Log first few rows to see what we're reading
        logger.info(f"  🔍 DEBUG: First 5 rows being read:")
        for idx, row in enumerate(data_rows[:5], start=2):
            col_a = row[0] if len(row) > 0 else '[EMPTY]'
            col_b = row[1] if len(row) > 1 else '[EMPTY]'
            logger.info(f"    Row {idx}: A='{col_a}' | B='{col_b}'")
        
        role_priority = {}
        for idx, role_name in enumerate(ROLE_HIERARCHY):
            role_priority[role_name] = idx
        
        logger.info(f"  📋 Role priorities created: {len(role_priority)} roles")
        
        def get_sort_key(row):
            role = row[1] if len(row) > 1 else 'Unknown'
            
            # Strip whitespace that might be causing mismatch
            role = role.strip() if role else 'Unknown'
            
            priority = role_priority.get(role, 999)
            name = row[0] if len(row) > 0 else ''
            
            # DEBUG: Log if role isn't found in hierarchy
            if priority == 999 and role != 'Unknown':
                logger.warning(f"    ⚠️ Role '{role}' NOT FOUND in hierarchy! Will be sorted last.")
            
            return (priority, name.lower())
        
        sorted_rows = sorted(data_rows, key=get_sort_key)
        
        logger.info(f"  📋 New order (by role hierarchy - first 10):")
        for idx, row in enumerate(sorted_rows[:10], start=2):
            name = row[0] if len(row) > 0 else 'Unknown'
            role = row[1] if len(row) > 1 else 'Unknown'
            role = role.strip() if role else 'Unknown'
            priority = role_priority.get(role, 999)
            logger.info(f"    {idx}. {name} - {role} (priority: {priority})")
        
        if len(sorted_rows) > 10:
            logger.info(f"    ... and {len(sorted_rows) - 10} more rows")
        
        if len(data_rows) > 0:
            clear_range = f"A2:ZZ{len(all_values)}"

            # ✅ SAFETY: attempt the write BEFORE clearing, using a try/retry pattern
            # so a Google 500 error never leaves the sheet empty
            num_rows = len(sorted_rows)
            num_cols = len(header)
            end_col_letter = col_num_to_letter(num_cols)
            write_range = f"A2:{end_col_letter}{num_rows + 1}"

            body = {
                'valueInputOption': 'USER_ENTERED',
                'data': [{
                    'range': write_range,
                    'values': sorted_rows
                }]
            }

            # Try up to 3 times with back-off before touching the sheet
            write_succeeded = False
            for attempt in range(1, 4):
                try:
                    # Clear first, then write — but only on the first attempt
                    # On retries the sheet is already cleared so skip the clear
                    if attempt == 1:
                        worksheet.batch_clear([clear_range])
                        logger.info(f"  🗑️ Cleared data range: {clear_range}")
                        await asyncio.sleep(0.3)

                    logger.info(f"  ✍️ Writing {num_rows} sorted rows to range: {write_range} (attempt {attempt}/3)")

                    sheets_service.spreadsheets().values().batchUpdate(
                        spreadsheetId=sheet_id,
                        body=body
                    ).execute()

                    write_succeeded = True
                    logger.info(f"  ✅ Successfully reorganized {num_rows} rows by role hierarchy")
                    await asyncio.sleep(0.5)
                    break

                except Exception as write_err:
                    logger.error(f"  ❌ Write attempt {attempt}/3 failed: {write_err}")
                    if attempt < 3:
                        wait = attempt * 5  # 5s, 10s
                        logger.info(f"  ⏳ Retrying in {wait}s...")
                        await asyncio.sleep(wait)

            if not write_succeeded:
                # Last-ditch restore: write the ORIGINAL (unsorted) rows back so
                # the sheet isn't left empty
                logger.error("  ❌ All write attempts failed — restoring original row order to prevent data loss")
                try:
                    restore_range = f"A2:{col_num_to_letter(num_cols)}{len(data_rows) + 1}"
                    restore_body = {
                        'valueInputOption': 'USER_ENTERED',
                        'data': [{'range': restore_range, 'values': data_rows}]
                    }
                    sheets_service.spreadsheets().values().batchUpdate(
                        spreadsheetId=sheet_id,
                        body=restore_body
                    ).execute()
                    logger.info("  ✅ Original data restored successfully (unsorted)")
                except Exception as restore_err:
                    logger.error(f"  ❌ CRITICAL: Restore also failed: {restore_err}")
                return  # Don't proceed further — sheet state is uncertain
        
    except Exception as e:
        logger.error(f"  ❌ Error reorganizing by role hierarchy: {e}")
        logger.error(traceback.format_exc())


async def update_formulas_for_all_rows(sheets_service, sheet_id, sheet_metadata_id, worksheet):
    """Update formulas in columns C (Rank) and D (Total) for all rows"""
    try:
        logger.info(f"  🔧 Updating formulas for all rows...")
        
        column_a_values = worksheet.col_values(1)
        
        if len(column_a_values) <= 1:
            logger.info(f"  ℹ️ No data rows to update formulas for")
            return
        
        last_row = len(column_a_values)
        header_row = worksheet.row_values(1)
        last_col_with_data = len(header_row)
        last_col_letter = col_num_to_letter(last_col_with_data)
        
        logger.info(f"  📊 Updating formulas from row 2 to {last_row}")
        logger.info(f"  📏 SUM range will be E2 to {last_col_letter}")
        
        try:
            c2_value = worksheet.acell('C2', value_render_option='FORMULA').value
            d2_value = worksheet.acell('D2', value_render_option='FORMULA').value
            
            has_array_rank = c2_value and 'ARRAYFORMULA' in str(c2_value).upper()
            has_array_total = d2_value and 'ARRAYFORMULA' in str(d2_value).upper()
            
            if has_array_rank and has_array_total:
                logger.info(f"  ✅ ARRAYFORMULA detected in C2 and D2 - preserving existing formulas")
                logger.info(f"    • Rank formula: {c2_value}")
                logger.info(f"    • Total formula: {d2_value}")
                return
            elif has_array_rank or has_array_total:
                logger.warning(f"  ⚠️ Only ONE column has ARRAYFORMULA - this shouldn't happen")
                if has_array_rank:
                    logger.info(f"    • Rank has ARRAYFORMULA: {c2_value}")
                if has_array_total:
                    logger.info(f"    • Total has ARRAYFORMULA: {d2_value}")
        except Exception as e:
            logger.warning(f"  ⚠️ Couldn't check for ARRAYFORMULA: {e}")
        
        logger.info(f"  🔄 Setting up ARRAYFORMULA for columns C and D...")

        # ✅ SAFETY: Back up existing column C values before clearing
        try:
            col_c_backup = worksheet.get(f"C2:C{last_row}", value_render_option='FORMULA')
        except Exception:
            col_c_backup = []

        logger.info(f"  🗑️ Clearing column C to make room for ARRAYFORMULA...")
        clear_range = f"C2:C{last_row}"
        worksheet.batch_clear([clear_range])
        await asyncio.sleep(0.3)

        batch_data = []

        rank_formula = f"=ARRAYFORMULA(RANK.EQ(D2:D{last_row},D$2:D${last_row}))"
        batch_data.append({
            'range': f"C2",
            'values': [[rank_formula]]
        })

        for row_num in range(2, last_row + 1):
            sum_formula = f"=SUM(E{row_num}:{last_col_letter}{row_num})"
            batch_data.append({
                'range': f"D{row_num}",
                'values': [[sum_formula]]
            })

        if batch_data:
            body = {
                'valueInputOption': 'USER_ENTERED',
                'data': batch_data
            }

            try:
                await _sheets_execute_with_retry(
                    lambda: sheets_service.spreadsheets().values().batchUpdate(
                        spreadsheetId=sheet_id,
                        body=body
                    ).execute(),
                    "formula write (C/D columns)"
                )
                logger.info(f"  ✅ Updated formulas:")
                logger.info(f"    • Column C (Rank): ARRAYFORMULA")
                logger.info(f"    • Column D (Total): Individual SUM formulas for {last_row - 1} rows")
            except Exception:
                # ✅ Restore column C backup so rank column isn't permanently blank
                if col_c_backup:
                    logger.warning("  ⚠️ Formula write failed — restoring column C backup...")
                    try:
                        restore_body = {
                            'valueInputOption': 'USER_ENTERED',
                            'data': [{'range': f"C2:C{last_row}", 'values': col_c_backup}]
                        }
                        sheets_service.spreadsheets().values().batchUpdate(
                            spreadsheetId=sheet_id,
                            body=restore_body
                        ).execute()
                        logger.info("  ✅ Column C restored from backup")
                    except Exception as restore_err:
                        logger.error(f"  ❌ Column C restore failed: {restore_err}")

        await asyncio.sleep(0.5)
        
    except Exception as e:
        logger.error(f"  ❌ Error updating formulas: {e}")
        logger.error(traceback.format_exc())

async def delete_rows_batch(sheets_service, sheet_id, sheet_metadata_id, row_numbers):
    """Delete multiple rows in reverse order, with per-row retry."""
    if not row_numbers:
        return

    logger.info(f"  🗑️ DELETING {len(row_numbers)} rows...")
    failed_rows = []

    # Delete in reverse order so row indices stay valid after each deletion
    for row_num in sorted(row_numbers, reverse=True):
        request_body = {
            'requests': [{
                'deleteDimension': {
                    'range': {
                        'sheetId': sheet_metadata_id,
                        'dimension': 'ROWS',
                        'startIndex': row_num - 1,
                        'endIndex': row_num
                    }
                }
            }]
        }
        try:
            await _sheets_execute_with_retry(
                lambda rb=request_body: sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=sheet_id,
                    body=rb
                ).execute(),
                f"delete row {row_num}"
            )
            logger.info(f"    ❌ DELETED row {row_num}")
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"    ⚠️ Could not delete row {row_num} after retries: {e}")
            failed_rows.append(row_num)

    if failed_rows:
        logger.warning(f"  ⚠️ {len(failed_rows)} row(s) could NOT be deleted (sheet unchanged for those rows): {failed_rows}")



# ==================== MILESTONE BADGE SYNC ====================

async def read_column_d_totals(worksheet) -> dict:
    """
    Read column A (user ID) and column D (Total) from a duty worksheet.

    ⚠️  BUG FIX: get_all_values() returns formula *strings* for formula cells
    (e.g. "=SUM(E2:AQ2)") rather than their computed values, so every Total
    using a SUM formula was silently returning 0.

    Fix: fetch column D separately with value_render_option='UNFORMATTED_VALUE'
    so Google Sheets returns the calculated number instead of the formula text.
    """
    try:
        col_a_values = worksheet.col_values(1)   # column A, strings
        # Fetch column D as computed (unformatted) values — NOT formula strings
        col_d_raw = worksheet.get('D1:D', value_render_option='UNFORMATTED_VALUE')

        if not col_a_values or len(col_a_values) <= 1:
            return {}

        totals = {}
        # col_a_values[0] is header "Name", col_d_raw[0] is header "Total"
        for row_idx, col_a in enumerate(col_a_values[1:], start=1):
            col_a = col_a.strip() if col_a else ""
            user_id = extract_user_id_from_cell(col_a)
            if user_id is None:
                continue

            try:
                # col_d_raw is a list of rows; row_idx skips the header
                raw = col_d_raw[row_idx][0] if (row_idx < len(col_d_raw) and col_d_raw[row_idx]) else 0
                total = int(float(raw)) if raw not in ('', None) else 0
            except (ValueError, TypeError, IndexError):
                total = 0

            totals[user_id] = total
            logger.debug(f"    user_id={user_id}  col_d_raw={raw!r}  total={total}")

        return totals
    except Exception as e:
        logger.error(f"  ❌ Error reading column D totals: {e}")
        logger.error(traceback.format_exc())
        return {}


async def read_sheet_week_and_role(worksheet) -> dict:
    """
    Read the weekly score and role for each staff member directly from the sheet.

    Sheet column layout:
      A  = User ID (or display name with embedded ID)
      B  = Role (e.g. "Senior Support") — written by the export
      C  = Username / display name
      D  = Total (cumulative SUM formula — all-time)
      E+ = Weekly date columns, one per export run, newest is rightmost

    Weekly score = value in the RIGHTMOST populated data column (col E+).
    This is the actual count for that single week — no diffing needed.
    Role is read straight from col B — no Discord API call needed.

    Returns:
        { user_id: { "total": int, "weekly": int, "role": str } }
    """
    try:
        all_values = worksheet.get_all_values()
        if not all_values or len(all_values) <= 1:
            return {}

        header_row = all_values[0]

        # Find the rightmost column with a header, skipping A-D (indices 0-3)
        rightmost_data_col = None
        for col_idx in range(len(header_row) - 1, 3, -1):
            if header_row[col_idx] and header_row[col_idx].strip():
                rightmost_data_col = col_idx
                break

        if rightmost_data_col is not None:
            logger.info(f"  📅 This week's column: {col_num_to_letter(rightmost_data_col + 1)} "
                        f"('{header_row[rightmost_data_col]}')")
        else:
            logger.warning("  ⚠️ No weekly data columns found (only A-D exist)")

        results = {}
        for row in all_values[1:]:
            if not row:
                continue

            col_a = row[0].strip() if row[0] else ""
            user_id = extract_user_id_from_cell(col_a)
            if user_id is None:
                continue

            role = row[1].strip() if len(row) > 1 and row[1] else "Staff"

            try:
                total = int(float(row[3])) if len(row) > 3 and row[3] not in ('', None) else 0
            except (ValueError, TypeError):
                total = 0

            weekly = 0
            if rightmost_data_col is not None and len(row) > rightmost_data_col:
                try:
                    weekly = int(float(row[rightmost_data_col])) if row[rightmost_data_col] not in ('', None) else 0
                except (ValueError, TypeError):
                    weekly = 0

            results[user_id] = {"total": total, "weekly": weekly, "role": role}

        return results

    except Exception as e:
        logger.error(f"  ❌ Error reading sheet week/role data: {e}")
        logger.error(traceback.format_exc())
        return {}


async def sync_milestone_totals(bot, duty_sheets: dict, client, source_guilds: list):
    """
    After a full-week export: read each duty sheet and push milestone_totals.json
    to GitHub automatically.

    Sheet column layout (A=ID, B=Role, C=Name, D=Total, E+=weekly date cols):
      - <duty_key>         : int — cumulative all-time score from col D
      - <duty_key>_weekly  : int — this week's score from the rightmost date column
      - role               : str — staff role read directly from col B

    The weekly score is the actual value written by the export for that week —
    no diffing of cumulative totals needed, no timestamp magic required.
    """
    import json as _json
    import os as _os

    logger.info("🏅 ============================================")
    logger.info("🏅 SYNCING MILESTONE TOTALS")
    logger.info("🏅 ============================================")

    # ⚠️  BUG FIX: The full-week export writes SUM formulas to column D then
    # immediately reorganises rows. Google Sheets needs a few seconds to finish
    # recalculating before we read column D back. Without this wait we were
    # reading stale/zero values and pushing them to GitHub.
    logger.info("  ⏳ Waiting 15 s for Google Sheets to recalculate column D formulas...")
    await asyncio.sleep(15)

    # Build user info lookup (display name and avatar_url)
    user_info_lookup = {}
    for guild_id in source_guilds:
        guild = bot.get_guild(guild_id)
        if guild:
            for member in guild.members:
                if not member.bot:
                    user_info_lookup[member.id] = {
                        'name': member.name,
                        'avatar_url': web_avatar_url(member.display_avatar)
                    }

    # Current duty-role holders per duty — HIDE (not delete) staff who no longer
    # hold a duty's role. DB is still saved below for everyone, so they reappear
    # automatically if they regain the role.
    current_duty_holders = {}
    for duty_key in duty_sheets:
        try:
            current_duty_holders[duty_key] = await get_staff_with_duty_roles(bot, source_guilds, duty_key)
        except Exception as e:
            logger.warning(f"  ⚠️ Could not resolve holders for '{duty_key}': {e}")
            current_duty_holders[duty_key] = {}

    # milestone_data["username"] = {"req": N, "req_weekly": N, "role": "...", "uid": 123, "avatar_url": "..."}
    milestone_data = {}

    for duty_key, sheet_info in duty_sheets.items():
        try:
            logger.info(f"  📊 Reading {duty_key} sheet (total + weekly + role)...")
            sheet = client.open_by_key(sheet_info['id'])
            worksheet = sheet.get_worksheet(0)

            sheet_data = await read_sheet_week_and_role(worksheet)
            logger.info(f"  ✅ Got {len(sheet_data)} rows for {duty_key}")

            for user_id, row_data in sheet_data.items():
                info = user_info_lookup.get(user_id, {'name': f"User_{user_id}", 'avatar_url': ""})
                display_name = info['name']
                
                if display_name not in milestone_data:
                    milestone_data[display_name] = {
                        "uid": str(user_id),
                        "avatar_url": info['avatar_url']
                    }

                # Only DISPLAY this duty if they still hold its role.
                holders = current_duty_holders.get(duty_key) or {}
                if (not holders) or (user_id in holders):
                    milestone_data[display_name][duty_key]             = row_data["total"]
                    milestone_data[display_name][f"{duty_key}_weekly"] = row_data["weekly"]

                # Role: don't overwrite a real role with a fallback "Staff"
                existing_role = milestone_data[display_name].get("role", "")
                if not existing_role or existing_role == "Staff":
                    milestone_data[display_name]["role"] = row_data["role"]

                # Save to database
                try:
                    await database.upsert_milestone_total(
                        user_id=user_id,
                        username=display_name,
                        duty_type=duty_key,
                        total=row_data["total"]
                    )
                except Exception as db_err:
                    logger.warning(f"  ⚠️ DB upsert failed for {display_name}/{duty_key}: {db_err}")

        except Exception as e:
            logger.error(f"  ❌ Failed to read milestone totals for {duty_key}: {e}")
            logger.error(traceback.format_exc())

    logger.info(f"  ✅ Built milestone_data for {len(milestone_data)} staff members")

    # Hide staff with no remaining duty roles (still saved in DB above).
    _DUTY_KEYS = ('message', 'role', 'req', 'modlog')
    _before = len(milestone_data)
    milestone_data = {
        n: d for n, d in milestone_data.items()
        if any(isinstance(d.get(k), (int, float)) for k in _DUTY_KEYS)
    }
    if _before - len(milestone_data):
        logger.info(f"  🙈 Hid {_before - len(milestone_data)} staff with no current duty roles (kept in DB)")

    # Embed per-user activity timeline (week-by-week history) for the profile page
    for display_name, data in milestone_data.items():
        uid = data.get('uid')
        if not uid:
            continue
        try:
            raw_history = await database.get_staff_insights_history(uid)
            weeks = {}
            for record in raw_history:
                if record['is_midweek']:
                    continue
                key = (record['week_start'], record['week_end'])
                if key not in weeks:
                    weeks[key] = {'week_start': record['week_start'], 'week_end': record['week_end'], 'duties': {}}
                weeks[key]['duties'][record['duty_type']] = record['count']
            def _parse_ws(k):
                try:
                    from datetime import datetime as _dt
                    return _dt.strptime(k[0], '%d/%m/%Y')
                except ValueError:
                    from datetime import datetime as _dt
                    return _dt.min
            sorted_weeks = sorted(weeks.items(), key=_parse_ws, reverse=True)
            data['activity_timeline'] = [v for _, v in sorted_weeks]
        except Exception as tl_err:
            logger.warning(f"  ⚠️ Could not fetch timeline for {display_name}: {tl_err}")

    # Write JSON locally
    json_path = _os.path.join(_os.path.dirname(__file__), 'milestone_totals.json')
    try:
        with open(json_path, 'w') as f:
            _json.dump(milestone_data, f, indent=2)
        logger.info(f"  ✅ Written milestone_totals.json")
    except Exception as e:
        logger.error(f"  ❌ Failed to write milestone_totals.json: {e}")

    # Push to GitHub automatically
    try:
        from tasks.staff_hub_writer import push_milestones_to_github
        logger.info("  📤 Pushing to GitHub...")
        await push_milestones_to_github(milestone_data)
    except Exception as gh_err:
        logger.error(f"  ❌ GitHub push failed: {gh_err}")

    # Sync Power Points rewards (badge roles + wave points bonuses)
    try:
        from tasks.power_points_rewards import sync_power_rewards
        logger.info("  🏆 Syncing Power Points rewards...")
        await sync_power_rewards(bot, milestone_data)
    except Exception as ppr_err:
        logger.error(f"  ❌ Power Points rewards sync failed: {ppr_err}")
        logger.error(traceback.format_exc())

    logger.info("🏅 Milestone sync complete")
    return milestone_data


# ==================== GUILD MEMBERSHIP CLEANUP ====================

async def get_all_known_user_ids_in_guilds(bot, source_guilds: list) -> set:
    """
    Return a set of all non-bot user IDs that are currently members
    of ANY of the source guilds.  Used for left-server detection.
    """
    present = set()
    for guild_id in source_guilds:
        guild = bot.get_guild(guild_id)
        if not guild:
            logger.warning(f"  ⚠️ Guild {guild_id} not found when building presence set")
            continue
        for member in guild.members:
            if not member.bot:
                present.add(member.id)
    logger.info(f"  👥 {len(present)} unique non-bot members found across {len(source_guilds)} guild(s)")
    return present


async def remove_left_server_users_from_db(user_ids_to_remove: list):
    """
    Delete wave_points and milestone_totals rows for users who are no longer
    in any source guild.  Safe to call with an empty list.
    """
    if not user_ids_to_remove:
        return

    logger.info(f"  🧹 Removing {len(user_ids_to_remove)} left-server users from DB...")
    try:
        pool = await database.get_pool()
        from datetime import datetime, timezone as _tz
        now = datetime.now(_tz.utc).isoformat()
        async with pool.acquire() as db:
            for uid in user_ids_to_remove:
                await db.execute(
                    "UPDATE wave_points SET left_at = ? WHERE user_id = ? AND left_at IS NULL",
                    (now, uid)
                )
                await db.execute(
                    "DELETE FROM milestone_totals WHERE user_id = ?", (uid,)
                )
                logger.info(f"    🎓 Archived user {uid} wave_points as alumni; removed milestone_totals")
            await db.commit()
        logger.info(f"  ✅ DB cleanup complete for {len(user_ids_to_remove)} left-server users")
    except Exception as e:
        logger.error(f"  ❌ Failed to remove left-server users from DB: {e}")


async def purge_left_server_users(bot, source_guilds: list) -> list:
    """
    Cross-reference every user_id stored in the DB against all source guilds.
    Anyone not found in *any* guild gets removed from the DB automatically.

    Returns a list of user_ids that were removed so callers can log/report them.
    """
    logger.info("🔍 Checking DB for users who have left all source guilds...")

    present_ids = await get_all_known_user_ids_in_guilds(bot, source_guilds)

    removed_ids = []
    try:
        pool = await database.get_pool()
        async with pool.acquire() as db:
            # Collect all user_ids tracked in either table
            tracked = set()
            async with db.execute("SELECT user_id FROM wave_points WHERE left_at IS NULL") as cur:
                async for row in cur:
                    tracked.add(row[0])
            async with db.execute("SELECT DISTINCT user_id FROM milestone_totals") as cur:
                async for row in cur:
                    tracked.add(row[0])

        gone = [uid for uid in tracked if uid not in present_ids]

        if gone:
            logger.info(f"  🚨 Found {len(gone)} user(s) no longer in any guild: {gone}")
            await remove_left_server_users_from_db(gone)
            removed_ids = gone
        else:
            logger.info("  ✅ All tracked users are still present in at least one guild")

    except Exception as e:
        logger.error(f"  ❌ Error during left-server purge: {e}")

    return removed_ids


# ==================== MAIN EXPORT FUNCTION ====================

async def export_staff_insights_reports(bot, start_date: str, end_date: str, is_test: bool = False, ctx=None, is_midweek: bool = False):
    """Export staff insights data to individual Google Sheets for each duty"""
    
    try:
        if is_midweek:
            start_datetime = get_start_datetime(start_date)
            midweek_end_datetime = start_datetime + timedelta(hours=72)
            calculated_end_date = midweek_end_datetime.strftime('%d/%m/%Y')
            logger.info(f"📊 Starting MID-WEEK Staff Insights export")
            logger.info(f"📅 Period: {start_date} → {calculated_end_date} (72 hours)")
            period_desc = "Mid-Week (72 hours)"
        else:
            calculated_end_date = end_date
            logger.info(f"📊 Starting FULL WEEK Staff Insights export")
            logger.info(f"📅 Period: {start_date} → {end_date} (168 hours)")
            period_desc = "Full Week (168 hours)"
        
        # Discord output disabled — staff insights now live on the web hub
        # (milestones leaderboard) + Google Sheets. progress_msg stays None so
        # the legacy `if progress_msg:` blocks below are inert no-ops.
        progress_msg = None

        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        sheets_service = build('sheets', 'v4', credentials=creds)
        
        if progress_msg:
            await progress_msg.edit(embed=discord.Embed(
                title=f"📊 Exporting Staff Insights Reports ({period_desc})",
                description="🔄 **Step 2/8:** Finding duty sheets...",
                color=discord.Color.blue()
            ))
        
        if is_midweek:
            duties_to_process = ['role', 'req']
            logger.info(f"🎯 Mid-week mode: Processing ONLY {', '.join(duties_to_process)}")
        else:
            duties_to_process = ['modlog', 'req', 'role', 'message']
            logger.info(f"🎯 Full week mode: Processing ALL duties")

        DUTY_SHEET_NAMES = {
            'modlog': 'Modlog',
            'req': 'Req',
            'role': 'Role',
            'message': 'Message'
        }
        
        logger.info(f"🔍 Searching for duty sheets in folder: {STAFF_INSIGHTS_FOLDER_ID}...")
        query = f"mimeType='application/vnd.google-apps.spreadsheet' and '{STAFF_INSIGHTS_FOLDER_ID}' in parents and trashed=false"
        results = drive_service.files().list(
            q=query,
            fields='files(id, name)',
            pageSize=1000
        ).execute()

        all_sheets = results.get('files', [])
        logger.info(f"📋 Found {len(all_sheets)} spreadsheets in the specified folder")
        
        duty_sheets = {}
        for duty in duties_to_process:
            sheet_name = DUTY_SHEET_NAMES[duty]
            found = False
            for sheet in all_sheets:
                if sheet_name.lower() in sheet['name'].lower():
                    duty_sheets[duty] = {
                        'id': sheet['id'],
                        'name': sheet['name']
                    }
                    logger.info(f"✅ Found {duty} sheet: '{sheet['name']}'")
                    found = True
                    break
            
            if not found:
                logger.error(f"❌ Could not find sheet containing '{sheet_name}'")
                if progress_msg:
                    await progress_msg.edit(embed=discord.Embed(
                        title="❌ Export Failed",
                        description=f"Could not find sheet containing: **{sheet_name}**",
                        color=discord.Color.red()
                    ))
                return
        
        if progress_msg:
            await progress_msg.edit(embed=discord.Embed(
                title=f"📊 Exporting Staff Insights Reports ({period_desc})",
                description="🔄 **Step 3/8:** Getting configuration...",
                color=discord.Color.blue()
            ))
        
        import json
        import os
        config_path = 'config.json'
        
        if not os.path.exists(config_path):
            logger.error("❌ config.json not found")
            if progress_msg:
                await progress_msg.edit(embed=discord.Embed(
                    title="❌ Export Failed",
                    description="config.json not found",
                    color=discord.Color.red()
                ))
            return
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        auto_config = config.get('automated_checks', {})
        source_guilds = auto_config.get('source_guilds', [])
        
        if not source_guilds:
            logger.error("❌ No source guilds configured")
            if progress_msg:
                await progress_msg.edit(embed=discord.Embed(
                    title="❌ Export Failed",
                    description="No source guilds configured",
                    color=discord.Color.red()
                ))
            return
        
        duty_names = {
            'modlog': '🔨 Mod Commands',
            'req': '🗺️ Map Request',
            'role': '👤 Role',
            'message': '📨 Messages'
        }

        # ── Left-server DB cleanup ─────────────────────────────────────────────
        logger.info("🧹 Running left-server user cleanup before scan...")
        left_server_removed = await purge_left_server_users(bot, source_guilds)
        if left_server_removed:
            logger.info(
                f"  🗑️ Removed {len(left_server_removed)} user(s) from DB "
                f"(no longer in any source guild): {left_server_removed}"
            )
        # ─────────────────────────────────────────────────────────────────────

        updated_sheets = []
        removal_summary = {}
        left_server_summary = len(left_server_removed)
        
        for i, duty in enumerate(duties_to_process, start=4):
            duty_name = duty_names[duty]
            
            if progress_msg:
                await progress_msg.edit(embed=discord.Embed(
                    title=f"📊 Exporting Staff Insights Reports ({period_desc})",
                    description=(
                        f"🔄 **Step {i}/{3 + len(duties_to_process)}:** Processing {duty_name}...\n\n"
                        f"**Completed:**\n" +
                        "\n".join([f"✅ {duty_names[d]}" for d in updated_sheets])
                    ),
                    color=discord.Color.blue()
                ))
            
            logger.info(f"\n📊 Processing {duty}...")
            
            try:
                logger.info(f"  👥 Getting staff with {duty} duty role...")
                current_staff_with_duty = await get_staff_with_duty_roles(bot, source_guilds, duty)
                
                sheet_info = duty_sheets[duty]
                sheet = client.open_by_key(sheet_info['id'])
                worksheet = sheet.get_worksheet(0)
                
                sheet_metadata = sheet.fetch_sheet_metadata()
                sheet_id = sheet_metadata['sheets'][0]['properties']['sheetId']
                
                await set_column_a_text_format(sheets_service, sheet_info['id'], sheet_id)
                
                logger.info(f"  🔍 Reading Column A...")
                column_a_values = worksheet.col_values(1)
                
                existing_user_ids = []
                user_id_to_row = {}
                invalid_rows = []
                
                for row_num, value in enumerate(column_a_values, start=1):
                    if row_num == 1:
                        continue
                    
                    user_id = extract_user_id_from_cell(value)
                    
                    if user_id is None:
                        if value and value.strip():
                            logger.warning(f"  ⚠️ Row {row_num} has NO VALID USER ID: '{value}' - MARKING FOR DELETION")
                            invalid_rows.append(row_num)
                        continue
                    
                    existing_user_ids.append(user_id)
                    user_id_to_row[user_id] = row_num
                
                logger.info(f"  ✅ Found {len(existing_user_ids)} valid users in Column A")
                logger.info(f"  🗑️ Found {len(invalid_rows)} INVALID rows to DELETE")
                
                if invalid_rows:
                    await delete_rows_batch(sheets_service, sheet_info['id'], sheet_id, invalid_rows)
                    
                    logger.info(f"  🔄 Re-reading Column A after deletions...")
                    await asyncio.sleep(0.5)
                    column_a_values = worksheet.col_values(1)
                    
                    existing_user_ids = []
                    user_id_to_row = {}
                    
                    for row_num, value in enumerate(column_a_values, start=1):
                        if row_num == 1:
                            continue
                        
                        user_id = extract_user_id_from_cell(value)
                        if user_id is not None:
                            existing_user_ids.append(user_id)
                            user_id_to_row[user_id] = row_num
                    
                    logger.info(f"  ✅ After deletion: {len(existing_user_ids)} valid users remain")
                
                users_to_remove = set()
                
                for user_id in existing_user_ids:
                    if user_id not in current_staff_with_duty:
                        users_to_remove.add(user_id)
                        logger.info(f"  🚨 User {user_id} NO LONGER has {duty} duty role - will be removed")
                
                if users_to_remove:
                    logger.info(f"  🚨 Found {len(users_to_remove)} users to REMOVE (no longer have duty role)")
                    removal_summary[duty] = len(users_to_remove)
                    
                    rows_to_delete = []
                    for user_id in users_to_remove:
                        if user_id in user_id_to_row:
                            row_num = user_id_to_row[user_id]
                            rows_to_delete.append(row_num)
                            user_name = current_staff_with_duty.get(user_id, f"User {user_id}")
                            logger.info(f"    🚨 REMOVING: {user_name} (ID: {user_id}) - Row {row_num}")
                    
                    await delete_rows_batch(sheets_service, sheet_info['id'], sheet_id, rows_to_delete)
                    
                    logger.info(f"  🔄 Re-reading Column A after removals...")
                    await asyncio.sleep(0.5)
                    column_a_values = worksheet.col_values(1)
                    
                    existing_user_ids = []
                    user_id_to_row = {}
                    
                    for row_num, value in enumerate(column_a_values, start=1):
                        if row_num == 1:
                            continue
                        
                        user_id = extract_user_id_from_cell(value)
                        if user_id is not None:
                            existing_user_ids.append(user_id)
                            user_id_to_row[user_id] = row_num
                    
                    logger.info(f"  ✅ After removals: {len(existing_user_ids)} valid users remain")
                else:
                    logger.info(f"  ℹ️ No users to remove (all sheet users still have duty role)")
                
                logger.info(f"  🔍 Scanning {duty} activity...")
                
                scan_start_dt = get_start_datetime(start_date)
                if is_midweek:
                    scan_end_dt = scan_start_dt + timedelta(hours=72)
                else:
                    scan_end_dt = get_end_datetime(end_date)
                
                stats = await scan_duty_activity(
                    bot,
                    duty,
                    source_guilds,
                    scan_start_dt,
                    scan_end_dt,
                    current_staff_with_duty
                )
                
                if stats is None:
                    stats = {}
                
                logger.info(f"  ✅ Scan found {len(stats)} users total ({len([s for s in stats.values() if s['count'] > 0])} with activity)")
                logger.info(f"  ✅ Total users to process: {len(stats)}")
                
                new_users = set(stats.keys()) - set(existing_user_ids)
                
                if new_users:
                    logger.info(f"  ➕ Found {len(new_users)} NEW USERS to add")
                    for uid in new_users:
                        logger.info(f"    ➕ NEW: {stats[uid]['name']} (ID: {uid}) - Count: {stats[uid]['count']}")
                else:
                    logger.info(f"  ℹ️ No new users to add")
                
                logger.info(f"  🔍 Finding next empty column...")
                next_col_index = find_next_empty_column(worksheet)
                
                required_rows = len(existing_user_ids) + len(new_users) + 1
                required_cols = next_col_index
                
                await expand_sheet_grid(
                    sheets_service, 
                    sheet_info['id'], 
                    sheet_id, 
                    required_rows, 
                    required_cols
                )
                
                col_letter = col_num_to_letter(next_col_index)
                logger.info(f"  📝 Writing results to Column {col_letter} (index {next_col_index})")
                
                header_text = format_header_date(start_date, calculated_end_date, is_midweek=is_midweek)
                
                batch_data = []
                
                batch_data.append({
                    'range': f"{col_letter}1",
                    'values': [[header_text]]
                })
                logger.info(f"  📅 Header: '{header_text}' in {col_letter}1")
                
                # ✅ CHECK AND UPDATE ROLES FOR ALL EXISTING USERS
                logger.info(f"  👤 Checking roles for {len(existing_user_ids)} existing users...")
                
                # First, read Column B to see what roles are already there
                try:
                    column_b_values = worksheet.col_values(2)  # Column B (1-indexed, but col_values uses 1-based)
                except:
                    column_b_values = []
                
                role_updates_needed = []
                
                for user_id in existing_user_ids:
                    if user_id not in user_id_to_row:
                        continue

                    row_num = user_id_to_row[user_id]

                    # Check what's currently in Column B for this row
                    current_role = ''
                    if row_num <= len(column_b_values):
                        current_role = column_b_values[row_num - 1]  # -1 because list is 0-indexed

                    # Always refresh role from Discord so promotions/demotions are reflected
                    member = None
                    highest_role = None

                    for guild_id in source_guilds:
                        guild = bot.get_guild(guild_id)
                        if guild:
                            member = guild.get_member(user_id)
                            if member:
                                highest_role = get_highest_role(member)
                                break

                    # Only write if we got a real role from Discord, or cell is empty
                    if highest_role and highest_role != 'Unknown':
                        if highest_role != current_role:
                            role_updates_needed.append({
                                'range': f"B{row_num}",
                                'values': [[highest_role]]
                            })
                            if current_role:
                                user_name = stats.get(user_id, {}).get('name', f'User {user_id}')
                                logger.info(f"    🔄 Row {row_num}: Role updated '{current_role}' → '{highest_role}' for {user_name}")
                    elif not current_role or not current_role.strip():
                        role_updates_needed.append({
                            'range': f"B{row_num}",
                            'values': [['Unknown']]
                        })
                        
                        user_name = stats.get(user_id, {}).get('name', f'User {user_id}')
                        logger.info(f"    📝 Row {row_num}: Adding role '{highest_role}' for {user_name}")
                
                if role_updates_needed:
                    logger.info(f"  ✅ Updating roles for {len(role_updates_needed)} existing users (new or changed)...")
                    batch_data.extend(role_updates_needed)
                else:
                    logger.info(f"  ℹ️ All existing users already have up-to-date roles in Column B")
                
                updates_count = 0
                for user_id, row_num in user_id_to_row.items():
                    if user_id not in stats:
                        continue
                    
                    data = stats[user_id]
                    count = data['count']
                    
                    batch_data.append({
                        'range': f"{col_letter}{row_num}",
                        'values': [[count]]
                    })
                    
                    logger.info(f"    ✅ Row {row_num}: {data['name']} = {count}")
                    updates_count += 1
                
                if new_users:
                    next_row = len(existing_user_ids) + 2
                    
                    sorted_new_users = sorted(new_users, key=lambda uid: stats[uid]['name'].lower())
                    
                    for user_id in sorted_new_users:
                        if user_id not in stats:
                            continue
                        
                        data = stats[user_id]
                        count = data['count']
                        user_name = data['name']
                        
                        name_with_id = f"{user_name} ({user_id})"
                        
                        member = None
                        highest_role = 'Unknown'
                        
                        # Find the member and get their highest staff role
                        for guild_id in source_guilds:
                            guild = bot.get_guild(guild_id)
                            if guild:
                                member = guild.get_member(user_id)
                                if member:
                                    highest_role = get_highest_role(member)
                                    break
                        
                        # Add ALL users from scan, regardless of staff role
                        batch_data.append({
                            'range': f"A{next_row}",
                            'values': [[name_with_id]]
                        })
                        
                        batch_data.append({
                            'range': f"B{next_row}",
                            'values': [[highest_role]]
                        })
                        
                        batch_data.append({
                            'range': f"{col_letter}{next_row}",
                            'values': [[count]]
                        })
                        
                        logger.info(f"    ➕ NEW ROW {next_row}: {name_with_id} | {highest_role} | {count}")
                        next_row += 1
                
                logger.info(f"  📝 Batch writing {len(batch_data)} updates...")
                logger.info(f"    • Updated {updates_count} existing rows")
                logger.info(f"    • Added {len(new_users)} new rows")
                
                if len(batch_data) == 0:
                    logger.warning(f"  ⚠️ No data to write for {duty}!")
                else:
                    body = {
                        'valueInputOption': 'USER_ENTERED',
                        'data': batch_data
                    }
                    
                    await _sheets_execute_with_retry(
                        lambda: sheets_service.spreadsheets().values().batchUpdate(
                            spreadsheetId=sheet_info['id'],
                            body=body
                        ).execute(),
                        f"main data write for {duty}"
                    )
                    
                    logger.info(f"  ✅ Successfully batch updated {duty} sheet")

                    logger.info(f"  💾 Saving {duty} scan results to insights history...")
                    try:
                        await database.save_staff_insight_batch(
                            stats=stats,
                            duty_type=duty,
                            week_start=start_date,         # DD/MM/YYYY — already in scope
                            week_end=calculated_end_date,  # DD/MM/YYYY — already in scope
                            is_midweek=is_midweek
                        )
                        logger.info(f"  ✅ Saved {len(stats)} records to insights history")
                    except Exception as hist_err:
                        logger.error(f"  ❌ Failed to save insights history for {duty}: {hist_err}")
                    # ✅ END NEW BLOCK

                    # Wait for Google Sheets to process the write before reading it back
                    logger.info(f"  ⏳ Waiting 3 seconds for Google Sheets to process...")
                    await asyncio.sleep(3.0)
                    
                    logger.info(f"  📏 Auto-resizing column {col_letter} if needed...")
                    await auto_resize_column_to_fit_header(
                        sheets_service,
                        sheet_info['id'],
                        sheet_id,
                        next_col_index - 1,
                        header_text
                    )
                    
                    logger.info(f"  👁️ Hiding historical columns...")
                    await hide_historical_columns(
                        sheets_service,
                        sheet_info['id'],
                        sheet_id,
                        next_col_index,
                        is_midweek=is_midweek,
                        duty_type=duty
                    )
                    
                    # ✅ FIX #1: Reorganize EVERY TIME (removed the if not is_midweek check)
                    logger.info(f"  🔄 Reorganizing by role hierarchy...")
                    await reorganize_by_role_hierarchy(
                        sheets_service,
                        sheet_info['id'],
                        sheet_id,
                        worksheet
                    )
                    
                    # ✅ FIXED: Update formulas AFTER reorganization (so they don't get wiped)
                    logger.info(f"  🔧 Updating formulas...")
                    await update_formulas_for_all_rows(
                        sheets_service,
                        sheet_info['id'],
                        sheet_id,
                        worksheet
                    )
                    
                    # ✅ FIX #2: Clear Column B formatting AFTER reorganization (to remove underlines)
                    # Re-read column A to get accurate row count after reorganization
                    column_a_values_after = worksheet.col_values(1)
                    last_row_after = len(column_a_values_after)
                    
                    logger.info(f"  ✨ Clearing Column B formatting for {last_row_after - 1} data rows...")
                    await clear_column_b_formatting(
                        sheets_service,
                        sheet_info['id'],
                        sheet_id,
                        last_row_after
                    )
                    
                    # Discord image posting removed — data is published to the
                    # web hub (milestones leaderboard) + Google Sheets only.
                    updated_sheets.append(duty)
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"  ❌ Failed to update {duty} sheet: {e}")
                logger.error(traceback.format_exc())
                continue
        
        if progress_msg:
            duty_list = "\n".join([f"✅ {duty_names[d]}" for d in updated_sheets])
            
            removal_text = ""
            if removal_summary:
                removal_text = "\n\n**Users Removed (no longer have duty role):**\n"
                for duty, count in removal_summary.items():
                    removal_text += f"• {duty_names[duty]}: {count} removed\n"
            if left_server_summary:
                removal_text += (
                    f"\n**Left-Server DB Cleanup:**\n"
                    f"• {left_server_summary} user(s) removed from DB "
                    f"(no longer in any source guild)\n"
                )
            
            period_text = f"**Period:** {start_date} → {calculated_end_date} ({period_desc})"
            header_text = f"**Header Format:** {'Amount on half weekly' if is_midweek else format_header_date(start_date, calculated_end_date)}"
            
            actions_text = (
                f"**Actions:**\n"
                f"• ✅ ONLY scanned users with duty-specific roles\n"
                f"• ✅ ALL users with duty role added to sheet (even with 0 activity)\n"
                f"• ✅ ONLY removed users who lost their duty role\n"
                f"• 🗑️ Deleted invalid rows (no user ID)\n"
                f"• ➕ Added new users in 'Name (UserID)' format\n"
                f"• 👤 Auto-populated roles for new users based on hierarchy\n"
                f"• 🔄 Updated existing rows\n"
                f"• 📊 Expanded grid to 500+ columns\n"
                f"• 📏 Smart column resize (only expands if header text is long)\n"
                f"• 🔧 Updated formulas in columns C (Rank) and D (Total)\n"
                f"• 👁️ Hidden historical columns ({'TWO before latest (shows Amount on half weekly + newest)' if is_midweek else 'ONE before latest (shows only newest)'})\n"
                f"• 📋 Reorganized rows by role hierarchy (Founder → Trial Staff)\n"
                f"• 🎨 Generated table images programmatically (no browser screenshot)\n"
                f"• 📸 Sent table images to duty channels\n"
                f"• ✨ Cleared Column B formatting (removed underlines)"
            )
            
            embed = discord.Embed(
                title=f"✅ Staff Insights Reports Exported ({period_desc})",
                description=(
                    f"Successfully updated **{len(updated_sheets)}/{len(duties_to_process)}** sheets\n\n"
                    f"**Updated:**\n{duty_list}\n\n"
                    f"{period_text}\n"
                    f"{header_text}\n"
                    f"{actions_text}"
                    f"{removal_text}"
                ),
                color=discord.Color.green()
            )
            
            await progress_msg.edit(embed=embed)
        
        logger.info(f"✅ Staff Insights export complete - {len(updated_sheets)}/{len(duties_to_process)} sheets updated")

        # ── 🏅 MILESTONE BADGE SYNC (full-week only) ───────────────────────────
        if not is_midweek and updated_sheets:
            logger.info("🏅 Syncing milestone totals after full-week export...")
            try:
                await sync_milestone_totals(
                    bot=bot,
                    duty_sheets={d: duty_sheets[d] for d in updated_sheets},
                    client=client,
                    source_guilds=source_guilds
                )
            except Exception as ms_err:
                logger.error(f"❌ Milestone sync failed: {ms_err}")
                logger.error(traceback.format_exc())
        # ── END MILESTONE BADGE SYNC ───────────────────────────────────────────
        
        if not is_test:
            logger.info(f"📝 Logging to database...")
            try:
                period = "Mid-Week" if is_midweek else "Full Week"
                
                auto_config = config.get('automated_checks', {})
                report_guild_id = auto_config.get('report_guild_id', 1041450125391835186)
                
                start_date_db = datetime.strptime(start_date, '%d/%m/%Y').strftime('%Y-%m-%d')
                end_date_db = datetime.strptime(calculated_end_date, '%d/%m/%Y').strftime('%Y-%m-%d')
                
                for duty in updated_sheets:
                    await database.mark_report_sent(
                        report_guild_id,
                        f'staff_insights_{duty}',
                        period,
                        start_date_db,
                        end_date_db
                    )
                    logger.info(f"  ✅ Logged {duty} to database")
                
            except Exception as e:
                logger.error(f"❌ Failed to log to database: {e}")
        else:
            logger.info(f"ℹ️ Test mode - skipping database logging")

    except Exception as e:
        logger.error(f"❌ Staff Insights export failed: {e}")
        logger.error(traceback.format_exc())
        
        if progress_msg:
            await progress_msg.edit(embed=discord.Embed(
                title="❌ Export Failed",
                description=f"Error: {str(e)[:200]}",
                color=discord.Color.red()
            ))
# ==================== EXACT TIMING AUTOMATION ====================

# Constants for exact timing
# Trigger times
# Mid-Week: 72h 30m
# Full Week: 169h 00m (30 minutes after weekly checks)
MID_WEEK_INSIGHTS_HOURS = 72 + (30 / 60)   # = 72.5
FULL_WEEK_INSIGHTS_HOURS = 169 + (0 / 60)   # = 169.0

def get_global_dates_from_config():
    """Get global dates from config.json and convert to YYYY-MM-DD format"""
    import json
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
        
        # ✅ Convert from DD/MM/YYYY to YYYY-MM-DD if needed
        if start_date and '/' in start_date:
            try:
                dt = datetime.strptime(start_date, '%d/%m/%Y')
                start_date = dt.strftime('%Y-%m-%d')
            except ValueError:
                pass  # Already in correct format or invalid
        
        if end_date and '/' in end_date:
            try:
                dt = datetime.strptime(end_date, '%d/%m/%Y')
                end_date = dt.strftime('%Y-%m-%d')
            except ValueError:
                pass  # Already in correct format or invalid
        
        return start_date, end_date
    except Exception as e:
        logger.error(f"Failed to load config.json: {e}")
        return None, None

def get_start_datetime_utc(start_date: str) -> datetime:
    """Convert start_date string to datetime at 00:00:00 UTC
    
    ✅ Handles both formats:
    - YYYY-MM-DD (from config conversion)
    - DD/MM/YYYY (original format)
    """
    if '-' in start_date:
        # YYYY-MM-DD format
        dt = datetime.strptime(start_date, '%Y-%m-%d')
    else:
        # DD/MM/YYYY format
        dt = datetime.strptime(start_date, '%d/%m/%Y')
    return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

async def run_insights_at_exact_time(bot, period: str, hours_to_wait: float):
    """
    Run staff insights at exact time (72:30:00 for mid-week, 169:00:00 for full week)
    
    ✅ CRITICAL FIX: Wait for bot ready INSIDE task
    ✅ NEW: "Too late" protection - skips if >1 hour past scheduled time
    ✅ FIXED: Re-reads dates from config RIGHT BEFORE running export
    """
    # ✅ CRITICAL FIX: Wait for bot ready INSIDE task
    await bot.wait_until_ready()
    logger.info(f"✅ {period} insights task is now active and waiting for triggers")
    
    while True:
        try:
            # Get global dates ONLY for calculating trigger time and checking if already sent
            start_date_for_trigger, end_date_for_trigger = get_global_dates_from_config()
            
            if not start_date_for_trigger or not end_date_for_trigger:
                logger.debug(f"⏸️ No global dates configured, waiting...")
                await asyncio.sleep(300)
                continue
            
            # Calculate exact trigger time
            start_datetime = get_start_datetime_utc(start_date_for_trigger)
            target_time = start_datetime + timedelta(hours=hours_to_wait)
            now = datetime.now(timezone.utc)
            
            # Check if already sent
            already_sent = False
            import json
            with open('config.json', 'r') as f:
                config = json.load(f)

            auto_config = config.get('automated_checks', {})
            report_guild_id = auto_config.get('report_guild_id', 1041450125391835186)

            # ✅ FIX: Normalise dates to YYYY-MM-DD so the DB check matches
            # what mark_report_sent stores (it always converts to YYYY-MM-DD).
            def _to_ymd(d):
                if '/' in d:
                    return datetime.strptime(d, '%d/%m/%Y').strftime('%Y-%m-%d')
                return d

            check_start = _to_ymd(start_date_for_trigger)

            # ✅ FIX: Calculate check_end the same way as export_staff_insights_reports
            if period == "Mid-Week":
                # For mid-week, end date is 72 hours after week start
                midweek_end_dt = start_datetime + timedelta(hours=72)
                check_end = midweek_end_dt.strftime('%Y-%m-%d')
            else:
                # For full week, use global end date
                check_end = _to_ymd(end_date_for_trigger)

            # Determine which duties to check based on period
            duties_to_check = ['role', 'req']
            if period == "Full Week":
                duties_to_check.extend(['modlog', 'message'])

            for duty in duties_to_check:
                if await database.check_report_already_sent(
                    report_guild_id,
                    f'staff_insights_{duty}',
                    period,
                    check_start,
                    check_end
                ):
                    already_sent = True
                    break
            
            if already_sent:
                logger.info(f"⏭️ {period} insights already sent for {start_date_for_trigger}, waiting for new week...")
                wait_until = target_time + timedelta(hours=168)
                wait_seconds = (wait_until - now).total_seconds()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                else:
                    # Dates in config.json are stale — log clearly and wait 30 min to avoid spam
                    logger.error(
                        f"❌ STUCK: {period} insights for {start_date_for_trigger} already sent, "
                        f"but next cycle ({wait_until}) is also in the past. "
                        f"Update global_dates in config.json to the current week's dates to resume. "
                        f"Retrying in 30 minutes."
                    )
                    await asyncio.sleep(1800)
                continue
            
            # Calculate time difference
            time_diff = (target_time - now).total_seconds()
            
            # "Too late" protection — skip only if missed by more than 24 hours
            TOO_LATE_SECONDS = 86400  # 24 hours
            if time_diff < -TOO_LATE_SECONDS:
                hours_late = abs(time_diff) / 3600
                logger.warning(f"⚠️ {period} insights trigger missed by {hours_late:.1f} hours - TOO LATE, skipping")
                logger.warning(f"   Target time was: {target_time}")
                logger.warning(f"   Current time is: {now}")

                # Wait until next week's equivalent trigger time
                wait_until = target_time + timedelta(hours=168)
                wait_seconds = (wait_until - now).total_seconds()
                if wait_seconds > 0:
                    logger.info(f"   ⏳ Waiting until next cycle: {wait_until}")
                    await asyncio.sleep(wait_seconds)
                else:
                    # Dates in config.json are stale - log clearly and wait 30 min to avoid spam
                    logger.error(
                        f"❌ STUCK: {period} insights next cycle ({wait_until}) is also in the past. "
                        f"Update global_dates in config.json to the current week's dates to resume. "
                        f"Retrying in 30 minutes."
                    )
                    await asyncio.sleep(1800)
                continue

            # If before trigger, wait
            if time_diff > 0:
                logger.info(f"⏰ {period} insights scheduled for {target_time} (in {time_diff/3600:.1f} hours)")
                logger.info(f"   Waiting {time_diff:.0f} seconds...")
                await asyncio.sleep(time_diff)

                # Re-check after waking
                now = datetime.now(timezone.utc)
                actual_diff = (now - target_time).total_seconds()

                if actual_diff > TOO_LATE_SECONDS:
                    logger.warning(f"⚠️ {period} insights woke up {actual_diff/3600:.1f} hours late - skipping")
                    wait_until = target_time + timedelta(hours=168)
                    wait_seconds = (wait_until - now).total_seconds()
                    if wait_seconds > 0:
                        await asyncio.sleep(wait_seconds)
                    else:
                        logger.error(
                            f"❌ STUCK: {period} insights next cycle ({wait_until}) is also in the past. "
                            f"Update global_dates in config.json to the current week's dates to resume. "
                            f"Retrying in 30 minutes."
                        )
                        await asyncio.sleep(1800)
                    continue  # continue is INSIDE the late check — normal wakeup falls through to run
            
            # RUN THE INSIGHTS!
            logger.info(f"📊 ========================================")
            logger.info(f"📊 RUNNING {period.upper()} STAFF INSIGHTS")
            
            # ✅ CRITICAL FIX: RE-READ DATES FROM CONFIG RIGHT BEFORE RUNNING
            # This ensures we use the CURRENT week's dates, not the dates from when we started waiting
            logger.info(f"📅 Re-reading dates from config.json to ensure current week...")
            start_date, end_date = get_global_dates_from_config()
            
            if not start_date or not end_date:
                logger.error(f"❌ Could not read dates from config after waking up!")
                await asyncio.sleep(300)
                continue
            
            logger.info(f"📊 Period: {start_date} → {end_date}")
            logger.info(f"📊 Exact time: {hours_to_wait} hours after start")
            logger.info(f"📊 ========================================")
            
            # Convert dates to DD/MM/YYYY format for the export function
            # Handle both formats since get_global_dates_from_config may return either
            if '/' in start_date:
                start_dd_mm_yyyy = start_date  # Already in DD/MM/YYYY
            else:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                start_dd_mm_yyyy = start_dt.strftime('%d/%m/%Y')
            
            if '/' in end_date:
                end_dd_mm_yyyy = end_date  # Already in DD/MM/YYYY
            else:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                end_dd_mm_yyyy = end_dt.strftime('%d/%m/%Y')
            
            logger.info(f"📅 Using dates for export: {start_dd_mm_yyyy} → {end_dd_mm_yyyy}")
            
            # Call the main export function
            is_midweek = (period == "Mid-Week")
            
            await export_staff_insights_reports(
                bot=bot,
                start_date=start_dd_mm_yyyy,
                end_date=end_dd_mm_yyyy,
                is_test=False,
                ctx=None,  # No context for automated run
                is_midweek=is_midweek
            )
            
            logger.info(f"✅ ========================================")
            logger.info(f"✅ {period.upper()} STAFF INSIGHTS COMPLETED")
            logger.info(f"✅ ========================================")
            
            # Wait until next week
            wait_until = start_datetime + timedelta(hours=168 + 24)
            wait_seconds = (wait_until - datetime.now(timezone.utc)).total_seconds()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
        
        except Exception as e:
            logger.error(f"❌ Error in {period} insights task: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(300)

# ==================== COG SETUP ====================

class StaffInsightsAutomation(discord.ext.commands.Cog):
    """Automated staff insights with exact timing"""
    
    def __init__(self, bot):
        self.bot = bot
        self.midweek_task = None
        self.fullweek_task = None
    
    async def cog_load(self):
        """Start background tasks when cog loads"""
         # ✅ CRITICAL FIX: Don't wait for ready here!
        logger.info("🚀 Starting automated staff insights with EXACT timing...")
        
        # Start tasks immediately - they will wait internally
        self.midweek_task = asyncio.create_task(
            run_insights_at_exact_time(self.bot, "Mid-Week", MID_WEEK_INSIGHTS_HOURS)
        )
        self.fullweek_task = asyncio.create_task(
            run_insights_at_exact_time(self.bot, "Full Week", FULL_WEEK_INSIGHTS_HOURS)
        )
        logger.info(f"⏰ Mid-Week insights: {MID_WEEK_INSIGHTS_HOURS} hours")
        logger.info(f"⏰ Full Week insights: {FULL_WEEK_INSIGHTS_HOURS} hours")
        logger.info(f"✅ Tasks created! (will activate when bot is ready)")
    
    def cog_unload(self):
        """Cancel background tasks when cog unloads"""
        if self.midweek_task:
            self.midweek_task.cancel()
        if self.fullweek_task:
            self.fullweek_task.cancel()
        
        logger.info("🛑 Staff insights tasks stopped")

async def setup(bot):
    await bot.add_cog(StaffInsightsAutomation(bot))