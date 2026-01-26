#!/usr/bin/env python3
"""
TMDB API Caching Module

Caches TMDB API responses to reduce API calls and improve performance.
"""

import os
import json
import hashlib
import time
from pathlib import Path
from typing import Any, Optional
from logger import get_logger

logger = get_logger(__name__)

# Cache configuration
CACHE_DIR = os.path.join(os.path.dirname(__file__), '.cache', 'tmdb')
DEFAULT_TTL = 86400  # 24 hours in seconds

# Ensure cache directory exists
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)


def _get_cache_key(endpoint: str, params: dict = None) -> str:
    """
    Generate a unique cache key from endpoint and parameters

    Args:
        endpoint: API endpoint path
        params: Query parameters

    Returns:
        SHA256 hash of the request
    """
    # Create a deterministic string from the request
    key_str = f"{endpoint}:{json.dumps(params, sort_keys=True) if params else ''}"
    return hashlib.sha256(key_str.encode()).hexdigest()


def _get_cache_path(key: str) -> str:
    """Get the file path for a cache key"""
    return os.path.join(CACHE_DIR, f"{key}.json")


def get(endpoint: str, params: dict = None, ttl: int = DEFAULT_TTL) -> Optional[Any]:
    """
    Get cached response for a request

    Args:
        endpoint: API endpoint path
        params: Query parameters
        ttl: Time-to-live in seconds (default 24 hours)

    Returns:
        Cached response data or None if not found/expired
    """
    cache_key = _get_cache_key(endpoint, params)
    cache_path = _get_cache_path(cache_key)

    if not os.path.exists(cache_path):
        return None

    try:
        with open(cache_path, 'r') as f:
            cache_entry = json.load(f)

        # Check if cache is expired
        cache_age = time.time() - cache_entry.get('timestamp', 0)
        if cache_age > ttl:
            logger.debug(f"Cache expired for {endpoint}")
            os.remove(cache_path)
            return None

        logger.debug(f"Cache hit for {endpoint} (age: {int(cache_age)}s)")
        return cache_entry.get('data')

    except (json.JSONDecodeError, KeyError, IOError) as e:
        logger.warning(f"Error reading cache file {cache_path}: {e}")
        # Delete corrupted cache file
        try:
            os.remove(cache_path)
        except OSError:
            pass
        return None


def set(endpoint: str, params: dict = None, data: Any = None) -> None:
    """
    Store response in cache

    Args:
        endpoint: API endpoint path
        params: Query parameters
        data: Response data to cache
    """
    cache_key = _get_cache_key(endpoint, params)
    cache_path = _get_cache_path(cache_key)

    cache_entry = {
        'timestamp': time.time(),
        'endpoint': endpoint,
        'params': params,
        'data': data
    }

    try:
        with open(cache_path, 'w') as f:
            json.dump(cache_entry, f)
        logger.debug(f"Cached response for {endpoint}")
    except IOError as e:
        logger.warning(f"Error writing cache file {cache_path}: {e}")


def clear() -> int:
    """
    Clear all cached TMDB responses

    Returns:
        Number of cache files deleted
    """
    count = 0
    try:
        for filename in os.listdir(CACHE_DIR):
            if filename.endswith('.json'):
                file_path = os.path.join(CACHE_DIR, filename)
                os.remove(file_path)
                count += 1
        logger.info(f"Cleared {count} cached TMDB responses")
    except OSError as e:
        logger.error(f"Error clearing cache: {e}")

    return count


def get_stats() -> dict:
    """
    Get cache statistics

    Returns:
        Dict with cache stats: total_files, total_size_bytes, oldest_entry, newest_entry
    """
    stats = {
        'total_files': 0,
        'total_size_bytes': 0,
        'oldest_entry': None,
        'newest_entry': None,
        'expired_count': 0,
    }

    try:
        current_time = time.time()
        for filename in os.listdir(CACHE_DIR):
            if not filename.endswith('.json'):
                continue

            file_path = os.path.join(CACHE_DIR, filename)
            stats['total_files'] += 1
            stats['total_size_bytes'] += os.path.getsize(file_path)

            try:
                with open(file_path, 'r') as f:
                    cache_entry = json.load(f)
                timestamp = cache_entry.get('timestamp', 0)

                # Check if expired
                if current_time - timestamp > DEFAULT_TTL:
                    stats['expired_count'] += 1

                # Track oldest/newest
                if stats['oldest_entry'] is None or timestamp < stats['oldest_entry']:
                    stats['oldest_entry'] = timestamp
                if stats['newest_entry'] is None or timestamp > stats['newest_entry']:
                    stats['newest_entry'] = timestamp

            except (json.JSONDecodeError, IOError):
                pass

    except OSError as e:
        logger.error(f"Error getting cache stats: {e}")

    return stats


def cleanup_expired(ttl: int = DEFAULT_TTL) -> int:
    """
    Remove expired cache entries

    Args:
        ttl: Time-to-live in seconds

    Returns:
        Number of cache files deleted
    """
    count = 0
    current_time = time.time()

    try:
        for filename in os.listdir(CACHE_DIR):
            if not filename.endswith('.json'):
                continue

            file_path = os.path.join(CACHE_DIR, filename)
            try:
                with open(file_path, 'r') as f:
                    cache_entry = json.load(f)

                timestamp = cache_entry.get('timestamp', 0)
                if current_time - timestamp > ttl:
                    os.remove(file_path)
                    count += 1
            except (json.JSONDecodeError, IOError):
                # Remove corrupted files
                try:
                    os.remove(file_path)
                    count += 1
                except OSError:
                    pass

        if count > 0:
            logger.info(f"Cleaned up {count} expired cache entries")

    except OSError as e:
        logger.error(f"Error cleaning up cache: {e}")

    return count
