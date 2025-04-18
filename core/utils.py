import os
import time
import asyncio
import random
import re
import aiohttp
from urllib.parse import urlparse
from core.config import (
    logger, last_progress_update_time, default_update_interval,
    PROGRESS_MILESTONES, MIN_TIME_BETWEEN_UPDATES, ALLOWED_FILE_EXTENSIONS,
    ALLOWED_MIME_TYPES, BLOCKED_DOMAINS, MAX_FILE_SIZE, AUTH_ENABLED,
    ALLOWED_USERS, ADMIN_USERS
)

def is_valid_url(url):
    """Check if the URL is valid and safe"""
    try:
        # Basic URL structure validation
        result = urlparse(url)
        if not all([result.scheme, result.netloc]):
            return False, "Invalid URL structure"

        # Check for blocked domains
        domain = result.netloc.lower()
        for blocked in BLOCKED_DOMAINS:
            if blocked in domain:
                return False, f"Blocked domain: {domain}"

        # Check for allowed schemes (only http and https)
        if result.scheme not in ['http', 'https']:
            return False, f"Invalid URL scheme: {result.scheme}"

        # Check file extension if present in path
        path = result.path.lower()
        if path and '.' in path:
            ext = os.path.splitext(path)[1]
            if ext and ext not in ALLOWED_FILE_EXTENSIONS:
                return False, f"Invalid file type: {ext}"

        return True, ""
    except ValueError as e:
        return False, f"URL parsing error: {str(e)}"

