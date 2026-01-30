# Docker Deployment Guide (Easy Way!)

This is the **simplest way** to deploy ytdlbot on Ubuntu. Docker handles all dependencies automatically!

## Prerequisites

- Ubuntu 20.04 or later
- Docker and Docker Compose installed
- At least 2GB RAM (4GB+ recommended)
- At least 20GB free disk space

## Step 1: Install Docker and Docker Compose

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to docker group (so you don't need sudo)
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install -y docker-compose-plugin

# Log out and back in (or run: newgrp docker) for group changes to take effect
```

Verify installation:
```bash
docker --version
docker compose version
```

## Step 2: Clone/Upload Project

```bash
# Clone repository (or upload your code)
cd /opt
sudo git clone <your-repo-url> ytdlbot
cd ytdlbot

# OR if uploading manually, make sure these directories exist:
# - src/
# - mini_app/ (optional, for Telegram mini app)
# - public_web/ (optional, for public web UI)
```

## Step 3: Configure Environment Variables

```bash
# Create .env file
nano .env
```

**Minimum required configuration:**

```bash
# Telegram Bot Configuration
WORKERS=100
APP_ID=your_telegram_app_id
APP_HASH=your_telegram_app_hash
BOT_TOKEN=your_bot_token_from_botfather
OWNER=your_telegram_user_id
AUTHORIZED_USER=user_id1,user_id2

# Database Configuration (using MySQL from docker-compose)
DB_DSN=mysql+pymysql://root:root@mysql/ytdlbot

# Redis Configuration (using Redis from docker-compose)
REDIS_HOST=redis

# Enable features
ENABLE_FFMPEG=True
AUDIO_FORMAT=m4a
ENABLE_ARIA2=True

# Web Server Configuration (NEW - for mini app and public API)
ENABLE_WEB_SERVER=True
HOST=0.0.0.0
PORT=8000

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
ALLOWED_ORIGINS=https://yourdomain.com

# Security Settings (NEW)
PRODUCTION=True
MAX_SEGMENT_DURATION=600
RATE_LIMIT_CREATE=5/minute
RATE_LIMIT_STATUS=30/minute
RATE_LIMIT_DOWNLOAD=10/minute
```

**Getting Telegram Credentials:**
1. **BOT_TOKEN**: Get from [@BotFather](https://t.me/botfather)
2. **APP_ID and APP_HASH**: Get from [https://my.telegram.org/apps](https://my.telegram.org/apps)
3. **OWNER**: Your Telegram user ID (use [@userinfobot](https://t.me/userinfobot))

## Step 4: Initialize Database

```bash
# Start MySQL container first
docker compose up -d mysql

# Wait for MySQL to be ready (about 30 seconds)
sleep 30

# Create database
docker compose exec mysql mysql -uroot -proot -e "CREATE DATABASE IF NOT EXISTS ytdlbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

## Step 5: Build and Start Everything

```bash
# Build the Docker image (includes all dependencies: Python, ffmpeg, aria2, deno)
docker compose build

# Start all services (bot, web server, MySQL, Redis)
docker compose up -d

# View logs
docker compose logs -f
```

That's it! 🎉

## Step 6: Verify Everything Works

```bash
# Check all containers are running
docker compose ps

# Check bot logs
docker compose logs ytdl -f

# Test web server health
curl http://localhost:8000/health
# Should return: {"status":"healthy"}

# Test bot on Telegram
# Send /start to your bot
```

## Step 7: Setup Reverse Proxy (Optional - for domain access)

If you want to access the web UI via a domain name:

```bash
# Install Nginx
sudo apt install -y nginx

# Create Nginx config
sudo nano /etc/nginx/sites-available/ytdlbot
```

Add:
```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
    }
}
```

Enable and restart:
```bash
sudo ln -s /etc/nginx/sites-available/ytdlbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## Step 8: Setup SSL (Optional)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

## Common Commands

```bash
# View logs
docker compose logs -f ytdl          # Bot logs
docker compose logs -f               # All services

# Restart services
docker compose restart ytdl          # Restart bot
docker compose restart               # Restart all

# Stop services
docker compose stop                  # Stop all
docker compose down                  # Stop and remove containers

# Update and rebuild
git pull                             # Get latest code
docker compose build                 # Rebuild image
docker compose up -d                 # Restart with new image

# Access container shell
docker compose exec ytdl sh          # Get shell in bot container

# Initialize proxies (run inside container)
docker compose exec ytdl python -c "from proxy.proxy_manager import update_proxies; update_proxies(max_workers=2, verbose=True)"
```

## Updating Proxy List (Recommended: Daily)

Create a cron job:

```bash
crontab -e
```

Add:
```
0 2 * * * cd /opt/ytdlbot && docker compose exec -T ytdl python -c "from proxy.proxy_manager import update_proxies; update_proxies(max_workers=2, verbose=False)"
```

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose logs ytdl

# Check if .env file exists and has correct values
cat .env

# Verify database is accessible
docker compose exec mysql mysql -uroot -proot -e "SHOW DATABASES;"
```

### Web server not accessible

```bash
# Check if web server is enabled in .env
grep ENABLE_WEB_SERVER .env

# Check if port 8000 is exposed
docker compose ps
# Should show: 0.0.0.0:8000->8000/tcp

# Test from inside container
docker compose exec ytdl curl http://localhost:8000/health
```

### Bot not responding

```bash
# Check bot logs
docker compose logs ytdl -f

# Verify BOT_TOKEN is correct
docker compose exec ytdl env | grep BOT_TOKEN

# Check database connection
docker compose exec ytdl python -c "from config import DB_DSN; print(DB_DSN)"
```

### Out of disk space

```bash
# Clean up Docker
docker system prune -a

# Check disk usage
docker system df
df -h
```

## What Docker Handles Automatically

✅ Python 3.12 installation  
✅ All Python dependencies (from requirements.txt)  
✅ ffmpeg installation  
✅ aria2 installation  
✅ deno installation (JavaScript runtime for YouTube)  
✅ PATH configuration  
✅ Database (MySQL)  
✅ Redis  
✅ All system dependencies  
✅ Isolated environment  

## File Structure

```
/opt/ytdlbot/
├── .env                    # Configuration file
├── docker-compose.yml      # Docker services definition
├── Dockerfile             # Bot container definition
├── src/                   # Bot source code
├── mini_app/              # Telegram mini app (optional)
├── public_web/            # Public web UI (optional)
├── proxy.json             # Proxy list (auto-generated)
└── youtube-cookies.txt    # YouTube cookies (optional)
```

## Production Tips

1. **Use a pre-built image** (faster startup):
   ```yaml
   # In docker-compose.yml, comment out build: and uncomment:
   image: bennythink/ytdlbot
   ```

2. **Add resource limits** in docker-compose.yml:
   ```yaml
   ytdl:
     deploy:
       resources:
         limits:
           memory: 2G
           cpus: '1.0'
   ```

3. **Use Docker secrets** for sensitive data (instead of .env)

4. **Setup log rotation** (already configured in docker-compose.yml)

5. **Regular backups**:
   ```bash
   # Backup database
   docker compose exec mysql mysqldump -uroot -proot ytdlbot > backup.sql
   ```

## That's It!

With Docker, you don't need to:
- ❌ Install Python manually
- ❌ Install ffmpeg, aria2, deno manually
- ❌ Configure PATH variables
- ❌ Setup virtual environments
- ❌ Worry about dependency conflicts

Everything is handled automatically! 🐳

