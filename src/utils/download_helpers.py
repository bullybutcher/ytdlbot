"""Helper functions for downloading videos with proxy support."""

import os
import random
import tempfile
import shutil
from typing import Optional, Dict, Any

import yt_dlp

from config import PROXY_FILE
from proxy import get_proxy, load_proxies, construct_proxy_string, update_proxies
from utils.format_selector import select_appropriate_format
from utils.trimming import extract_trimmed_duration


def get_video_info_with_proxy(
    url: str,
    proxy: Optional[Dict] = None,
    proxy_file: str = "proxy.json",
    verbose: bool = True,
) -> Optional[Dict[str, Any]]:
    """Get video information without downloading to estimate file size.
    
    Args:
        url: URL to get info for
        proxy: Proxy dictionary to use. If None, a random proxy will be selected
        proxy_file: Name of the proxy file to load proxies from
        verbose: Whether to print status messages
        
    Returns:
        Dictionary with video info including filesize_approx, or None if failed
    """
    try:
        if proxy is None:
            try:
                proxies = load_proxies(proxy_file)
                proxy = random.choice(proxies) if proxies else None
            except (FileNotFoundError, Exception):
                if verbose:
                    logger.warning("Could not load proxy file")
                proxy = None
        
        opts = {
            'quiet': not verbose,
            'no_warnings': not verbose,
        }
        
        # Add proxy if available
        if proxy:
            proxy_str = construct_proxy_string(proxy)
            opts['proxy'] = f'http://{proxy_str}'
        
        # Configure JavaScript runtime (deno) if not already set
        deno_path = shutil.which('deno')
        if deno_path:
            opts['js_runtimes'] = {'deno': {'path': deno_path}}
        else:
            opts['js_runtimes'] = {'deno': {}}
        
        # Enable remote components for JavaScript challenge solving (recommended)
        if 'remote_components' not in opts:
            opts['remote_components'] = ['ejs:github']
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        if verbose:
            import logging
            logging.getLogger(__name__).error(f"Error getting video info: {e}")
        return None