async def check_url_headers(url):
    """Check URL headers for content type and size"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, allow_redirects=True, timeout=30) as response:
                # Check if response is OK
                if response.status != 200:
                    return False, f"HTTP error: {response.status}"

                # Check content type
                content_type = response.headers.get('Content-Type', '')
                valid_mime = False
                for allowed_mime in ALLOWED_MIME_TYPES:
                    if allowed_mime in content_type.lower():
                        valid_mime = True
                        break

                if not valid_mime and content_type:
                    return False, f"Invalid content type: {content_type}"

                # Check content length
                content_length = response.headers.get('Content-Length')
                if content_length:
                    size = int(content_length)
                    if size > MAX_FILE_SIZE:
                        size_mb = size / (1024 * 1024)
                        max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
                        return False, f"File too large: {size_mb:.2f}MB (maximum: {max_size_mb:.2f}MB)"

                return True, ""
    except aiohttp.ClientError as e:
        return False, f"URL access error: {str(e)}"
    except Exception as e:
        return False, f"URL check error: {str(e)}"

def is_youtube_url(url):
    """Check if the URL is a YouTube URL"""
    return 'youtube.com' in url or 'youtu.be' in url

def is_instagram_url(url):
    """Check if the URL is an Instagram URL"""
    return ('instagram.com' in url or 'instagr.am' in url or
            'instagram.com/reel' in url or 'instagram.com/p/' in url or
            'instagram.com/tv/' in url or 'instagram.com/stories/' in url)

def is_facebook_url(url):
    """Check if the URL is a Facebook URL"""
    return ('facebook.com' in url or 'fb.com' in url or 'fb.watch' in url or
            'facebook.com/watch' in url or 'facebook.com/video' in url or
            'm.facebook.com' in url)

def is_twitter_url(url):
    """Check if the URL is a Twitter/X URL"""
    return ('twitter.com' in url or 'x.com' in url or 't.co' in url or
            'twitter.com/i/status' in url or 'x.com/i/status' in url or
            'twitter.com/i/spaces' in url or 'x.com/i/spaces' in url)

def is_tiktok_url(url):
    """Check if the URL is a TikTok URL"""
    return 'tiktok.com' in url or 'vm.tiktok.com' in url

def is_reddit_url(url):
    """Check if the URL is a Reddit URL"""
    return 'reddit.com' in url or 'redd.it' in url

def is_vimeo_url(url):
    """Check if the URL is a Vimeo URL"""
    return 'vimeo.com' in url

def is_dailymotion_url(url):
    """Check if the URL is a Dailymotion URL"""
    return 'dailymotion.com' in url or 'dai.ly' in url



def is_social_media_url(url):
    """Check if the URL is from a supported social media platform"""
    return (is_instagram_url(url) or is_facebook_url(url) or
            is_twitter_url(url) or is_tiktok_url(url) or
            is_reddit_url(url) or is_vimeo_url(url) or
            is_dailymotion_url(url))

def is_user_authorized(user_id):
    """Check if a user is authorized to use the bot"""
    if not AUTH_ENABLED:
        return True

    if not ALLOWED_USERS:  # Empty list means all users allowed
        return True

    return user_id in ALLOWED_USERS or user_id in ADMIN_USERS

def is_admin_user(user_id):
    """Check if a user is an admin"""
    return user_id in ADMIN_USERS

def sanitize_filename(filename):
    """Sanitize filename to prevent path traversal attacks"""
    # Remove path components
    filename = os.path.basename(filename)

    # Replace potentially dangerous characters
    filename = re.sub(r'[^\w\.-]', '_', filename)

    # Ensure filename isn't empty
    if not filename:
        timestamp = int(time.time())
        filename = f"download_{timestamp}.bin"

    return filename

async def progress_callback(current, total, message, start_time, file_name):
    """Callback to update download progress"""
    global last_progress_update_time, default_update_interval
    if total == 0:
        return

    now = time.time()
    # Use the global update interval to avoid Telegram flood limits (20 messages per minute)
    # Add a small random jitter to avoid synchronized updates
    min_update_interval = default_update_interval + random.uniform(0.5, 1.0)  # Small jitter

    # Enforce minimum time between ANY updates (global rate limiting)
    if now - last_progress_update_time < MIN_TIME_BETWEEN_UPDATES:
        return

    # Calculate progress percentage
    percentage = current * 100 / total

    # Only update if enough time has passed since last update AND we're at a milestone
    # or if this is the first update (0%) or final update (100%)
    should_update = False

    # Check if we're at a milestone percentage (0%, 25%, 50%, 75%, 100%)
    # Update only at specific milestones to stay within Telegram's rate limit (20 messages per minute)
    current_milestone = None
    for milestone in PROGRESS_MILESTONES:
        if abs(percentage - milestone) < 2.0:  # Reduced tolerance to 2%
            current_milestone = milestone
            break

    # Update only at milestones and if enough time has passed (3 seconds between updates)
    if current_milestone is not None and now - last_progress_update_time >= min_update_interval:
        should_update = True
    # Always update on first progress (0%) and completion (100%) if enough time has passed
    elif (percentage < 0.1 or percentage > 99.9) and now - last_progress_update_time >= min_update_interval:
        should_update = True

    if should_update:
        # Check if we've had a recent FLOOD_WAIT error and add extra delay if needed
        if default_update_interval > 3:  # If we've increased the interval due to FLOOD_WAIT
            # Add a small safety delay
            await asyncio.sleep(random.uniform(1.0, 2.0))  # Moderate delay to stay within rate limits

        speed = current / (now - start_time)
        elapsed_time = now - start_time

        if speed > 0:
            eta = (total - current) / speed
        else:
            eta = 0

        # Format progress message
        progress_message = f"📥 **Downloading:**\n"
        progress_message += f"**File:** {file_name}\n"
        progress_message += f"**Progress:** {percentage:.1f}%\n"
        progress_message += f"**Speed:** {humanbytes(speed)}/s\n"
        progress_message += f"**Downloaded:** {humanbytes(current)} / {humanbytes(total)}\n"
        progress_message += f"**Time remaining:** {format_time(eta)}\n"

        try:
            # Use a try-except with retry logic for edit_text
            max_retries = 1  # Reduced retries to avoid multiple FLOOD_WAIT errors
            retry_count = 0
            success = False

            while retry_count < max_retries and not success:
                try:
                    await message.edit_text(progress_message)
                    # Update the last update time only on successful edit
                    last_progress_update_time = now
                    success = True
                except Exception as retry_error:
                    if "FLOOD_WAIT" in str(retry_error):
                        retry_count += 1
                        # Extract wait time from error message
                        try:
                            wait_time_str = str(retry_error).split("wait of ")[1].split(" seconds")[0]
                            wait_seconds = int(float(wait_time_str)) + random.randint(15, 30)  # Increased buffer
                            logger.warning(f"FLOOD_WAIT encountered: {retry_error}")
                            logger.info(f"Waiting for {wait_seconds} seconds before retrying")

                            # Implement moderate backoff to stay within Telegram's rate limit
                            default_update_interval = min(10, default_update_interval * 2)  # Cap at 10 seconds, moderate multiplier

                            # Wait before retry
                            await asyncio.sleep(wait_seconds)
                        except Exception:
                            # If we can't parse the wait time, use a moderate default
                            logger.warning(f"Could not parse FLOOD_WAIT time, using default wait")
                            await asyncio.sleep(random.uniform(3.0, 5.0))  # Moderate default wait
                            default_update_interval = min(10, default_update_interval * 2)  # Increase interval moderately
                    else:
                        # Don't raise the error, just log it and continue
                        logger.error(f"Failed to update progress message: {retry_error}")
                        break

            # Reset start time for speed calculation if successful
            if success:
                return now

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error updating progress: {error_msg}")

            # Handle Telegram FLOOD_WAIT errors
            if "FLOOD_WAIT" in error_msg:
                try:
                    # Extract wait time from error message
                    wait_time_str = error_msg.split("wait of ")[1].split(" seconds")[0]
                    wait_seconds = int(float(wait_time_str)) + random.randint(15, 30)  # Increased buffer
                    logger.warning(f"FLOOD_WAIT encountered: {error_msg}")
                    logger.info(f"Waiting for {wait_seconds} seconds before retrying")

                    # Implement moderate backoff to stay within Telegram's rate limit
                    # Double the current interval and add the wait time with a moderate buffer
                    default_update_interval = min(10, default_update_interval * 2)  # Cap at 10 seconds, moderate multiplier
                    default_update_interval = max(default_update_interval, wait_seconds + 3)  # At least wait_seconds + small buffer

                    logger.info(f"Increased minimum update interval to {default_update_interval} seconds")

                    # Wait for the required time plus a small safety margin
                    await asyncio.sleep(wait_seconds + 3)  # Small safety margin
                except Exception as parse_error:
                    logger.error(f"Error parsing FLOOD_WAIT time: {parse_error}")
                    # If we can't parse the wait time, use a moderate default
                    default_update_interval = min(10, default_update_interval * 2 + 3)  # Moderate multiplier and buffer
                    await asyncio.sleep(10)  # Wait 10 seconds as a fallback

    return start_time

def humanbytes(size):
    """Convert bytes to human readable format"""
    if not size:
        return ""
    power = 2**10
    n = 0
    units = {0: "", 1: "KB", 2: "MB", 3: "GB", 4: "TB"}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {units[n]}"

def format_time(seconds):
    """Format seconds to readable time"""
    if seconds < 60:
        return f"{seconds:.0f} seconds"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.0f} minutes"
    else:
        hours = seconds / 3600
        return f"{hours:.1f} hours"