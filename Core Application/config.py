"""
Configuration module for webseries scraper
Loads settings from config.yaml and merges with defaults
"""

import os
import yaml
from pathlib import Path
from copy import deepcopy


def load_env_file(env_path='.env'):
    """
    Load environment variables from .env file

    Args:
        env_path: Path to .env file
    """
    env_file = Path(env_path)
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                # Parse KEY=VALUE format
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # Only set if not already in environment
                    if key and key not in os.environ:
                        os.environ[key] = value


# Load .env file on import
load_env_file()


# Get script directory for relative paths
script_dir = Path(__file__).parent.parent

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
        'temp_dir': os.environ.get('QBITTORRENT_TEMP_DIR', str(script_dir / 'Data & Cache' / 'downloads' / 'temp')),
        'completed_dir': os.environ.get('QBITTORRENT_COMPLETED_DIR', str(script_dir / 'Data & Cache' / 'downloads' / 'completed')),
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
    'openrouter': {
        'api_key': os.environ.get('OPENROUTER_API_KEY', ''),
        'model': os.environ.get('OPENROUTER_MODEL', 'openai/gpt-5-nano'),
        'timeout': 30
    },
    'output': {
        'json_file': str(script_dir / 'Data & Cache' / 'data' / 'webseries.json'),
        'enabled': True
    },
    'logging': {
        'level': 'INFO',
        'file': str(script_dir / 'Data & Cache' / 'logs' / 'scraper.log'),
        'max_bytes': 10485760,  # 10MB
        'backup_count': 5,
        'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    },
    'video_processing': {
        'mkvmerge_path': '/usr/bin/mkvmerge',
        'completed_dir': str(script_dir / 'Data & Cache' / 'downloads' / 'completed'),
        'processing_dir': str(script_dir / 'Data & Cache' / 'downloads' / 'processing'),
        'processed_dir': str(script_dir / 'Data & Cache' / 'downloads' / 'processed'),
        'watch_interval': 30,
        'timeout': 600
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
