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
from core.utils import humanbytes
from handlers.handlers import start_command, help_command, handle_url
from services.downloaders import cleanup_old_downloads, check_disk_space

# Install uvloop for faster asyncio performance
uvloop.install()

# Disable Pyrogram's internal logging
pyrogram_logger = logging.getLogger("pyrogram")
pyrogram_logger.setLevel(logging.ERROR)  # Only show ERROR level logs

# Initialize the bot with improved flood wait handling
app = Client(
    "video_downloader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    sleep_threshold=60,  # Sleep if flood wait is more than 60 seconds
    max_concurrent_transmissions=3,  # Limit concurrent operations
    no_updates=False  # Still receive updates
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

# Handle YouTube format selection
async def handle_youtube_format_selection(client, message):
    """Handle YouTube format selection commands"""
    user_id = message.from_user.id
    command = message.text.strip().lower()

    # Check if we have stored data for this user
    if not hasattr(client, 'user_data') or user_id not in client.user_data:
        await message.reply_text("⚠️ No pending YouTube download. Please send a YouTube URL first.")
        return

    # Get stored data
    user_data = client.user_data[user_id]
    if 'youtube_url' not in user_data or 'file_path' not in user_data:
        await message.reply_text("⚠️ No pending YouTube download. Please send a YouTube URL first.")
        return

    # Get the original processing message
    try:
        processing_msg = await client.get_messages(message.chat.id, user_data['processing_msg_id'])
    except Exception as e:
        logger.error(f"Error getting processing message: {e}")
        # Create a new processing message
        processing_msg = await message.reply_text("🔄 Processing your selection...")

    # Get stored URL and file path
    url = user_data['youtube_url']
    file_path = user_data['file_path']

    # Track download
    from handlers.handlers import active_downloads, user_download_counts
    today = time.strftime("%Y-%m-%d")
    if user_id not in active_downloads:
        active_downloads[user_id] = 0
    active_downloads[user_id] += 1

    if user_id not in user_download_counts:
        user_download_counts[user_id] = {}
    if today not in user_download_counts[user_id]:
        user_download_counts[user_id][today] = 0
    user_download_counts[user_id][today] += 1

    # Process the command
    try:
        from services.downloaders import download_youtube_video, get_youtube_formats
        from handlers.handlers import progress_for_pyrogram

        # Check if it's the audio command
        if command == "/audio":
            # Download as MP3
            success, result = await download_youtube_video(url, file_path, processing_msg, user_id, None, True)
        else:
            # Extract format number
            format_num = None
            if command.startswith("/"):
                try:
                    format_num = int(command[1:]) - 1  # Convert to 0-based index
                except ValueError:
                    pass

            if format_num is None:
                await processing_msg.edit_text("⚠️ Invalid format selection. Please select a valid option.")
                active_downloads[user_id] -= 1
                user_download_counts[user_id][today] -= 1
                return

            # Get available formats
            formats_info = await get_youtube_formats(url)
            if not formats_info or format_num < 0 or format_num >= len(formats_info['formats']):
                await processing_msg.edit_text("⚠️ Invalid format selection. Please select a valid option.")
                active_downloads[user_id] -= 1
                user_download_counts[user_id][today] -= 1
                return

            # Get selected format
            selected_format = formats_info['formats'][format_num]
            format_id = selected_format['format_id']

            # Download with selected format
            success, result = await download_youtube_video(url, file_path, processing_msg, user_id, format_id)

        # Clear stored data
        del client.user_data[user_id]

        if success:
            # Video downloaded successfully, send it to the user
            file_path = result  # In case the downloader returned a different path
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)

            # Update message before sending file
            await processing_msg.edit_text(f"✅ Download complete!\n\n**File:** {file_name}\n**Size:** {humanbytes(file_size)}\n\n🔄 Now sending the file...")

            # Send the file based on extension
            try:
                # Get file extension
                _, file_ext = os.path.splitext(file_path)
                file_ext = file_ext.lower()

                # Common video formats to send as video
                video_extensions = ['.mp4', '.mov', '.avi', '.webm']

                # Send as video or document based on extension
                if file_ext in video_extensions:
                    # Send as video
                    await client.send_video(
                        chat_id=message.chat.id,
                        video=file_path,
                        caption=f"🎬 Video: {file_name}\n📏 Size: {humanbytes(file_size)}",
                        progress=progress_for_pyrogram,
                        progress_args=("📤 Uploading video...", processing_msg, time.time())
                    )
                elif file_ext == '.mp3':
                    # Send as audio
                    await client.send_audio(
                        chat_id=message.chat.id,
                        audio=file_path,
                        caption=f"🎵 Audio: {file_name}\n📏 Size: {humanbytes(file_size)}",
                        progress=progress_for_pyrogram,
                        progress_args=("📤 Uploading audio...", processing_msg, time.time())
                    )
                else:
                    # Send as document
                    await client.send_document(
                        chat_id=message.chat.id,
                        document=file_path,
                        caption=f"📁 File: {file_name}\n📏 Size: {humanbytes(file_size)}",
                        progress=progress_for_pyrogram,
                        progress_args=("📤 Uploading file...", processing_msg, time.time())
                    )

                # Delete the downloaded file after sending
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"Deleted file after sending: {file_path}")
                    else:
                        logger.info(f"File already deleted or doesn't exist: {file_path}")
                except Exception as e:
                    logger.error(f"Error deleting file: {str(e)}")

                # Final success message
                await processing_msg.edit_text(f"✅ File sent successfully!\n\n**File:** {file_name}\n**Size:** {humanbytes(file_size)}")

            except Exception as e:
                logger.error(f"Error sending file: {str(e)}")
                await processing_msg.edit_text(f"⚠️ Error sending file: {str(e)}")

                # Try to clean up the file
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as cleanup_error:
                    logger.error(f"Error during cleanup: {str(cleanup_error)}")
        else:
            # Download failed
            await processing_msg.edit_text(f"⚠️ Download failed: {result}")

            # Try to clean up any partial downloads
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Cleaned up partial download: {file_path}")
                else:
                    logger.info(f"No partial download to clean up")
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {str(cleanup_error)}")
    except Exception as e:
        logger.error(f"Error in YouTube format selection handler: {str(e)}")
        await processing_msg.edit_text(f"⚠️ An error occurred: {str(e)}")
    finally:
        # Decrement active downloads counter
        active_downloads[user_id] -= 1

# Handle all text messages (URLs)
@app.on_message(filters.text & ~filters.command(["start", "help", "stats", "cleanup"]))
async def url_handler(client, message):
    # Check if it's a format selection command
    if message.text.startswith("/") and (message.text.lower() == "/audio" or message.text[1:].isdigit()):
        await handle_youtube_format_selection(client, message)
    else:
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