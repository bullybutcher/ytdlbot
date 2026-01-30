"""Download queue system for FastAPI endpoints."""

import asyncio
import logging
import queue as stdlib_queue
import threading
from typing import Callable, Any, Tuple

logger = logging.getLogger(__name__)


def download_worker_thread(worker_id: int, download_queue: stdlib_queue.Queue, shutdown_event: threading.Event):
    """Worker thread that processes downloads from the queue concurrently.
    
    Each worker runs in its own thread, creating isolated instances.
    Multiple workers process from the same queue, giving true concurrency.
    
    Args:
        worker_id: Unique worker identifier
        download_queue: Queue containing download tasks
        shutdown_event: Event to signal workers to stop
    """
    logger.info(f"Download worker {worker_id} started")

    while not shutdown_event.is_set():
        try:
            # Get next download task from queue (blocking with timeout to check shutdown)
            try:
                task = download_queue.get(timeout=1.0)
            except stdlib_queue.Empty:
                continue  # Check shutdown and retry

            if task is None:  # Shutdown signal
                break

            func, args, kwargs, future = task
            try:
                # Run the download function synchronously in this worker thread
                # Each thread creates its own instances, avoiding connection conflicts
                result = func(*args, **kwargs)
                if not future.cancelled():
                    # Set result in the event loop that created the future
                    # Use call_soon_threadsafe to safely set result from worker thread
                    try:
                        loop = future.get_loop()
                        if loop.is_closed():
                            logger.warning(f"Worker {worker_id}: Event loop closed, cannot set result")
                        else:
                            loop.call_soon_threadsafe(future.set_result, result)
                    except RuntimeError:
                        # Fallback if get_loop() fails - try to set directly (may work in some cases)
                        try:
                            future.set_result(result)
                        except Exception:
                            logger.error(f"Worker {worker_id}: Failed to set result on future")
            except Exception as e:
                if not future.cancelled():
                    try:
                        loop = future.get_loop()
                        if not loop.is_closed():
                            loop.call_soon_threadsafe(future.set_exception, e)
                    except RuntimeError:
                        try:
                            future.set_exception(e)
                        except Exception:
                            logger.error(f"Worker {worker_id}: Failed to set exception on future")
            finally:
                download_queue.task_done()
        except Exception as e:
            logger.error(f"Error in download worker {worker_id}: {e}")

    logger.info(f"Download worker {worker_id} stopped")


class DownloadQueue:
    """Multi-threaded download queue for FastAPI endpoints."""

    def __init__(self, max_workers: int = 10, max_queue_size: int = 20):
        """Initialize download queue.
        
        Args:
            max_workers: Number of worker threads
            max_queue_size: Maximum queue size
        """
        self.max_workers = max_workers
        self.download_queue = stdlib_queue.Queue(maxsize=max_queue_size)
        self.shutdown_event = threading.Event()
        self.workers = []

    def start(self):
        """Start worker threads."""
        self.workers = []
        for i in range(self.max_workers):
            worker = threading.Thread(
                target=download_worker_thread,
                args=(i + 1, self.download_queue, self.shutdown_event),
                daemon=True,
                name=f"DownloadWorker-{i + 1}",
            )
            worker.start()
            self.workers.append(worker)
        logger.info(f"Download queue system initialized with {self.max_workers} worker threads")

    def stop(self, timeout: float = 5.0):
        """Stop worker threads.
        
        Args:
            timeout: Maximum time to wait for workers to finish
        """
        self.shutdown_event.set()

        # Signal all workers to stop
        for _ in self.workers:
            try:
                self.download_queue.put_nowait(None)
            except stdlib_queue.Full:
                pass

        # Wait for all workers to finish
        for worker in self.workers:
            worker.join(timeout=timeout)

        logger.info(f"Download queue shut down ({len(self.workers)} workers stopped)")

    async def queue_download(self, func: Callable, *args, **kwargs) -> Any:
        """Queue a download function to run in one of the worker threads.
        
        Args:
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Result from the function
            
        Raises:
            RuntimeError: If queue is full
        """
        # Create a future to track completion
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        # Queue the task
        try:
            self.download_queue.put_nowait((func, args, kwargs, future))
        except stdlib_queue.Full:
            future.set_exception(RuntimeError("Download queue is full. Please try again later."))

        # Wait for the result
        return await future

