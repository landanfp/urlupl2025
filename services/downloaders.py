import os
import sys
import time
import asyncio
import aiohttp
import yt_dlp
import shutil
import re
import subprocess
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

def clean_youtube_url(url):
    """Clean YouTube URL by removing tracking parameters and normalizing format"""
    try:
        # Parse the URL
        parsed_url = urlparse(url)

        # Check if it's a YouTube URL
        if 'youtube.com' in parsed_url.netloc or 'youtu.be' in parsed_url.netloc:
            # For youtu.be short URLs
            if 'youtu.be' in parsed_url.netloc:
                video_id = parsed_url.path.strip('/')
                return f"https://www.youtube.com/watch?v={video_id}"

            # For regular youtube.com URLs
            query_params = parse_qs(parsed_url.query)

            # Keep only the video ID parameter
            if 'v' in query_params:
                video_id = query_params['v'][0]
                return f"https://www.youtube.com/watch?v={video_id}"

            # Handle YouTube shorts
            if '/shorts/' in parsed_url.path:
                video_id = parsed_url.path.split('/shorts/')[1].split('/')[0]
                return f"https://www.youtube.com/watch?v={video_id}"

        # If not a recognized YouTube format or couldn't parse, return original URL
        return url
    except Exception as e:
        logger.error(f"Error cleaning YouTube URL: {e}")
        return url  # Return original URL in case of any error

from core.config import (
    logger, DOWNLOAD_DIR, MAX_FILE_SIZE, DOWNLOAD_TIMEOUT,
    ALLOWED_FILE_EXTENSIONS
)
from core.utils import (
    progress_callback, format_time, humanbytes, sanitize_filename,
    is_youtube_url, is_instagram_url, is_facebook_url, is_twitter_url,
    is_tiktok_url, is_reddit_url, is_vimeo_url, is_dailymotion_url,
    is_social_media_url
)

