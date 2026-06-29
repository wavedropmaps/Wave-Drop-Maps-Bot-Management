"""
Core Module
Core functionality for the Discord Staff Activity Bot
"""

# Import from cache
from .cache import config_cache, rate_limiter, ConfigCache, RateLimitTracker

# Import from constants
from .constants import (
    CONFIG_FILE,
    CREDENTIALS_FILE,
    TEMPLATE_SHEET_ID,
    EXPORT_FOLDER_ID,
    SCOPES,
    COLUMN_I_PIXEL_LIMIT,
    MID_WEEK_HOURS,
    FULL_WEEK_HOURS,
    STAFF_SHEET_EXPORT_OFFSET_HOURS,
    PAGINATION_CHUNK_SIZE,
    MAX_EMBED_FIELD_LENGTH,
    MAX_EMBED_DESCRIPTION_LENGTH,
    MESSAGE_FETCH_BATCH_SIZE
)

# Import from shutdown
from .shutdown import shutdown_handler, setup_signal_handlers

# Import from helpers (all the utility functions)
from .helpers import (
    get_automation_config,
    get_screenshot_channels,
    get_staff_members_from_guild,
    parse_date,
    get_start_datetime,
    get_end_datetime,
    validate_date_range,
    create_error_embed,
    create_success_embed,
    extract_embed_content,
    send_paginated,
    get_member,
    check_if_user_is_away,
    check_dates_configured,
    format_duration,
    format_number,
    get_readable_text_channels,
    safe_history_fetch,
    scan_channels_parallel,
    predict_end_of_week_performance,
    is_allowed_channel,
    AWAY_ROLE_ID
)

__all__ = [
    # Cache
    'config_cache',
    'rate_limiter',
    'ConfigCache',
    'RateLimitTracker',
    
    # Constants
    'CONFIG_FILE',
    'CREDENTIALS_FILE',
    'TEMPLATE_SHEET_ID',
    'EXPORT_FOLDER_ID',
    'SCOPES',
    'COLUMN_I_PIXEL_LIMIT',
    'MID_WEEK_HOURS',
    'FULL_WEEK_HOURS',
    'STAFF_SHEET_EXPORT_OFFSET_HOURS',
    'PAGINATION_CHUNK_SIZE',
    'MAX_EMBED_FIELD_LENGTH',
    'MAX_EMBED_DESCRIPTION_LENGTH',
    'MESSAGE_FETCH_BATCH_SIZE',
    
    # Shutdown
    'shutdown_handler',
    'setup_signal_handlers',
    
    # Helpers
    'get_automation_config',
    'get_screenshot_channels',
    'get_staff_members_from_guild',
    'parse_date',
    'get_start_datetime',
    'get_end_datetime',
    'validate_date_range',
    'create_error_embed',
    'create_success_embed',
    'extract_embed_content',
    'send_paginated',
    'get_member',
    'check_if_user_is_away',
    'check_dates_configured',
    'format_duration',
    'format_number',
    'get_readable_text_channels',
    'safe_history_fetch',
    'scan_channels_parallel',
    'predict_end_of_week_performance',
    'is_allowed_channel',
    'AWAY_ROLE_ID'
]