def download_to_telegram(
    urls,
    yt_dlp_options=None,
    proxy=None,
    proxy_file="proxy.json",
    max_retries=10,
    verbose=True,
    ffmpeg_location=None,
    max_file_size_mb=50,
    video_info=None,
):
    """Download using yt-dlp with a proxy and return file path for Telegram upload.
    
    This function is designed for Telegram bots - it downloads to a temporary file
    and returns the file path and metadata. The file can be sent to Telegram and
    optionally cleaned up afterward.
    
    Args:
        urls: URL or list of URLs to download (only first URL is used)
        yt_dlp_options: Dictionary of yt-dlp options. Defaults to best quality video+audio merged.
        proxy: Proxy dictionary to use. If None, a random proxy will be selected from proxy_file
        proxy_file: Name of the proxy file to load proxies from
        max_retries: Maximum number of retries with different proxies on error
        verbose: Whether to print status messages
        ffmpeg_location: Path to ffmpeg executable (optional)
        max_file_size_mb: Maximum file size in MB (default 50MB for Telegram)
        video_info: Optional pre-fetched video info dict. If provided, skips the initial fetch to save proxy usage.
        
    Returns:
        Dictionary with keys:
            - 'success': bool - Whether download was successful
            - 'file_path': str - Path to downloaded file (None if failed)
            - 'title': str - Video title (None if failed)
            - 'ext': str - File extension (None if failed)
            - 'duration': int - Video duration in seconds (None if failed)
            - 'temp_dir': str - Temporary directory path (for cleanup in main process, picklable)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if isinstance(urls, str):
        urls = [urls]
    
    # Use first URL only
    url = urls[0] if urls else None
    if not url:
        return {'success': False, 'file_path': None, 'title': None, 'ext': None, 'duration': None, 'temp_dir': None}
    
    # Create temporary directory for download
    temp_dir = tempfile.mkdtemp(prefix='yt_dlp_telegram_')
    # Use a simple filename template in the temp directory
    temp_file_template = os.path.join(temp_dir, 'video.%(ext)s')
    
    # Store info for return
    info_dict = {}
    
    def progress_hook(d):
        """Hook to capture video info during download."""
        if d['status'] == 'finished':
            info_dict.update(d.get('info_dict', {}))
    
    retries = 0
    used_proxies = set()
    downloaded_file_path = None
    failed_formats = set()  # Track formats that failed (not available)
    # Use provided video_info if available, otherwise will fetch it
    cached_video_info = video_info
    
    while retries < max_retries:
        try:
            # Get or use cached video info
            if cached_video_info is None:
                if verbose:
                    logger.info("Getting video information...")
                cached_video_info = get_video_info_with_proxy(url, proxy=proxy, proxy_file=proxy_file, verbose=verbose)
            
            # Extract trimmed duration from download_ranges if present
            trimmed_duration = None
            if yt_dlp_options and 'download_ranges' in yt_dlp_options:
                trimmed_duration = extract_trimmed_duration(yt_dlp_options.get('download_ranges'), verbose=verbose)
            
            # Check if format is already specified (e.g., for audio-only downloads)
            format_already_set = yt_dlp_options and 'format' in yt_dlp_options and yt_dlp_options.get('format')
            
            # Only select format if not already set (e.g., audio mode already has 'bestaudio/best')
            selected_format = None
            if not format_already_set:
                # Select appropriate format based on file size, excluding failed formats
                # Use trimmed duration if available to select appropriate format for the segment
                if cached_video_info:
                    selected_format = select_appropriate_format(
                        cached_video_info, 
                        max_size_mb=max_file_size_mb, 
                        verbose=verbose, 
                        excluded_formats=failed_formats,
                        trimmed_duration=trimmed_duration
                    )
                else:
                    if verbose:
                        logger.info("Could not get video info, using safe default format (MP4, mobile-compatible)")
                    # Safe default: prefer MP4, avoid MKV, reasonable quality
                    selected_format = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/bestvideo+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
                
                # If no format found (exhausted all options), return error
                if selected_format is None:
                    if verbose:
                        logger.warning("No suitable format available within size limit after excluding unavailable formats")
                    return {
                        'success': False,
                        'file_path': None,
                        'title': None,
                        'ext': None,
                        'duration': None,
                        'temp_dir': None,
                        'error': 'No suitable format available within 50MB limit. The video may be too long or high quality.'
                    }
            
            # Build options with selected format
            if yt_dlp_options is None:
                current_opts = {
                    'format': selected_format,
                    'merge_output_format': 'mp4',
                    'quiet': not verbose,
                    'no_warnings': not verbose,
                }
            else:
                current_opts = yt_dlp_options.copy()
                if 'merge_output_format' not in current_opts:
                    current_opts['merge_output_format'] = 'mp4'
                # Only set format if not already specified (e.g., audio mode)
                if 'format' not in current_opts and selected_format:
                    current_opts['format'] = selected_format
                # Always override quiet/no_warnings based on verbose parameter
                current_opts['quiet'] = not verbose
                current_opts['no_warnings'] = not verbose
            
            # Add output template and other options
            opts = current_opts.copy()
            opts['outtmpl'] = temp_file_template
            opts['progress_hooks'] = [progress_hook]
            
            # Add ffmpeg location if specified
            if ffmpeg_location and 'ffmpeg_location' not in opts:
                opts['ffmpeg_location'] = ffmpeg_location
            
            # Configure JavaScript runtime (deno) if not already set
            if 'js_runtimes' not in opts:
                deno_path = shutil.which('deno')
                if deno_path:
                    opts['js_runtimes'] = {'deno': {'path': deno_path}}
                else:
                    opts['js_runtimes'] = {'deno': {}}
            
            # Enable remote components for JavaScript challenge solving (recommended)
            if 'remote_components' not in opts:
                opts['remote_components'] = ['ejs:github']
            
            # Get proxy
            if proxy is None:
                try:
                    proxies = load_proxies(proxy_file)
                    available_proxies = [
                        p for p in proxies 
                        if f"{p.get('host')}:{p.get('port')}" not in used_proxies
                    ]
                    if not available_proxies:
                        available_proxies = proxies
                        used_proxies.clear()
                    if available_proxies:
                        proxy = random.choice(available_proxies)
                        used_proxies.add(f"{proxy.get('host')}:{proxy.get('port')}")
                except (FileNotFoundError, Exception) as e:
                    if verbose:
                        logger.warning(f"Could not load proxy: {e}")
                    proxy = None
            
            if proxy:
                proxy_str = construct_proxy_string(proxy)
                opts['proxy'] = f'http://{proxy_str}'
                if verbose:
                    city = proxy.get('city', 'Unknown')
                    country = proxy.get('country', 'Unknown')
                    logger.info(f"Using proxy from {city}, {country}")
            
            # Create YoutubeDL instance and download
            with yt_dlp.YoutubeDL(opts) as ydl:
                # Extract info first to get title
                info = ydl.extract_info(url, download=False)
                info_dict.update(info)
                
                # Download the video
                ydl.download([url])
            
            # Find the downloaded file - yt-dlp may have added extension
            downloaded_file_path = None
            for file in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, file)
                if os.path.isfile(file_path) and not file.endswith('.part'):
                    downloaded_file_path = file_path
                    break
            
            if not downloaded_file_path or not os.path.exists(downloaded_file_path):
                # Try to find any file in the directory
                files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
                if files:
                    downloaded_file_path = os.path.join(temp_dir, files[0])
                else:
                    raise Exception("Downloaded file not found")
            
            # Get file info
            title = info_dict.get('title', 'Unknown')
            ext = info_dict.get('ext', os.path.splitext(downloaded_file_path)[1].lstrip('.'))
            duration = info_dict.get('duration')
            
            # Ensure file extension is mp4 (for mobile compatibility)
            if ext and ext.lower() not in ['mp4', 'm4v']:
                if verbose:
                    logger.warning(f"File format is {ext}, expected MP4. This may not play well on mobile.")
            
            # Return temp_dir so cleanup can be done in main process (closures aren't picklable)
            result = {
                'success': True,
                'file_path': downloaded_file_path,
                'title': title,
                'ext': ext,
                'duration': duration,
                'temp_dir': temp_dir,  # Return temp_dir for cleanup in main process (picklable)
            }
            
            return result
            
        except FileNotFoundError:
            if verbose:
                logger.warning(f"'{proxy_file}' not found. Starting proxy list update...")
            try:
                update_proxies(filename=proxy_file, verbose=verbose)
                proxy = None
            except Exception:
                pass
            retries += 1
            
        except (yt_dlp.utils.DownloadError, Exception) as e:
            error_msg = str(e).lower()
            error_msg_original = str(e)  # Keep original for logging
            
            # Check if we have a format selected - if so, 403s are likely format-specific
            current_format = opts.get('format') if 'opts' in locals() else None
            has_format = current_format is not None and current_format != ''
            
            # Check for 403/Forbidden errors
            is_403_error = "403" in error_msg or "forbidden" in error_msg or "access denied" in error_msg
            is_format_unavailable = "requested format is not available" in error_msg or "format is not available" in error_msg
            
            # If we have a format and get a 403, treat it as format-related
            if has_format and is_403_error:
                if verbose:
                    logger.warning(f"Format blocked by YouTube (403): {error_msg_original[:100]}")
                    logger.info(f"Current format: {current_format}")
                # Add the failed format to excluded list and retry format selection
                failed_formats.add(current_format)
                # Also add individual format IDs if it's a combination (e.g., "137+140")
                if '+' in current_format:
                    parts = current_format.split('+')
                    for part in parts:
                        failed_formats.add(part.strip())
                if verbose:
                    logger.info(f"Excluding format '{current_format}' and retrying format selection...")
                # Don't increment retries for format errors - we'll retry with new format
                # Reset proxy to None to get a fresh proxy for the retry
                proxy = None
                continue
            
            # Format unavailable errors
            if is_format_unavailable:
                if verbose:
                    logger.warning(f"Format not available: {error_msg_original[:100]}")
                    logger.info(f"Current format: {current_format or 'N/A'}")
                if current_format:
                    failed_formats.add(current_format)
                    if '+' in current_format:
                        parts = current_format.split('+')
                        for part in parts:
                            failed_formats.add(part.strip())
                    if verbose:
                        logger.info(f"Excluding format '{current_format}' and retrying format selection...")
                proxy = None
                continue
            
            # Generic 403 or "Sign in to" errors - retry with new proxy (only if no format was selected)
            if "Sign in to" in error_msg or (is_403_error and not has_format):
                if verbose:
                    logger.warning("Got 'Sign in to confirm' or '403' error. Trying again with another proxy...")
                proxy = None
                retries += 1
                continue
            
            # Cleanup on error
            try:
                if downloaded_file_path and os.path.exists(downloaded_file_path):
                    os.remove(downloaded_file_path)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
            except:
                pass
            raise
    
    # Cleanup on failure
    try:
        if downloaded_file_path and os.path.exists(downloaded_file_path):
            os.remove(downloaded_file_path)
        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)
    except:
        pass
    
    return {'success': False, 'file_path': None, 'title': None, 'ext': None, 'duration': None, 'temp_dir': None}

