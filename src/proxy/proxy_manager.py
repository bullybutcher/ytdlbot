"""Proxy management system for yt-dlp."""

import json
import os
import random
import time
import io
import importlib
import inspect
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, List, Dict

import requests
from tqdm import tqdm

SPEEDTEST_URL = "http://212.183.159.230/5MB.zip"


def is_valid_proxy(proxy: Dict) -> bool:
    """Check if the proxy is valid.
    
    Args:
        proxy: Proxy dictionary
        
    Returns:
        True if proxy is valid, False otherwise
    """
    return (
        proxy.get("host") is not None
        and proxy.get("country") != "Russia"
        and proxy.get("country") != "RU"
    )


def construct_proxy_string(proxy: Dict) -> str:
    """Construct a proxy string from the proxy dictionary.
    
    Args:
        proxy: Proxy dictionary with host, port, username (optional), password (optional)
        
    Returns:
        Proxy string in format "host:port" or "username:password@host:port"
    """
    if proxy.get("username"):
        return f'{proxy["username"]}:{proxy["password"]}@{proxy["host"]}:{proxy["port"]}'
    return f'{proxy["host"]}:{proxy["port"]}'


def test_proxy(proxy: Dict) -> Optional[Dict]:
    """Test the proxy by measuring the download time.
    
    Args:
        proxy: Proxy dictionary
        
    Returns:
        Proxy dictionary with added "time" key if successful, None otherwise
    """
    proxy_str = construct_proxy_string(proxy)
    start_time = time.perf_counter()
    try:
        response = requests.get(
            SPEEDTEST_URL,
            stream=True,
            proxies={"http": f"http://{proxy_str}"},
            timeout=5,
        )
        response.raise_for_status()

        total_length = response.headers.get("content-length")
        if total_length is None or int(total_length) != 5242880:
            return None

        with io.BytesIO() as f:
            download_time, _ = download_with_progress(
                response, f, total_length, start_time
            )
            return {"time": download_time, **proxy}
    except requests.RequestException:
        return None


def download_with_progress(response, f, total_length: int, start_time: float):
    """Download content from the response with progress tracking.
    
    Args:
        response: Requests response object
        f: File-like object to write to
        total_length: Total content length
        start_time: Start time for download
        
    Returns:
        Tuple of (download_time, downloaded_bytes)
    """
    downloaded_bytes = 0
    for chunk in response.iter_content(1024):
        downloaded_bytes += len(chunk)
        f.write(chunk)
        done = int(30 * downloaded_bytes / int(total_length))
        if done == 6:
            break
        if (
            done > 3
            and (downloaded_bytes // (time.perf_counter() - start_time) / 100000) < 1.0
        ):
            return float("inf"), downloaded_bytes
    return round(time.perf_counter() - start_time, 2), downloaded_bytes


def get_proxy_file_path(filename: str = "proxy.json") -> str:
    """Get the full path to the proxy file.
    
    Args:
        filename: Name of the proxy file
        
    Returns:
        Full path to the proxy file
    """
    # Get the project root (parent of src/)
    project_root = Path(__file__).parent.parent.parent
    return str(project_root / filename)


def save_proxies_to_file(proxies: List[Dict], filename: str = "proxy.json", verbose: bool = True):
    """Save the best proxies to a JSON file.
    
    Args:
        proxies: List of proxy dictionaries
        filename: Name of the proxy file to save
        verbose: Whether to print status messages
    """
    json_path = get_proxy_file_path(filename)
    with open(json_path, "w") as f:
        json.dump(proxies, f, indent=4)
    if verbose:
        print(f"proxy.json saved to {json_path}")


def load_proxies(filename: str = "proxy.json") -> List[Dict]:
    """Load proxies from a JSON file.
    
    Args:
        filename: Name of the proxy file
        
    Returns:
        List of proxy dictionaries
        
    Raises:
        FileNotFoundError: If proxy file doesn't exist
    """
    json_path = get_proxy_file_path(filename)
    with open(json_path, "r") as f:
        return json.load(f)


def get_best_proxies(providers: List, max_workers: int = 2) -> List[Dict]:
    """Return the top five proxies based on speed from all providers.
    
    Args:
        providers: List of ProxyProvider instances
        max_workers: Number of concurrent threads for testing
        
    Returns:
        List of top 5 fastest proxy dictionaries
    """
    all_proxies = []
    for provider in providers:
        try:
            print(f"Fetching proxies from {provider.__class__.__name__}")
            proxies = provider.fetch_proxies()
            all_proxies.extend([proxy for proxy in proxies if is_valid_proxy(proxy)])
        except Exception as e:
            print(f"Failed to fetch proxies from {provider.__class__.__name__}: {e}")

    best_proxies = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(test_proxy, proxy): proxy for proxy in all_proxies}
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Testing proxies",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_noinv_fmt}]",
            unit=" proxies",
            unit_scale=True,
            ncols=80,
        ):
            result = future.result()
            if result is not None:
                best_proxies.append(result)
    return sorted(best_proxies, key=lambda x: x["time"])[:5]


def update_proxies(max_workers: int = 2, filename: str = "proxy.json", verbose: bool = True) -> List[Dict]:
    """Update the proxies list and save the best ones.
    
    Args:
        max_workers: Number of concurrent threads for testing proxies
        filename: Name of the proxy file to save
        verbose: Whether to print progress messages
        
    Returns:
        List of best proxies
    """
    providers = []
    providers_dir = Path(__file__).parent / "providers"
    
    for filename_provider in os.listdir(providers_dir):
        # Check if the file is a Python module
        if filename_provider.endswith(".py") and filename_provider != "__init__.py":
            module_name = filename_provider[:-3]  # Remove the '.py' suffix
            module_path = f"proxy.providers.{module_name}"
            module = importlib.import_module(module_path)
            classes = inspect.getmembers(module, inspect.isclass)
            for class_name, class_obj in classes:
                if class_name != "ProxyProvider" and issubclass(class_obj, ProxyProvider):
                    providers.append(class_obj())
                    break
    
    if verbose:
        print(f"Using up to {max_workers} concurrent threads")
    best_proxies = get_best_proxies(providers, max_workers)
    save_proxies_to_file(best_proxies, filename, verbose)
    if verbose:
        print("All done.")
    return best_proxies


def get_proxy(filename: str = "proxy.json") -> Optional[Dict]:
    """Get a random proxy from the proxy file.
    
    Args:
        filename: Name of the proxy file
        
    Returns:
        Proxy dictionary or None if file not found
    """
    try:
        proxies = load_proxies(filename)
        return random.choice(proxies) if proxies else None
    except FileNotFoundError:
        return None

