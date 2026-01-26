"""
Configuration module for webseries scraper
Loads settings from config.yaml and merges with defaults
"""

import os
import yaml
from pathlib import Path
from copy import deepcopy


# Default config structure
DEFAULT_CONFIG = {
    'database': {
        'url': os.environ.get('DATABASE_URL', '')
    },
    'qbittorrent': {
        'host': os.environ.get('QBITTORRENT_HOST', 'localhost'),
        'port': int(os.environ.get('QBITTORRENT_PORT', 8090)),
        'username': os.environ.get('QBITTORRENT_USERNAME', ''),
        'password': os.environ.get('QBITTORRENT_PASSWORD', ''),
        'save_path': os.environ.get('QBITTORRENT_SAVE_PATH', ''),
        'temp_dir': os.environ.get('QBITTORRENT_TEMP_DIR', '/home/webseries/downloads/temp'),
        'completed_dir': os.environ.get('QBITTORRENT_COMPLETED_DIR', '/home/webseries/downloads/completed'),
        'max_active': int(os.environ.get('QBITTORRENT_MAX_ACTIVE', 5)),
        'category': os.environ.get('QBITTORRENT_CATEGORY', '')
    },
    'scraper': {
        'base_url': 'https://www.1tamilmv.rsvp',
        'pages': None,  # None = unlimited
        'rate_limit': 2.0,  # seconds between requests
        'timeout': 30,
        'quality_filter': True,
        'exclude_4k': True,
        'preferred_quality': '1080p'
    },
    'output': {
        'json_file': 'data/webseries.json',
        'enabled': True
    },
    'logging': {
        'level': 'INFO',
        'file': 'logs/scraper.log',
        'max_bytes': 10485760,  # 10MB
        'backup_count': 5,
        'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    }
}


def deep_merge(base_dict, update_dict):
    """
    Deep merge two dictionaries

    Args:
        base_dict: Base dictionary (will be modified)
        update_dict: Dictionary with updates (takes precedence)
    """
    for key, value in update_dict.items():
        if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
            deep_merge(base_dict[key], value)
        else:
            base_dict[key] = value


def load_config(config_path='config.yaml'):
    """
    Load config from file, merge with defaults

    Args:
        config_path: Path to config file (default: config.yaml)

    Returns:
        dict: Merged configuration dictionary
    """
    # Deep copy defaults to avoid modifying global
    config = deepcopy(DEFAULT_CONFIG)

    # Override with file if exists
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file) as f:
            user_config = yaml.safe_load(f)
            if user_config:
                deep_merge(config, user_config)

    return config


def get_config():
    """
    Get configuration singleton (lazy loaded)

    Returns:
        dict: Configuration dictionary
    """
    if not hasattr(get_config, '_instance'):
        get_config._instance = load_config()
    return get_config._instance
