"""FastAPI web server for ytdlbot with webhook support and public API."""

import asyncio
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Literal, Tuple
from urllib.parse import urlparse

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import (
    ENABLE_WEB_SERVER,
    WEBHOOK_URL,
    WEBHOOK_SECRET,
    WEBHOOK_PATH,
    HOST,
    PORT,
    ALLOWED_ORIGINS,
    PRODUCTION,
    MAX_SEGMENT_DURATION,
    MAX_REQUEST_SIZE_MB,
    RATE_LIMIT_CREATE,
    RATE_LIMIT_STATUS,
    RATE_LIMIT_DOWNLOAD,
    PUBLIC_DOWNLOAD_TTL_SECONDS,
    BOT_TOKEN,
    MINI_APP_URL,
)

logger = logging.getLogger(__name__)

# Global variables for download queue and cleanup tasks
download_queue = None
public_cleanup_task = None
public_download_jobs: Dict[str, 'PublicDownloadJob'] = {}
public_jobs_lock = asyncio.Lock()

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    global download_queue, public_cleanup_task
    
    # Startup
    if ENABLE_WEB_SERVER:
        # Initialize download queue if needed
        from utils.download_queue import DownloadQueue
        from config import MAX_CONCURRENT_DOWNLOADS
        from utils.cleanup import public_download_cleanup_loop
        
        download_queue = DownloadQueue(
            max_workers=MAX_CONCURRENT_DOWNLOADS,
            max_queue_size=MAX_CONCURRENT_DOWNLOADS * 2
        )
        download_queue.start()
        logger.info(f"Download queue initialized with {MAX_CONCURRENT_DOWNLOADS} workers")
        
        # Initialize cleanup task with job registry
        from utils.cleanup import public_download_jobs as cleanup_jobs, public_jobs_lock as cleanup_lock
        global public_download_jobs, public_jobs_lock
        public_download_jobs = cleanup_jobs
        public_jobs_lock = cleanup_lock
        
        # Start background cleanup task for public download jobs
        public_cleanup_task = asyncio.create_task(public_download_cleanup_loop())
        
        # Note: Pyrogram webhook support is limited - bot can still run in polling mode
        if WEBHOOK_URL:
            logger.info(f"Webhook URL configured: {WEBHOOK_URL} (Pyrogram webhook integration pending)")
    
    yield
    
    # Shutdown
    if ENABLE_WEB_SERVER:
        # Stop public download cleanup task
        if public_cleanup_task:
            public_cleanup_task.cancel()
            try:
                await public_cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Shutdown download queue
        if download_queue:
            download_queue.stop()
            logger.info("Download queue shut down")
        
        # Remove webhook if configured
        if WEBHOOK_URL:
            try:
                from main import app as pyrogram_app
                await pyrogram_app.bot.delete_webhook()
            except Exception as e:
                logger.error(f"Failed to delete webhook: {e}")


# Create FastAPI app with lifespan
app = FastAPI(lifespan=lifespan if ENABLE_WEB_SERVER else None, title="ytdlbot API")

# Initialize rate limiter state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS
if ALLOWED_ORIGINS:
    origins = [origin.strip() for origin in ALLOWED_ORIGINS.split(",") if origin.strip()]
else:
    origins = ["*"]
    if PRODUCTION:
        logger.warning("⚠️  WARNING: CORS is set to allow all origins (*) in production. Set ALLOWED_ORIGINS environment variable.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

# Request size limit middleware
@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    """Limit request body size to prevent DoS attacks."""
    if request.method == "POST":
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > MAX_REQUEST_SIZE_MB:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Request body too large. Maximum size is {MAX_REQUEST_SIZE_MB}MB"
                    )
            except ValueError:
                pass  # Invalid content-length header, let it through
    
    response = await call_next(request)
    return response


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "bot": "running"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    """Handle incoming webhook requests from Telegram."""
    if not ENABLE_WEB_SERVER:
        return JSONResponse({"error": "Web server not enabled"}, status_code=503)
    
    # Validate secret token if configured
    if WEBHOOK_SECRET:
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret_header != WEBHOOK_SECRET:
            return JSONResponse({"error": "Forbidden"}, status_code=403)
    
    try:
        # Import here to avoid circular imports
        from main import app as pyrogram_app
        
        data = await request.json()
        # Pyrogram handles updates differently - we need to process the raw update
        # For now, return success - webhook integration with Pyrogram needs more work
        # The bot can still run in polling mode
        logger.info("Received webhook update (Pyrogram webhook integration pending)")
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return JSONResponse({"error": "Internal server error"}, status_code=500)


