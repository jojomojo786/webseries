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
            return BeautifulSoup(response.text, "lxml")
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def extract_topics_from_page(soup: BeautifulSoup) -> list[dict]:
    """Extract topic titles and URLs from a forum page"""
    topics = []

    # Find all topic links - they're in h4 tags with links to /forums/topic/
    for link in soup.find_all("a", href=re.compile(r"/forums/topic/")):
        title = link.get("title") or link.get_text(strip=True)
        if not title or len(title) < 10:
            continue

        href = link.get("href")
        if href:
            full_url = urljoin(BASE_URL, href)
            # Clean the title
            title = re.sub(r'\s+', ' ', title).strip()

            # Avoid duplicates
            if not any(t["url"] == full_url for t in topics):
                topics.append({
                    "title": title,
                    "url": full_url
                })

    return topics


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
            torrents.append({
                "type": "magnet",
                "name": requests.utils.unquote(name),
                "link": magnet
            })

    # Find .torrent file links
    for link in soup.find_all("a", href=re.compile(r"\.torrent")):
        torrent_url = link.get("href")
        if torrent_url:
            name = link.get_text(strip=True) or torrent_url.split("/")[-1]
            torrents.append({
                "type": "torrent",
                "name": name,
                "link": urljoin(BASE_URL, torrent_url)
            })

    return torrents


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


def scrape_forum(max_pages: int = None, include_torrents: bool = True) -> list[dict]:
    """
    Scrape the forum for all web series topics

    Args:
        max_pages: Maximum number of pages to scrape (None for all)
        include_torrents: Whether to also scrape torrent links from each topic

    Returns:
        List of scraped items with title, url, and optionally torrents
    """
    print(f"Starting scrape of 1TamilMV Web Series forum...")

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
                    item["torrents"] = torrents
                    print(f"    Found {len(torrents)} torrent links")
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
    parser.add_argument("--output", type=str, default="data/webseries.json", help="Output JSON file path")

    args = parser.parse_args()

    data = scrape_forum(
        max_pages=args.pages,
        include_torrents=not args.no_torrents
    )

    if data:
        save_to_json(data, args.output)
        print(f"\nScraping complete! Total items: {len(data)}")
    else:
        print("No data scraped")


if __name__ == "__main__":
    main()
