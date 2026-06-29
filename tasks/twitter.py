"""
Twitter/X Feed Monitor
======================
Monitors Nitter RSS feeds and posts new tweets to Discord channels
Currently tracking: @Aufruss via Nitter
"""

import asyncio
import discord
from discord.ext import tasks, commands
import feedparser
import logging
import aiosqlite
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger('discord')

# RSS feed configuration
TWITTER_FEEDS = {
    'fortnite': {
        'url': 'https://nitter.net/Fortnite/rss',
        'channel_id': 1050926043998990396,
        'username': '@Fortnite',
        'color': discord.Color.from_rgb(29, 155, 240)  # Twitter blue
    },
    'fortnitestatus': {
        'url': 'https://nitter.net/FortniteStatus/rss',
        'channel_id': 1115617065731100782,
        'username': '@FortniteStatus',
        'color': discord.Color.from_rgb(29, 155, 240)  # Twitter blue
    },
    'fncompetitive': {
        'url': 'https://nitter.net/FNCompetitive/rss',
        'channel_id': 1050926043998990396,
        'username': '@FNCompetitive',
        'color': discord.Color.from_rgb(29, 155, 240)  # Twitter blue
    },
    'shiinaabr': {
        'url': 'https://nitter.net/ShiinaBR/rss',
        'channel_id': 1128324094501335191,
        'username': '@ShiinaBR',
        'color': discord.Color.from_rgb(29, 155, 240)  # Twitter blue
    },
    'hypex': {
        'url': 'https://nitter.net/HYPEX/rss',
        'channel_id': 1128324094501335191,
        'username': '@HYPEX',
        'color': discord.Color.from_rgb(29, 155, 240)  # Twitter blue
    },
    'djlorenzouasset': {
        'url': 'https://nitter.net/djlorenzouasset/rss',
        'channel_id': 1128324094501335191,
        'username': '@djlorenzouasset',
        'color': discord.Color.from_rgb(29, 155, 240)  # Twitter blue
    }
}

# Database for tracking posted tweets
DB_FILE = Path('data/twitter_feed.db')


