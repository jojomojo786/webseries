#!/usr/bin/env python3
"""
1TamilMV Web Series Scraper
Scrapes titles and torrent/magnet links from the forum
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import time
from datetime import datetime
from urllib.parse import urljoin

BASE_URL = "https://www.1tamilmv.rsvp"
FORUM_URL = f"{BASE_URL}/index.php?/forums/forum/19-web-series-tv-shows/&sortby=start_date&sortdirection=desc"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


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
            print(f"Error fetching {url}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def extract_topics_from_page(soup: BeautifulSoup) -> list[dict]:
    """Extract topic titles and URLs from a forum page"""
    topics = []
    seen_urls = set()

    # Patterns to skip in titles (pagination, navigation links)
    skip_title_patterns = [
        r"^go to page",
        r"^\d+$",
        r"^page \d+",
        r"^next$",
        r"^prev$",
        r"^first$",
        r"^last$",
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
            topics.append({
                "title": title,
                "url": full_url
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

    # Find .torrent file links
    for link in soup.find_all("a", href=re.compile(r"\.torrent")):
        torrent_url = link.get("href")
        if torrent_url:
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


def get_torrent_quality(name: str) -> str:
    """Extract quality from torrent name"""
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
    return "unknown"


def filter_highest_quality(torrents: list[dict]) -> tuple[list[dict], bool]:
    """
    Filter torrents to keep best quality (1080p preferred, exclude 4K).
    Keeps ALL torrents of the best available quality (for series with multiple episode batches).

    Returns:
        tuple: (filtered_torrents, is_4k_only) - is_4k_only is True if only 4K was available
    """
    if not torrents:
        return [], False

    # First, filter out 4K torrents
    non_4k_torrents = [t for t in torrents if not is_4k_torrent(t.get("name", ""))]

    # If all torrents are 4K, return empty and flag it
    if not non_4k_torrents:
        # Return the 4K links for display but flag as 4K-only
        sorted_4k = sorted(torrents, key=lambda x: x.get("size_bytes", 0), reverse=True)
        return sorted_4k, True

    # Group torrents by quality
    quality_priority = ["1080p", "720p", "480p", "360p", "unknown"]

    # Find the best available quality
    for quality in quality_priority:
        quality_torrents = [t for t in non_4k_torrents if get_torrent_quality(t.get("name", "")) == quality]
        if quality_torrents:
            # Return ALL torrents of this quality (for multiple episode batches)
            return sorted(quality_torrents, key=lambda x: x.get("size_bytes", 0), reverse=True), False

    # Fallback: return all non-4K torrents sorted by size
    return sorted(non_4k_torrents, key=lambda x: x.get("size_bytes", 0), reverse=True), False


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


def scrape_forum(max_pages: int = None, include_torrents: bool = True, highest_quality: bool = False) -> list[dict]:
    """
    Scrape the forum for all web series topics

    Args:
        max_pages: Maximum number of pages to scrape (None for all)
        include_torrents: Whether to also scrape torrent links from each topic
        highest_quality: If True, only keep the largest (highest quality) torrent per topic

    Returns:
        List of scraped items with title, url, and optionally torrents
    """
    print(f"Starting scrape of 1TamilMV Web Series forum...")
    if highest_quality:
        print("  Mode: Best quality (1080p preferred, 4K excluded)")

    # Get first page to determine total pages
    soup = get_page(FORUM_URL)
    if not soup:
        print("Failed to fetch forum page")
        return []

    total_pages = get_total_pages(soup)
    pages_to_scrape = min(total_pages, max_pages) if max_pages else total_pages
    print(f"Found {total_pages} pages, will scrape {pages_to_scrape}")

    all_items = []

    for page_num in range(1, pages_to_scrape + 1):
        if page_num == 1:
            page_url = FORUM_URL
            page_soup = soup  # Reuse first page
        else:
            page_url = f"{BASE_URL}/index.php?/forums/forum/19-web-series-tv-shows/page/{page_num}/&sortby=start_date&sortdirection=desc"
            page_soup = get_page(page_url)
            if not page_soup:
                print(f"Failed to fetch page {page_num}, skipping...")
                continue

        print(f"Scraping page {page_num}/{pages_to_scrape}...")
        topics = extract_topics_from_page(page_soup)
        print(f"  Found {len(topics)} topics")

        for topic in topics:
            item = {
                "title": topic["title"],
                "url": topic["url"],
                "scraped_at": datetime.now().isoformat()
            }

            if include_torrents:
                print(f"  Fetching torrents for: {topic['title'][:50]}...")
                topic_soup = get_page(topic["url"])
                if topic_soup:
                    torrents = extract_torrents_from_topic(topic_soup)

                    # Filter for highest quality if requested
                    if highest_quality and torrents:
                        torrents, is_4k_only = filter_highest_quality(torrents)
                        if torrents:
                            quality = get_torrent_quality(torrents[0]['name'])
                            if is_4k_only:
                                print(f"    ⚠️  4K ONLY: {torrents[0]['size_human']} - {torrents[0]['name'][:50]}...")
                                torrents = []  # Don't include 4K-only entries
                            else:
                                print(f"    {len(torrents)}x {quality} torrents (largest: {torrents[0]['size_human']})")
                    else:
                        print(f"    Found {len(torrents)} torrent links")

                    item["torrents"] = torrents
                else:
                    item["torrents"] = []
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

    print(f"Saved {len(data)} items to {filename}")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Scrape 1TamilMV Web Series forum")
    parser.add_argument("--pages", type=int, default=None, help="Max pages to scrape (default: all)")
    parser.add_argument("--no-torrents", action="store_true", help="Skip scraping individual topic pages for torrents")
    parser.add_argument("--all-torrents", "-a", action="store_true", help="Include all torrents instead of just the highest quality")
    parser.add_argument("--output", type=str, default="data/webseries.json", help="Output JSON file path")

    args = parser.parse_args()

    data = scrape_forum(
        max_pages=args.pages,
        include_torrents=not args.no_torrents,
        highest_quality=not args.all_torrents  # Highest quality is default
    )

    if data:
        save_to_json(data, args.output)
        print(f"\nScraping complete! Total items: {len(data)}")
    else:
        print("No data scraped")


if __name__ == "__main__":
    main()
