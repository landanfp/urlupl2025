import os
import re
import time
import asyncio
import random
from urllib.parse import urlparse

from core.config import (
    logger, AUTH_ENABLED, MAX_CONCURRENT_DOWNLOADS,
    MAX_DOWNLOADS_PER_USER, MAX_FILE_SIZE
)
from core.utils import (
    is_valid_url, is_youtube_url, check_url_headers,
    is_user_authorized, is_admin_user, format_time, humanbytes,
    is_social_media_url
)
from services.downloaders import (
    download_direct_video, download_youtube_video, download_social_media_video,
    generate_file_path, cleanup_old_downloads, check_disk_space
)

async def start_command(client, message):
    """Handle /start command"""
    user_id = message.from_user.id
    user_name = message.from_user.first_name

    # Check if user is authorized if auth is enabled
    if AUTH_ENABLED and not is_user_authorized(user_id):
        await message.reply_text(
            f"Hello {user_name}! I am a video downloader bot, but you are not authorized to use this bot.\n\n"
            "Please contact the bot admin."
        )
        return

    # For authorized users
    await message.reply_text(
        f"Hello {user_name}! I am a video downloader bot. Send me any video link and I will download and send it to you.\n\n"
        "I use Pyrogram which allows me to send files up to 2GB!\n\n"
        "Type /help to learn about commands."
    )

async def help_command(client, message):
    """Handle /help command"""
    user_id = message.from_user.id

    # Basic commands for all users
    basic_commands = (
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
    )

    # Admin commands (only shown to admins)
    admin_commands = ""
    if is_admin_user(user_id):
        admin_commands = (
            "\n**Admin Commands:**\n"
            "/stats - Show bot statistics\n"
            "/cleanup - Remove old files\n"
        )

    # Usage information
    usage_info = (
        "\n**Usage:**\n"
        "Just send me any video URL and I will download and send it to you.\n"
        "I can download videos from YouTube, Twitter, Instagram and many other platforms.\n"
    )

    # Limitations and notes
    limitations = (
        "\n**Limitations and Notes:**\n"
        f"- Maximum file size: {MAX_FILE_SIZE/(1024*1024*1024):.1f}GB (Telegram limit)\n"
        f"- Maximum {MAX_CONCURRENT_DOWNLOADS} downloads at a time\n"
        f"- Maximum {MAX_DOWNLOADS_PER_USER} downloads per day\n"
        "- Download time depends on URL and file size\n"
        "- Files are automatically deleted after 24 hours\n"
    )

    # Combine all sections
    help_text = basic_commands + admin_commands + usage_info + limitations

    await message.reply_text(help_text)

# Dictionary to track active downloads per user
active_downloads = {}

# Dictionary to track daily download counts per user
user_download_counts = {}

