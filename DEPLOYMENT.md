# Ubuntu Server Deployment Guide

This guide will help you deploy ytdlbot on a fresh Ubuntu server.

## Prerequisites

- Ubuntu 20.04 or later (22.04 recommended)
- Root or sudo access
- At least 2GB RAM (4GB+ recommended)
- At least 20GB free disk space
- Domain name (optional, for webhook/web UI)

## Step 1: Initial Server Setup

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install essential tools
sudo apt install -y git curl wget build-essential
```

## Step 2: Install Python and Dependencies

```bash
# Install Python 3.12 and pip
sudo apt install -y python3.12 python3.12-venv python3-pip python3.12-dev

# Install system dependencies
sudo apt install -y ffmpeg aria2 deno redis-server mysql-server

# Install PDM (Python Dependency Manager)
pip3 install --user pdm
export PATH="$HOME/.local/bin:$PATH"
```

## Step 3: Install Deno (JavaScript Runtime for YouTube)

```bash
# Install deno using the official installer
curl -fsSL https://deno.land/install.sh | sh

# Add to PATH (add to ~/.bashrc for persistence)
export DENO_INSTALL="$HOME/.deno"
export PATH="$DENO_INSTALL/bin:$PATH"

# Verify installation
deno --version
```

## Step 4: Setup Database

### Option A: MySQL (Recommended for production)

```bash
# Secure MySQL installation
sudo mysql_secure_installation

# Create database and user
sudo mysql -u root -p << EOF
CREATE DATABASE ytdlbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'ytdlbot'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON ytdlbot.* TO 'ytdlbot'@'localhost';
FLUSH PRIVILEGES;
EOF
```

### Option B: SQLite (Simpler, for testing)

No setup needed - SQLite will be created automatically.

## Step 5: Setup Redis

```bash
# Redis should already be installed, just start it
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Verify Redis is running
redis-cli ping
# Should return: PONG
```

## Step 6: Clone and Setup Project

```bash
# Clone the repository (or upload your code)
cd /opt
sudo git clone <your-repo-url> ytdlbot
# OR if you have the code locally, upload it via SCP/FTP

cd ytdlbot

# Install Python dependencies using PDM
pdm install

# OR use pip (alternative method)
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Step 7: Configure Environment Variables

```bash
# Create .env file
cp .env.example .env  # If .env.example exists
# OR create manually:
nano .env
```

### Required Configuration (.env file):

```bash
# Telegram Bot Configuration
WORKERS=100
APP_ID=your_telegram_app_id
APP_HASH=your_telegram_app_hash
BOT_TOKEN=your_bot_token_from_botfather
OWNER=your_telegram_user_id
AUTHORIZED_USER=user_id1,user_id2

# Database Configuration
# For MySQL:
DB_DSN=mysql+pymysql://ytdlbot:your_secure_password@localhost/ytdlbot
# For SQLite:
# DB_DSN=sqlite:///db.sqlite

# Redis Configuration
REDIS_HOST=localhost

# Optional: Enable features
ENABLE_FFMPEG=True
AUDIO_FORMAT=m4a
ENABLE_ARIA2=True

# Web Server Configuration (NEW - for mini app and public API)
ENABLE_WEB_SERVER=True
HOST=0.0.0.0
PORT=8000
WEBHOOK_URL=https://yourdomain.com  # Optional, for webhook mode
WEBHOOK_SECRET=your_webhook_secret  # Optional, for webhook security
WEBHOOK_PATH=/webhook

# Resource Management (NEW)
MAX_DISK_USAGE_MB=1000
MAX_MEMORY_USAGE_MB=2000
MAX_CONCURRENT_DOWNLOADS=10
MAX_CONCURRENT_PER_IP=3

# Proxy Settings (NEW - for YouTube downloads)
PROXY_FILE=proxy.json
MAX_PROXY_WORKERS=2

# Public API Settings (NEW)
PUBLIC_DOWNLOAD_TTL_SECONDS=1800
PUBLIC_MAX_FILE_SIZE_MB=200
PUBLIC_CLEANUP_INTERVAL_SECONDS=60
PUBLIC_JOB_RETENTION_SECONDS=3600

# Security Settings (NEW)
PRODUCTION=True
MAX_SEGMENT_DURATION=600
MAX_REQUEST_SIZE_MB=1
RATE_LIMIT_CREATE=5/minute
RATE_LIMIT_STATUS=30/minute
RATE_LIMIT_DOWNLOAD=10/minute
ALLOWED_ORIGINS=https://yourdomain.com,https://*.yourdomain.com

# Optional: YouTube cookies and tokens
# POTOKEN=your_po_token  # For YouTube access
# BROWSERS=firefox,chrome  # For cookie extraction
```

