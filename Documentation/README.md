# 1TamilMV Web Series Scraper

A Python scraper for extracting web series titles and torrent links from the 1TamilMV forum.

> **Note**: This tool is for educational purposes only. Please respect copyright laws and the platform's terms of service.

## Prerequisites

- Python 3.8 or higher
- MySQL/MariaDB database
- pip (Python package manager)
- qBittorrent with Web UI enabled (for download feature)
- mkvmerge (MKVToolNix) for video processing
- TMDB API Key (for metadata fetching)
- OpenRouter API Key (for AI-powered series matching and episode validation)

## Features

- **Unified CLI**: Single command with subcommands for scraping, database management, downloads, and video processing
- **Colored Logging**: Console and file logging with automatic rotation (10MB)
- **Configuration**: YAML-based config with environment variable support
- **Database Storage**: MySQL integration with normalized schema (series → seasons → torrents)
- **Quality Filtering**: Automatically selects highest quality (1080p preferred, 4K excluded)
- **Smart Parsing**: Extracts seasons, episodes, file sizes, and quality from torrent names
- **Database Tools**: Integrity checks, orphan fixing, statistics, and data clearing
- **qBittorrent Integration**: Download torrents directly to temp/completed folders
- **AI-Powered Series Matching**: Find tmdb_id and imdb_id using poster analysis with GPT-5.2/GPT-5 Nano Vision
- **Episode Management**: Import, scan, validate with AI, and fetch episode metadata from TMDB
- **Video Processing**: Process MKV files to keep only Tamil audio tracks using mkvmerge
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

# API Keys (optional - for AI finder and metadata)
RAPIDAPI_KEY=your_rapidapi_key
TMDB_API_KEY=your_tmdb_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
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
./scraper process --all       # Process all videos (Tamil audio only)
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

# Video processing commands
./scraper process --file /path/to/file.mkv   # Process single file
./scraper process --series "Series Name"     # Process specific series
./scraper process --all                      # Process all series
./scraper process --watch                    # Watch mode for new files
./scraper process --dry-run                  # Preview changes
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

### AI-Powered Series Finder

Find `tmdb_id` and `imdb_id` for series using AI poster analysis:

```bash
# Match a specific series using AI
python3 cli.py --finder <series_id>

# Match all series without tmdb_id
python3 cli.py --finder-all

# Dry run to preview
python3 cli.py --finder-all --dry-run
```

**How it works:**
1. Downloads poster from `poster_url` column
2. **Primary**: Analyzes poster with GPT-5 Nano (3000 tokens, high reasoning effort)
   - Attempts to extract TMDB/IMDb IDs directly from the poster
   - If IDs found, updates database immediately
3. **Fallback**: If primary fails, uses GPT-5.2 for complex analysis
4. **Legacy**: Falls back to TMDB search if AI ID extraction fails
5. Updates database: `tmdb_id`, `imdb_id`, `gpt=1`

**Database columns updated:**
- `tmdb_id` - TMDB series ID
- `imdb_id` - IMDb ID (tt1234567 format)
- `gpt` - 1 = AI success, 0 = failed

### Episode Management

Manage completed episodes with AI-powered validation and metadata fetching from TMDB:

```bash
# Default: Scan → AI Fallback (for ambiguous files) → Import to DB
python3 cli.py episodes

# Scan completed folder for episodes
python3 cli.py episodes --scan

# Import scanned episodes into database
python3 cli.py episodes --import-db

# Auto-import workflow: scan → import → match → fetch-metadata
python3 cli.py episodes --auto-import

# Fetch episode metadata from TMDB
python3 cli.py episodes --fetch-metadata

# Match series to TMDB (traditional method)
python3 cli.py episodes --match-series <series_id>

# Match all series without TMDB IDs (traditional method)
python3 cli.py episodes --match-all-series

# Validate metadata
python3 cli.py episodes --validate

# TMDB cache management
python3 cli.py episodes --cache-stats
python3 cli.py episodes --cache-clear
python3 cli.py episodes --cache-cleanup
```

