# 1TamilMV Web Series Scraper

A Python scraper for extracting web series titles and torrent links from the 1TamilMV forum.

## Features

- Scrapes all web series topics from the forum
- Extracts magnet links and .torrent file links from each topic
- Supports pagination (35+ pages)
- Rate limiting to be server-friendly
- Outputs to JSON format

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Scrape all pages with torrent links
python scraper.py

# Scrape only first 5 pages
python scraper.py --pages 5

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
        "link": "magnet:?xt=..."
      }
    ]
  }
]
```

## License

MIT
