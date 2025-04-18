# URL Uploader Pro

This is a secure and advanced Telegram bot that can download videos from URLs and send them to you. Just send the bot any video URL and it will download and send it back to you. It can also download videos from YouTube, Twitter, Instagram and many other platforms.

## Features

### Main Features
- Download from video URLs (.mp4, .mkv, etc)
- Download from YouTube video URLs
- Download videos from social media platforms:
  - Instagram (posts, reels, IGTV, stories)
  - Facebook (videos, reels, watch pages)
  - Twitter/X (video tweets, spaces)
  - TikTok (videos)
  - Reddit (video posts)
  - Vimeo, Dailymotion and other platforms

- Can send files up to 2GB
- Download and upload with progress tracking

### Security Features
- URL filtering and validation
- File type and size checking
- User authentication and authorization
- Secure file handling
- Automatic file cleanup

### Administrative Features
- Bot statistics (/stats)
- Manual cleanup (/cleanup)
- User limits and restrictions

## Setup Instructions

### Requirements

- Python 3.8 or higher
- pip (Python package manager)
- Telegram bot token (get from @BotFather)
- Telegram API ID and API Hash (get from https://my.telegram.org/apps)

### Installation

1. Clone the repository
   ```
   git clone https://github.com/Denisery/url-uploader-pro.git
   ```

2. Navigate to the project directory
   ```
   cd url-uploader-pro
   ```

3. Install required packages
   ```
   pip install -r requirements.txt
   ```

4. Copy the `.env.example` file to `.env` and add your Telegram bot token
   ```
   cp .env.example .env
   ```

5. Add your Telegram bot token, API ID and API Hash to the `.env` file
   ```
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   API_ID=your_api_id_here
   API_HASH=your_api_hash_here

   # Optional settings
   DOWNLOAD_DIR=./downloads
   AUTH_ENABLED=false
   # ALLOWED_USERS=123456789,987654321
   # ADMIN_USERS=123456789
   ```

### Running the Bot

#### Run directly with Python

```
python bot.py
```

#### Run with Docker

1. Build and run the Docker image
   ```
   docker-compose up -d --build
   ```

2. View logs
   ```
   docker-compose logs -f
   ```

3. Stop the bot
   ```
   docker-compose down
   ```

## Usage

1. Start your bot on Telegram (`/start`)
2. Send any video URL to the bot:
   - YouTube video URL
   - Instagram post or reel URL
   - Facebook video URL
   - Twitter/X video URL
   - TikTok video URL
   - Reddit video URL
   - Direct video file URL
3. The bot will download the video and send it to you

## Notes

- Downloading and sending large video files may take time
- Bot can send files up to 2GB
- Files are automatically deleted after 24 hours
- There is a limit of maximum 2 downloads at a time and maximum 10 downloads per day

## Security Features

### URL Validation
The bot checks all URLs and only downloads from safe URLs. It performs the following checks:
- URL structure (HTTP/HTTPS only)
- Blocked domains
- Allowed file types
- File size limits

### User Authentication
The bot has a user authentication system that can be activated by setting `AUTH_ENABLED=true` in the `.env` file. After this, only authorized users can use the bot.

### File Management
- All downloaded files are handled securely
- Filenames are sanitized
- Old files are automatically removed
- Disk space is monitored


## API Endpoints

### Status Endpoint

To get the bot status and system information, make a GET request to the status endpoint:

```
GET http://localhost:8080
```

Example response:

```json
{
  "status": "ok",
  "timestamp": 1682152345,
  "uptime": 3600,
  "bot": {
    "active_downloads": 1,
    "users": 5,
    "files": 10
  },
  "system": {
    "cpu_percent": 25.5,
    "memory_percent": 40.2,
    "disk": {
      "total_gb": 50.0,
      "used_gb": 25.0,
      "free_gb": 25.0,
      "percent": 50.0
    }
  }
}
```