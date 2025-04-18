import os
import logging
import re
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Load environment variables
load_dotenv()

# Configure logging
if os.getenv("ENV") == "development":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()
        ]
    )

logger = logging.getLogger("core.config")

# Configuration variables
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")

# Create download directory if it doesn't exist
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Progress update configuration
last_progress_update_time = 0
default_update_interval = 3  # 3 seconds between updates (20 messages per minute)
PROGRESS_MILESTONES = [0, 25, 50, 75, 100]  # Update progress at these percentages

# Rate limiting configuration
MIN_TIME_BETWEEN_UPDATES = 3  # 3 seconds minimum time between ANY updates (20 messages per minute)

# Security configuration
MAX_FILE_SIZE = float(os.getenv("MAX_FILE_SIZE", 1.8 * 1024 * 1024 * 1024))  # 1.8GB max file size (Telegram limit is 2GB)
ALLOWED_FILE_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mp3', '.m4a']
ALLOWED_MIME_TYPES = [
    'video/', 'audio/', 'application/octet-stream',
    'application/mp4', 'application/x-matroska'
]

# Blocklist for potentially malicious domains
BLOCKED_DOMAINS = [
    'malware.com', 'phishing.com', 'virus.com',
    # Add more blocked domains as needed
]

# User authentication
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"  # Set to True to enable user authentication

# Parse allowed users from environment variable
ALLOWED_USERS_STR = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(user_id.strip()) for user_id in ALLOWED_USERS_STR.split(",") if user_id.strip()] if ALLOWED_USERS_STR else []

# Parse admin users from environment variable
ADMIN_USERS_STR = os.getenv("ADMIN_USERS", "")
ADMIN_USERS = [int(user_id.strip()) for user_id in ADMIN_USERS_STR.split(",") if user_id.strip()] if ADMIN_USERS_STR else []

# Download limits
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", 2))  # Maximum number of concurrent downloads
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", 3600))  # 1 hour timeout for downloads
MAX_DOWNLOADS_PER_USER = int(os.getenv("MAX_DOWNLOADS_PER_USER", 10))  # Maximum downloads per user per day

# Cleanup settings
CLEANUP_INTERVAL_HOURS = int(os.getenv("CLEANUP_INTERVAL_HOURS", 24))  # Cleanup files older than this many hours