# Helper functions for validation and security
def validate_youtube_url(url: str) -> Tuple[bool, Optional[str]]:
    """Validate that URL is a YouTube URL.
    
    Returns:
        (is_valid, error_message)
    """
    if not url:
        return False, "URL is required"
    
    if len(url) > 2048:
        return False, "URL exceeds maximum length of 2048 characters"
    
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"
    
    allowed_domains = ['youtube.com', 'www.youtube.com', 'youtu.be', 'm.youtube.com']
    
    # Check domain
    if parsed.netloc not in allowed_domains:
        return False, f"Only YouTube URLs are allowed. Domain '{parsed.netloc}' is not permitted."
    
    # Validate video ID format for standard YouTube URLs
    if parsed.netloc in ['youtube.com', 'www.youtube.com', 'm.youtube.com']:
        if 'v=' in parsed.query:
            video_id = parsed.query.split('v=')[1].split('&')[0]
            if not re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
                return False, "Invalid YouTube video ID format"
        elif '/watch/' in parsed.path:
            # Handle /watch/video_id format
            video_id = parsed.path.split('/watch/')[-1].split('/')[0]
            if not re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
                return False, "Invalid YouTube video ID format"
    
    # Validate youtu.be short URLs
    if parsed.netloc == 'youtu.be':
        video_id = parsed.path.lstrip('/').split('?')[0].split('/')[0]
        if not re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
            return False, "Invalid YouTube video ID format"
    
    return True, None


def check_origin(req: Request) -> None:
    """Check that request originates from allowed origin.
    
    Supports wildcard subdomains (e.g., *.klipr.app matches any.klipr.app).
    
    Raises HTTPException if origin is not allowed.
    """
    if not ALLOWED_ORIGINS:
        return  # No restrictions if not configured
    
    # If ALLOWED_ORIGINS is "*", allow all origins (development mode)
    if origins == ["*"]:
        return
    
    # Get origin from Origin header (CORS requests) or Referer header (regular requests)
    origin = req.headers.get('Origin')
    if not origin:
        # Fallback to Referer header
        referer = req.headers.get('Referer')
        if referer:
            try:
                parsed = urlparse(referer)
                origin = f"{parsed.scheme}://{parsed.netloc}"
            except Exception:
                pass
    
    # If still no origin, check if it's a same-origin request
    if not origin:
        host = req.headers.get('Host')
        if host:
            for allowed in origins:
                allowed_domain = allowed.replace('https://', '').replace('http://', '').rstrip('/')
                if _matches_origin(host, allowed_domain):
                    return
                if host == allowed_domain:
                    return
    
    # Check if origin is in allowed list
    if origin:
        normalized_origin = origin.rstrip('/')
        origin_domain = normalized_origin.replace('https://', '').replace('http://', '')
        
        for allowed in origins:
            normalized_allowed = allowed.rstrip('/')
            
            # Exact match
            if normalized_origin == normalized_allowed:
                return
            
            # Match without protocol
            allowed_domain = normalized_allowed.replace('https://', '').replace('http://', '')
            if origin_domain == allowed_domain:
                return
            
            # Wildcard subdomain matching
            if _matches_origin(origin_domain, allowed_domain):
                return
    
    # Origin not allowed
    raise HTTPException(
        status_code=403,
        detail="Access denied. Requests must originate from an allowed domain."
    )


def _matches_origin(origin_domain: str, allowed_pattern: str) -> bool:
    """Check if origin domain matches allowed pattern, supporting wildcard subdomains."""
    allowed_domain = allowed_pattern.replace('https://', '').replace('http://', '')
    
    # Exact match
    if origin_domain == allowed_domain:
        return True
    
    # Wildcard subdomain matching
    if allowed_domain.startswith('*.'):
        base_domain = allowed_domain[2:]
        if origin_domain.endswith('.' + base_domain) or origin_domain == base_domain:
            return True
    
    return False


