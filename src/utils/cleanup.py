"""Background cleanup tasks for expired download jobs and temporary files."""

import asyncio
import logging
import os
import shutil
import time
from typing import Optional, Dict

from config import (
    PUBLIC_CLEANUP_INTERVAL_SECONDS,
    PUBLIC_DOWNLOAD_TTL_SECONDS,
    PUBLIC_JOB_RETENTION_SECONDS,
)

logger = logging.getLogger(__name__)

# Job registry - will be initialized by web server
public_download_jobs: Dict[str, 'PublicDownloadJob'] = {}
public_jobs_lock = asyncio.Lock()


async def public_download_cleanup_loop():
    """Periodic cleanup for public download jobs and temp files."""
    while True:
        try:
            await asyncio.sleep(PUBLIC_CLEANUP_INTERVAL_SECONDS)
            
            if public_download_jobs is None or public_jobs_lock is None:
                continue
            
            now = time.time()
            to_delete = []
            
            async with public_jobs_lock:
                for job_id, job in public_download_jobs.items():
                    # Expire old jobs and clean up their files
                    if now > job.expires_at and job.status != "expired":
                        job.status = "expired"
                        if not job.error:
                            job.error = "Download link expired"
                        if job.file_path or job.temp_dir:
                            cleanup_temp_file(job.file_path, job.temp_dir, verbose=True)
                            job.file_path = None
                            job.temp_dir = None

                    # Remove jobs long after expiry to keep memory bounded
                    if now - job.created_at > (PUBLIC_DOWNLOAD_TTL_SECONDS + PUBLIC_JOB_RETENTION_SECONDS):
                        to_delete.append(job_id)

                for job_id in to_delete:
                    public_download_jobs.pop(job_id, None)
                    
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in public download cleanup loop: {e}")


def cleanup_temp_file(file_path: Optional[str], temp_dir: Optional[str], verbose: bool = False):
    """Clean up temporary file and directory.
    
    Args:
        file_path: Path to temporary file
        temp_dir: Path to temporary directory
        verbose: Whether to print cleanup messages
    """
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            if verbose:
                logger.info(f"Cleaned up temp file: {file_path}")
        if temp_dir and os.path.exists(temp_dir):
            try:
                os.rmdir(temp_dir)
            except OSError:
                # Directory might not be empty, try to remove all files
                shutil.rmtree(temp_dir, ignore_errors=True)
            if verbose:
                logger.info(f"Cleaned up temp directory: {temp_dir}")
    except Exception as e:
        if verbose:
            logger.warning(f"Could not cleanup temp file: {e}")

