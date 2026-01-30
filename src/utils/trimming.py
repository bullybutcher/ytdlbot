"""Video trimming utilities."""

from typing import Optional, Callable, List, Dict, Any


def format_time(seconds: float) -> str:
    """Format seconds to MM:SS.mmm or HH:MM:SS.mmm with millisecond precision."""
    total_seconds = int(seconds)
    milliseconds = int((seconds - total_seconds) * 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"
    return f"{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def estimate_file_size_mb(
    video_info: Optional[Dict[str, Any]],
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
) -> Optional[float]:
    """Estimate file size in MB for a video or video segment.
    
    Args:
        video_info: Video info dict from yt-dlp
        start_time: Start time in seconds for trimmed segment (None for full video)
        end_time: End time in seconds for trimmed segment (None for full video)
    
    Returns:
        Estimated file size in MB, or None if cannot estimate
    """
    if not video_info:
        return None
    
    # Get full video size
    filesize_approx = video_info.get('filesize_approx') or video_info.get('filesize')
    if not filesize_approx:
        return None
    
    full_size_mb = filesize_approx / (1024 * 1024)
    
    # If it's a full video (no trimming), return full size
    if start_time is None or end_time is None:
        return full_size_mb
    
    # For trimmed segments, calculate proportion based on duration
    full_duration = video_info.get('duration', 0)
    if full_duration and full_duration > 0:
        segment_duration = end_time - start_time
        if segment_duration > 0:
            estimated_size = (full_size_mb * segment_duration) / full_duration
            return estimated_size
    
    # Fallback: if we can't calculate proportion, return a conservative estimate
    # Assume segment is 10% of full video (conservative)
    return full_size_mb * 0.1


def create_download_ranges(
    start_time: float, end_time: float
) -> Callable[[Any, Any], List[Dict[str, float]]]:
    """Create a download_ranges function for yt-dlp.
    
    Args:
        start_time: Start time in seconds
        end_time: End time in seconds
        
    Returns:
        Callable that returns download ranges for yt-dlp
    """
    def download_ranges(info_dict: Any, ydl: Any) -> List[Dict[str, float]]:
        """Return download ranges for yt-dlp."""
        return [{'start_time': start_time, 'end_time': end_time}]
    
    return download_ranges


def extract_trimmed_duration(
    download_ranges: Optional[Any], verbose: bool = False
) -> Optional[float]:
    """Extract trimmed duration from download_ranges option.
    
    Args:
        download_ranges: download_ranges option value (callable or list)
        verbose: Whether to print debug messages
        
    Returns:
        Trimmed duration in seconds, or None if not a trimmed segment
    """
    if not download_ranges:
        return None
    
    try:
        if callable(download_ranges):
            # For lambda functions, call it with dummy objects to extract the ranges
            class DummyInfo:
                pass
            class DummyYDL:
                pass
            ranges = download_ranges(DummyInfo(), DummyYDL())
            if ranges and len(ranges) > 0 and isinstance(ranges[0], dict):
                start_time = ranges[0].get('start_time', 0)
                end_time = ranges[0].get('end_time', 0)
                if end_time > start_time:
                    duration = end_time - start_time
                    if verbose:
                        print(f"Detected trimmed segment: {start_time:.1f}s - {end_time:.1f}s (duration: {duration:.1f}s)")
                    return duration
        elif isinstance(download_ranges, list) and len(download_ranges) > 0:
            start_time = download_ranges[0].get('start_time', 0)
            end_time = download_ranges[0].get('end_time', 0)
            if end_time > start_time:
                duration = end_time - start_time
                if verbose:
                    print(f"Detected trimmed segment: {start_time:.1f}s - {end_time:.1f}s (duration: {duration:.1f}s)")
                return duration
    except Exception as e:
        if verbose:
            print(f"Could not extract trimmed duration from download_ranges: {e}")
    
    return None

