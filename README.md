# 1TamilMV Web Series Scraper

A Python scraper for extracting web series titles and torrent links from the 1TamilMV forum.

> **Note**: This tool is for educational purposes only. Please respect copyright laws and the platform's terms of service.

## Prerequisites

- Python 3.8 or higher
- MySQL/MariaDB database
- pip (Python package manager)
- qBittorrent with Web UI enabled (for download feature)

## Features

- **Unified CLI**: Single command with subcommands for scraping, database management, and downloads
- **Colored Logging**: Console and file logging with automatic rotation (10MB)
- **Configuration**: YAML-based config with environment variable support
- **Database Storage**: MySQL integration with normalized schema (series → seasons → torrents)
- **Quality Filtering**: Automatically selects highest quality (1080p preferred, 4K excluded)
- **Smart Parsing**: Extracts seasons, episodes, file sizes, and quality from torrent names
- **Database Tools**: Integrity checks, orphan fixing, statistics, and data clearing
- **qBittorrent Integration**: Download torrents directly to temp/completed folders
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
cat > .env << EOF
DATABASE_URL=mysql://user:password@host:port/database
QBITTORRENT_HOST=localhost
QBITTORRENT_PORT=8090
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=adminadmin
QBITTORRENT_TEMP_DIR=/home/webseries/downloads/temp
QBITTORRENT_COMPLETED_DIR=/home/webseries/downloads/completed
EOF
```

Enable qBittorrent Web UI:
1. Open qBittorrent
2. Go to Tools → Options → Web UI
3. Enable Web UI (default port: 8090)
4. Set username and password

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

### Downloading Torrents

```bash
# Download torrents (saves to temp folder)
python3 cli.py download --limit 1

# Download with filters
python3 cli.py download --quality 1080p --limit 5
python3 cli.py download --series-id 1
python3 cli.py download --season-id 5

# Move completed torrents to completed folder
python3 cli.py move-completed

# Watch mode - automatically move completed torrents
python3 cli.py move-completed --watch --interval 30

# Dry run to preview
python3 cli.py download --dry-run
```

### Download Workflow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          TORRENT DOWNLOAD WORKFLOW                          │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
  │   DATABASE  │────▶│   DOWNLOAD   │────▶│ qBittorrent     │
  │             │     │   COMMAND    │     │ (Port 8090)     │
  │ ┌─────────┐ │     │              │     │                 │
  │ │torrents │ │     │ • Fetch from │     │ ┌─────────────┐ │
  │ │ table   │ │     │   DB        │     │ │Downloads to │ │
  │ │         │ │     │ • Filter     │     │ │  temp folder│ │
  │ │link col │ │     │ • Add to qB  │     │ └─────────────┘ │
  │ │(magnets)│ │     └──────────────┘     │        │        │
  └─────────────┘                           │        ▼        │
                                            │   ┌──────────┐  │
                                            │   │  temp/   │  │
                                            │   │          │  │
                                            │   │ S01E01.mk│ │
                                            │   └──────────┘  │
                                            │        │        │
                                            │        │ 100%   │
                                            │        ▼        │
                                            │   ┌──────────┐  │
       ┌───────────────────────────────────▶│completed/│  │
       │                                    │          │  │
       │  move-completed                    │ S01E01.mk│  │
       │  command                           └──────────┘  │
       │                                                  │
       └──────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                            COMMAND FLOW                                      │
└─────────────────────────────────────────────────────────────────────────────┘

  1. SCRAPING                    2. DOWNLOADING              3. COMPLETION
  ┌─────────────┐              ┌──────────────┐            ┌─────────────┐
  │ cli.py run  │              │ cli.py       │            │ cli.py      │
  │              │              │ download      │            │ move-       │
  │ Scrapes      │─────────────▶│ --limit 1    │───────────▶│ completed   │
  │ forum → DB   │              │              │            │             │
  └─────────────┘              └──────────────┘            └─────────────┘
        │                              │                         │
        ▼                              ▼                         ▼
   Stores magnet              Adds magnet to             Moves files
   links in DB                qBittorrent (temp)         temp→completed


┌─────────────────────────────────────────────────────────────────────────────┐
│                        DIRECTORY STRUCTURE                                   │
└─────────────────────────────────────────────────────────────────────────────┘

  /home/webseries/downloads/
  ├── temp/              # Active downloads go here
  │   ├── Series.S01E01.1080p.mkv
  │   └── Series.S01E02.1080p.mkv  ← downloading...
  │
  └── completed/         # Completed files are moved here
      ├── Series.S01E01.1080p.mkv
      └── Series.S01E02.1080p.mkv  ← done!

```

**Optional: Make it available system-wide** (run from any directory):

```bash
# Create a symlink to /usr/local/bin (replace /path/to/project with actual path)
sudo ln -s $(pwd)/scraper /usr/local/bin/scraper

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
torrents (id, series_id, season_id, type, name, link, size_human, quality, status)
```

**Torrent Status Values:**
- `0` - Failed/Pending (will be re-downloaded)
- `1` - Successfully downloaded (will be skipped)
- `NULL` - Not yet downloaded

The download command automatically skips torrents with `status = 1`, preventing duplicate downloads. Status is set to `1` when a torrent completes and is moved to the completed folder.

## Troubleshooting

### Database Connection Issues
- Verify your `DATABASE_URL` in `.env` is correct
- Ensure MySQL service is running: `sudo systemctl status mysql`

### qBittorrent Connection Issues
- Verify qBittorrent Web UI is enabled (Tools → Options → Web UI)
- Check the port (default: 8090)
- Verify username/password credentials
- Test connection: `curl http://localhost:8090/api/v2/app/version`

### Permission Denied on Symlink
- Use `sudo` when creating the symlink
- Ensure the `scraper` file is executable: `chmod +x scraper`

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - feel free to use this project for personal or educational purposes.
