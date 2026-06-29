"""
Wave Bot - Cache System
Configuration caching and rate limiting
"""

import asyncio
import os
import json
from datetime import datetime, timezone
from typing import Dict, Any
import logging

from .constants import CONFIG_FILE

logger = logging.getLogger('discord')

# ==================== CONFIG CACHE ====================

class ConfigCache:
    """In-memory config cache with auto-reload on file changes"""
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._last_modified = 0
        self._lock = asyncio.Lock()
    
    async def get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        """Get guild config with automatic cache refresh"""
        async with self._lock:
            guild_id_str = str(guild_id)
            
            # Check if file was modified
            try:
                current_mtime = os.path.getmtime(CONFIG_FILE)
                if current_mtime > self._last_modified:
                    await self._reload_config()
                    self._last_modified = current_mtime
            except OSError:
                pass
            
            # Get from cache or create default
            if 'guild_configs' not in self._cache:
                self._cache['guild_configs'] = {}
            
            if guild_id_str not in self._cache['guild_configs']:
                # Create default config for new guild
                self._cache['guild_configs'][guild_id_str] = {
                    'request_channel_id': None,
                    'ping_channel_id': None,
                    'uptime_channel_id': None,
                    'logging_channel_id': None,
                    'staff_role_id': None,
                    'automation_enabled': False,
                    'midweek_report_enabled': False,
                    'fullweek_report_enabled': False,
                    'staff_sheet_export_enabled': False,
                    'reply_dm_channel_id': None,
                    'reply_dm_staff_role_ids': [],
                    'reply_dm_log_channel_id': None,
                    'reply_dm_autodelete_enabled': False
                }
                # Save to file
                await self._save_config()
            
            return self._cache['guild_configs'][guild_id_str]
    
    async def update_guild_config(self, guild_id: int, updates: Dict[str, Any]):
        """Update guild config and save to file"""
        async with self._lock:
            guild_id_str = str(guild_id)
            
            if 'guild_configs' not in self._cache:
                self._cache['guild_configs'] = {}
            
            if guild_id_str not in self._cache['guild_configs']:
                self._cache['guild_configs'][guild_id_str] = {}
            
            # Apply updates
            self._cache['guild_configs'][guild_id_str].update(updates)
            
            # Save to file
            await self._save_config()
            
            logger.info(f"✅ Updated config for guild {guild_id}: {list(updates.keys())}")
    
    async def get_global_config(self) -> Dict[str, Any]:
        """Get global config (dates, settings)"""
        async with self._lock:
            # Check if file was modified
            try:
                current_mtime = os.path.getmtime(CONFIG_FILE)
                if current_mtime > self._last_modified:
                    await self._reload_config()
                    self._last_modified = current_mtime
            except OSError:
                pass
            
            # Return global config or default
            if 'global' not in self._cache:
                self._cache['global'] = {
                    'start_date': None,
                    'end_date': None,
                    'timezone': 'UTC'
                }
                await self._save_config()
            
            return self._cache['global']

    async def get_global_dates(self) -> Dict[str, str]:
        """
        Get global start and end dates
        
        Returns:
            dict with 'start_date' and 'end_date' keys (both strings in dd/mm/yyyy format)
        """
        global_config = await self.get_global_config()
        return {
            'start_date': global_config.get('start_date'),
            'end_date': global_config.get('end_date')
        }

    async def update_global_config(self, updates: Dict[str, Any]):
        """Update global config and save to file"""
        async with self._lock:
            if 'global' not in self._cache:
                self._cache['global'] = {}
            
            self._cache['global'].update(updates)
            await self._save_config()
            
            logger.info(f"✅ Updated global config: {list(updates.keys())}")
    
    async def _reload_config(self):
        """Reload config from file"""
        try:
            with open(CONFIG_FILE, 'r') as f:
                self._cache = json.load(f)
            logger.info(f"🔄 Config reloaded from {CONFIG_FILE}")
        except FileNotFoundError:
            # Create new config file
            self._cache = {
                'global': {
                    'start_date': None,
                    'end_date': None,
                    'timezone': 'UTC'
                },
                'guild_configs': {}
            }
            await self._save_config()
            logger.info(f"📝 Created new config file: {CONFIG_FILE}")
        except json.JSONDecodeError:
            logger.error(f"❌ Invalid JSON in {CONFIG_FILE}")
    
    async def save(self):
        """Manually save config to file (public method)"""
        async with self._lock:
            await self._save_config()

    async def _save_config(self):
        """Save config to file"""
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self._cache, f, indent=2)
            self._last_modified = os.path.getmtime(CONFIG_FILE)
            logger.debug(f"💾 Config saved to {CONFIG_FILE}")
        except Exception as e:
            logger.error(f"❌ Failed to save config: {e}")

# ==================== RATE LIMITER ====================

class RateLimitTracker:
    """Global rate limit tracking for API requests"""
    def __init__(self, min_delay: float = 0.5):
        self.last_request: Dict[str, datetime] = {}
        self.min_delay = min_delay  # Minimum seconds between requests to same endpoint
        self._lock = asyncio.Lock()
    
    async def wait_if_needed(self, endpoint: str):
        """Wait if we're requesting too fast"""
        async with self._lock:
            now = datetime.now()
            if endpoint in self.last_request:
                elapsed = (now - self.last_request[endpoint]).total_seconds()
                if elapsed < self.min_delay:
                    wait_time = self.min_delay - elapsed
                    await asyncio.sleep(wait_time)

            # Evict entries too old to ever throttle again. Anything older than the
            # cutoff can't trigger a wait, so it's dead weight — drop it. This keeps
            # last_request from growing unbounded when endpoint keys vary (e.g. per-id).
            cutoff = now.timestamp() - max(60.0, self.min_delay * 10)
            stale = [k for k, v in self.last_request.items() if v.timestamp() < cutoff]
            for k in stale:
                del self.last_request[k]

            self.last_request[endpoint] = datetime.now()

# ==================== GLOBAL INSTANCES ====================

config_cache = ConfigCache()
rate_limiter = RateLimitTracker()