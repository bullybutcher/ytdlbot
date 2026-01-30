"""Resource manager for tracking and limiting concurrent downloads."""

import asyncio
import time
from typing import Dict, Optional, Tuple


class ResourceManager:
    """Manages resource limits for concurrent downloads."""

    def __init__(self, max_disk_mb: int, max_memory_mb: int, max_concurrent: int):
        """Initialize resource manager.
        
        Args:
            max_disk_mb: Maximum disk usage in MB
            max_memory_mb: Maximum memory usage in MB
            max_concurrent: Maximum concurrent downloads
        """
        self.max_disk_mb = max_disk_mb
        self.max_memory_mb = max_memory_mb
        self.max_concurrent = max_concurrent
        self.active_downloads: Dict[str, Dict] = {}  # {task_id: {'disk_mb': X, 'memory_mb': Y, 'started_at': timestamp}}
        self.lock = asyncio.Lock()

    async def can_start_download(self, estimated_size_mb: float) -> Tuple[bool, Optional[str]]:
        """Check if new download can start based on resources.
        
        Args:
            estimated_size_mb: Estimated file size in MB
            
        Returns:
            Tuple of (can_start: bool, error_message: Optional[str])
        """
        async with self.lock:
            # Calculate current usage
            current_disk = sum(d["disk_mb"] for d in self.active_downloads.values())
            current_memory = sum(d["memory_mb"] for d in self.active_downloads.values())
            current_count = len(self.active_downloads)

            # Add 20% safety margin for disk space estimation inaccuracies
            estimated_with_margin = estimated_size_mb * 1.2

            # Check limits
            if current_count >= self.max_concurrent:
                return False, "Maximum concurrent downloads reached. Please try again in a moment."
            if current_disk + estimated_with_margin > self.max_disk_mb:
                return False, "Server is busy. Please try again in a moment."
            if current_memory + 300 > self.max_memory_mb:  # ~300MB per download
                return False, "Server is busy. Please try again in a moment."

            return True, None

    async def register_download(self, task_id: str, estimated_size_mb: float):
        """Register a new download.
        
        Args:
            task_id: Unique task identifier
            estimated_size_mb: Estimated file size in MB
        """
        async with self.lock:
            self.active_downloads[task_id] = {
                "disk_mb": estimated_size_mb,
                "memory_mb": 300,  # Estimated memory per download
                "started_at": time.time(),
            }

    async def unregister_download(self, task_id: str):
        """Unregister completed/failed download.
        
        Args:
            task_id: Unique task identifier
        """
        async with self.lock:
            if task_id in self.active_downloads:
                self.active_downloads.pop(task_id)

    def get_stats(self) -> Dict:
        """Get current resource usage statistics.
        
        Returns:
            Dictionary with current usage stats
        """
        current_disk = sum(d["disk_mb"] for d in self.active_downloads.values())
        current_memory = sum(d["memory_mb"] for d in self.active_downloads.values())
        current_count = len(self.active_downloads)

        return {
            "active_downloads": current_count,
            "disk_usage_mb": current_disk,
            "memory_usage_mb": current_memory,
            "max_concurrent": self.max_concurrent,
            "max_disk_mb": self.max_disk_mb,
            "max_memory_mb": self.max_memory_mb,
        }


class PerIPLimiter:
    """Tracks and limits concurrent downloads per IP address."""

    def __init__(self, max_concurrent_per_ip: int):
        """Initialize per-IP limiter.
        
        Args:
            max_concurrent_per_ip: Maximum concurrent downloads per IP
        """
        self.max_concurrent_per_ip = max_concurrent_per_ip
        self.ip_downloads: Dict[str, set] = {}  # {ip: set of task_ids}
        self.lock = asyncio.Lock()

    async def can_start_download(self, ip_address: str, task_id: str) -> Tuple[bool, Optional[str]]:
        """Check if IP can start another download.
        
        Args:
            ip_address: IP address
            task_id: Unique task identifier
            
        Returns:
            Tuple of (can_start: bool, error_message: Optional[str])
        """
        async with self.lock:
            if ip_address not in self.ip_downloads:
                self.ip_downloads[ip_address] = set()

            current_count = len(self.ip_downloads[ip_address])
            if current_count >= self.max_concurrent_per_ip:
                return False, f"Maximum {self.max_concurrent_per_ip} concurrent downloads per IP. Please wait for current downloads to complete."

            self.ip_downloads[ip_address].add(task_id)
            return True, None

    async def unregister_download(self, ip_address: str, task_id: str):
        """Unregister a download for an IP.
        
        Args:
            ip_address: IP address
            task_id: Unique task identifier
        """
        async with self.lock:
            if ip_address in self.ip_downloads:
                self.ip_downloads[ip_address].discard(task_id)
                # Clean up empty IP entries
                if not self.ip_downloads[ip_address]:
                    del self.ip_downloads[ip_address]

