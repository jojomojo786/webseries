#!/usr/bin/env python3
"""
Seasons AI Matcher - Create and fix season records using AI torrent name analysis

Similar to series_ai_matcher but for seasons table:
1. Finds torrents without season_id
2. Groups torrents by series
3. Uses AI to determine season numbers from torrent names
4. Creates missing season records
5. Links torrents to seasons
6. (Optional) Updates year, quality fields

Stores MINIMAL data in seasons table (series_id, season_number, year, quality)
"""

import os
import sys
import re
import json
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add all subdirectories to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir / "Episode Management"))
sys.path.insert(0, str(script_dir))

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db import get_connection
from logger import get_logger

logger = get_logger(__name__)

# Configuration
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')


def extract_season_basic(torrent_name: str) -> Optional[int]:
    """
    Extract season number using regex patterns (fast path)

    Args:
        torrent_name: Torrent file name

    Returns:
        Season number or None
    """
    patterns = [
        r'\b[Ss](\d+)\b',  # S01, S02
        r'\bSeason\s*(\d+)\b',  # Season 1, Season 2
        r'\bSeries\s*(\d+)\b',  # Series 1, Series 2
    ]

    for pattern in patterns:
        match = re.search(pattern, torrent_name)
        if match:
            return int(match.group(1))

    return None


def determine_seasons_with_ai(torrents: List[Dict], series_name: str) -> Dict[int, List[Dict]]:
    """
    Use AI to group torrents by season number

    Args:
        torrents: List of torrent dicts with 'id', 'name', 'series_id'
        series_name: Name of the series for context

    Returns:
        Dict mapping season_number -> list of torrents
    """
    if not torrents:
        return {}

    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY not set")
        return {}

    # First, try regex extraction for quick wins
    season_map = {}
    uncertain = []

    for torrent in torrents:
        season = extract_season_basic(torrent['name'])
        if season:
            if season not in season_map:
                season_map[season] = []
            season_map[season].append(torrent)
        else:
            uncertain.append(torrent)

    # If all torrents were matched by regex, return early
    if not uncertain:
        logger.info(f"All torrents matched via regex: {len(season_map)} season(s)")
        return season_map

    # Use AI for uncertain torrents
    logger.info(f"Using AI for {len(uncertain)} uncertain torrent(s)")

    # Build torrent list for AI
    torrent_list = "\n".join([
        f"{i+1}. ID:{t['id']} - {t['name'][:80]}"
        for i, t in enumerate(uncertain[:20])  # Limit to 20 for AI
    ])

    prompt = f"""You are analyzing torrent names for a TV series to determine which SEASON each torrent belongs to.

Series Name: {series_name}

Analyze these torrent names and determine the SEASON NUMBER for each:
{torrent_list}

For torrents that don't explicitly mention a season, use your knowledge:
- Check if episode numbers indicate the season (EP01-10 is usually Season 1)
- Look for year clues (2024 releases are newer seasons)
- Consider the series context

Return ONLY valid JSON like:
{{
  "1": [1, 2, 3],
  "2": [4, 5],
  "unknown": [6]
}}

Where keys are season numbers (as strings) and values are lists of torrent IDs from the list above.
Use "unknown" for torrents you cannot determine."""

    try:
        response = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {OPENROUTER_API_KEY}'
            },
            json={
                'model': 'openai/gpt-5-nano',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.1,
                'max_tokens': 1000
            },
            timeout=30
        )
        response.raise_for_status()
        result = response.json()

        content = result['choices'][0]['message']['content'].strip()

        # Extract JSON from response
        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            ai_results = json.loads(json_match.group())

            # Map torrent IDs to seasons
            torrent_by_id = {t['id']: t for t in uncertain}

            for season_str, torrent_ids in ai_results.items():
                if season_str == 'unknown':
                    continue

                try:
                    season_num = int(season_str)
                    if season_num not in season_map:
                        season_map[season_num] = []

                    for tid in torrent_ids:
                        if tid in torrent_by_id:
                            season_map[season_num].append(torrent_by_id[tid])
                            logger.debug(f"AI assigned torrent {tid} to season {season_num}")
                except (ValueError, TypeError):
                    continue

        return season_map

    except Exception as e:
        logger.error(f"AI season determination failed: {e}")
        # Return what we got from regex
        return season_map


def extract_year_from_name(torrent_name: str) -> Optional[int]:
    """Extract year from torrent name"""
    match = re.search(r'\b(20\d{2})\b', torrent_name)
    if match:
        return int(match.group(1))
    return None