def generate_file_path(url, user_id=None):
    """Generate a file path for the download based on URL"""
    try:
        # Extract filename from URL or create a timestamp-based name
        parsed_url = urlparse(url)
        path = parsed_url.path
        filename = os.path.basename(path)

        # Sanitize the filename to prevent path traversal attacks
        filename = sanitize_filename(filename)

        # Try to extract extension from URL query parameters if present
        if '.' not in filename:
            import re
            # Check for file extension in the URL path or query
            ext_match = re.search(r'\.(mp4|mkv|avi|mov|wmv|flv|webm|mp3|m4a)(?=[?&]|$)', url.lower())
            if ext_match:
                ext = ext_match.group(0)
                timestamp = int(time.time())
                filename = f"download_{timestamp}{ext}"
            else:
                # Default to a generic extension, will be updated later if possible
                timestamp = int(time.time())
                filename = f"download_{timestamp}.bin"

        # Create user-specific directory if user_id is provided
        target_dir = DOWNLOAD_DIR
        if user_id:
            target_dir = os.path.join(DOWNLOAD_DIR, f"user_{user_id}")

        # Ensure the download directory exists
        os.makedirs(target_dir, exist_ok=True)

        # Create full file path
        file_path = os.path.join(target_dir, filename)

        # If file already exists, add timestamp to make it unique
        if os.path.exists(file_path):
            name, ext = os.path.splitext(filename)
            timestamp = int(time.time())
            filename = f"{name}_{timestamp}{ext}"
            file_path = os.path.join(target_dir, filename)

        logger.info(f"Initial file path generated: {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"Error generating file path: {e}")
        # Fallback to a default filename
        timestamp = int(time.time())
        return os.path.join(DOWNLOAD_DIR, f"download_{timestamp}.bin")

async def cleanup_old_downloads(max_age_hours=24):
    """Clean up old downloads to free up disk space"""
    try:
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        # Get all files in the download directory
        for root, dirs, files in os.walk(DOWNLOAD_DIR):
            for file in files:
                file_path = os.path.join(root, file)

                # Skip .gitkeep and other special files
                if file.startswith('.'):
                    continue

                # Check file age
                file_age = current_time - os.path.getmtime(file_path)
                if file_age > max_age_seconds:
                    try:
                        # Get base name to find related files
                        base_name = os.path.splitext(os.path.basename(file_path))[0]
                        dir_path = os.path.dirname(file_path)

                        # Delete the main file
                        os.remove(file_path)
                        logger.info(f"Cleaned up old file: {file_path}")

                        # Find and delete any related files with the same base name
                        for related_file in os.listdir(dir_path):
                            if related_file.startswith(base_name) and os.path.join(dir_path, related_file) != file_path:
                                try:
                                    related_path = os.path.join(dir_path, related_file)
                                    os.remove(related_path)
                                    logger.info(f"Cleaned up related file: {related_path}")
                                except Exception as related_e:
                                    logger.error(f"Error removing related file {related_file}: {related_e}")
                    except Exception as e:
                        logger.error(f"Error removing old file {file_path}: {e}")

        # Clean up empty user directories
        for item in os.listdir(DOWNLOAD_DIR):
            if item.startswith('user_'):
                dir_path = os.path.join(DOWNLOAD_DIR, item)
                if os.path.isdir(dir_path) and not os.listdir(dir_path):
                    try:
                        os.rmdir(dir_path)
                        logger.info(f"Removed empty directory: {dir_path}")
                    except Exception as e:
                        logger.error(f"Error removing directory {dir_path}: {e}")

    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

async def check_disk_space():
    """Check available disk space"""
    try:
        # Get disk usage statistics
        total, used, free = shutil.disk_usage(DOWNLOAD_DIR)

        # Convert to GB for readability
        total_gb = total / (1024**3)
        used_gb = used / (1024**3)
        free_gb = free / (1024**3)

        # Log disk usage
        logger.info(f"Disk usage: {used_gb:.2f}GB used out of {total_gb:.2f}GB, {free_gb:.2f}GB free")

        # Check if free space is less than 1GB
        if free_gb < 1.0:
            logger.warning(f"Low disk space: only {free_gb:.2f}GB available!")
            # Trigger emergency cleanup
            await cleanup_old_downloads(max_age_hours=1)  # Clean files older than 1 hour

        return free_gb
    except Exception as e:
        logger.error(f"Error checking disk space: {e}")
        return None

async def download_youtube_video(url, file_path, message, user_id=None):
    """Download video from YouTube using yt-dlp"""
    try:
        await message.edit_text("⏳ Downloading YouTube video...")

        # Clean and normalize YouTube URL to avoid tracking parameters
        url = clean_youtube_url(url)
        logger.info(f"Cleaned YouTube URL: {url}")

        # Extract filename without extension for better naming
        filename_base = os.path.splitext(os.path.basename(file_path))[0]

        # Create user-specific directory if user_id is provided
        target_dir = DOWNLOAD_DIR
        if user_id:
            target_dir = os.path.join(DOWNLOAD_DIR, f"user_{user_id}")
            os.makedirs(target_dir, exist_ok=True)

        # Configure yt-dlp options
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': os.path.join(target_dir, f"{filename_base}.%(ext)s"),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'geo_bypass': True,
            'merge_output_format': 'mp4',  # Force output to be mp4
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }

        # Start time for progress calculation
        start_time = time.time()
        file_name = os.path.basename(file_path)

        # Custom progress hook to update Telegram message
        def progress_hook(d):
            if d['status'] == 'downloading':
                try:
                    total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded_bytes = d.get('downloaded_bytes', 0)

                    if total_bytes > 0:
                        # Use non-blocking progress update
                        asyncio.create_task(
                            progress_callback(downloaded_bytes, total_bytes, message, start_time, file_name)
                        )
                except Exception as e:
                    logger.error(f"Error in YouTube progress hook: {e}")

        # Add progress hook
        ydl_opts['progress_hooks'] = [progress_hook]

        # Download the video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_file = ydl.prepare_filename(info)

            # Verify the file exists
            if not os.path.exists(downloaded_file):
                # Try to find the file with a different extension
                base_path = os.path.splitext(downloaded_file)[0]
                potential_files = [f for f in os.listdir(os.path.dirname(downloaded_file))
                                if f.startswith(os.path.basename(base_path))]

                if potential_files:
                    downloaded_file = os.path.join(os.path.dirname(downloaded_file), potential_files[0])
                    logger.info(f"Found alternative file: {downloaded_file}")
                else:
                    raise FileNotFoundError(f"Downloaded file not found: {downloaded_file}")

            # Get video title for better logging
            video_title = info.get('title', 'Unknown Title')
            logger.info(f"Downloaded YouTube video: {video_title}")

        # Return the actual downloaded file path
        return True, downloaded_file

    except FileNotFoundError as e:
        logger.error(f"File not found error: {str(e)}")
        return False, f"YouTube video was downloaded but file not found."

    except Exception as e:
        error_message = str(e)
        logger.error(f"YouTube download error: {error_message}")

        # Handle specific YouTube errors
        if "Video unavailable" in error_message or "This video is no longer available" in error_message:
            return False, "Video is not available. It may be private or removed."
        elif "This video is private" in error_message:
            return False, "This video is private and cannot be downloaded."
        elif "This video is only available for registered users" in error_message:
            return False, "This video is only available for registered users."
        elif "Sign in to confirm you're not a bot" in error_message or "cookies" in error_message:
            return False, "Video could not be downloaded due to YouTube bot detection. Please try again later or try another video."
        elif "FLOOD_WAIT" in error_message:
            # Extract wait time if possible
            try:
                wait_time = int(error_message.split("wait of ")[1].split(" seconds")[0])
                return False, f"Telegram rate limit. Please try again after {wait_time} seconds."
            except:
                return False, "Telegram rate limit. Please try again after a few minutes."
        else:
            return False, f"Error downloading YouTube video: {error_message}"

