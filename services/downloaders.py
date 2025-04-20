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
        files_cleaned = 0

        # Get all files in the download directory
        for root, dirs, files in os.walk(DOWNLOAD_DIR):
            for file in files:
                # Skip .gitkeep and other special files
                if file.startswith('.'):
                    continue

                file_path = os.path.join(root, file)

                try:
                    # Check if file exists and get its age
                    if not os.path.exists(file_path):
                        continue

                    file_age = current_time - os.path.getmtime(file_path)
                    if file_age <= max_age_seconds:
                        continue  # Skip files that aren't old enough

                    # Get base name to find related files
                    base_name = os.path.splitext(os.path.basename(file_path))[0]
                    dir_path = os.path.dirname(file_path)

                    # Delete the main file
                    os.remove(file_path)
                    files_cleaned += 1
                    logger.info(f"Cleaned up old file: {file_path}")

                    # Find and delete any related files with the same base name
                    for related_file in os.listdir(dir_path):
                        if related_file.startswith(base_name) and os.path.join(dir_path, related_file) != file_path:
                            try:
                                related_path = os.path.join(dir_path, related_file)
                                if os.path.exists(related_path):
                                    os.remove(related_path)
                                    logger.info(f"Cleaned up related file: {related_path}")
                            except Exception as related_e:
                                logger.error(f"Error removing related file {related_file}: {related_e}")

                except Exception as file_error:
                    logger.error(f"Error processing file {file_path}: {file_error}")

        # Clean up empty user directories
        for item in os.listdir(DOWNLOAD_DIR):
            if item.startswith('user_'):
                dir_path = os.path.join(DOWNLOAD_DIR, item)
                if os.path.isdir(dir_path):
                    try:
                        # Check if directory is empty
                        if not os.listdir(dir_path):
                            os.rmdir(dir_path)
                            logger.info(f"Removed empty directory: {dir_path}")
                    except Exception as dir_error:
                        logger.error(f"Error checking/removing directory {dir_path}: {dir_error}")

        logger.info(f"Cleanup completed: {files_cleaned} files removed")
        return files_cleaned
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return 0

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

