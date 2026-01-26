# 1TamilMV Web Series Scraper

A Python scraper for extracting web series titles and torrent links from the 1TamilMV forum.

## Features

- **Unified CLI**: Single command with subcommands for scraping and database management
- **Colored Logging**: Console and file logging with automatic rotation (10MB)
- **Configuration**: YAML-based config with environment variable support
- **Database Storage**: MySQL integration with normalized schema (series → seasons → torrents)
- **Quality Filtering**: Automatically selects highest quality (1080p preferred, 4K excluded)
- **Smart Parsing**: Extracts seasons, episodes, file sizes, and quality from torrent names
- **Database Tools**: Integrity checks, orphan fixing, statistics, and data clearing
- **Backward Compatible**: Legacy `scraper.py` still works with argparse

## Installation

```bash
# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Optional: Create config file from template
cp config.yaml.example config.yaml
# Edit config.yaml with your settings
```

## Configuration

Set up your environment variables:

```bash
# Create a .env file (use .env.example as template)
echo "DATABASE_URL=mysql://user:password@host:port/database" > .env
```

## Usage

### Method 1: Unified CLI (Recommended)

The `scraper` command provides a unified interface to all functionality:

```bash
# From the project directory
./scraper run                 # Run scraper
./scraper db stats            # Show statistics
./scraper db check            # Verify integrity
./scraper --debug run --pages 1  # Debug mode

# Scraper options
./scraper run --pages 5                    # Scrape 5 pages
./scraper run -a                           # Include all torrents
./scraper run --no-torrents                # Skip topic scraping
./scraper run --no-json                    # Skip JSON output
./scraper run --no-db                      # Skip database save

# Database commands
./scraper db stats         # Show database statistics
./scraper db check         # Verify database integrity
./scraper db fix-orphans   # Fix orphaned torrent records
./scraper db clear         # Clear all data (with confirmation)
```

**Optional: Make it available system-wide** (run from any directory):

```bash
# Create a symlink to /usr/local/bin
sudo ln -s /Users/adeelafzal/Downloads/Cursor\ Projects/webseries/scraper /usr/local/bin/scraper

# Then you can use it from anywhere:
scraper db stats
scraper run --pages 5
```

### Method 2: Using cli.py directly

```bash
# Run scraper
python3 cli.py run

# Database commands
python3 cli.py db stats
python3 cli.py db check
```

### Method 3: Legacy scraper.py (Backward Compatible)

```bash
# Scrape all pages (highest quality torrent per series by default)
python3 scraper.py

# Scrape only first 5 pages
python3 scraper.py --pages 5

# Include all torrents (not just highest quality)
python3 scraper.py --all-torrents
# or
python3 scraper.py -a

# Scrape without fetching individual topic pages (faster, titles only)
python3 scraper.py --no-torrents

# Custom output file
python3 scraper.py --output data/output.json
```

## Output Format

```json
[
  {
    "title": "Series Name (2024) S01 EP (01-10) ...",
    "url": "https://www.1tamilmv.rsvp/index.php?/forums/topic/...",
    "scraped_at": "2024-01-26T12:00:00",
    "torrents": [
      {
        "type": "magnet",
        "name": "filename",
        "link": "magnet:?xt=...",
        "size_bytes": 6192692569,
        "size_human": "5.77 GB"
      }
    ]
  }
]
```

## Logging

Logs are automatically created in `logs/scraper.log` with the following features:

- **Colored console output**: INFO (green), WARNING (yellow), ERROR (red)
- **File rotation**: Automatic rotation at 10MB, keeps 5 backup logs
- **Configurable levels**: Set via `--debug` flag or in `config.yaml`

```bash
# Enable debug logging
./scraper --debug run

# View logs
tail -f logs/scraper.log
```

## Database Schema

The scraper uses a normalized three-table structure:

```
series (id, title, url, created_at, updated_at)
  ↓
seasons (id, series_id, season_number, year, episode_count, total_size_human, quality, created_at, updated_at)
  ↓
torrents (id, series_id, season_id, type, name, link, size_bytes, size_human, quality)
```

## License

MIT