**AI Episode Validation:**
The default `episodes` command now includes AI fallback for:
- Filenames without clear episode numbers
- Short series names with ambiguous patterns
- Batch range episodes (EP01-EP10)
- Uses OpenRouter GPT-5 Nano with 10000 max tokens for reasoning

### Video Processing with mkvmerge

Process downloaded MKV files to keep only Tamil audio tracks:

```bash
# Process a single file
python3 cli.py process --file /path/to/file.mkv

# Process a specific series folder
python3 cli.py process --series "Series Name"

# Process all downloaded series
python3 cli.py process --all

# Watch mode - continuously process new files
python3 cli.py process --watch --interval 30

# Dry run to preview changes
python3 cli.py process --dry-run --all
```

**How it works:**
1. Scans for MKV files in the completed directory
2. Uses mkvmerge to identify and keep only Tamil audio tracks
3. Detects Tamil by language code (tam/ta) or track name analysis
4. Falls back to first audio track if no language metadata exists
5. Preserves folder structure and removes empty folders
6. Creates processed copies with `_TamilOnly` suffix

**Requirements:**
- mkvmerge (part of MKVToolNix)
- Install via: `sudo apt install mkvtoolnix` (Debian/Ubuntu)

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
│                        EPISODE MANAGEMENT WORKFLOW                           │
└─────────────────────────────────────────────────────────────────────────────┘

  1. SCRAPE & DOWNLOAD        2. IMPORT EPISODES          3. AI FINDER
  ┌─────────────┐             ┌──────────────┐            ┌─────────────┐
  │ cli.py run  │────────────▶│ cli.py       │───────────▶│ cli.py      │
  │ & download  │             │ episodes     │            │ --finder    │
  │             │             │ --import-db  │            │             │
  │ Stores in   │             │              │            │ Analyzes    │
  │ completed/  │             │ Scans files  │            │ poster with │
  └─────────────┘             │ → episodes DB│            │ AI vision   │
                              └──────────────┘            │ Gets tmdb_id │
                                                          │ + imdb_id   │
                                                          └─────────────┘
                                                                  │
  4. FETCH METADATA            5. VALIDATE                    ▼
  ┌─────────────┐             ┌──────────────┐      ┌─────────────┐
  │ cli.py      │             │ cli.py       │      │  SERIES     │
  │ episodes    │             │ episodes     │      │  TABLE      │
  │ --fetch-    │             │ --validate   │      │             │
  │ metadata    │             │              │      │ tmdb_id ✓   │
  │             │             │ Checks       │      │ imdb_id ✓   │
  │ Uses tmdb_id│             │ episode      │      │ gpt = 1     │
  │ from series │             │ counts       │      └─────────────┘
  └─────────────┘             └──────────────┘
        │
        ▼
  ┌─────────────┐
  │  EPISODES   │
  │  TABLE      │
  │             │
  │ name ✓      │
  │ overview ✓  │
  │ air_date ✓  │
  │ runtime ✓   │
  └─────────────┘

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

The scraper uses a normalized structure with multiple tables:

```
series (id, title, name, url, poster_url, tmdb_id, imdb_id, gpt, year, summary, rating, created_at, updated_at)
  ↓
seasons (id, series_id, season_number, year, episode_count, total_size_human, quality, created_at, updated_at)
  ↓
torrents (id, series_id, season_id, type, name, link, size_human, quality, status)
  ↓
episodes (id, series_id, season_number, episode_number, file_path, file_size_mb, quality, status, name, overview, air_date, runtime, still_url, created_at)
```

**Series Table Columns:**
- `tmdb_id` - TMDB series ID (found via AI --finder)
- `imdb_id` - IMDb ID in tt1234567 format (found via AI --finder)
- `poster_url` - Poster image URL for AI analysis
- `gpt` - AI matching status: 1 = success, 0 = failed
- `name` - Clean series name from TMDB
- `summary` - Series overview
- `rating` - TMDB rating
- `year` - Release year

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