async def get_youtube_formats(url):
    """Get available formats for a YouTube video"""
    try:
        # Clean and normalize YouTube URL
        url = clean_youtube_url(url)
        logger.info(f"Getting formats for YouTube URL: {url}")

        # Configure yt-dlp options for format extraction
        ydl_opts = {
            'quiet': False,  # Enable output for debugging
            'no_warnings': False,  # Show warnings for debugging
            'nocheckcertificate': True,
            'geo_bypass': True,
            'skip_download': True,  # Don't download, just get info
        }

        # Extract available formats
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                if not info:
                    logger.error(f"No info returned for URL: {url}")
                    return None
                logger.info(f"Successfully extracted info for video: {info.get('title', 'Unknown')}")
            except Exception as extract_error:
                logger.error(f"Error extracting info: {extract_error}")
                return None

            # Get video title and other metadata
            video_title = info.get('title', 'Unknown Title')
            video_id = info.get('id', 'Unknown ID')
            duration = info.get('duration', 0)  # Duration in seconds
            thumbnail = info.get('thumbnail', None)

            # Filter and organize formats
            formats = []
            audio_formats = []
            seen_resolutions = set()

            # First, find the best audio format for MP3 conversion
            best_audio = None
            for f in info.get('formats', []):
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    # This is an audio-only format
                    f_abr = f.get('abr', 0) or 0  # Handle None values
                    best_abr = best_audio.get('abr', 0) or 0 if best_audio else 0
                    if best_audio is None or f_abr > best_abr:
                        best_audio = f

            # Add MP3 option if we found an audio format
            if best_audio:
                audio_formats.append({
                    'format_id': f"audio-mp3",
                    'ext': 'mp3',
                    'format_note': f"MP3 Audio",
                    'filesize': best_audio.get('filesize', 0) or 0,  # Handle None values
                    'abr': best_audio.get('abr', 0) or 0,  # Handle None values
                })

            # Add video formats (only mp4 with audio)
            for f in info.get('formats', []):
                # Skip formats without video
                if f.get('vcodec') == 'none':
                    continue

                # Get resolution
                height = f.get('height', 0) or 0  # Handle None values
                width = f.get('width', 0) or 0    # Handle None values
                resolution = f"{width}x{height}" if width and height else "Unknown"

                # Skip duplicates
                if resolution in seen_resolutions:
                    continue

                # Only include formats with both video and audio, or formats that can be merged
                has_audio = f.get('acodec') != 'none'
                is_mp4 = f.get('ext') == 'mp4'

                if (is_mp4 and has_audio) or (height in [144, 240, 360, 480, 720, 1080, 1440, 2160]):
                    format_id = f.get('format_id', '')
                    format_note = f.get('format_note', '')
                    filesize = f.get('filesize', 0) or 0  # Handle None values

                    # Create a readable format description
                    if height:
                        quality = f"{height}p"
                        if height >= 720:
                            quality += " HD"
                        if height >= 1080:
                            quality += " FHD"
                        if height >= 2160:
                            quality += " 4K"
                    else:
                        quality = format_note or "Unknown"

                    formats.append({
                        'format_id': format_id,
                        'ext': f.get('ext', 'mp4'),
                        'height': height,
                        'width': width,
                        'resolution': resolution,
                        'quality': quality,
                        'format_note': format_note,
                        'filesize': filesize,
                        'has_audio': has_audio,
                    })
                    seen_resolutions.add(resolution)

            # Sort formats by resolution (height)
            formats.sort(key=lambda x: x.get('height', 0), reverse=True)

            # Add a "best" option at the top
            formats.insert(0, {
                'format_id': 'best',
                'ext': 'mp4',
                'quality': 'Best Quality',
                'format_note': 'Highest quality available',
                'filesize': 0,
            })

            return {
                'title': video_title,
                'id': video_id,
                'duration': duration,
                'thumbnail': thumbnail,
                'formats': formats,
                'audio_formats': audio_formats,
            }
    except Exception as e:
        logger.error(f"Error getting YouTube formats: {e}")
        return None

