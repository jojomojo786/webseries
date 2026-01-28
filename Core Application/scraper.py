#!/usr/bin/env python3
"""
1TamilMV Web Series Scraper
Scrapes titles and torrent/magnet links from the forum
"""

import sys
from pathlib import Path

# Add all subdirectories to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir))

import requests
from bs4 import BeautifulSoup
import json
import re
import time
import os
from datetime import datetime
from urllib.parse import urljoin
from dotenv import load_dotenv

from logger import get_logger

# Load environment variables
load_dotenv()

BASE_URL = "https://www.1tamilmv.rsvp"

def get_forum_url(sort_by: str = "start_date") -> str:
    """Get forum URL with specified sort order.
    Args:
        sort_by: 'start_date' (newly created topics) or 'last_post' (recently updated topics)
    """
    return f"{BASE_URL}/index.php?/forums/forum/19-web-series-tv-shows/&sortby={sort_by}&sortdirection=desc"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

logger = get_logger(__name__)


def get_page(url: str, retries: int = 3) -> BeautifulSoup | None:
    """Fetch a page and return BeautifulSoup object"""
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            # Try lxml first, fallback to html.parser
            try:
                return BeautifulSoup(response.text, "lxml")
            except Exception:
                return BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def extract_forum_date_from_row(topic_link) -> str | None:
    """Extract forum post date from the topic's row on the forum listing page"""
    # The <time> element is in the same row as the topic link
    # Navigate up to find the containing row, then find the time element
    row = topic_link.find_parent("div", class_="ipsDataItem_main")
    if row:
        # Look for the <time> element with datetime attribute
        time_elem = row.find("time", attrs={"datetime": True})
        if time_elem and time_elem.get("datetime"):
            return time_elem.get("datetime")
    return None


def extract_topics_from_page(soup: BeautifulSoup) -> list[dict]:
    """Extract topic titles, URLs, and forum dates from a forum page"""
    topics = []
    seen_urls = set()

    # Patterns to skip in titles (pagination, navigation links, non-series content)
    skip_title_patterns = [
        r"^go to page",
        r"^\d+$",
        r"^page \d+",
        r"^next$",
        r"^prev$",
        r"^first$",
        r"^last$",
    ]

    # Content to exclude (not actual web series)
    exclude_content = [
        "audio launch",
        "press meet",
        "trailer launch",
        "teaser launch",
        "music launch",
    ]

    # Find all topic links
    for link in soup.find_all("a", href=re.compile(r"/forums/topic/")):
        href = link.get("href", "")

        # Skip pagination URLs within topics (e.g., /page/2/#comments)
        if "/page/" in href or "#comments" in href or "#" in href:
            continue

        # Skip preview URLs
        if "preview=" in href:
            continue

        title = link.get("title") or link.get_text(strip=True)
        if not title or len(title) < 20:
            continue

        # Skip pagination/navigation link titles
        title_lower = title.lower().strip()
        if any(re.match(pattern, title_lower) for pattern in skip_title_patterns):
            continue

        # Skip if title is just a number
        if re.match(r"^#?\d+$", title.strip()):
            continue

        # Skip non-series content (audio launches, press meets, etc.)
        if any(excl in title_lower for excl in exclude_content):
            continue

        full_url = urljoin(BASE_URL, href)

        # Normalize URL for deduplication
        # This site uses ?/forums/topic/ID-slug/ format, so extract the topic ID
        topic_match = re.search(r"/forums/topic/(\d+)", full_url)
        if topic_match:
            normalized_url = topic_match.group(1)  # Just use topic ID
        else:
            normalized_url = full_url.rstrip("/")

        if normalized_url not in seen_urls:
            seen_urls.add(normalized_url)
            # Clean the title
            title = re.sub(r'\s+', ' ', title).strip()
            # Extract forum date from the same row
            forum_date = extract_forum_date_from_row(link)
            topics.append({
                "title": title,
                "url": full_url,
                "forum_date": forum_date
            })

    return topics


