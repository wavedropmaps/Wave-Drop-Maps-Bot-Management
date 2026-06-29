"""
WaveBot - Global Constants
All configuration constants and defaults
"""

import os
from datetime import timedelta

# ==================== FILE PATHS ====================
CONFIG_FILE = 'config.json'
CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')

# ==================== GOOGLE SHEETS ====================
TEMPLATE_SHEET_ID = '1ygVKm6JqNlYgam7vZv660lSeDrRh1vDo6-Q8ZkTxV4M'
EXPORT_FOLDER_ID = '17oo-jdrpsUD-C3xEC1Pqo4imhjK7Ousq'
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# ==================== SCREENSHOT SETTINGS ====================
COLUMN_I_PIXEL_LIMIT = 1200  # Approximate right edge of column I

# ==================== AUTOMATION SCHEDULE ====================
MID_WEEK_HOURS = 72  # 3 days
FULL_WEEK_HOURS = 168  # 7 days
STAFF_SHEET_EXPORT_OFFSET_HOURS = 1  # Hours after full week

# ==================== PAGINATION ====================
PAGINATION_CHUNK_SIZE = 20
MAX_EMBED_FIELD_LENGTH = 1024
MAX_EMBED_DESCRIPTION_LENGTH = 4096

# ==================== RATE LIMITING ====================
MESSAGE_FETCH_BATCH_SIZE = 10