async def handle_url(client, message):
    """Handle URL messages"""
    url = message.text.strip()

    # Check if the message is actually a URL (starts with http:// or https://)
    if not url.startswith('http://') and not url.startswith('https://'):
        # Not a URL, ignore silently
        return

    # Check if message.from_user is None (can happen in channels or some special cases)
    if message.from_user is None:
        # Use chat_id as user_id for tracking purposes
        user_id = message.chat.id
        # Only log this at debug level to avoid filling logs
        logger.debug(f"message.from_user is None, using chat_id {user_id} instead")
    else:
        user_id = message.from_user.id

    # Check if user is authorized to use the bot
    if AUTH_ENABLED and not is_user_authorized(user_id):
        await message.reply_text("⛔ You are not authorized to use this bot.")
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        return

    # Check concurrent downloads limit
    if user_id in active_downloads and active_downloads[user_id] >= MAX_CONCURRENT_DOWNLOADS:
        await message.reply_text(f"⚠️ You are already running {MAX_CONCURRENT_DOWNLOADS} downloads. Please wait for them to complete.")
        return

    # Check daily download limit
    today = time.strftime("%Y-%m-%d")
    if today in user_download_counts.get(user_id, {}):
        if user_download_counts[user_id][today] >= MAX_DOWNLOADS_PER_USER and not is_admin_user(user_id):
            await message.reply_text(f"⚠️ You have reached your daily limit of {MAX_DOWNLOADS_PER_USER} downloads. Please try again tomorrow.")
            return

    # Check if the message contains a valid URL
    is_valid, error_msg = is_valid_url(url)
    if not is_valid:
        await message.reply_text(f"⚠️ {error_msg}")
        return

    # Send initial processing message
    processing_msg = await message.reply_text("🔍 Checking URL...")

    try:
        # Track active downloads
        if user_id not in active_downloads:
            active_downloads[user_id] = 0
        active_downloads[user_id] += 1

        # Track daily downloads
        if user_id not in user_download_counts:
            user_download_counts[user_id] = {}
        if today not in user_download_counts[user_id]:
            user_download_counts[user_id][today] = 0
        user_download_counts[user_id][today] += 1

        # Check URL headers for content type and size only for direct video links
        # Skip for YouTube and social media URLs as they're handled differently
        if not is_youtube_url(url) and not is_social_media_url(url):
            valid_url, error_msg = await check_url_headers(url)
            if not valid_url:
                await processing_msg.edit_text(f"⚠️ {error_msg}")
                # Decrement counters since download won't proceed
                active_downloads[user_id] -= 1
                user_download_counts[user_id][today] -= 1
                return

        # Run cleanup of old downloads in the background
        asyncio.create_task(cleanup_old_downloads())

        # Generate a file path for the download
        file_path = generate_file_path(url, user_id)

        # Update processing message
        try:
            await processing_msg.edit_text("⏳ Starting download...")
        except Exception as e:
            if "FLOOD_WAIT" in str(e):
                logger.warning(f"FLOOD_WAIT encountered: {e}")
                try:
                    # Extract wait time from error message
                    wait_time = int(str(e).split("wait of ")[1].split(" seconds")[0]) + 15  # Increased buffer from 5 to 15
                    logger.info(f"Waiting for {wait_time} seconds before retrying")
                    await asyncio.sleep(wait_time)
                    # Try again after waiting, but with reduced frequency of updates
                    try:
                        await processing_msg.edit_text("⏳ Starting download...")
                    except Exception as retry_error:
                        logger.error(f"Error during retry after FLOOD_WAIT: {retry_error}")
                        # Continue with download even if message update fails
                except Exception as retry_error:
                    logger.error(f"Error during retry after FLOOD_WAIT: {retry_error}")
                    # Continue with download even if message update fails
            else:
                logger.error(f"Error updating message: {e}")
                # Continue with download even if message update fails

        # Download the video based on URL type
        if is_youtube_url(url):
            success, result = await download_youtube_video(url, file_path, processing_msg, user_id)
        elif is_social_media_url(url):
            success, result = await download_social_media_video(url, file_path, processing_msg, user_id)
        else:
            success, result = await download_direct_video(url, file_path, processing_msg, user_id)

        if success:
            # Video downloaded successfully, send it to the user
            file_path = result  # In case the downloader returned a different path
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)

            # Update message before sending file
            await processing_msg.edit_text(f"✅ Download complete!\n\n**File:** {file_name}\n**Size:** {file_size / (1024 * 1024):.2f} MB\n\n🔄 Now sending the file...")

            # Send the file based on extension
            try:
                # Get file extension
                _, file_ext = os.path.splitext(file_path)
                file_ext = file_ext.lower()

                # Common video formats to send as video
                video_extensions = ['.mp4', '.mov', '.avi', '.webm']

                # If it's a common video format, send as video
                if file_ext in video_extensions:
                    await message.reply_video(
                        video=file_path,
                        caption=f"🎬 **Video:** {file_name}\n📏 **Size:** {file_size / (1024 * 1024):.2f} MB",
                        progress=progress_for_pyrogram,
                        progress_args=("📤 Uploading video...", processing_msg, time.time())
                    )
                else:
                    # For other formats like .mkv, send as document
                    await message.reply_document(
                        document=file_path,
                        caption=f"📁 **File name:** {file_name}\n📏 **Size:** {file_size / (1024 * 1024):.2f} MB",
                        progress=progress_for_pyrogram,
                        progress_args=("📤 Uploading file...", processing_msg, time.time())
                    )

                # Delete the processing message
                await processing_msg.delete()

                # Delete the downloaded file and any related files to save space
                try:
                    # Delete the main file
                    os.remove(file_path)
                    logger.info(f"Deleted file: {file_path}")

                    # Check for any other files with similar base name (for audio/video parts)
                    base_name = os.path.splitext(os.path.basename(file_path))[0]
                    dir_path = os.path.dirname(file_path)

                    # Find and delete any related files
                    for filename in os.listdir(dir_path):
                        if filename.startswith(base_name) and os.path.join(dir_path, filename) != file_path:
                            try:
                                related_file = os.path.join(dir_path, filename)
                                os.remove(related_file)
                                logger.info(f"Deleted related file: {related_file}")
                            except Exception as related_e:
                                logger.error(f"Error deleting related file {filename}: {related_e}")
                except Exception as e:
                    logger.error(f"Error deleting file: {e}")

                # Decrement active downloads counter
                if user_id in active_downloads:
                    active_downloads[user_id] = max(0, active_downloads[user_id] - 1)

                # No need to do anything else, we're already returning

                # Return from function to prevent any further processing
                return
            except Exception as e:
                await processing_msg.edit_text(f"❌ Error sending file: {str(e)}")
                logger.error(f"Error sending file: {e}")
        else:
            # Download failed
            await processing_msg.edit_text(f"❌ Download failed: {result}")

            # Decrement active downloads counter
            if user_id in active_downloads:
                active_downloads[user_id] = max(0, active_downloads[user_id] - 1)
    except Exception as e:
        # Decrement active downloads counter
        if user_id in active_downloads:
            active_downloads[user_id] = max(0, active_downloads[user_id] - 1)

        # Log the error
        logger.error(f"Error processing URL: {e}")

        # Try to notify the user about the error
        error_message = f"❌ Error in processing: {str(e)}"

        try:
            await processing_msg.edit_text(error_message)
        except Exception as msg_error:
            if "FLOOD_WAIT" in str(msg_error):
                logger.warning(f"FLOOD_WAIT encountered while reporting error: {msg_error}")
                try:
                    # Extract wait time from error message
                    wait_time = int(str(msg_error).split("wait of ")[1].split(" seconds")[0]) + 5
                    await asyncio.sleep(wait_time)
                    # Try again after waiting
                    await processing_msg.edit_text(error_message)
                except Exception:
                    # If still fails, try to send a new message instead
                    try:
                        await message.reply_text(error_message)
                    except Exception as final_error:
                        logger.error(f"Failed to notify user about error: {final_error}")
            else:
                # If not a FLOOD_WAIT error, try to send a new message
                try:
                    await message.reply_text(error_message)
                except Exception as final_error:
                    logger.error(f"Failed to notify user about error: {final_error}")

        # Clean up any partial downloads and related files
        try:
            if 'file_path' in locals() and os.path.exists(file_path):
                # Delete the main file
                os.remove(file_path)
                logger.info(f"Cleaned up partial download: {file_path}")

                # Check for any other files with similar base name (for audio/video parts)
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                dir_path = os.path.dirname(file_path)

                # Find and delete any related files
                for filename in os.listdir(dir_path):
                    if filename.startswith(base_name) and os.path.join(dir_path, filename) != file_path:
                        try:
                            related_file = os.path.join(dir_path, filename)
                            os.remove(related_file)
                            logger.info(f"Cleaned up related partial file: {related_file}")
                        except Exception as related_e:
                            logger.error(f"Error cleaning up related file {filename}: {related_e}")
        except Exception as cleanup_error:
            logger.error(f"Error cleaning up partial download: {cleanup_error}")

        return  # Return after handling the exception to prevent further processing