async def download_direct_video(url, file_path, message, user_id=None):
    """Download video from direct URL using aiohttp"""
    try:
        await message.edit_text("⏳ Downloading video...")

        # Start time for progress calculation
        start_time = time.time()

        # Create download directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Check disk space before downloading
        free_space = await check_disk_space()
        if free_space is not None and free_space < 2.0:  # Require at least 2GB free
            return False, "Low disk space. Please try again later."

        # Set timeout for download
        timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT)

        # Download the file with progress updates
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return False, f"Download failed: HTTP status {response.status}"

                # Check Content-Disposition header for filename
                content_disposition = response.headers.get('Content-Disposition')
                content_type = response.headers.get('Content-Type', '')

                # Try to get the correct filename and extension from headers
                if content_disposition:
                    import re
                    # Look for filename in Content-Disposition header
                    filename_match = re.search(r'filename=[\'"]?([^\'";]+)', content_disposition)
                    if filename_match:
                        original_filename = filename_match.group(1)
                        # Update file_path with the correct extension
                        dir_name = os.path.dirname(file_path)
                        file_path = os.path.join(dir_name, original_filename)

                        # If file already exists, add timestamp to make it unique
                        if os.path.exists(file_path):
                            name, ext = os.path.splitext(original_filename)
                            timestamp = int(time.time())
                            new_filename = f"{name}_{timestamp}{ext}"
                            file_path = os.path.join(dir_name, new_filename)

                # If no filename from Content-Disposition, try to determine from Content-Type or URL
                elif '.' not in os.path.basename(file_path) or os.path.splitext(file_path)[1] == '.bin':
                    dir_name = os.path.dirname(file_path)
                    base_name = os.path.splitext(os.path.basename(file_path))[0]

                    # First try to extract extension from URL
                    import re
                    extension = '.bin'  # Default
                    ext_match = re.search(r'.(mp4|mkv|avi|mov|wmv|flv|webm|mp3|m4a)(?=[?&]|$)', url.lower())
                    if ext_match:
                        extension = f'.{ext_match.group(1)}'
                        logger.info(f"Extracted extension from URL: {extension}")
                    # If not found in URL, try to determine from Content-Type
                    elif content_type:
                        # Map content types to extensions
                        if 'video/mp4' in content_type:
                            extension = '.mp4'
                        elif 'video/x-matroska' in content_type:
                            extension = '.mkv'
                        elif 'video/webm' in content_type:
                            extension = '.webm'
                        elif 'audio/mpeg' in content_type:
                            extension = '.mp3'
                        logger.info(f"Determined extension from Content-Type: {extension}")

                    # Update file path with correct extension
                    file_path = os.path.join(dir_name, f"{base_name}{extension}")

                file_name = os.path.basename(file_path)
                logger.info(f"Downloading to: {file_path}")

                # Get content length for progress calculation
                total_size = int(response.headers.get('Content-Length', 0))

                # Open file for writing
                with open(file_path, 'wb') as f:
                    downloaded_size = 0
                    chunk_size = 1024 * 1024  # 1MB chunks

                    async for chunk in response.content.iter_chunked(chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)

                            # Update progress
                            await progress_callback(
                                downloaded_size, total_size, message, start_time, file_name
                            )

                            # Add a small delay to prevent CPU overuse
                            await asyncio.sleep(0.01)

        # Verify the download was successful
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return True, file_path
        else:
            # Clean up empty or corrupted file
            if os.path.exists(file_path):
                os.remove(file_path)
            return False, "Download failed: File is empty or corrupted"

    except asyncio.CancelledError:
        # Handle cancellation
        logger.info("Download was cancelled")
        # Clean up partial download
        if os.path.exists(file_path):
            os.remove(file_path)
        return False, "Download was cancelled"

    except aiohttp.ClientError as e:
        logger.error(f"Network error during download: {e}")
        # Clean up partial download
        if os.path.exists(file_path):
            os.remove(file_path)
        return False, f"Network error: {str(e)}"

    except Exception as e:
        error_message = str(e)
        logger.error(f"Direct download error: {error_message}")

        # Clean up partial download
        if os.path.exists(file_path):
            os.remove(file_path)

        # Handle specific errors
        if "FLOOD_WAIT" in error_message:
            # Extract wait time if possible
            try:
                wait_time = int(error_message.split("wait of ")[1].split(" seconds")[0])
                return False, f"Telegram rate limit. Please try again after {wait_time} seconds."
            except:
                return False, "Telegram rate limit. Please try again after a few minutes."
        else:
            return False, f"Error downloading video: {error_message}"