def sanitize_error_message(error: Exception, production_mode: bool) -> str:
    """Sanitize error messages for client responses."""
    if not production_mode:
        return str(error)
    
    error_str = str(error).lower()
    
    if "url" in error_str or "youtube" in error_str:
        return "Invalid YouTube URL provided"
    elif "timestamp" in error_str or "time" in error_str:
        return "Invalid timestamp values"
    elif "size" in error_str or "limit" in error_str:
        return "Request exceeds size limits"
    elif "not found" in error_str or "404" in error_str:
        return "Resource not found"
    elif "403" in error_str or "forbidden" in error_str:
        return "Access denied"
    elif "rate limit" in error_str:
        return "Too many requests. Please try again later."
    else:
        return "An error occurred processing your request"


# Data models for public API
@dataclass
class PublicDownloadJob:
    """Represents a public (non-Telegram) download job."""
    job_id: str
    url: str
    mode: str  # "video" or "audio"
    start: Optional[float] = None
    end: Optional[float] = None
    status: str = "queued"  # queued | running | ready | failed | expired
    error: Optional[str] = None
    file_path: Optional[str] = None
    temp_dir: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[float] = None
    created_at: float = 0.0
    expires_at: float = 0.0
    consumed: bool = False
    task_id: str = ""
    estimated_size_mb: float = 0.0


class CreateDownloadRequest(BaseModel):
    """Request body for creating a public download job."""
    url: str
    mode: Literal["video", "audio"]
    start: Optional[float] = None
    end: Optional[float] = None


class CreateDownloadResponse(BaseModel):
    """Response body for creating a public download job."""
    job_id: str


class DownloadStatusResponse(BaseModel):
    """Status response for a public download job."""
    job_id: str
    status: Literal["queued", "running", "ready", "failed", "expired"]
    error: Optional[str] = None
    download_url: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[float] = None
    mode: Optional[str] = None


# ============================================================================
# PUBLIC DOWNLOAD API ENDPOINTS (for non-Telegram users)
# ============================================================================

@app.post("/api/downloads", response_model=CreateDownloadResponse)
@limiter.limit(RATE_LIMIT_CREATE)
async def create_public_download(body: CreateDownloadRequest, request: Request):
    """Create a public download job (non-Telegram users)."""
    try:
        # Check origin - only allow requests from allowed domains
        check_origin(request)
        
        # Validate YouTube URL
        is_valid, error_msg = validate_youtube_url(body.url)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Enhanced timestamp validation
        if body.start is not None:
            if body.start < 0:
                raise HTTPException(status_code=400, detail="Start time must be >= 0")
            if body.start > 86400 * 365:  # Prevent extremely large values (1 year)
                raise HTTPException(status_code=400, detail="Start time value is too large")
        
        if body.end is not None:
            if body.end > 86400 * 365:  # Prevent extremely large values
                raise HTTPException(status_code=400, detail="End time value is too large")
        
        if body.start is not None and body.end is not None:
            if body.end <= body.start:
                raise HTTPException(status_code=400, detail="End time must be greater than start time")
            
            # Check segment duration limit
            segment_duration = body.end - body.start
            if segment_duration > MAX_SEGMENT_DURATION:
                raise HTTPException(
                    status_code=400,
                    detail=f"Segment duration ({segment_duration:.1f}s) exceeds maximum allowed duration ({MAX_SEGMENT_DURATION}s)"
                )
        
        # Get client IP for per-IP limiting
        client_ip = get_remote_address(request)
        job_id = str(uuid.uuid4())
        task_id = f"public_{job_id}"
        
        # Check per-IP concurrent download limit
        from utils.resource_manager import PerIPLimiter
        from config import MAX_CONCURRENT_PER_IP
        per_ip_limiter = PerIPLimiter(MAX_CONCURRENT_PER_IP)
        can_start, error_msg = await per_ip_limiter.can_start_download(client_ip, task_id)
        if not can_start:
            raise HTTPException(status_code=429, detail=error_msg)
        
        now = time.time()
        
        # Create job record
        job = PublicDownloadJob(
            job_id=job_id,
            url=body.url,
            mode=body.mode,
            start=body.start,
            end=body.end,
            status="queued",
            created_at=now,
            expires_at=now + PUBLIC_DOWNLOAD_TTL_SECONDS,
            task_id=task_id,
        )
        
        async with public_jobs_lock:
            public_download_jobs[job_id] = job
        
        logger.info(f"Created public download job {job_id}: {body.url} ({body.mode}) from IP {client_ip}")
        
        # Start download in background
        asyncio.create_task(_process_public_download(job_id, client_ip))
        
        return CreateDownloadResponse(job_id=job_id)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating public download job: {e}", exc_info=True)
        error_msg = sanitize_error_message(e, PRODUCTION)
        raise HTTPException(status_code=500, detail=error_msg)


