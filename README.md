# 1TamilMV Web Series Scraper

A Python scraper for extracting web series titles and torrent links from the 1TamilMV forum.

## Features

- Scrapes all web series topics from the forum
- Extracts magnet links and .torrent file links from each topic
- **Highest quality mode**: Automatically selects the largest (highest quality) torrent
- File size parsing from magnet links and torrent names
- Supports pagination (35+ pages)
- Rate limiting to be server-friendly
- Outputs to JSON format

## Installation

```bash
# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

```bash
# Scrape all pages with all torrent links
python scraper.py

# Scrape only first 5 pages
python scraper.py --pages 5

# Get only the highest quality (largest) torrent per series
python scraper.py --highest-quality
# or
python scraper.py -hq

# Combine options
python scraper.py --pages 10 --highest-quality

# Scrape without fetching individual topic pages (faster, titles only)
python scraper.py --no-torrents

# Custom output file
python scraper.py --output data/output.json
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

## License

MIT