async def download_social_media_video(url, file_path, message, user_id=None):
    """Download video from social media platforms using yt-dlp"""
    # Determine platform for better user feedback
    platform = "सोशल मीडिया"
    if is_instagram_url(url):
        platform = "Instagram"
    elif is_facebook_url(url):
        platform = "Facebook"
    elif is_twitter_url(url):
        platform = "Twitter/X"
    elif is_tiktok_url(url):
        platform = "TikTok"
    elif is_reddit_url(url):
        platform = "Reddit"
    elif is_vimeo_url(url):
        platform = "Vimeo"
    elif is_dailymotion_url(url):
        platform = "Dailymotion"

    try:
        await message.edit_text(f"⏳ Downloading {platform} video...")

        # Extract filename without extension for better naming
        filename_base = os.path.splitext(os.path.basename(file_path))[0]

        # Create user-specific directory if user_id is provided
        target_dir = DOWNLOAD_DIR
        if user_id:
            target_dir = os.path.join(DOWNLOAD_DIR, f"user_{user_id}")
            os.makedirs(target_dir, exist_ok=True)

        # Configure yt-dlp options with platform-specific settings
        ydl_opts = {
            'format': 'best',
            'outtmpl': os.path.join(target_dir, f"{filename_base}.%(ext)s"),
            'noplaylist': True,
            'progress_hooks': [],
            'quiet': True,
            'cookiefile': None,  # No cookies by default
            'ignoreerrors': False,
            'no_warnings': True,
            'merge_output_format': 'mp4',  # Force output to be mp4
            'ffmpeg_location': 'ffmpeg',  # Ensure ffmpeg is in PATH
        }

        # Platform-specific options
        if is_instagram_url(url):
            # Instagram often requires higher quality selection and special handling
            # Use best format to get a complete video with audio
            ydl_opts['format'] = 'best'
            # Add additional options for Instagram
            ydl_opts.update({
                'extract_flat': False,
                'ignoreerrors': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 10,
                'nocheckcertificate': True,
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }]
            })
        elif is_tiktok_url(url):
            # TikTok often has watermarks, try to get without watermark
            ydl_opts['format'] = 'best'
            # Add additional options for TikTok
            ydl_opts.update({
                'extract_flat': False,
                'ignoreerrors': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 10,
                'nocheckcertificate': True,
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }]
            })
        elif is_twitter_url(url):
            # Twitter videos sometimes need special handling
            ydl_opts['format'] = 'best'
            # Add additional options for Twitter
            ydl_opts.update({
                'extract_flat': False,
                'ignoreerrors': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 10,
                'nocheckcertificate': True,
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }]
            })

        # Start time for progress calculation
        start_time = time.time()
        file_name = os.path.basename(file_path)

        # Custom progress hook to update Telegram message
        def progress_hook(d):
            if d['status'] == 'downloading':
                try:
                    total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded_bytes = d.get('downloaded_bytes', 0)

                    if total_bytes > 0:
                        # Use non-blocking progress update
                        asyncio.create_task(
                            progress_callback(downloaded_bytes, total_bytes, message, start_time, file_name)
                        )
                except Exception as e:
                    logger.error(f"Error in social media progress hook: {e}")

        # Add progress hook
        ydl_opts['progress_hooks'].append(progress_hook)

        # Download the video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                # First try to extract info without downloading
                logger.info(f"Extracting info from {platform} URL: {url}")
                info_dict = ydl.extract_info(url, download=False)

                # Check if we got a playlist instead of a single video
                if 'entries' in info_dict:
                    # Take the first video from the playlist
                    logger.info(f"Playlist detected, using first video")
                    info_dict = info_dict['entries'][0]

                # Get video title and other metadata
                video_title = info_dict.get('title', 'Unknown Title')
                video_id = info_dict.get('id', 'Unknown ID')
                logger.info(f"Found {platform} video: {video_title} (ID: {video_id})")

                # Now download the video
                logger.info(f"Downloading {platform} video: {video_title}")
                info = ydl.extract_info(url, download=True)

                # Handle playlist case again for the actual download
                if 'entries' in info:
                    info = info['entries'][0]

                # Get the downloaded file path
                downloaded_file = ydl.prepare_filename(info)

                # Verify the file exists
                if not os.path.exists(downloaded_file):
                    # Try to find the file with a different extension
                    base_path = os.path.splitext(downloaded_file)[0]
                    potential_files = [f for f in os.listdir(os.path.dirname(downloaded_file))
                                    if f.startswith(os.path.basename(base_path))]

                    if potential_files:
                        downloaded_file = os.path.join(os.path.dirname(downloaded_file), potential_files[0])
                        logger.info(f"Found alternative file: {downloaded_file}")
                    else:
                        raise FileNotFoundError(f"Downloaded file not found: {downloaded_file}")

                logger.info(f"Successfully downloaded {platform} video: {video_title} to {downloaded_file}")

                # Return the actual downloaded file path
                return True, downloaded_file

            except FileNotFoundError as e:
                logger.error(f"File not found error: {str(e)}")
                return False, f"{platform} video was downloaded but file not found."

    except yt_dlp.utils.DownloadError as e:
        error_message = str(e)
        logger.error(f"yt-dlp download error: {error_message}")

        # Handle specific yt-dlp errors
        if "Video unavailable" in error_message or "This video is no longer available" in error_message:
            return False, "Video is not available. It may be private or removed."
        elif "This video is private" in error_message:
            return False, "This video is private and cannot be downloaded."
        elif "Login required" in error_message or "requires authentication" in error_message:
            return False, "Login required to download this video."
        elif "Unsupported URL" in error_message or "is not a supported URL" in error_message:
            return False, f"Unsupported URL. This {platform} video cannot be downloaded."
        elif "Unable to extract" in error_message:
            return False, f"Unable to extract video from {platform}. The video may not be available or the platform may have changed its API."
        elif "HTTP Error 404" in error_message:
            return False, f"{platform} video not found (404 error)."
        else:
            return False, f"Error downloading {platform} video: {error_message}"

    except Exception as e:
        error_message = str(e)
        logger.error(f"Social media download error: {error_message}")

        # Handle specific errors
        if "FLOOD_WAIT" in error_message:
            # Extract wait time if possible
            try:
                wait_time = int(error_message.split("wait of ")[1].split(" seconds")[0])
                return False, f"Telegram rate limit. Please try again after {wait_time} seconds."
            except:
                return False, "Telegram rate limit. Please try again after a few minutes."
        else:
            return False, f"Error downloading {platform} video: {error_message}"