async def _process_public_download(job_id: str, client_ip: str):
    """Background task to process a public download job."""
    from utils.download_helpers import get_video_info_with_proxy, download_to_telegram
    from utils.trimming import estimate_file_size_mb
    from utils.resource_manager import ResourceManager, PerIPLimiter
    from utils.cleanup import cleanup_temp_file
    from config import MAX_DISK_USAGE_MB, MAX_MEMORY_USAGE_MB, MAX_CONCURRENT_DOWNLOADS, MAX_CONCURRENT_PER_IP
    
    resource_manager = ResourceManager(MAX_DISK_USAGE_MB, MAX_MEMORY_USAGE_MB, MAX_CONCURRENT_DOWNLOADS)
    per_ip_limiter = PerIPLimiter(MAX_CONCURRENT_PER_IP)
    
    async with public_jobs_lock:
        job = public_download_jobs.get(job_id)
        if not job:
            return
        job.status = "running"
    
    try:
        # Get video info for size estimation
        video_info = get_video_info_with_proxy(job.url, None, "proxy.json", True)
        
        # Estimate file size
        estimated_size_mb = estimate_file_size_mb(video_info, job.start, job.end)
        if estimated_size_mb is None:
            estimated_size_mb = 20.0  # Conservative default
        
        # Update job with estimate
        async with public_jobs_lock:
            job.estimated_size_mb = estimated_size_mb
        
        # Check resource limits
        can_start, error_msg = await resource_manager.can_start_download(estimated_size_mb)
        if not can_start:
            async with public_jobs_lock:
                job.status = "failed"
                job.error = error_msg
            return
        
        # Register with resource manager
        await resource_manager.register_download(job.task_id, estimated_size_mb)
        
        try:
            # Build yt-dlp options based on mode
            yt_dlp_options = {}
            if job.mode == "audio":
                yt_dlp_options = {
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                }
            
            # Add timestamp trimming if specified
            if job.start is not None and job.end is not None:
                from utils.trimming import create_download_ranges
                yt_dlp_options['download_ranges'] = create_download_ranges(job.start, job.end)
            
            # Queue the download
            result = await download_queue.queue_download(
                download_to_telegram,
                job.url,
                yt_dlp_options if yt_dlp_options else None,
                None,  # proxy
                "proxy.json",  # proxy_file
                10,  # max_retries
                True,  # verbose
                None,  # ffmpeg_location
                50,  # max_file_size_mb
                video_info,  # pre-fetched video info
            )
            
            if result['success']:
                async with public_jobs_lock:
                    job.status = "ready"
                    job.file_path = result['file_path']
                    job.temp_dir = result['temp_dir']
                    job.title = result.get('title')
                    job.duration = result.get('duration')
                logger.info(f"Public download {job_id} completed successfully")
            else:
                async with public_jobs_lock:
                    job.status = "failed"
                    job.error = result.get('error', 'Download failed')
                logger.error(f"Public download {job_id} failed")
                # Cleanup temp files if any
                if result.get('temp_dir'):
                    cleanup_temp_file(result.get('file_path'), result.get('temp_dir'), verbose=True)
        
        finally:
            await resource_manager.unregister_download(job.task_id)
            await per_ip_limiter.unregister_download(client_ip, job.task_id)
    
    except Exception as e:
        logger.error(f"Error processing public download {job_id}: {e}", exc_info=True)
        async with public_jobs_lock:
            job.status = "failed"
            job.error = sanitize_error_message(e, PRODUCTION)
        # Clean up per-IP tracking on error
        await per_ip_limiter.unregister_download(client_ip, job.task_id)


