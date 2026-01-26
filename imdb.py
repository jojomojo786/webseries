#!/usr/bin/env python3
"""
IMDB Metadata Fetcher for Web Series

Fetches metadata from IMDB/TMDB APIs and updates the series table.
Inspired by fetcher/fill_imdb.php

Usage:
    python imdb.py                  # Process series without metadata
    python imdb.py --dry-run        # Show what would be done without changes
    python imdb.py --id 123         # Process specific series by DB ID
    python imdb.py --limit 10       # Process up to 10 series
"""

import os
import re
import argparse
import requests
from urllib.parse import quote
from datetime import datetime

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db import get_connection

# Setup basic logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# API Configuration
RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY', '')
RAPIDAPI_HOST = 'imdb236.p.rapidapi.com'
TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '')

# API Headers
RAPIDAPI_HEADERS = {
    'x-rapidapi-host': RAPIDAPI_HOST,
    'x-rapidapi-key': RAPIDAPI_KEY
}

# Cache for country code to name mapping
_country_cache = None


def fetch_country_mapping() -> dict:
    """
    Fetch country code to name mapping from IMDB API

    Returns: dict mapping ISO codes to country names
    """
    global _country_cache

    if _country_cache is not None:
        return _country_cache

    if not RAPIDAPI_KEY:
        return {}

    try:
        url = f"https://{RAPIDAPI_HOST}/api/imdb/countries"
        response = requests.get(url, headers=RAPIDAPI_HEADERS, timeout=30)
        response.raise_for_status()

        data = response.json()

        _country_cache = {}
        if isinstance(data, list):
            for country in data:
                if 'iso_3166_1' in country and 'name' in country:
                    _country_cache[country['iso_3166_1']] = country['name']

        logger.info(f"Loaded {len(_country_cache)} country mappings")
        return _country_cache

    except requests.RequestException as e:
        logger.error(f"Failed to fetch country mapping: {e}")
        _country_cache = {}
        return _country_cache


def get_country_name(country_code: str) -> str:
    """Convert country code to full name"""
    mapping = fetch_country_mapping()
    return mapping.get(country_code, country_code)