def parse_size_from_name(name: str) -> int:
    """Parse file size from torrent name, returns size in bytes"""
    # Match patterns like "5.7GB", "1.5GB", "500MB", "1TB"
    size_match = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB|MB|KB)", name, re.IGNORECASE)
    if size_match:
        value = float(size_match.group(1))
        unit = size_match.group(2).upper()
        multipliers = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
        return int(value * multipliers.get(unit, 1))
    return 0


def extract_poster_from_topic(soup: BeautifulSoup) -> str | None:
    """Extract poster image URL from a topic page"""
    # Find the post content wrapper
    content_wrap = soup.find("div", class_="cPost_contentWrap")
    if content_wrap:
        # Find the first image in the comment content
        comment_content = content_wrap.find("div", attrs={"data-role": "commentContent"})
        if comment_content:
            img = comment_content.find("img", class_="ipsImage")
            if img and img.get("src"):
                return img.get("src")
    return None


def extract_torrents_from_topic(soup: BeautifulSoup) -> list[dict]:
    """Extract torrent/magnet links from a topic page"""
    torrents = []

    # Find magnet links
    for link in soup.find_all("a", href=re.compile(r"^magnet:")):
        magnet = link.get("href")
        if magnet:
            # Extract name from magnet link
            name_match = re.search(r"dn=([^&]+)", magnet)
            name = name_match.group(1) if name_match else link.get_text(strip=True)
            name = requests.utils.unquote(name)

            # Extract size from xl= parameter (exact size in bytes)
            size_match = re.search(r"xl=(\d+)", magnet)
            if size_match:
                size_bytes = int(size_match.group(1))
            else:
                # Fallback: parse size from name
                size_bytes = parse_size_from_name(name)

            torrents.append({
                "type": "magnet",
                "name": name,
                "link": magnet,
                "size_bytes": size_bytes,
                "size_human": format_size(size_bytes) if size_bytes > 0 else "unknown"
            })

    # Find .torrent file links (exclude magnet links that contain .torrent in the name)
    for link in soup.find_all("a", href=re.compile(r"\.torrent")):
        torrent_url = link.get("href")
        if torrent_url and not torrent_url.startswith("magnet:"):
            name = link.get_text(strip=True) or torrent_url.split("/")[-1]
            size_bytes = parse_size_from_name(name)
            torrents.append({
                "type": "torrent",
                "name": name,
                "link": urljoin(BASE_URL, torrent_url),
                "size_bytes": size_bytes,
                "size_human": format_size(size_bytes) if size_bytes > 0 else "unknown"
            })

    return torrents


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable size"""
    if size_bytes >= 1024**4:
        return f"{size_bytes / 1024**4:.2f} TB"
    elif size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.2f} GB"
    elif size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.2f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    return f"{size_bytes} B"


def is_4k_torrent(name: str) -> bool:
    """Check if torrent is 4K/2160p quality"""
    name_lower = name.lower()
    # Patterns that indicate 4K quality
    patterns_4k = ["4k", "2160p", "uhd", "4k sdr", "4k hdr"]
    return any(p in name_lower for p in patterns_4k)


def detect_quality_with_ai(name: str) -> str:
    """Use OpenRouter GPT-5-nano to detect video quality from torrent name"""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY not found, returning unknown")
        return "unknown"

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-5-nano",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a video quality detector. Analyze the torrent name and determine the video quality. Respond with ONLY one of these exact values: 4k, 1080p, 720p, 480p, 360p. If you cannot determine the quality with reasonable confidence, respond with: unknown. No explanations, just the quality value."
                    },
                    {
                        "role": "user",
                        "content": f"What is the video quality of this torrent: {name}"
                    }
                ],
                "max_tokens": 10000,
                "temperature": 0
            },
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        quality = result["choices"][0]["message"]["content"].strip().lower()

        # Validate the response
        valid_qualities = ["4k", "1080p", "720p", "480p", "360p", "unknown"]
        if quality in valid_qualities:
            logger.info(f"    🤖 AI detected quality: {quality} for {name[:50]}...")
            return quality
        else:
            logger.warning(f"    AI returned invalid quality '{quality}', using unknown")
            return "unknown"
    except Exception as e:
        logger.warning(f"    AI quality detection failed: {e}")
        return "unknown"


def get_torrent_quality(name: str) -> str:
    """Extract quality from torrent name, use AI if pattern matching fails"""
    name_lower = name.lower()
    if "2160p" in name_lower or "4k" in name_lower:
        return "4k"
    elif "1080p" in name_lower:
        return "1080p"
    elif "720p" in name_lower:
        return "720p"
    elif "480p" in name_lower:
        return "480p"
    elif "360p" in name_lower:
        return "360p"

    # Use AI to detect quality when pattern matching fails
    return detect_quality_with_ai(name)


def extract_episode_range(name: str) -> str:
    """Extract episode range from torrent name for grouping"""
    name_lower = name.lower()

    # Match patterns like:
    # - "EP (01-08)" -> "01-08"
    # - "S02 EP01" -> "01" (space between S## and EP)
    # - "S02EP01" -> "01" (no space)
    # - "S01E01" -> "01"
    # - "EP01" -> "01"
    # - No episode info -> "full"

    # Match EP (XX-YY) pattern (e.g., "EP (01-08)")
    match = re.search(r'ep\s*\((\d+(?:-\d+)?)\)', name_lower)
    if match:
        return match.group(1)

    # Match S## EP## pattern (e.g., "S02 EP01" with space)
    match = re.search(r's\d+\s+ep(\d+)', name_lower)
    if match:
        return match.group(1)

    # Match S##EP## pattern (e.g., "S02EP01" no space)
    match = re.search(r's\d+ep(\d+)', name_lower)
    if match:
        return match.group(1)

    # Match S##E## pattern (e.g., "S01E01")
    match = re.search(r's\d+e(\d+)', name_lower)
    if match:
        return match.group(1)

    # Match EP## pattern (e.g., "EP01")
    match = re.search(r'\bep(\d+)\b', name_lower)
    if match:
        return match.group(1)

    return "full"


def filter_highest_quality(torrents: list[dict]) -> tuple[list[dict], bool]:
    """
    Filter torrents to keep ONLY THE LARGEST size torrent per episode range.
    Ignores quality preferences - always uses largest file (including 4K).

    Returns:
        tuple: (filtered_torrents, is_4k_only) - is_4k_only is always False now
    """
    if not torrents:
        return [], False

    # Group ALL torrents by episode range (including 4K)
    episode_groups: dict[str, list[dict]] = {}
    for t in torrents:
        ep_range = extract_episode_range(t.get("name", ""))
        if ep_range not in episode_groups:
            episode_groups[ep_range] = []
        episode_groups[ep_range].append(t)

    # Keep only the largest torrent per episode range
    filtered = []
    for ep_range, group in episode_groups.items():
        largest = max(group, key=lambda x: x.get("size_bytes", 0))
        filtered.append(largest)

    # Sort by size descending
    return sorted(filtered, key=lambda x: x.get("size_bytes", 0), reverse=True), False


def get_total_pages(soup: BeautifulSoup) -> int:
    """Get total number of pages from pagination"""
    # Look for "Page X of Y" pattern
    page_info = soup.find(string=re.compile(r"Page \d+ of \d+"))
    if page_info:
        match = re.search(r"Page \d+ of (\d+)", page_info)
        if match:
            return int(match.group(1))

    # Alternative: find last page link
    pagination_links = soup.find_all("a", href=re.compile(r"/page/\d+/"))
    if pagination_links:
        pages = []
        for link in pagination_links:
            match = re.search(r"/page/(\d+)/", link.get("href", ""))
            if match:
                pages.append(int(match.group(1)))
        if pages:
            return max(pages)

    return 1


def scrape_forum(max_pages: int = None, include_torrents: bool = True, highest_quality: bool = False, sort_by: str = "last_post") -> list[dict]:
    """
    Scrape the forum for all web series topics

    Args:
        max_pages: Maximum number of pages to scrape (None for all)
        include_torrents: Whether to also scrape torrent links from each topic
        highest_quality: If True, only keep the largest size torrent per episode range (includes 4K)
        sort_by: 'start_date' (newly created topics) or 'last_post' (recently updated topics)

    Returns:
        List of scraped items with title, url, and optionally torrents
    """
    logger.info("Starting scrape of 1TamilMV Web Series forum...")
    if highest_quality:
        logger.info("  Mode: Largest size only (includes 4K, no quality filtering)")
    logger.info(f"  Sort by: {sort_by}")

    forum_url = get_forum_url(sort_by)

    # Get first page to determine total pages
    soup = get_page(forum_url)
    if not soup:
        logger.error("Failed to fetch forum page")
        return []

    total_pages = get_total_pages(soup)
    pages_to_scrape = min(total_pages, max_pages) if max_pages else total_pages
    logger.info(f"Found {total_pages} pages, will scrape {pages_to_scrape}")

    all_items = []

    for page_num in range(1, pages_to_scrape + 1):
        if page_num == 1:
            page_url = forum_url
            page_soup = soup  # Reuse first page
        else:
            page_url = f"{BASE_URL}/index.php?/forums/forum/19-web-series-tv-shows/page/{page_num}/&sortby={sort_by}&sortdirection=desc"
            page_soup = get_page(page_url)
            if not page_soup:
                logger.warning(f"Failed to fetch page {page_num}, skipping...")
                continue

        logger.info(f"Scraping page {page_num}/{pages_to_scrape}...")
        topics = extract_topics_from_page(page_soup)
        logger.info(f"  Found {len(topics)} topics")

        for topic in topics:
            item = {
                "title": topic["title"],
                "url": topic["url"],
                "forum_date": topic.get("forum_date"),
                "scraped_at": datetime.now().isoformat()
            }

            if include_torrents:
                logger.info(f"  🔍 Fetching: {topic['title'][:60]}...")
                topic_soup = get_page(topic["url"])
                if topic_soup:
                    # Extract poster image
                    poster_url = extract_poster_from_topic(topic_soup)
                    if poster_url:
                        item["poster_url"] = poster_url

                    torrents = extract_torrents_from_topic(topic_soup)

                    if torrents:
                        # Filter for largest size per episode range if requested
                        if highest_quality:
                            torrents, _ = filter_highest_quality(torrents)

                        # Show torrent summary
                        for t in torrents[:3]:  # Show first 3 torrents
                            quality = get_torrent_quality(t['name'])
                            logger.info(f"    ✔ {quality:6s} | {t['size_human']:>10s} | {t['name'][:50]}...")
                        if len(torrents) > 3:
                            logger.info(f"    ... and {len(torrents) - 3} more torrent(s)")

                        item["torrents"] = torrents
                    else:
                        logger.info(f"    ✗ No torrents found, skipping")
                        time.sleep(0.5)
                        continue  # Skip topics without torrents
                else:
                    logger.info(f"    ✗ Failed to fetch page, skipping")
                    continue  # Skip if page couldn't be fetched
                time.sleep(0.5)  # Be nice to the server

            all_items.append(item)

        time.sleep(1)  # Rate limiting between pages

    return all_items


def save_to_json(data: list[dict], filename: str = "data/webseries.json"):
    """Save scraped data to JSON file"""
    import os
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved {len(data)} items to {filename}")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Scrape 1TamilMV Web Series forum")
    parser.add_argument("--pages", type=int, default=None, help="Max pages to scrape (default: all)")
    parser.add_argument("--no-torrents", action="store_true", help="Skip scraping individual topic pages for torrents")
    parser.add_argument("--all-torrents", "-a", action="store_true", help="Include all torrents instead of just the highest quality")
    parser.add_argument("--output", type=str, default="data/webseries.json", help="Output JSON file path")
    parser.add_argument("--no-db", action="store_true", help="Don't save to MySQL database (database is default)")
    parser.add_argument("--no-json", action="store_true", help="Don't save to JSON file")

    args = parser.parse_args()

    data = scrape_forum(
        max_pages=args.pages,
        include_torrents=not args.no_torrents,
        highest_quality=not args.all_torrents  # Highest quality is default
    )

    if data:
        # Save to database (default, unless --no-db is specified)
        if not args.no_db:
            from db import save_to_database
            save_to_database(data)

        # Save to JSON (unless --no-json is specified)
        if not args.no_json:
            save_to_json(data, args.output)

        logger.info(f"\nScraping complete! Total items: {len(data)}")
    else:
        logger.warning("No data scraped")


if __name__ == "__main__":
    main()