@app.get("/api/downloads/{job_id}", response_model=DownloadStatusResponse)
@limiter.limit(RATE_LIMIT_STATUS)
async def get_public_download_status(job_id: str, request: Request):
    """Get status of a public download job."""
    try:
        # Check origin - only allow requests from allowed domains
        check_origin(request)
        
        async with public_jobs_lock:
            job = public_download_jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            
            # Build response
            response = DownloadStatusResponse(
                job_id=job.job_id,
                status=job.status,
                error=job.error,
                title=job.title,
                duration=job.duration,
                mode=job.mode,
            )
            
            # Add download URL if ready
            if job.status == "ready" and not job.consumed:
                response.download_url = f"/api/downloads/{job_id}/file"
            
            return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting download status for {job_id}: {e}", exc_info=True)
        error_msg = sanitize_error_message(e, PRODUCTION)
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/api/downloads/{job_id}/file")
@limiter.limit(RATE_LIMIT_DOWNLOAD)
async def download_public_file(job_id: str, request: Request, background_tasks: BackgroundTasks):
    """Download the file for a public download job (one-time use)."""
    try:
        # Check origin - only allow requests from allowed domains
        check_origin(request)
        
        async with public_jobs_lock:
            job = public_download_jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            
            # Check if already consumed
            if job.consumed:
                raise HTTPException(status_code=410, detail="Download link has already been used (one-time use)")
            
            # Check if expired
            if time.time() > job.expires_at:
                job.status = "expired"
                raise HTTPException(status_code=410, detail="Download link has expired")
            
            # Check if ready
            if job.status != "ready":
                raise HTTPException(status_code=404, detail=f"Download not ready (status: {job.status})")
            
            if not job.file_path or not os.path.exists(job.file_path):
                raise HTTPException(status_code=404, detail="File not found")
            
            # Mark as consumed
            job.consumed = True
            logger.info(f"Public download {job_id} file served (one-time link consumed)")
        
        # Schedule cleanup after response is sent
        from utils.cleanup import cleanup_temp_file
        background_tasks.add_task(cleanup_temp_file, job.file_path, job.temp_dir, True)
        
        # Determine filename
        filename = f"{job.title or 'video'}.{'mp3' if job.mode == 'audio' else 'mp4'}"
        
        # Serve the file
        return FileResponse(
            path=job.file_path,
            filename=filename,
            media_type='application/octet-stream',
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading file for {job_id}: {e}", exc_info=True)
        error_msg = sanitize_error_message(e, PRODUCTION)
        raise HTTPException(status_code=500, detail=error_msg)


# ============================================================================
# TELEGRAM MINI APP ENDPOINTS
# ============================================================================

@app.post("/api/mini_app/submit")
async def mini_app_submit(request: Request, background_tasks: BackgroundTasks):
    """Receive timestamp data from mini app."""
    try:
        body_bytes = await request.body()
        if body_bytes:
            import json
            payload = json.loads(body_bytes.decode('utf-8'))
        else:
            payload = {}
        
        query_id = payload.get('query_id')
        data = payload.get('data', {})
        
        video_url = data.get('videoUrl') or f"https://www.youtube.com/watch?v={data.get('videoId')}"
        start_time = float(data.get('startFloat') or data.get('start', 0))
        end_time = float(data.get('endFloat') or data.get('end', 0))
        chat_id = int(data.get('chatId', 0))
        audio_only = data.get('audioOnly', False)

        if not chat_id:
            return JSONResponse({"success": False, "error": "Chat ID is required"})

        if start_time < 0 or end_time <= start_time:
            return JSONResponse({"success": False, "error": "Invalid timestamps."})

        if not BOT_TOKEN:
            return JSONResponse({"success": False, "error": "Bot token not configured"}, status_code=500)

        # Answer the web app query (required for InlineKeyboardButton)
        if query_id:
            try:
                from pyrogram import Client
                # Note: This would need proper Pyrogram integration
                # For now, just log
                logger.info(f"Mini app query_id: {query_id}")
            except Exception as e:
                logger.warning(f"Could not answer web app query: {e}")

        # Start download in background
        # Note: This would need proper integration with Pyrogram bot
        logger.info(f"Mini app download request: {video_url}, start={start_time}, end={end_time}, chat_id={chat_id}, audio_only={audio_only}")
        
        return JSONResponse({"success": True, "message": "Download started"})
        
    except Exception as e:
        logger.error(f"ERROR: Exception in mini_app_submit: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# Mount static files for mini app and public web UI
mini_app_path = Path(__file__).parent.parent / "mini_app"
if mini_app_path.exists():
    app.mount("/mini_app", StaticFiles(directory=str(mini_app_path), html=True), name="mini_app")

public_web_path = Path(__file__).parent.parent / "public_web"
if public_web_path.exists():
    app.mount("/web", StaticFiles(directory=str(public_web_path), html=True), name="public_web")


def start_web_server():
    """Start the FastAPI web server."""
    if not ENABLE_WEB_SERVER:
        logger.info("Web server is disabled. Set ENABLE_WEB_SERVER=True to enable.")
        return
    
    import uvicorn
    
    logger.info(f"Starting FastAPI server on {HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)

