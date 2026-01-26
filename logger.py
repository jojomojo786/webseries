"""
Logging module for webseries scraper
Setup colored console and file logging with rotation
"""

import logging
import colorlog
from pathlib import Path
from logging.handlers import RotatingFileHandler


def setup_logging(config):
    """
    Setup colored console and file logging with rotation

    Args:
        config: Configuration dictionary with logging settings

    Returns:
        logging.Logger: Root logger instance
    """
    # Create logs directory
    log_file = Path(config['logging']['file'])
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, config['logging']['level']))

    # Remove existing handlers
    logger.handlers.clear()

    # Console handler with colors
    console_handler = colorlog.StreamHandler()
    console_format = colorlog.ColoredFormatter(
        '%(log_color)s%(asctime)s - %(levelname)-8s%(reset)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=config['logging']['max_bytes'],
        backupCount=config['logging']['backup_count']
    )
    file_format = logging.Formatter(config['logging']['format'])
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    return logger


def get_logger(name):
    """
    Get a logger instance with the specified name

    Args:
        name: Logger name (typically __name__)

    Returns:
        logging.Logger: Logger instance
    """
    return logging.getLogger(name)