def search_imdb_by_title(title: str, year: int = None) -> dict | None:
    """
    Search IMDB for a series by title

    Returns: dict with id, title, year or None
    """
    if not RAPIDAPI_KEY:
        logger.error("RAPIDAPI_KEY not set")
        return None

    # Clean title for search - remove quality tags, season info, etc.
    clean_title = re.sub(r'\s*\(?\d{4}\)?.*$', '', title)  # Remove year and everything after
    clean_title = re.sub(r'\s*S\d+.*$', '', clean_title, flags=re.IGNORECASE)  # Remove S01, etc.
    clean_title = re.sub(r'\s*-\s*\[.*$', '', clean_title)  # Remove quality tags
    clean_title = clean_title.strip()

    logger.info(f"Searching IMDB for: '{clean_title}'")

    try:
        url = f"https://{RAPIDAPI_HOST}/api/imdb/autocomplete"
        params = {'query': clean_title}

        response = requests.get(url, headers=RAPIDAPI_HEADERS, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data or not isinstance(data, list):
            logger.warning(f"No results for '{clean_title}'")
            return None

        # Filter for TV series
        for item in data:
            item_type = item.get('type', '').lower()
            if item_type in ['tvseries', 'tvminiseries', 'tvmovie']:
                logger.info(f"Found: {item.get('primaryTitle')} ({item.get('startYear')}) - {item.get('id')}")
                return {
                    'imdb_id': item.get('id'),
                    'title': item.get('primaryTitle'),
                    'year': item.get('startYear')
                }

        # If no TV series found, return first result
        if data:
            item = data[0]
            logger.info(f"Found (first result): {item.get('primaryTitle')} ({item.get('startYear')}) - {item.get('id')}")
            return {
                'imdb_id': item.get('id'),
                'title': item.get('primaryTitle'),
                'year': item.get('startYear')
            }

        return None

    except requests.RequestException as e:
        logger.error(f"IMDB search error: {e}")
        return None


def fetch_imdb_details(imdb_id: str) -> dict | None:
    """
    Fetch detailed metadata from IMDB API

    Returns: dict with all metadata or None
    """
    if not RAPIDAPI_KEY:
        logger.error("RAPIDAPI_KEY not set")
        return None

    logger.info(f"Fetching IMDB details for: {imdb_id}")

    try:
        url = f"https://{RAPIDAPI_HOST}/api/imdb/{imdb_id}"
        response = requests.get(url, headers=RAPIDAPI_HEADERS, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data or 'id' not in data:
            logger.error(f"Invalid response for {imdb_id}")
            return None

        return data

    except requests.RequestException as e:
        logger.error(f"IMDB fetch error: {e}")
        return None


def fetch_tmdb_by_imdb(imdb_id: str) -> dict | None:
    """
    Fetch TMDB data using IMDB ID (for images and additional data)

    Returns: dict with tmdb_id, poster, backdrop or None
    """
    if not TMDB_API_KEY:
        logger.warning("TMDB_API_KEY not set, skipping TMDB lookup")
        return None

    try:
        url = f"https://api.themoviedb.org/3/find/{imdb_id}"
        params = {
            'api_key': TMDB_API_KEY,
            'external_source': 'imdb_id'
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        # Check TV results first, then movie results
        results = data.get('tv_results', []) or data.get('movie_results', [])

        if results:
            item = results[0]
            tmdb_data = {
                'tmdb_id': item.get('id'),
                'overview': item.get('overview'),
                'vote_average': item.get('vote_average'),
                'original_language': item.get('original_language'),
            }

            if item.get('poster_path'):
                tmdb_data['poster_url'] = f"https://image.tmdb.org/t/p/original{item['poster_path']}"

            if item.get('backdrop_path'):
                tmdb_data['backdrop_url'] = f"https://image.tmdb.org/t/p/original{item['backdrop_path']}"

            logger.info(f"Found TMDB data: ID={tmdb_data['tmdb_id']}")
            return tmdb_data

        return None

    except requests.RequestException as e:
        logger.error(f"TMDB fetch error: {e}")
        return None


def fetch_tmdb_details(tmdb_id: int, media_type: str = 'tv') -> dict | None:
    """
    Fetch full TMDB TV series details

    Returns: dict with status, networks, dates, etc.
    """
    if not TMDB_API_KEY or not tmdb_id:
        return None

    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
        params = {'api_key': TMDB_API_KEY}

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        result = {
            'status': data.get('status'),
            'tagline': data.get('tagline'),
            'first_air_date': data.get('first_air_date'),
            'last_air_date': data.get('last_air_date'),
            'in_production': data.get('in_production', False),
            'episode_runtime': data.get('episode_run_time', [None])[0] if data.get('episode_run_time') else None,
            'vote_count': data.get('vote_count'),
        }

        # Networks
        networks = data.get('networks', [])
        if networks:
            result['networks'] = ', '.join([n.get('name', '') for n in networks if n.get('name')])

        # Creators
        created_by = data.get('created_by', [])
        if created_by:
            result['created_by'] = ', '.join([c.get('name', '') for c in created_by if c.get('name')])

        # Production companies
        companies = data.get('production_companies', [])
        if companies:
            result['production_companies'] = ', '.join([c.get('name', '') for c in companies if c.get('name')])

        # Origin country (get full names)
        origin_countries = data.get('origin_country', [])
        if origin_countries:
            country_names = [get_country_name(code) for code in origin_countries]
            result['origin_country'] = ', '.join(country_names)

        return result

    except requests.RequestException as e:
        logger.error(f"TMDB details error: {e}")
        return None


def fetch_tmdb_videos(tmdb_id: int, media_type: str = 'tv') -> str | None:
    """
    Fetch trailer key from TMDB

    Returns: YouTube video key or None
    """
    if not TMDB_API_KEY or not tmdb_id:
        return None

    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/videos"
        params = {'api_key': TMDB_API_KEY}

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        results = data.get('results', [])

        # Find official trailer first
        for video in results:
            if video.get('type') == 'Trailer' and video.get('official'):
                return video.get('key')

        # Fallback to any trailer
        for video in results:
            if video.get('type') == 'Trailer':
                return video.get('key')

        return None

    except requests.RequestException as e:
        logger.error(f"TMDB videos error: {e}")
        return None


def extract_year_from_title(title: str) -> int | None:
    """Extract year from series title"""
    match = re.search(r'\((\d{4})\)', title)
    if match:
        return int(match.group(1))
    match = re.search(r'\b(20\d{2})\b', title)
    if match:
        return int(match.group(1))
    return None


def parse_imdb_data(imdb_data: dict, tmdb_data: dict = None, tmdb_details: dict = None) -> dict:
    """
    Parse IMDB and TMDB data into our series table format

    Returns: dict ready for database update
    """
    result = {
        'imdb_id': imdb_data.get('id'),
        'name': imdb_data.get('primaryTitle'),
        'original_title': imdb_data.get('originalTitle'),
        'year': imdb_data.get('startYear'),
        'end_year': imdb_data.get('endYear'),
        'summary': imdb_data.get('description'),
        'rating': imdb_data.get('averageRating'),
        'vote_count': imdb_data.get('numVotes'),
        'content_rating': imdb_data.get('contentRating'),
        'is_adult': 1 if imdb_data.get('isAdult') else 0,
    }

    # Genres
    genres = imdb_data.get('genres', [])
    if isinstance(genres, list):
        result['genres'] = ', '.join(genres)
    elif isinstance(genres, str):
        result['genres'] = genres

    # Keywords/interests
    interests = imdb_data.get('interests', [])
    if isinstance(interests, list):
        result['keywords'] = ', '.join(interests)

    # Language detection
    spoken_langs = imdb_data.get('spokenLanguages', [])
    if 'ta' in spoken_langs or 'Tamil' in spoken_langs:
        if len(spoken_langs) == 1:
            result['language'] = 'Tamil'
        else:
            result['language'] = 'Tamil'  # Tamil is present
    elif imdb_data.get('originalLanguage') == 'ta':
        result['language'] = 'Tamil'
    else:
        result['language'] = 'Tamil Dubbed'  # Default for this scraper

    # Origin country from IMDB (convert codes to names)
    countries = imdb_data.get('countriesOfOrigin', [])
    if countries:
        country_names = [get_country_name(code) for code in countries]
        result['origin_country'] = ', '.join(country_names)

    # Directors
    directors = imdb_data.get('directors', [])
    if directors:
        director_names = [d.get('fullName', '') for d in directors if d.get('fullName')]
        if director_names:
            result['directors'] = ', '.join(director_names)

    # Writers
    writers = imdb_data.get('writers', [])
    if writers:
        writer_names = [w.get('fullName', '') for w in writers if w.get('fullName')]
        if writer_names:
            result['writers'] = ', '.join(writer_names)

    # Cast (filter for actors only, limit to top 10)
    cast = imdb_data.get('cast', [])
    if cast:
        valid_jobs = ['actor', 'actress', 'voice', 'voice actor', 'voice actress']
        actor_names = []
        for c in cast:
            job = c.get('job', '').lower()
            if job in valid_jobs and c.get('fullName'):
                actor_names.append(c['fullName'])
            if len(actor_names) >= 10:
                break
        if actor_names:
            result['cast'] = ', '.join(actor_names)

    # Production companies from IMDB
    companies = imdb_data.get('productionCompanies', [])
    if companies:
        company_names = [c.get('name', '') for c in companies if c.get('name')]
        if company_names:
            result['production_companies'] = ', '.join(company_names)

    # Release date
    if imdb_data.get('releaseDate'):
        result['first_air_date'] = imdb_data['releaseDate']

    # Trailer from IMDB
    if imdb_data.get('trailer'):
        trailer_url = imdb_data['trailer']
        # Extract YouTube video ID
        match = re.search(r'[?&]v=([^&]+)', trailer_url)
        if match:
            result['trailer_key'] = match.group(1)
        else:
            match = re.search(r'youtu\.be/([^?]+)', trailer_url)
            if match:
                result['trailer_key'] = match.group(1)

    # Merge TMDB basic data
    if tmdb_data:
        if tmdb_data.get('tmdb_id'):
            result['tmdb_id'] = tmdb_data['tmdb_id']

        if tmdb_data.get('poster_url') and not result.get('poster_url'):
            result['poster_url'] = tmdb_data['poster_url']

        if tmdb_data.get('backdrop_url'):
            result['backdrop_url'] = tmdb_data['backdrop_url']

        if not result.get('summary') and tmdb_data.get('overview'):
            result['summary'] = tmdb_data['overview']

        if not result.get('rating') and tmdb_data.get('vote_average'):
            result['rating'] = tmdb_data['vote_average']

    # Merge TMDB detailed data
    if tmdb_details:
        if tmdb_details.get('status'):
            result['status'] = tmdb_details['status']

        if tmdb_details.get('tagline'):
            result['tagline'] = tmdb_details['tagline']

        if tmdb_details.get('first_air_date') and not result.get('first_air_date'):
            result['first_air_date'] = tmdb_details['first_air_date']

        if tmdb_details.get('last_air_date'):
            result['last_air_date'] = tmdb_details['last_air_date']

        if tmdb_details.get('networks'):
            result['networks'] = tmdb_details['networks']

        if tmdb_details.get('created_by'):
            result['created_by'] = tmdb_details['created_by']

        if tmdb_details.get('episode_runtime'):
            result['episode_runtime'] = tmdb_details['episode_runtime']

        if tmdb_details.get('in_production') is not None:
            result['in_production'] = 1 if tmdb_details['in_production'] else 0

        if tmdb_details.get('vote_count') and not result.get('vote_count'):
            result['vote_count'] = tmdb_details['vote_count']

        if tmdb_details.get('production_companies') and not result.get('production_companies'):
            result['production_companies'] = tmdb_details['production_companies']

        if tmdb_details.get('origin_country') and not result.get('origin_country'):
            result['origin_country'] = tmdb_details['origin_country']

    return result


def update_series_metadata(series_id: int, metadata: dict, dry_run: bool = False) -> bool:
    """
    Update series table with metadata

    Returns: True on success
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would update series {series_id}:")
        for key, value in metadata.items():
            if value is not None:
                display_val = str(value)[:50] + '...' if len(str(value)) > 50 else value
                logger.info(f"  {key}: {display_val}")
        return True

    conn = get_connection()
    if not conn:
        return False

    cursor = conn.cursor()

    try:
        # Build dynamic UPDATE query
        fields = []
        values = []

        for field in [
            'imdb_id', 'tmdb_id', 'name', 'original_title', 'year', 'end_year',
            'summary', 'tagline', 'genres', 'keywords', 'language', 'rating',
            'vote_count', 'episode_runtime', 'content_rating', 'origin_country',
            'status', 'first_air_date', 'last_air_date', 'networks',
            'production_companies', 'is_adult', 'in_production',
            'trailer_key', 'poster_url', 'backdrop_url',
            'cast', 'directors', 'writers', 'created_by'
        ]:
            if field in metadata and metadata[field] is not None:
                fields.append(f"{field} = %s")
                values.append(metadata[field])

        if not fields:
            logger.warning(f"No metadata to update for series {series_id}")
            return False

        # Add updated_at
        fields.append("updated_at = %s")
        values.append(datetime.now())

        # Add series_id for WHERE clause
        values.append(series_id)

        sql = f"UPDATE series SET {', '.join(fields)} WHERE id = %s"
        cursor.execute(sql, values)
        conn.commit()

        logger.info(f"Updated series {series_id} with {len(fields)-1} fields")
        return True

    except Exception as e:
        logger.error(f"Database error updating series {series_id}: {e}")
        conn.rollback()
        return False

    finally:
        cursor.close()
        conn.close()


def process_series(series_id: int = None, limit: int = 10, dry_run: bool = False) -> int:
    """
    Process series to fetch and update metadata

    Args:
        series_id: Specific series ID to process (or None for batch)
        limit: Max number of series to process
        dry_run: If True, don't make any changes

    Returns: Number of series processed
    """
    conn = get_connection()
    if not conn:
        return 0

    cursor = conn.cursor(dictionary=True)

    try:
        if series_id:
            # Process specific series
            cursor.execute('SELECT id, title, imdb_id FROM series WHERE id = %s', (series_id,))
        else:
            # Find series without metadata (no name or no imdb_id)
            cursor.execute('''
                SELECT id, title, imdb_id
                FROM series
                WHERE (name IS NULL OR name = '' OR imdb_id IS NULL OR imdb_id = '')
                ORDER BY id DESC
                LIMIT %s
            ''', (limit,))

        series_list = cursor.fetchall()

        if not series_list:
            logger.info("No series found that need metadata")
            return 0

        logger.info(f"Found {len(series_list)} series to process")

        processed = 0

        for series in series_list:
            sid = series['id']
            title = series['title']
            imdb_id = series.get('imdb_id')

            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {title[:60]}...")
            logger.info(f"Series ID: {sid}, IMDB ID: {imdb_id or 'None'}")

            # Step 1: Get IMDB ID if not present
            if not imdb_id or not imdb_id.startswith('tt'):
                year = extract_year_from_title(title)
                search_result = search_imdb_by_title(title, year)

                if search_result:
                    imdb_id = search_result['imdb_id']
                    logger.info(f"Found IMDB ID: {imdb_id}")
                else:
                    logger.warning(f"Could not find IMDB ID for: {title}")
                    continue

            # Step 2: Fetch IMDB details
            imdb_data = fetch_imdb_details(imdb_id)
            if not imdb_data:
                logger.warning(f"Could not fetch IMDB data for: {imdb_id}")
                continue

            # Step 3: Fetch TMDB data (for images)
            tmdb_data = fetch_tmdb_by_imdb(imdb_id)

            # Step 4: Fetch TMDB details (for status, networks, etc.)
            tmdb_details = None
            if tmdb_data and tmdb_data.get('tmdb_id'):
                tmdb_details = fetch_tmdb_details(tmdb_data['tmdb_id'], 'tv')

                # Step 5: Get trailer
                trailer_key = fetch_tmdb_videos(tmdb_data['tmdb_id'], 'tv')
                if trailer_key:
                    tmdb_data['trailer_key'] = trailer_key

            # Step 6: Parse and combine data
            metadata = parse_imdb_data(imdb_data, tmdb_data, tmdb_details)

            # Step 7: Update database
            if update_series_metadata(sid, metadata, dry_run):
                processed += 1

        return processed

    finally:
        cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Fetch IMDB metadata for web series')
    parser.add_argument('--dry-run', '-d', action='store_true', help='Show what would be done without changes')
    parser.add_argument('--id', type=int, help='Process specific series by database ID')
    parser.add_argument('--limit', type=int, default=10, help='Max series to process (default: 10)')

    args = parser.parse_args()

    if args.dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN MODE - No changes will be made")
        logger.info("=" * 60)

    # Check API keys
    if not RAPIDAPI_KEY:
        logger.error("RAPIDAPI_KEY environment variable not set")
        logger.error("Set it with: export RAPIDAPI_KEY='your-key-here'")
        return

    if not TMDB_API_KEY:
        logger.warning("TMDB_API_KEY not set - images may not be fetched")

    processed = process_series(
        series_id=args.id,
        limit=args.limit,
        dry_run=args.dry_run
    )

    logger.info(f"\n{'='*60}")
    logger.info(f"Processed {processed} series")
    if args.dry_run:
        logger.info("DRY RUN - No changes were made")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
