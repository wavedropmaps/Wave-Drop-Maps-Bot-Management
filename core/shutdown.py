"""
Wave Bot - Shutdown Handler
Graceful shutdown with cleanup
"""

import logging
import signal
import asyncio

logger = logging.getLogger('discord')

async def shutdown_handler(bot):
    """Handle graceful shutdown"""
    logger.info("🛑 Initiating graceful shutdown...")
    
    try:
        # Stop background tasks properly using their stop methods
        logger.info("Stopping background tasks...")
        
        if hasattr(bot, 'automated_reports'):
            bot.automated_reports.stop_tasks()
            logger.info("✅ Automated report tasks stopped")
        
        if hasattr(bot, 'maintenance_tasks'):
            bot.maintenance_tasks.stop_tasks()
            logger.info("✅ Maintenance tasks stopped")
        
        if hasattr(bot, 'leaderboard_tasks'):
            bot.leaderboard_tasks.stop_tasks()
            logger.info("✅ Leaderboard tasks stopped")
        
        # Give tasks a moment to cancel cleanly
        await asyncio.sleep(0.5)
        
        # Clean up database
        logger.info("Cleaning up database...")
        try:
            import database
            await database.vacuum_database()
            await database.close_db()
            logger.info("✅ Database cleaned and closed")
        except Exception as e:
            logger.warning(f"⚠️ Database cleanup warning: {e}")
        
        # Close bot connection
        logger.info("Closing bot connection...")
        await bot.close()
        logger.info("✅ Bot connection closed")
        logger.info("✅ Shutdown complete")
        
    except asyncio.CancelledError:
        logger.info("✅ Shutdown cancelled gracefully")
    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")


def setup_signal_handlers(bot):
    """Setup signal handlers for graceful shutdown"""
    
    def handle_signal(sig, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(shutdown_handler(bot))
    
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_signal)   # Ctrl+C
    signal.signal(signal.SIGTERM, handle_signal)  # Kill command
    
    logger.info("✅ Signal handlers configured")