async def progress_for_pyrogram(current, total, text, message, start):
    """Progress callback for Pyrogram"""
    try:
        if total == 0:
            return

        now = time.time()
        diff = now - start

        if diff < 1:
            return

        # Global variable to track last update time for this specific upload
        if not hasattr(progress_for_pyrogram, 'last_update_time'):
            progress_for_pyrogram.last_update_time = 0

        # Minimum time between updates (60 seconds + random jitter)
        min_update_interval = 60 + random.uniform(15, 30)

        # Calculate progress percentage
        speed = current / diff
        percentage = current * 100 / total

        # Only update at specific milestones to reduce frequency
        # For downloads: 0%, 25%, 50%, 75%, 100% or if it's been a very long time
        # For uploads: More frequent updates with smaller intervals
        should_update = False

        # Check if this is an upload (text starts with "📤")
        is_upload = text.startswith("📤")

        if is_upload:
            # For uploads: Update more frequently with smaller percentage intervals
            milestones = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
            # Check if we're at a milestone percentage with smaller tolerance for uploads
            is_milestone = any(abs(percentage - m) < 2.0 for m in milestones)
            # Use shorter minimum interval for uploads
            min_update_interval = 10 + random.uniform(5, 10)
        else:
            # For downloads: Use original milestone settings
            milestones = [0, 25, 50, 75, 100]
            # Check if we're at a milestone percentage
            is_milestone = any(abs(percentage - m) < 5.0 for m in milestones)

        # Update at milestones and if enough time has passed
        if (is_milestone or now - progress_for_pyrogram.last_update_time > 120) and now - progress_for_pyrogram.last_update_time >= min_update_interval:
            should_update = True

        if not should_update:
            return

        # Format the progress bar
        progress = "[{0}{1}]".format(
            ''.join("█" for _ in range(int(percentage / 5))),
            ''.join("░" for _ in range(20 - int(percentage / 5)))
        )

        current_mb = current / 1024 / 1024
        total_mb = total / 1024 / 1024

        if speed > 0:
            eta = (total - current) / speed
        else:
            eta = 0

        text = f"{text}\n\n{progress} {percentage:.1f}%\n⚡️ {current_mb:.2f} MB / {total_mb:.2f} MB\n🚀 {speed / 1024 / 1024:.2f} MB/s\n⏱ {format_time(eta)}"

        try:
            await message.edit_text(text)
            # Update the last update time only on successful edit
            progress_for_pyrogram.last_update_time = now
        except Exception as e:
            if "FLOOD_WAIT" in str(e):
                # If we hit a flood wait, increase the minimum interval for future updates
                logger.warning(f"FLOOD_WAIT encountered: {e}")
                try:
                    # Wait the required time plus some extra buffer
                    wait_time = int(str(e).split("wait of ")[1].split(" seconds")[0]) + 30
                    await asyncio.sleep(wait_time)
                    # Try again after waiting
                    try:
                        await message.edit_text(text)
                        progress_for_pyrogram.last_update_time = time.time() + 120  # Add extra buffer to last update time
                    except Exception as retry_error:
                        logger.error(f"Error during retry after FLOOD_WAIT: {retry_error}")
                except Exception as parse_error:
                    logger.error(f"Error parsing FLOOD_WAIT time: {parse_error}")
                    # Wait a conservative amount of time
                    await asyncio.sleep(180)
            else:
                logger.error(f"Error updating progress message: {e}")
    except Exception as e:
        logger.error(f"Error in progress callback: {e}")

# This function is now imported from core.utils