async def download_youtube_video(url, file_path, message, user_id=None, format_id=None, is_audio=False):
    """Download video from YouTube using yt-dlp"""
    try:
        await message.edit_text("⏳ Analyzing YouTube video...")

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
        # Check if ffmpeg is installed
        has_ffmpeg = shutil.which('ffmpeg') is not None

        # Use video title in the output filename
        output_template = os.path.join(target_dir, "%(title)s.%(ext)s")

        # If no format_id is provided, show format selection
        if format_id is None and not is_audio:
            # Get available formats
            formats_info = await get_youtube_formats(url)
            if not formats_info:
                logger.warning(f"Failed to get formats, falling back to best quality for {url}")
                # Fall back to best quality
                format_id = 'best'
                await message.edit_text("⏳ Failed to get formats. Downloading best quality...")
            else:
                # Create format selection message
                format_msg = f"🎬 **{formats_info['title']}**\n\n**Select Quality:**\n"

                # Add video formats
                for i, fmt in enumerate(formats_info['formats'][:8]):  # Limit to 8 options
                    filesize = fmt.get('filesize', 0)
                    filesize_str = f" ({humanbytes(filesize)})" if filesize else ""
                    format_msg += f"/{i+1} - {fmt['quality']}{filesize_str}\n"

                # Add audio option
                if formats_info['audio_formats']:
                    audio_fmt = formats_info['audio_formats'][0]
                    filesize = audio_fmt.get('filesize', 0)
                    filesize_str = f" ({humanbytes(filesize)})" if filesize else ""
                    format_msg += f"\n/audio - MP3 Audio{filesize_str}\n"

                # Send format selection message
                await message.edit_text(format_msg)
                return True, "format_selection"

        # Configure download options based on format selection
        if is_audio:
            await message.edit_text("⏳ Downloading YouTube audio...")
            # Download as MP3
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'geo_bypass': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'restrictfilenames': True,  # Restrict filenames to ASCII characters
            }
        elif format_id == 'best':
            await message.edit_text("⏳ Downloading best quality YouTube video...")
            # Use best quality
            if has_ffmpeg:
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl': output_template,
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
                    'restrictfilenames': True,  # Restrict filenames to ASCII characters
                }
            else:
                # If ffmpeg is not available, use a single format that doesn't require merging
                logger.warning("ffmpeg not found. Using fallback format selection without merging.")
                ydl_opts = {
                    'format': 'best[ext=mp4]/best',  # Prefer mp4 but fall back to best available single format
                    'outtmpl': output_template,
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'nocheckcertificate': True,
                    'geo_bypass': True,
                    'restrictfilenames': True,  # Restrict filenames to ASCII characters
                }
        else:
            await message.edit_text("⏳ Downloading selected quality YouTube video...")
            # Use selected format
            if has_ffmpeg:
                ydl_opts = {
                    'format': f"{format_id}+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    'outtmpl': output_template,
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
                    'restrictfilenames': True,  # Restrict filenames to ASCII characters
                }
            else:
                # If ffmpeg is not available, use a single format that doesn't require merging
                logger.warning("ffmpeg not found. Using fallback format selection without merging.")
                ydl_opts = {
                    'format': f"{format_id}/best[ext=mp4]/best",
                    'outtmpl': output_template,
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'nocheckcertificate': True,
                    'geo_bypass': True,
                    'restrictfilenames': True,  # Restrict filenames to ASCII characters
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

            # For MP3 conversion, the extension will be changed
            if is_audio:
                # Change extension from original to mp3
                base_path = os.path.splitext(downloaded_file)[0]
                downloaded_file = f"{base_path}.mp3"

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
            if is_audio:
                logger.info(f"Downloaded YouTube audio: {video_title}")
            else:
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

        # Check if ffmpeg is installed
        has_ffmpeg = shutil.which('ffmpeg') is not None

        # Use video title in the output filename
        output_template = os.path.join(target_dir, "%(title)s.%(ext)s")

        # Configure yt-dlp options with platform-specific settings
        ydl_opts = {
            'format': 'best[ext=mp4]/best' if not has_ffmpeg else 'best',
            'outtmpl': output_template,
            'noplaylist': True,
            'progress_hooks': [],
            'quiet': True,
            'cookiefile': None,  # No cookies by default
            'ignoreerrors': False,
            'no_warnings': True,
            'restrictfilenames': True,  # Restrict filenames to ASCII characters
        }

        # Add ffmpeg-specific options only if ffmpeg is available
        if has_ffmpeg:
            ydl_opts.update({
                'merge_output_format': 'mp4',  # Force output to be mp4
                'ffmpeg_location': 'ffmpeg',  # Ensure ffmpeg is in PATH
            })

        # Platform-specific options
        if is_instagram_url(url):
            # Instagram often requires higher quality selection and special handling
            # Use best format to get a complete video with audio
            ydl_opts['format'] = 'best'
            # Add additional options for Instagram
            instagram_opts = {
                'extract_flat': False,
                'ignoreerrors': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 10,
                'nocheckcertificate': True,
            }

            # Add ffmpeg post-processors only if available
            if has_ffmpeg:
                instagram_opts['postprocessors'] = [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }]

            ydl_opts.update(instagram_opts)
        elif is_tiktok_url(url):
            # TikTok often has watermarks, try to get without watermark
            ydl_opts['format'] = 'best'
            # Add additional options for TikTok
            tiktok_opts = {
                'extract_flat': False,
                'ignoreerrors': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 10,
                'nocheckcertificate': True,
            }

            # Add ffmpeg post-processors only if available
            if has_ffmpeg:
                tiktok_opts['postprocessors'] = [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }]

            ydl_opts.update(tiktok_opts)
        elif is_twitter_url(url):
            # Twitter videos sometimes need special handling
            ydl_opts['format'] = 'best'
            # Add additional options for Twitter
            twitter_opts = {
                'extract_flat': False,
                'ignoreerrors': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 10,
                'nocheckcertificate': True,
            }

            # Add ffmpeg post-processors only if available
            if has_ffmpeg:
                twitter_opts['postprocessors'] = [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }]

            ydl_opts.update(twitter_opts)

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
