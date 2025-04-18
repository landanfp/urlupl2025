import os
import sys
import logging
import asyncio
import uvloop
import shutil
import json
import time
import psutil
import pyrogram
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from aiohttp import web

# Import modules
from core.config import (
    API_ID, API_HASH, BOT_TOKEN, logger, DOWNLOAD_DIR,
    AUTH_ENABLED, ADMIN_USERS
)
from handlers.handlers import start_command, help_command, handle_url
from services.downloaders import cleanup_old_downloads, check_disk_space

# Install uvloop for faster asyncio performance
uvloop.install()

# Initialize the bot
app = Client(
    "video_downloader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Register command handlers
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await start_command(client, message)

@app.on_message(filters.command("help"))
async def help_handler(client, message):
    await help_command(client, message)

# Admin commands
@app.on_message(filters.command("stats"))
async def stats_handler(client, message):
    """Show bot statistics"""
    # Check if user is admin
    if AUTH_ENABLED and message.from_user.id not in ADMIN_USERS:
        await message.reply_text("⛔ Only admins can use this command.")
        return

    try:
        # Get disk usage
        total, used, free = shutil.disk_usage(DOWNLOAD_DIR)
        total_gb = total / (1024**3)
        used_gb = used / (1024**3)
        free_gb = free / (1024**3)

        # Count files in download directory
        file_count = 0
        for root, dirs, files in os.walk(DOWNLOAD_DIR):
            file_count += len(files)

        # Get active downloads from handlers
        from handlers.handlers import active_downloads, user_download_counts
        total_active = sum(active_downloads.values())

        # Format stats message
        stats_text = (
            "**Bot Statistics:**\n\n"
            f"**Disk Usage:** {used_gb:.2f}GB / {total_gb:.2f}GB ({free_gb:.2f}GB free)\n"
            f"**Downloaded Files:** {file_count}\n"
            f"**Active Downloads:** {total_active}\n"
            f"**Users:** {len(user_download_counts)}\n"
        )

        await message.reply_text(stats_text)
    except Exception as e:
        await message.reply_text(f"Error getting statistics: {str(e)}")
        logger.error(f"Error getting stats: {e}")

@app.on_message(filters.command("cleanup"))
async def cleanup_handler(client, message):
    """Clean up old downloads"""
    # Check if user is admin
    if AUTH_ENABLED and message.from_user.id not in ADMIN_USERS:
        await message.reply_text("⛔ Only admins can use this command.")
        return

    try:
        # Send initial message
        status_msg = await message.reply_text("Cleaning up old files...")

        # Get initial file count
        initial_count = 0
        for root, dirs, files in os.walk(DOWNLOAD_DIR):
            initial_count += len(files)

        # Run cleanup
        await cleanup_old_downloads(max_age_hours=1)  # Clean files older than 1 hour

        # Get new file count
        new_count = 0
        for root, dirs, files in os.walk(DOWNLOAD_DIR):
            new_count += len(files)

        # Calculate deleted files
        deleted_count = initial_count - new_count

        # Update message
        await status_msg.edit_text(f"Cleanup complete! {deleted_count} files removed.")
    except Exception as e:
        await message.reply_text(f"Error during cleanup: {str(e)}")
        logger.error(f"Error during cleanup: {e}")

# Status route for health check
async def status_check():
    """Check system status and return JSON response"""
    try:
        # Get system info
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        disk = shutil.disk_usage(DOWNLOAD_DIR)
        disk_total = disk.total / (1024**3)  # GB
        disk_used = disk.used / (1024**3)    # GB
        disk_free = disk.free / (1024**3)    # GB
        disk_percent = (disk.used / disk.total) * 100

        # Count files in download directory
        file_count = 0
        for root, dirs, files in os.walk(DOWNLOAD_DIR):
            file_count += len(files)

        # Get active downloads
        from handlers.handlers import active_downloads, user_download_counts
        total_active = sum(active_downloads.values())

        # Create status response
        status = {
            "status": "ok",
            "timestamp": int(time.time()),
            "uptime": int(time.time() - psutil.boot_time()),
            "bot": {
                "active_downloads": total_active,
                "users": len(user_download_counts),
                "files": file_count
            },
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "disk": {
                    "total_gb": round(disk_total, 2),
                    "used_gb": round(disk_used, 2),
                    "free_gb": round(disk_free, 2),
                    "percent": round(disk_percent, 2)
                }
            }
        }

        return web.json_response(status)
    except Exception as e:
        logger.error(f"Error in status check: {e}")
        return web.json_response({"status": "error", "error": str(e)}, status=500)

# Setup web server for status endpoint
async def setup_web_server():
    """Setup web server for status endpoint"""
    app = web.Application()
    app.router.add_get('/', lambda request: status_check())

    # Get port from environment or use default
    port = int(os.getenv("STATUS_PORT", 8080))

    # Start web server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    logger.info(f"Status endpoint available at http://0.0.0.0:{port}/")

# Handle all text messages (URLs)
@app.on_message(filters.text & ~filters.command(["start", "help", "stats", "cleanup"]))
async def url_handler(client, message):
    await handle_url(client, message)

# Validate environment variables
def validate_environment():
    """Validate required environment variables"""
    missing_vars = []

    if not API_ID:
        missing_vars.append("API_ID")
    if not API_HASH:
        missing_vars.append("API_HASH")
    if not BOT_TOKEN:
        missing_vars.append("TELEGRAM_BOT_TOKEN")

    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these variables in your .env file and try again.")
        return False

    return True

# Startup tasks
async def run_startup_tasks():
    """Run tasks at bot startup"""
    try:
        # Check disk space
        free_space = await check_disk_space()
        if free_space is not None and free_space < 1.0:  # Less than 1GB free
            logger.warning(f"Low disk space at startup: only {free_space:.2f}GB available")
            # Run cleanup
            await cleanup_old_downloads()

        # Create download directory if it doesn't exist
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        # Setup web server for status endpoint
        await setup_web_server()

        logger.info("Startup tasks completed successfully")
    except Exception as e:
        logger.error(f"Error during startup tasks: {e}")

# Start the bot
if __name__ == "__main__":
    # Validate environment variables
    if not validate_environment():
        sys.exit(1)

    print("Bot is starting...")

    # Create a separate event loop for startup tasks
    async def start_bot():
        # Run startup tasks first
        await run_startup_tasks()
        logger.info("Startup tasks completed, starting bot...")

        # Start the bot
        await app.start()

        # Idle to keep the bot running
        await idle()

        # Stop the bot when idle is interrupted
        await app.stop()

    # Run the startup and bot in the event loop
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())