def extract_quality_from_name(torrent_name: str) -> Optional[str]:
    """Extract quality from torrent name"""
    match = re.search(r'\b(\d{3,4}[ip])\b', torrent_name, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    # Check for common quality tags
    for q in ['4K', '2160p', '1080p', '720p', '480p']:
        if re.search(r'\b' + q + r'\b', torrent_name, re.IGNORECASE):
            return q.upper()

    return None


def get_best_quality_for_season(torrents: List[Dict]) -> Optional[str]:
    """
    Determine best quality from a list of torrents

    Priority: 4K > 1080p > 720p > 480p
    """
    quality_order = ['4K', '2160P', '1080P', '720P', '480P']

    qualities = []
    for t in torrents:
        q = extract_quality_from_name(t.get('name', ''))
        if q:
            qualities.append(q.upper())

    if not qualities:
        return None

    for priority_q in quality_order:
        if priority_q in qualities:
            return priority_q

    return qualities[0] if qualities else None


def get_year_for_season(torrents: List[Dict]) -> Optional[int]:
    """Get most common year from torrents for a season"""
    years = []
    for t in torrents:
        year = extract_year_from_name(t.get('name', ''))
        if year:
            years.append(year)

    if not years:
        return None

    # Return most common year
    from collections import Counter
    return Counter(years).most_common(1)[0][0]


def create_season_if_not_exists(series_id: int, season_number: int,
                                  year: Optional[int] = None,
                                  quality: Optional[str] = None) -> Optional[int]:
    """
    Create a season record if it doesn't exist

    Args:
        series_id: Series database ID
        season_number: Season number (1, 2, 3...)
        year: Optional year
        quality: Optional quality

    Returns:
        season_id or None
    """
    conn = get_connection()
    if not conn:
        return None

    cursor = conn.cursor(dictionary=True)

    try:
        # Check if season exists
        cursor.execute('''
            SELECT id FROM seasons
            WHERE series_id = %s AND season_number = %s
        ''', (series_id, season_number))

        existing = cursor.fetchone()
        if existing:
            logger.debug(f"Season {season_number} already exists for series {series_id}")
            return existing['id']

        # Insert new season
        insert_fields = {
            'series_id': series_id,
            'season_number': season_number
        }

        if year:
            insert_fields['year'] = year
        if quality:
            insert_fields['quality'] = quality

        columns = ', '.join(insert_fields.keys())
        placeholders = ', '.join(['%s'] * len(insert_fields))
        values = list(insert_fields.values())

        cursor.execute(f'''
            INSERT INTO seasons ({columns})
            VALUES ({placeholders})
        ''', values)

        conn.commit()
        season_id = cursor.lastrowid
        logger.info(f"✓ Created season {season_number} for series {series_id} (ID: {season_id})")
        return season_id

    except Exception as e:
        logger.error(f"Error creating season: {e}")
        conn.rollback()
        return None

    finally:
        cursor.close()
        conn.close()


def link_torrents_to_season(season_id: int, torrent_ids: List[int]) -> int:
    """
    Link torrents to a season

    Args:
        season_id: Season database ID
        torrent_ids: List of torrent IDs to link

    Returns:
        Number of torrents linked
    """
    if not torrent_ids:
        return 0

    conn = get_connection()
    if not conn:
        return 0

    cursor = conn.cursor()

    try:
        # Update torrents with season_id
        placeholders = ', '.join(['%s'] * len(torrent_ids))
        cursor.execute(f'''
            UPDATE torrents
            SET season_id = %s
            WHERE id IN ({placeholders})
        ''', [season_id] + torrent_ids)

        conn.commit()
        updated = cursor.rowcount
        logger.info(f"✓ Linked {updated} torrent(s) to season {season_id}")
        return updated

    except Exception as e:
        logger.error(f"Error linking torrents: {e}")
        conn.rollback()
        return 0

    finally:
        cursor.close()
        conn.close()


def match_seasons_for_series(series_id: int, dry_run: bool = False) -> Dict:
    """
    Find and create seasons for a specific series

    Args:
        series_id: Series database ID
        dry_run: If True, don't make changes

    Returns:
        Dict with results
    """
    conn = get_connection()
    if not conn:
        return {'error': 'Could not connect to database'}

    cursor = conn.cursor(dictionary=True)

    try:
        # Get series info
        cursor.execute('''
            SELECT id, title, name
            FROM series
            WHERE id = %s
        ''', (series_id,))

        series = cursor.fetchone()
        if not series:
            return {'error': f'Series {series_id} not found'}

        series_name = series.get('name') or series.get('title', 'Unknown')

        # Find torrents without season_id for this series
        cursor.execute('''
            SELECT id, name, series_id
            FROM torrents
            WHERE series_id = %s AND season_id IS NULL
            ORDER BY id
        ''', (series_id,))

        torrents = cursor.fetchall()

        if not torrents:
            logger.info(f"No torrents without season_id for series {series_id}")
            return {
                'series_id': series_id,
                'series_name': series_name,
                'torrents_found': 0,
                'seasons_created': 0,
                'torrents_linked': 0
            }

        logger.info(f"Found {len(torrents)} torrent(s) without season for '{series_name}'")

        # Use AI to group by season
        season_map = determine_seasons_with_ai(torrents, series_name)

        if not season_map:
            return {
                'series_id': series_id,
                'series_name': series_name,
                'torrents_found': len(torrents),
                'seasons_created': 0,
                'torrents_linked': 0,
                'error': 'Could not determine seasons'
            }

        # Process each season
        results = {
            'series_id': series_id,
            'series_name': series_name,
            'torrents_found': len(torrents),
            'seasons_created': 0,
            'torrents_linked': 0,
            'seasons': []
        }

        for season_num, season_torrents in sorted(season_map.items()):
            if not season_torrents:
                continue

            torrent_ids = [t['id'] for t in season_torrents]
            year = get_year_for_season(season_torrents)
            quality = get_best_quality_for_season(season_torrents)

            print(f"\n  Season {season_num}:")
            print(f"    Torrents: {len(season_torrents)}")
            if year:
                print(f"    Year: {year}")
            if quality:
                print(f"    Quality: {quality}")

            if dry_run:
                print(f"    [DRY RUN] Would create season and link {len(torrent_ids)} torrents")
                results['seasons'].append({
                    'season_number': season_num,
                    'torrent_count': len(torrent_ids),
                    'year': year,
                    'quality': quality
                })
                results['seasons_created'] += 1
                results['torrents_linked'] += len(torrent_ids)
            else:
                # Create season
                season_id = create_season_if_not_exists(
                    series_id, season_num, year, quality
                )

                if season_id:
                    # Link torrents
                    linked = link_torrents_to_season(season_id, torrent_ids)
                    results['seasons_created'] += 1
                    results['torrents_linked'] += linked
                    results['seasons'].append({
                        'season_id': season_id,
                        'season_number': season_num,
                        'torrent_count': linked,
                        'year': year,
                        'quality': quality
                    })

        return results

    except Exception as e:
        logger.error(f"Error matching seasons for series {series_id}: {e}")
        return {'error': str(e)}

    finally:
        cursor.close()
        conn.close()


def match_all_seasons_with_ai(dry_run: bool = False) -> Dict:
    """
    Find and create seasons for all series with orphaned torrents

    Args:
        dry_run: If True, don't make changes

    Returns:
        Dict with results
    """
    conn = get_connection()
    if not conn:
        return {'error': 'Could not connect to database'}

    cursor = conn.cursor(dictionary=True)

    try:
        # Find series with torrents without season_id
        cursor.execute('''
            SELECT DISTINCT s.id, s.title, s.name,
                   COUNT(t.id) as orphan_count
            FROM series s
            JOIN torrents t ON s.id = t.series_id
            WHERE t.season_id IS NULL
            GROUP BY s.id
            ORDER BY s.id
        ''')

        series_list = cursor.fetchall()

        if not series_list:
            logger.info("No series found with torrents without season_id")
            return {
                'total': 0,
                'processed': 0,
                'seasons_created': 0,
                'torrents_linked': 0
            }

        logger.info(f"Found {len(series_list)} series with orphaned torrents")

        results = {
            'total': len(series_list),
            'processed': 0,
            'seasons_created': 0,
            'torrents_linked': 0,
            'series': []
        }

        for idx, series in enumerate(series_list, 1):
            series_id = series['id']
            series_name = series.get('name') or series.get('title', 'Unknown')
            orphan_count = series['orphan_count']

            print(f"\n{'='*80}")
            print(f"{idx}/{len(series_list)}: {series_name} ({orphan_count} orphaned torrents)")
            print(f"{'='*80}")

            result = match_seasons_for_series(series_id, dry_run)

            if 'error' not in result:
                results['processed'] += 1
                results['seasons_created'] += result.get('seasons_created', 0)
                results['torrents_linked'] += result.get('torrents_linked', 0)
                results['series'].append(result)

        return results

    except Exception as e:
        logger.error(f"Error in match_all_seasons_with_ai: {e}")
        return {'error': str(e)}

    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Match seasons using AI torrent analysis')
    parser.add_argument('--series-id', type=int, help='Process specific series ID')
    parser.add_argument('--all', action='store_true', help='Process all series with orphaned torrents')
    parser.add_argument('--dry-run', action='store_true', help='Dry run - no changes')

    args = parser.parse_args()

    if args.series_id:
        result = match_seasons_for_series(args.series_id, args.dry_run)
        if 'error' not in result:
            print(f"\n{'='*80}")
            print("RESULTS")
            print(f"{'='*80}")
            print(f"Seasons created: {result.get('seasons_created', 0)}")
            print(f"Torrents linked: {result.get('torrents_linked', 0)}")
    elif args.all:
        results = match_all_seasons_with_ai(args.dry_run)
        if 'error' not in results:
            print(f"\n{'='*80}")
            print("SUMMARY")
            print(f"{'='*80}")
            print(f"Series processed: {results.get('processed', 0)}/{results.get('total', 0)}")
            print(f"Seasons created: {results.get('seasons_created', 0)}")
            print(f"Torrents linked: {results.get('torrents_linked', 0)}")
    else:
        parser.print_help()
