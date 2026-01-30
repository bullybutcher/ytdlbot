"""Smart format selector for yt-dlp based on file size limits."""

from typing import Optional, Set, Dict, Any


def select_appropriate_format(
    info: Optional[Dict[str, Any]],
    max_size_mb: int = 50,
    verbose: bool = True,
    excluded_formats: Optional[Set[str]] = None,
    trimmed_duration: Optional[float] = None,
) -> Optional[str]:
    """Select an appropriate format based on expected file size.
    
    Analyzes available formats to find the best quality that fits within the size limit.
    Uses actual format information rather than simple heuristics.
    
    Args:
        info: Video info dictionary from yt-dlp (can be None)
        max_size_mb: Maximum file size in MB (default 50MB for Telegram)
        verbose: Whether to print status messages
        excluded_formats: Set of format IDs or format strings to exclude (e.g., {'137', '140', '137+140'})
        trimmed_duration: Optional duration in seconds for trimmed segments. If provided, uses this instead of full video duration.
        
    Returns:
        Format string for yt-dlp, or None if no suitable format found
    """
    if excluded_formats is None:
        excluded_formats = set()
    
    # Handle None info
    if info is None:
        if verbose:
            print("No video info available, using safe default format")
        # Safe default: prefer MP4, avoid MKV, reasonable quality
        return 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/bestvideo+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
    
    max_size_bytes = max_size_mb * 1024 * 1024
    # Use trimmed duration if provided, otherwise use full video duration
    full_duration = info.get('duration', 0)
    duration = trimmed_duration if trimmed_duration is not None else full_duration
    formats = info.get('formats', [])
    
    # Calculate scaling factor for trimmed segments
    duration_scale = 1.0
    if trimmed_duration is not None and full_duration > 0:
        duration_scale = trimmed_duration / full_duration
    
    if trimmed_duration and verbose:
        print(f"Using trimmed duration {trimmed_duration:.1f}s (full video: {full_duration:.1f}s, scale: {duration_scale:.3f}) for format selection")
    
    # Quick check: if best format fits, use it (scale filesize if trimmed)
    filesize_approx = info.get('filesize_approx') or info.get('filesize')
    if filesize_approx:
        # Scale down filesize if this is a trimmed segment
        scaled_filesize = filesize_approx * duration_scale
        if scaled_filesize <= max_size_bytes:
            if verbose:
                print(f"Best quality fits ({scaled_filesize/(1024*1024):.1f}MB <= {max_size_mb}MB), using best quality")
            # Best quality fits, but still prefer MP4 for mobile compatibility
            return 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/bestvideo+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
    
    if not formats:
        # No format list available, use fallback selector
        if verbose:
            print("No format list available, using fallback selector")
        return 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480][ext=mp4]+bestaudio/best[ext=mp4]/best'
    
    # Analyze available formats to find best quality that fits
    if verbose:
        print(f"Analyzing {len(formats)} available formats to find best quality within {max_size_mb}MB limit...")
    
    # Separate video-only, audio-only, and combined formats
    video_formats = []
    audio_formats = []
    combined_formats = []
    
    for fmt in formats:
        vcodec = fmt.get('vcodec', 'none')
        acodec = fmt.get('acodec', 'none')
        has_video = vcodec != 'none'
        has_audio = acodec != 'none'
        
        # Check if format is MP4-compatible
        ext = fmt.get('ext', '').lower()
        container = fmt.get('container', '').lower()
        is_mp4_compatible = ext in ['mp4', 'm4v'] or container in ['mp4', 'm4v', 'm4a']
        
        # Skip formats that aren't MP4-compatible for mobile
        if not is_mp4_compatible:
            continue
        
        if has_video and has_audio:
            combined_formats.append(fmt)
        elif has_video:
            video_formats.append(fmt)
        elif has_audio:
            audio_formats.append(fmt)
    
    # Function to estimate file size for a format
    def estimate_format_size(fmt):
        """Estimate total file size for a format.
        
        For trimmed segments, scales down the filesize proportionally.
        """
        filesize = fmt.get('filesize') or fmt.get('filesize_approx')
        if filesize:
            # If this is a trimmed segment, scale down the filesize proportionally
            if duration_scale < 1.0:
                return filesize * duration_scale
            return filesize
        
        # Estimate from bitrate and duration (duration is already trimmed if applicable)
        tbr = fmt.get('tbr')  # Total bitrate
        vbr = fmt.get('vbr')  # Video bitrate
        abr = fmt.get('abr')  # Audio bitrate
        
        if tbr and duration:
            # Total bitrate in kbps * duration in seconds / 8 = bytes
            return (tbr * 1000 * duration) / 8
        elif vbr and abr and duration:
            # Video + audio bitrates
            return ((vbr + abr) * 1000 * duration) / 8
        elif vbr and duration:
            # Video only, estimate audio at 128kbps
            return ((vbr + 128) * 1000 * duration) / 8
        elif abr and duration:
            # Audio only
            return (abr * 1000 * duration) / 8
        
        return None
    
    # Function to calculate quality score
    def quality_score(fmt):
        """Calculate quality score for a format (higher is better)."""
        height = fmt.get('height', 0) or 0
        width = fmt.get('width', 0) or 0
        fps = fmt.get('fps', 0) or 0
        tbr = fmt.get('tbr') or fmt.get('vbr') or 0
        
        # Score based on resolution, fps, and bitrate
        return (height * width) + (fps * 100) + (tbr * 10)
    
    # Check combined formats first (simpler, no merging needed)
    suitable_combined = []
    for fmt in combined_formats:
        format_id = fmt.get('format_id')
        # Skip excluded formats
        if format_id in excluded_formats:
            continue
        size = estimate_format_size(fmt)
        if size and size <= max_size_bytes:
            suitable_combined.append({
                'format_id': format_id,
                'quality_score': quality_score(fmt),
                'filesize': size,
                'height': fmt.get('height', 0),
                'width': fmt.get('width', 0),
            })
    
    if suitable_combined:
        # Sort by quality, but prefer lower resolutions to avoid YouTube blocking
        # Lower resolutions (720p, 480p) are less likely to get 403 errors
        suitable_combined.sort(key=lambda x: (x['height'] <= 720, x['quality_score']), reverse=True)
        best = suitable_combined[0]
        if verbose:
            print(f"Selected combined format: {best['width']}x{best['height']}, "
                  f"estimated size: {best['filesize']/(1024*1024):.1f}MB")
        return best['format_id']
    
    # Try video+audio combinations
    suitable_combinations = []
    
    # Sort video formats by quality (highest first)
    video_formats.sort(key=lambda x: quality_score(x), reverse=True)
    # Sort audio formats by quality (highest first)
    audio_formats.sort(key=lambda x: quality_score(x), reverse=True)
    
    # Try combinations of video + audio formats
    for vfmt in video_formats[:10]:  # Limit to top 10 video formats to avoid too many combinations
        v_id = vfmt.get('format_id')
        v_size = estimate_format_size(vfmt)
        if not v_size:
            continue
        
        # Find best audio that fits with this video
        for afmt in audio_formats[:5]:  # Limit to top 5 audio formats
            a_id = afmt.get('format_id')
            # Skip excluded format combinations
            format_combo = f"{v_id}+{a_id}"
            if v_id in excluded_formats or a_id in excluded_formats or format_combo in excluded_formats:
                continue
            
            a_size = estimate_format_size(afmt)
            if not a_size:
                continue
            
            total_size = v_size + a_size
            if total_size <= max_size_bytes:
                # Check if both are MP4-compatible
                v_ext = vfmt.get('ext', '').lower()
                a_ext = afmt.get('ext', '').lower()
                v_mp4 = v_ext in ['mp4', 'm4v']
                a_mp4 = a_ext in ['m4a', 'mp4', 'aac']
                
                if v_mp4 and a_mp4:
                    suitable_combinations.append({
                        'video_id': v_id,
                        'audio_id': a_id,
                        'quality_score': quality_score(vfmt) + (quality_score(afmt) * 0.1),  # Video quality is more important
                        'filesize': total_size,
                        'height': vfmt.get('height', 0),
                        'width': vfmt.get('width', 0),
                    })
                    break  # Found best audio for this video, move to next video
    
    if suitable_combinations:
        # Sort by quality, but prefer lower resolutions and combined formats
        # Lower resolutions (720p, 480p) are less likely to get 403 errors from YouTube
        suitable_combinations.sort(key=lambda x: (x['height'] <= 720, x['quality_score']), reverse=True)
        best = suitable_combinations[0]
        if verbose:
            print(f"Selected video+audio combination: {best['width']}x{best['height']}, "
                  f"estimated size: {best['filesize']/(1024*1024):.1f}MB")
        return f"{best['video_id']}+{best['audio_id']}"
    
    # Fallback: use resolution-based selector (will try progressively lower resolutions)
    if verbose:
        print("No suitable format found in analysis, using fallback resolution-based selector")
    # Return None if we've excluded too many formats and can't find anything
    if excluded_formats and len(excluded_formats) > 10:
        if verbose:
            print("Too many formats excluded, no suitable format available")
        return None
    return 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720][ext=mp4]+bestaudio/bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480][ext=mp4]+bestaudio/best[ext=mp4]/best'