### Getting Telegram Credentials:

1. **BOT_TOKEN**: Get from [@BotFather](https://t.me/botfather) on Telegram
2. **APP_ID and APP_HASH**: Get from [https://my.telegram.org/apps](https://my.telegram.org/apps)
3. **OWNER**: Your Telegram user ID (use [@userinfobot](https://t.me/userinfobot))

## Step 8: Initialize Proxy System (Optional but Recommended)

```bash
# Activate virtual environment
source venv/bin/activate  # or: source .venv/bin/activate (if using PDM)

# Run proxy update script (this will fetch and test proxies)
cd src
python -c "from proxy.proxy_manager import update_proxies; update_proxies(max_workers=2, verbose=True)"
```

This will create `proxy.json` in the project root with the best available proxies.

## Step 9: Setup Systemd Services

### Option A: Single Service (Bot + Web Server together)

If you want to run both the bot and web server together, you need to modify `src/main.py` to start the web server in a background thread. Add this before `app.run()`:

```python
# In src/main.py, before app.run()
if ENABLE_WEB_SERVER:
    from web_server import start_web_server
    import threading
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
```

Then create a single systemd service:

```bash
sudo nano /etc/systemd/system/ytdlbot.service
```

Add the following content:

```ini
[Unit]
Description=ytdlbot Telegram Bot and Web Server
After=network.target mysql.service redis-server.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/ytdlbot
Environment="PATH=/opt/ytdlbot/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/ytdlbot/venv/bin/python /opt/ytdlbot/src/main.py
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ytdlbot

# Resource limits
LimitNOFILE=65536
MemoryMax=2G

[Install]
WantedBy=multi-user.target
```

### Option B: Separate Services (Recommended for Production)

Create separate services for bot and web server:

**1. Bot Service:**

```bash
sudo nano /etc/systemd/system/ytdlbot.service
```

```ini
[Unit]
Description=ytdlbot Telegram Bot
After=network.target mysql.service redis-server.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/ytdlbot
Environment="PATH=/opt/ytdlbot/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/ytdlbot/venv/bin/python /opt/ytdlbot/src/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ytdlbot
LimitNOFILE=65536
MemoryMax=2G

[Install]
WantedBy=multi-user.target
```

**2. Web Server Service:**

```bash
sudo nano /etc/systemd/system/ytdlbot-web.service
```

```ini
[Unit]
Description=ytdlbot Web Server
After=network.target ytdlbot.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/ytdlbot
Environment="PATH=/opt/ytdlbot/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/ytdlbot/venv/bin/python -c "from src.web_server import start_web_server; start_web_server()"
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ytdlbot-web
LimitNOFILE=65536
MemoryMax=1G

[Install]
WantedBy=multi-user.target
```

**Important**: Adjust paths and user according to your setup!

Enable and start the services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ytdlbot
sudo systemctl start ytdlbot

# If using separate web server service:
sudo systemctl enable ytdlbot-web
sudo systemctl start ytdlbot-web

# Check status
sudo systemctl status ytdlbot
sudo systemctl status ytdlbot-web  # If using separate service

# View logs
sudo journalctl -u ytdlbot -f
sudo journalctl -u ytdlbot-web -f  # If using separate service
```

## Step 10: Setup Web Server (Nginx Reverse Proxy)

If you enabled `ENABLE_WEB_SERVER=True`, you'll need to set up a reverse proxy:

```bash
# Install Nginx
sudo apt install -y nginx

# Create Nginx configuration
sudo nano /etc/nginx/sites-available/ytdlbot
```

Add the following configuration:

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    # For Let's Encrypt certificate
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        
        # Increase timeouts for large file downloads
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/ytdlbot /etc/nginx/sites-enabled/
sudo nginx -t  # Test configuration
sudo systemctl restart nginx
```

## Step 11: Setup SSL Certificate (Optional but Recommended)

```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Obtain SSL certificate
sudo certbot --nginx -d yourdomain.com

# Auto-renewal is set up automatically
```

## Step 12: Setup Firewall

```bash
# Install UFW if not already installed
sudo apt install -y ufw

# Allow SSH, HTTP, HTTPS
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Enable firewall
sudo ufw enable
```

## Step 13: Verify Installation

1. **Check bot is running:**
   ```bash
   sudo systemctl status ytdlbot
   ```

2. **Test bot on Telegram:**
   - Send `/start` to your bot
   - Send a YouTube URL to test download

3. **Test web server (if enabled):**
   ```bash
   curl http://localhost:8000/health
   # Should return: {"status":"healthy"}
   ```

4. **Test public web UI:**
   - Visit `http://yourdomain.com/web` in browser
   - Should show the YouTube downloader interface

5. **Test mini app:**
   - The mini app is accessible at `/mini_app` route
   - Configure `MINI_APP_URL` in Telegram Bot settings

## Step 14: Monitoring and Maintenance

### View Logs

```bash
# Bot logs
sudo journalctl -u ytdlbot -f

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Update Proxy List (Recommended: Daily)

Create a cron job to update proxies:

```bash
crontab -e
```

Add:
```
0 2 * * * cd /opt/ytdlbot && /opt/ytdlbot/venv/bin/python -c "from src.proxy.proxy_manager import update_proxies; update_proxies(max_workers=2, verbose=False)"
```

### Disk Space Monitoring

Monitor disk usage regularly:

```bash
df -h
du -sh /opt/ytdlbot
```

## Troubleshooting

### Bot not starting

1. Check logs: `sudo journalctl -u ytdlbot -n 50`
2. Verify .env file has all required variables
3. Check database connection: `mysql -u ytdlbot -p ytdlbot`
4. Check Redis: `redis-cli ping`

### Web server not accessible

1. Check if web server is enabled: `ENABLE_WEB_SERVER=True` in .env
2. Check if port 8000 is listening: `sudo netstat -tlnp | grep 8000`
3. Check Nginx configuration: `sudo nginx -t`
4. Check firewall: `sudo ufw status`

### Downloads failing

1. Check proxy.json exists and has valid proxies
2. Update proxies: Run proxy update script
3. Check disk space: `df -h`
4. Check yt-dlp version: `yt-dlp --version`
5. Verify deno is installed: `deno --version`

### High memory usage

1. Reduce `MAX_CONCURRENT_DOWNLOADS` in .env
2. Reduce `MAX_MEMORY_USAGE_MB` in .env
3. Monitor with: `htop` or `free -h`

## Quick Start Script

For a faster setup, you can use this script (save as `setup.sh`):

```bash
#!/bin/bash
set -e

echo "Installing dependencies..."
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip python3.12-dev \
    ffmpeg aria2 redis-server mysql-server nginx git curl

echo "Installing Deno..."
curl -fsSL https://deno.land/install.sh | sh
export DENO_INSTALL="$HOME/.deno"
export PATH="$DENO_INSTALL/bin:$PATH"

echo "Setting up Python environment..."
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo "Setup complete! Now:"
echo "1. Configure .env file"
echo "2. Setup database"
echo "3. Start the service"
```

Make it executable: `chmod +x setup.sh`

## Additional Notes

- **Security**: Always use strong passwords and keep your server updated
- **Backups**: Regularly backup your database and .env file
- **Updates**: Keep yt-dlp updated: `pip install --upgrade yt-dlp`
- **Resource Limits**: Adjust limits in .env based on your server capacity
- **Domain**: For production, use a proper domain name with SSL

## Support

For issues and questions:
- Check the main README.md
- Review logs for error messages
- Ensure all dependencies are installed correctly

