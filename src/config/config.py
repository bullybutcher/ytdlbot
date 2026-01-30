#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - config.py
# 8/28/21 15:01
#

__author__ = "Benny <benny.think@gmail.com>"

import os


def get_env(name: str, default=None):
    val = os.getenv(name, default)
    if val is None:
        return None
    if isinstance(val, str):
        if val.lower() == "true":
            return True
        if val.lower() == "false":
            return False
        if val.isdigit() and name != "AUTHORIZED_USER":
            return int(val)
    return val


# general settings
WORKERS: int = get_env("WORKERS", 100)
APP_ID: int = get_env("APP_ID")
APP_HASH = get_env("APP_HASH")
BOT_TOKEN = get_env("BOT_TOKEN")
OWNER = [int(i) for i in str(get_env("OWNER")).split(",")]
# db settings
AUTHORIZED_USER: str = get_env("AUTHORIZED_USER", "")
DB_DSN = get_env("DB_DSN")
REDIS_HOST = get_env("REDIS_HOST")

ENABLE_FFMPEG = get_env("ENABLE_FFMPEG")
AUDIO_FORMAT = get_env("AUDIO_FORMAT", "m4a")
M3U8_SUPPORT = get_env("M3U8_SUPPORT")
ENABLE_ARIA2 = get_env("ENABLE_ARIA2")

RCLONE_PATH = get_env("RCLONE")

# payment settings
ENABLE_VIP = get_env("ENABLE_VIP")
PROVIDER_TOKEN = get_env("PROVIDER_TOKEN")
FREE_DOWNLOAD = get_env("FREE_DOWNLOAD", 3)
TOKEN_PRICE = get_env("TOKEN_PRICE", 10)  # 1 USD=10 downloads

# For advance users
# Please do not change, if you don't know what these are.
TG_NORMAL_MAX_SIZE = 2000 * 1024 * 1024
CAPTION_URL_LENGTH_LIMIT = 150

# This will set the value for the tmpfile path(engine path). If not, will return None and use system's default path.
# Please ensure that the directory exists and you have necessary permissions to write to it.
TMPFILE_PATH = get_env("TMPFILE_PATH")

# Proxy settings
PROXY_FILE = get_env("PROXY_FILE", "proxy.json")
MAX_PROXY_WORKERS = get_env("MAX_PROXY_WORKERS", 2)

# Web server settings
ENABLE_WEB_SERVER = get_env("ENABLE_WEB_SERVER", False)
WEBHOOK_URL = get_env("WEBHOOK_URL")
WEBHOOK_SECRET = get_env("WEBHOOK_SECRET")
WEBHOOK_PATH = get_env("WEBHOOK_PATH", "/webhook")
HOST = get_env("HOST", "0.0.0.0")
PORT = get_env("PORT", 8000)
MINI_APP_URL = get_env("MINI_APP_URL")

# Resource management
MAX_DISK_USAGE_MB = get_env("MAX_DISK_USAGE_MB", 1000)
MAX_MEMORY_USAGE_MB = get_env("MAX_MEMORY_USAGE_MB", 2000)
MAX_CONCURRENT_DOWNLOADS = get_env("MAX_CONCURRENT_DOWNLOADS", 10)
MAX_CONCURRENT_PER_IP = get_env("MAX_CONCURRENT_PER_IP", 3)

# Public download API settings
PUBLIC_DOWNLOAD_TTL_SECONDS = get_env("PUBLIC_DOWNLOAD_TTL_SECONDS", 1800)  # 30 minutes
PUBLIC_MAX_FILE_SIZE_MB = get_env("PUBLIC_MAX_FILE_SIZE_MB", 200)
PUBLIC_CLEANUP_INTERVAL_SECONDS = get_env("PUBLIC_CLEANUP_INTERVAL_SECONDS", 60)
PUBLIC_JOB_RETENTION_SECONDS = get_env("PUBLIC_JOB_RETENTION_SECONDS", 3600)

# Security settings
PRODUCTION = get_env("PRODUCTION", False)
MAX_SEGMENT_DURATION = get_env("MAX_SEGMENT_DURATION", 600)  # 10 minutes
MAX_REQUEST_SIZE_MB = get_env("MAX_REQUEST_SIZE_MB", 1)
RATE_LIMIT_CREATE = get_env("RATE_LIMIT_CREATE", "5/minute")
RATE_LIMIT_STATUS = get_env("RATE_LIMIT_STATUS", "30/minute")
RATE_LIMIT_DOWNLOAD = get_env("RATE_LIMIT_DOWNLOAD", "10/minute")
ALLOWED_ORIGINS = get_env("ALLOWED_ORIGINS", "")