class TwitterMonitor(commands.Cog):
    """Monitors Twitter/Nitter feeds and posts to Discord"""

    def __init__(self, bot):
        self.bot = bot
        self.feed_data = {}
        self.initialize_db()
        self.start_tasks()

    def initialize_db(self):
        """Create database if it doesn't exist"""
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)

        import sqlite3
        try:
            conn = sqlite3.connect(DB_FILE, timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS twitter_posts (
                    post_id TEXT NOT NULL,
                    feed_key TEXT NOT NULL,
                    title TEXT,
                    url TEXT,
                    author TEXT,
                    posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    discord_message_id INTEGER,
                    PRIMARY KEY (post_id, feed_key)
                )
            ''')

            # Migrate legacy single-column PK (post_id) -> composite (post_id, feed_key).
            # The old global PK rejected the same tweet appearing in two feeds (e.g. a
            # retweet of @FortniteStatus by @FNCompetitive), raising
            # "UNIQUE constraint failed: twitter_posts.post_id".
            cursor.execute("PRAGMA table_info(twitter_posts)")
            pk_cols = [row[1] for row in cursor.fetchall() if row[5] > 0]
            if pk_cols == ['post_id']:
                logger.info("🔧 Migrating twitter_posts -> composite PK (post_id, feed_key)...")
                cursor.execute("ALTER TABLE twitter_posts RENAME TO twitter_posts_old")
                cursor.execute('''
                    CREATE TABLE twitter_posts (
                        post_id TEXT NOT NULL,
                        feed_key TEXT NOT NULL,
                        title TEXT,
                        url TEXT,
                        author TEXT,
                        posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        discord_message_id INTEGER,
                        PRIMARY KEY (post_id, feed_key)
                    )
                ''')
                cursor.execute('''
                    INSERT OR IGNORE INTO twitter_posts
                    (post_id, feed_key, title, url, author, posted_at, discord_message_id)
                    SELECT post_id, feed_key, title, url, author, posted_at, discord_message_id
                    FROM twitter_posts_old
                ''')
                cursor.execute("DROP TABLE twitter_posts_old")
                logger.info("✅ twitter_posts migration complete")

            # Check which feeds already have data in database
            cursor.execute('SELECT DISTINCT feed_key FROM twitter_posts')
            existing_feeds = set(row[0] for row in cursor.fetchall())

            # Find NEW feeds that need initialization
            new_feeds = set(TWITTER_FEEDS.keys()) - existing_feeds

            if new_feeds:
                logger.info(f"🆕 Found {len(new_feeds)} new feed(s): {', '.join(new_feeds)}")
                logger.info("⚠️ Initializing new feeds — will skip old tweets and only post NEW ones")

                for feed_key in new_feeds:
                    feed_config = TWITTER_FEEDS[feed_key]
                    logger.info(f"📊 Pre-populating {feed_key} ({feed_config['username']})...")

                    entries = self._parse_feed_sync(feed_config['url'])
                    for entry in entries:
                        post_id = entry.get('id', entry.get('link', ''))
                        cursor.execute('''
                            INSERT OR IGNORE INTO twitter_posts
                            (post_id, feed_key, title, url, author)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (post_id, feed_key, entry.get('title', 'No title'),
                              entry.get('link', ''), entry.get('author', feed_config['username'])))
                    logger.info(f"✅ Marked {len(entries)} existing tweets as already posted for {feed_key}")
            else:
                logger.info("✅ All feeds already initialized")

            conn.commit()
            conn.close()
            logger.info("✅ Twitter feed database initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Twitter DB: {e}")

    def _parse_feed_sync(self, feed_url: str) -> list:
        """Synchronous version for database initialization"""
        try:
            feed = feedparser.parse(feed_url)
            return feed.entries if feed.entries else []
        except Exception as e:
            logger.error(f"❌ Error parsing feed {feed_url}: {e}")
            return []

    def start_tasks(self):
        """Start all Twitter monitoring tasks"""
        if not self.monitor_feeds.is_running():
            self.monitor_feeds.start()
            logger.info("✅ Twitter feed monitoring started (first check in 30 seconds, then every 5 min)")

    def stop_tasks(self):
        """Stop all Twitter monitoring tasks"""
        if self.monitor_feeds.is_running():
            self.monitor_feeds.cancel()
        logger.info("✅ Twitter feed monitoring stopped")

    def cog_unload(self):
        """Called when cog is unloaded"""
        self.stop_tasks()

    async def post_already_exists(self, post_id: str, feed_key: str) -> bool:
        """Check if this tweet has already been posted for this specific feed"""
        try:
            async with aiosqlite.connect(DB_FILE, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                cursor = await db.execute(
                    'SELECT 1 FROM twitter_posts WHERE post_id = ? AND feed_key = ?',
                    (post_id, feed_key)
                )
                result = await cursor.fetchone()
                return result is not None
        except Exception as e:
            logger.error(f"❌ Error checking if post exists: {e}")
            return False

    async def record_post(self, post_id: str, feed_key: str, title: str,
                         url: str, author: str, message_id: int = None):
        """Record that a tweet has been posted"""
        try:
            async with aiosqlite.connect(DB_FILE, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                cursor = await db.execute('''
                    INSERT OR IGNORE INTO twitter_posts
                    (post_id, feed_key, title, url, author, discord_message_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (post_id, feed_key, title, url, author, message_id))
                await db.commit()
                if cursor.rowcount > 0:
                    logger.debug(f"✅ Recorded post: {post_id} [{feed_key}]")
                else:
                    logger.debug(f"⏭️ Post already recorded: {post_id} [{feed_key}]")
        except Exception as e:
            logger.error(f"❌ Error recording post: {e}")

    def parse_feed(self, feed_url: str) -> list:
        """Fetch and parse RSS feed"""
        try:
            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                logger.warning(f"⚠️ Feed parsing failed: {feed.bozo_exception}")

            return feed.entries if feed.entries else []
        except Exception as e:
            logger.error(f"❌ Error parsing feed {feed_url}: {e}")
            return []

    def _extract_tweet_id(self, nitter_url: str, username: str) -> str:
        """Extract tweet ID from Nitter URL and return Twitter/X URL"""
        try:
            # Nitter URL format: https://nitter.net/username/status/TWEET_ID#m
            if '/status/' in nitter_url:
                tweet_id = nitter_url.split('/status/')[1].split('#')[0].split('?')[0]
                # Proper X.com format: https://x.com/@username/status/TWEET_ID
                clean_username = username.lstrip('@')
                return f"https://x.com/{clean_username}/status/{tweet_id}"
            return nitter_url  # Fallback to original if parsing fails
        except Exception as e:
            logger.warning(f"⚠️ Failed to convert URL: {e}, using original")
            return nitter_url

    def _extract_image_from_entry(self, entry) -> str:
        """Extract image URL from tweet entry description and convert to Twitter URL"""
        try:
            description = entry.get('description', '')
            if not description:
                return None

            # Look for img src in HTML description
            import re
            import urllib.parse

            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description)
            if not img_match:
                return None

            nitter_img_url = img_match.group(1)

            # Convert Nitter image URL to actual Twitter URL
            # Nitter format: https://nitter.net/pic/[URL_ENCODED_PATH]
            # Twitter format: https://pbs.twimg.com/[DECODED_PATH]
            if '/pic/' in nitter_img_url:
                # Extract the encoded path after /pic/
                encoded_path = nitter_img_url.split('/pic/')[1]
                # URL decode it
                decoded_path = urllib.parse.unquote(encoded_path)
                # Build the actual Twitter media URL
                twitter_img_url = f"https://pbs.twimg.com/{decoded_path}"
                logger.debug(f"Converted image URL: {twitter_img_url}")
                return twitter_img_url

            return nitter_img_url
        except Exception as e:
            logger.debug(f"Could not extract image: {e}")
            return None

    async def post_tweet_to_discord(self, feed_key: str, entry) -> bool:
        """Post a tweet to the configured Discord channel"""
        feed_config = TWITTER_FEEDS.get(feed_key)
        if not feed_config:
            logger.error(f"❌ No config found for feed: {feed_key}")
            return False

        try:
            channel = self.bot.get_channel(feed_config['channel_id'])
            if not channel:
                logger.error(f"❌ Channel {feed_config['channel_id']} not found")
                return False

            # Extract tweet data
            title = entry.get('title', 'No title')
            nitter_url = entry.get('link', '')
            author = entry.get('author', feed_config['username'])
            twitter_url = self._extract_tweet_id(nitter_url, author)  # Convert to actual Twitter/X link
            image_url = self._extract_image_from_entry(entry)  # Get tweet image if available

            # Clean up title (Nitter adds "RT by @user: " prefix)
            if title.startswith('RT by '):
                title = title.split(': ', 1)[1] if ': ' in title else title

            # Create embed with Twitter/X link instead of Nitter
            embed = discord.Embed(
                title=title[:256],  # Discord title limit
                url=twitter_url,  # ← Points to actual Twitter/X, not Nitter
                color=feed_config['color'],
                timestamp=datetime.now(timezone.utc)
            )

            embed.set_author(
                name=feed_config['username'],
                url=f"https://x.com/{feed_config['username'].lstrip('@')}"  # Link to actual Twitter/X profile
            )

            # Add image if available
            if image_url:
                embed.set_image(url=image_url)

            embed.set_footer(text="Twitter Feed Monitor")

            # Send the embed
            message = await channel.send(embed=embed)

            logger.info(
                f"✅ Posted tweet from {author} to {channel.name} "
                f"(Twitter URL: {twitter_url})"
            )

            return message.id

        except Exception as e:
            logger.error(f"❌ Error posting tweet to Discord: {e}", exc_info=True)
            return None

    async def process_feed(self, feed_key: str, feed_config: dict) -> tuple:
        """Process a single feed (can run in parallel)"""
        try:
            entries = await asyncio.to_thread(self.parse_feed, feed_config['url'])

            if not entries:
                logger.debug(f"⏭️ No entries in {feed_key} feed")
                return feed_key, 0, 0

            new_count = 0
            skipped_count = 0

            # Check all entries (newest first)
            for entry in entries[:20]:
                post_id = entry.get('id', entry.get('link', ''))

                if await self.post_already_exists(post_id, feed_key):
                    skipped_count += 1
                    continue

                message_id = await self.post_tweet_to_discord(feed_key, entry)

                if message_id:
                    await self.record_post(
                        post_id=post_id,
                        feed_key=feed_key,
                        title=entry.get('title', 'No title'),
                        url=entry.get('link', ''),
                        author=entry.get('author', feed_config['username']),
                        message_id=message_id
                    )
                    new_count += 1

            return feed_key, new_count, skipped_count

        except Exception as e:
            logger.error(f"❌ Error monitoring {feed_key}: {e}", exc_info=True)
            return feed_key, 0, 0

    @tasks.loop(minutes=5)
    async def monitor_feeds(self):
        """Check all feeds in parallel every 5 minutes"""
        import asyncio

        # Fetch all feeds in parallel (much faster!)
        tasks = [
            self.process_feed(feed_key, feed_config)
            for feed_key, feed_config in TWITTER_FEEDS.items()
        ]

        results = await asyncio.gather(*tasks)

        # Log results
        for feed_key, new_count, skipped_count in results:
            if new_count > 0:
                logger.info(f"📊 {feed_key}: Posted {new_count} new tweet(s)")

    @monitor_feeds.before_loop
    async def before_monitor(self):
        """Wait for bot to be ready before monitoring"""
        await self.bot.wait_until_ready()
        logger.info("🚀 Twitter monitor ready, starting feed checks every 5 minutes...")
        print("\n✅ TWITTER MONITOR ACTIVE - Will check every 5 minutes\n")


async def setup(bot):
    """Required setup function for cog loading"""
    await bot.add_cog(TwitterMonitor(bot))
    logger.info("✅ TwitterMonitor cog loaded")
