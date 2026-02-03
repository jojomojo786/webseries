#!/usr/bin/env python3
"""
Series AI Matcher - Find TMDB IDs for series using AI vision poster analysis

Similar workflow to renaming.php but for TV series:
1. Download poster from poster_url
2. Analyze poster with AI vision to extract context
3. Search TMDB with poster context for accurate matching
4. Update series table with tmdb_id and metadata
"""

import os
import sys
import re
import json
import time
import hashlib
import base64
import requests
from pathlib import Path

# Add all subdirectories to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir / "Episode Management"))
sys.path.insert(0, str(script_dir))
from typing import Optional, Dict, Any

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_connection
from logger import get_logger

# Import IMDB metadata fetching functions
from imdb import (
    fetch_imdb_details,
    fetch_tmdb_by_imdb,
    fetch_tmdb_details,
    fetch_tmdb_videos,
    parse_imdb_data,
    update_series_metadata,
    search_imdb_by_title
)

# Import image downloader
from image_downloader import download_series_images, update_series_image_paths

logger = get_logger(__name__)

# Configuration
TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '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')

# Poster cache directory
POSTER_CACHE_DIR = '/tmp/series_ai_posters'
Path(POSTER_CACHE_DIR).mkdir(parents=True, exist_ok=True)


def find_ids_with_gpt52(poster_path: str, series_name: str) -> Optional[Dict]:
    """
    Fallback: Use GPT-5.2 to directly find TMDB/IMDb IDs from poster

    Args:
        poster_path: Path to poster image
        series_name: Series name for context

    Returns:
        Dict with tmdb_id and/or imdb_id if found, None otherwise
    """
    if not os.path.exists(poster_path):
        return None

    logger.info("🔄 Fallback: Using GPT-5.2 to find TMDB/IMDb IDs...")

    # Read and encode poster
    with open(poster_path, 'rb') as f:
        image_data = f.read()

    base64_image = base64.b64encode(image_data).decode('utf-8')

    # Detect mime type
    if poster_path.lower().endswith('.png'):
        mime_type = 'image/png'
    else:
        mime_type = 'image/jpeg'

    data_url = f"data:{mime_type};base64,{base64_image}"

    prompt = f"""Analyze this TV series poster and identify the show.

Series name hint: {series_name}

Your task:
1. Read any text visible on the poster (title, actors, network)
2. Identify the TV series
3. Based on your knowledge, provide the TMDB ID and IMDb ID

You MUST provide your best estimate for the IDs based on the series name.
Common Indian streaming series are on TMDB. Search your knowledge for the IDs.

Return ONLY valid JSON:
{{
    "series_name": "Official series name",
    "tmdb_id": 295241,
    "imdb_id": "tt37356230",
    "confidence": "high/medium/low",
    "reasoning": "Brief explanation"
}}"""

    try:
        payload = {
            'model': 'openai/gpt-5.2',
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': prompt},
                        {'type': 'image_url', 'image_url': {'url': data_url}}
                    ]
                }
            ],
            'temperature': 0.1,
            'max_tokens': 2000
        }

        response = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {OPENROUTER_API_KEY}'
            },
            json=payload,
            timeout=60
        )

        response.raise_for_status()
        result = response.json()

        if 'choices' not in result or not result['choices']:
            return None

        message = result['choices'][0]['message']
        content = message.get('content', '').strip()

        # For reasoning models, check reasoning field if content is empty
        if not content and message.get('reasoning'):
            content = message.get('reasoning', '')

        logger.debug(f"GPT-5.2 response: {content[:500]}")

        # Extract JSON from response
        json_match = re.search(r'\{[^{}]*"tmdb_id"[^{}]*\}', content, re.DOTALL)
        if not json_match:
            json_match = re.search(r'\{[^{}]*"series_name"[^{}]*\}', content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())

            tmdb_id = data.get('tmdb_id')
            imdb_id = data.get('imdb_id')
            confidence = data.get('confidence', 'low')

            if tmdb_id or imdb_id:
                logger.info(f"✅ GPT-5.2 found: TMDB={tmdb_id}, IMDb={imdb_id} (confidence: {confidence})")
                return {
                    'id': tmdb_id,
                    'imdb_id': imdb_id,
                    'name': data.get('series_name'),
                    'gpt52_match': True
                }

        return None

    except Exception as e:
        logger.error(f"GPT-5.2 fallback error: {e}")
        return None


def clean_series_name(title: str) -> str:
    """
    Extract clean series name from release title

    Removes common release info patterns:
    - Year like (2026)
    - Season info S01, S02
    - Episode info EP01, EP(01-10)
    - Quality markers (WEB-DL, 1080p, 720p, AVC, AAC, etc.)
    - Audio language brackets [Tamil + Telugu + Hindi]
    - File size info (800MB, 4GB, etc.)
    - ESub, x265, etc.

    Args:
        title: Raw release title

    Returns:
        Clean series name
    """
    if not title:
        return ''

    # Remove year in parentheses at start or after name
    title = re.sub(r'\s*\(\d{4}\)\s*', ' ', title)

    # Remove season/episode info
    title = re.sub(r'\s+S\d+\s*', ' ', title)
    title = re.sub(r'\s+EP\d+', ' ', title)
    title = re.sub(r'\s+EP\s*\(\d+(-\d+)?\)', ' ', title)

    # Remove quality and encoding info
    title = re.sub(r'\s+TRUE WEB-DL.*$', '', title)
    title = re.sub(r'\s+WEB-DL.*$', '', title)
    title = re.sub(r'\s+WEBRip.*$', '', title)
    title = re.sub(r'\s+1080p.*$', '', title)
    title = re.sub(r'\s+720p.*$', '', title)
    title = re.sub(r'\s+480p.*$', '', title)
    title = re.sub(r'\s+4K.*$', '', title)
    title = re.sub(r'\s+x265.*$', '', title)
    title = re.sub(r'\s+x264.*$', '', title)
    title = re.sub(r'\s+AVC.*$', '', title)
    title = re.sub(r'\s+HEVC.*$', '', title)

    # Remove audio/codec info in brackets
    title = re.sub(r'\s*\[.*?\]\s*', ' ', title)

    # Remove size info
    title = re.sub(r'\s+\d+MB.*$', '', title)
    title = re.sub(r'\s+\d+\.?\d*GB.*$', '', title)

    # Remove ESub and similar
    title = re.sub(r'\s+-\s*ESub\s*$', '', title)
    title = re.sub(r'\s+ESub\s*$', '', title)

    # Clean up extra spaces and dashes
    title = re.sub(r'\s+-\s+', ' ', title)
    title = re.sub(r'\s+', ' ', title)

    return title.strip()


def download_poster(poster_url: str, cache_path: str) -> bool:
    """
    Download poster image from URL to cache

    Args:
        poster_url: URL of the poster image
        cache_path: Local path to save the poster

    Returns:
        True if download succeeded
    """
    try:
        logger.debug(f"Downloading poster: {poster_url}")
        response = requests.get(poster_url, timeout=30)
        response.raise_for_status()

        with open(cache_path, 'wb') as f:
            f.write(response.content)

        logger.info(f"✓ Poster downloaded: {cache_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to download poster: {e}")
        return False


def analyze_poster_with_ai(poster_path: str, expected_title: str) -> Optional[Dict]:
    """
    Analyze poster using AI vision to extract context

    Similar to renaming.php verifyPosterOriginWithGPT() function:
    - Extracts actor names from poster
    - Extracts director names
    - Identifies production companies
    - Determines country/origin (India, South Korea, etc.)
    - Checks if title matches

    Args:
        poster_path: Path to poster image
        expected_title: Expected series title

    Returns:
        Dict with analysis results or None
    """
    if not os.path.exists(poster_path):
        logger.error(f"Poster file does not exist: {poster_path}")
        return None

    logger.info("🔍 Analyzing poster with GPT-5 Nano Vision...")

    # Read and encode image
    with open(poster_path, 'rb') as f:
        image_data = f.read()

    data_url = f"data:image/jpeg;base64,{base64.b64encode(image_data).decode()}"

    prompt = f"""Analyze this TV series poster and EXTRACT SPECIFIC DETAILS:

Expected Series: '{expected_title}'

YOUR TASKS:
1. READ all visible text on poster carefully
2. EXTRACT actor names (starring, featuring, with, etc.)
3. EXTRACT director names (directed by, created by, etc.)
4. EXTRACT network/platform names (Netflix, Disney+, HBO, etc.)
5. EXTRACT production company names
6. IDENTIFY country/origin from names:
   - India = Indian names, Hindi/Tamil/Telugu text
   - South Korea = Hangul text, Korean names
   - China = Chinese characters
   - Japan = Japanese characters/names
   - Thailand = Thai text/names
7. Does title match '{expected_title}'?
8. Is poster quality good?
9. PROVIDE TMDB ID and IMDb ID if you know them for this series

IMPORTANT:
- Extract ACTUAL NAMES you see on poster
- Look for non-Latin scripts to identify origin
- Check if actor/director names sound Indian, Korean, Chinese, etc.
- If you recognize this series, provide the TMDB and IMDb IDs

Respond in JSON format:
{{
  "is_indian": true/false,
  "country_origin": "India/South Korea/China/Japan/Thailand/Other",
  "actors_on_poster": ["name1", "name2", ...],
  "directors_on_poster": ["name1", "name2", ...],
  "networks": ["network1", ...],
  "production_companies": ["company1", ...],
  "matches_expected": true/false,
  "poster_quality": "good/bad",
  "confidence": "high/medium/low",
  "tmdb_id": 123456 or null,
  "imdb_id": "tt1234567" or null,
  "reasoning": "List all names you found and why you think it's from [country]"
}}"""

    try:
        payload = {
            'model': 'openai/gpt-5-nano',
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': prompt},
                        {'type': 'image_url', 'image_url': {'url': data_url}}
                    ]
                }
            ],
            'temperature': 0.1,
            'max_tokens': 3000,
            'reasoning_effort': 'medium'
        }

        response = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {OPENROUTER_API_KEY}'
            },
            json=payload,
            timeout=45
        )

        response.raise_for_status()
        result = response.json()

        if 'choices' not in result or not result['choices']:
            logger.error("Invalid API response structure")
            return None

        content = result['choices'][0]['message']['content'].strip()

        # Fallback: Check reasoning field if content is empty
        if not content and 'reasoning' in result['choices'][0]['message']:
            content = result['choices'][0]['message']['reasoning'].strip()

        # Extract JSON from response
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            analysis = json.loads(json_str)

            # Display results
            print(f"\n📊 POSTER ANALYSIS RESULTS:")
            print(f"  🇮🇳 Indian Series: {'✅ YES' if analysis.get('is_indian') else '❌ NO'}")
            print(f"  🌍 Country Origin: {analysis.get('country_origin', 'Unknown')}")

            if analysis.get('actors_on_poster'):
                print(f"  🎭 Actors on Poster: {', '.join(analysis['actors_on_poster'][:5])}")
            if analysis.get('directors_on_poster'):
                print(f"  🎬 Directors on Poster: {', '.join(analysis['directors_on_poster'][:3])}")
            if analysis.get('networks'):
                print(f"  📺 Networks: {', '.join(analysis['networks'][:3])}")
            if analysis.get('production_companies'):
                print(f"  🏢 Production: {', '.join(analysis['production_companies'][:3])}")

            # Show IDs if found by gpt-5-nano
            if analysis.get('tmdb_id'):
                print(f"  🎯 TMDB ID: {analysis['tmdb_id']}")
            if analysis.get('imdb_id'):
                print(f"  🎬 IMDb ID: {analysis['imdb_id']}")

            print(f"  🎯 Confidence: {analysis.get('confidence', 'unknown')}")
            print(f"  💭 Reasoning: {analysis.get('reasoning', 'none')[:100]}...\n")

            # Log if IDs were found
            if analysis.get('tmdb_id') or analysis.get('imdb_id'):
                logger.info(f"✅ GPT-5-nano found IDs: TMDB={analysis.get('tmdb_id')}, IMDb={analysis.get('imdb_id')}")

            return analysis

        logger.warning("Could not extract JSON from AI response")
        return None

    except Exception as e:
        logger.error(f"Error analyzing poster with AI: {e}")
        return None


def enrich_with_imdb_id(result: Dict) -> Dict:
    """
    Fetch external IDs from TMDB to get imdb_id

    Args:
        result: TMDB search result with 'id' field

    Returns:
        Result with added 'imdb_id' field
    """
    if not result or not result.get('id'):
        return result

    tmdb_id = result['id']
    try:
        external_url = f'https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids'
        external_params = {'api_key': TMDB_API_KEY}
        external_response = requests.get(external_url, params=external_params, timeout=10)
        external_response.raise_for_status()
        external_data = external_response.json()
        if external_data.get('imdb_id'):
            result['imdb_id'] = external_data['imdb_id']
            logger.info(f"✓ Found IMDb ID: {external_data['imdb_id']}")
    except Exception as e:
        logger.warning(f"Could not fetch external IDs: {e}")

    return result


def search_tmdb_with_context(title: str, year: int, poster_context: Optional[Dict] = None) -> Optional[Dict]:
    """
    Search TMDB for TV series with poster context for better matching

    Similar to renaming.php selectBestMatchWithPoster() logic

    Args:
        title: Series title to search
        year: Release year
        poster_context: Poster analysis results from AI

    Returns:
        Dict with tmdb_id and metadata or None
    """
    if not TMDB_API_KEY:
        logger.warning("TMDB_API_KEY not set")
        return None

    logger.info(f"Searching TMDB for: '{title}' ({year})")

    try:
        # Search TMDB API
        params = {
            'api_key': TMDB_API_KEY,
            'query': title,
            'type': 'tv',
            'first_air_date_year': year
        }

        response = requests.get(
            'https://api.themoviedb.org/3/search/tv',
            params=params,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        results = data.get('results', [])
        if not results:
            logger.warning(f"No TMDB results found for '{title}' in {year}")

            # FALLBACK: Try IMDB search via RapidAPI
            logger.info("🔄 Trying IMDB search as fallback...")
            imdb_result = search_imdb_by_title(title, year)

            if imdb_result:
                # Use IMDB ID to find TMDB data
                tmdb_from_imdb = fetch_tmdb_by_imdb(imdb_result['imdb_id'])
                if tmdb_from_imdb:
                    logger.info(f"✅ Found via IMDB fallback: {tmdb_from_imdb.get('name') or title} (TMDB ID: {tmdb_from_imdb.get('tmdb_id')})")
                    # Return in the same format as TMDB search
                    return {
                        'id': tmdb_from_imdb.get('tmdb_id'),
                        'imdb_id': imdb_result['imdb_id'],
                        'name': imdb_result.get('title'),
                        'overview': tmdb_from_imdb.get('overview'),
                        'poster_path': tmdb_from_imdb.get('poster_url'),
                        'from_imdb_fallback': True
                    }

            return None

        # Filter to same year
        exact_matches = [r for r in results if r.get('first_air_date', '')[:4] == str(year)]
        results = exact_matches if exact_matches else results

        logger.info(f"Found {len(results)} TMDB result(s)")

        # If only one match, return it
        if len(results) == 1:
            match = results[0]
            logger.info(f"✓ Single match: {match.get('name')} (TMDB: {match.get('id')})")
            return enrich_with_imdb_id(match)

        # Multiple matches - use AI to select best match
        if poster_context and len(results) > 1:
            logger.info("\n🤖 Using AI to select best match from poster context...")

            # Build candidate list with TMDB details
            candidates_text = f"CANDIDATE TV SERIES FROM TMDB:\n\n"
            for idx, result in enumerate(results[:10]):  # Limit to 10
                candidates_text += f"=== CANDIDATE {idx + 1} ===\n"
                candidates_text += f"TMDB ID: {result['id']}\n"
                candidates_text += f"Name: {result.get('name')}\n"
                candidates_text += f"Original Name: {result.get('original_name')}\n"
                candidates_text += f"Overview: {(result.get('overview', 'N/A')[:100])}...\n\n"

            # Build prompt for AI matching
            prompt = f"""Select which TMDB TV series candidate matches the poster by comparing SPECIFIC DETAILS.

POSTER ANALYSIS (from poster):
Country Origin: {poster_context.get('country_origin', 'Unknown')}
Is Indian Series: {'Yes' if poster_context.get('is_indian') else 'No'}
Actors on Poster: {', '.join(poster_context.get('actors_on_poster', [])[:5])}
Directors on Poster: {', '.join(poster_context.get('directors_on_poster', [])[:3])}
Networks: {', '.join(poster_context.get('networks', [])[:3])}
Full Reasoning: {poster_context.get('reasoning', 'None')[:200]}

{candidates_text}
INSTRUCTIONS:
1. Look at the actors, directors, networks from the poster analysis above
2. Match those SPECIFIC NAMES with the series name/overview in each candidate
3. Match the Country (India vs other countries) from poster
4. SELECT the candidate whose name/overview/network matches what you saw on the poster

Respond with ONLY the number (1, 2, 3, etc.) and which specific detail matched.
Format: NUMBER: [series name] - [network/actor/director] match
If no match, respond: NO MATCH"""

            try:
                payload = {
                    'model': 'openai/gpt-5-nano',
                    'messages': [
                        {'role': 'user', 'content': prompt}
                    ],
                    'temperature': 0.1,
                    'max_tokens': 800,
                    'reasoning_effort': 'low'
                }

                response = requests.post(
                    'https://openrouter.ai/api/v1/chat/completions',
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {OPENROUTER_API_KEY}'
                    },
                    json=payload,
                    timeout=45
                )

                response.raise_for_status()
                ai_result = response.json()

                if 'choices' in ai_result and ai_result['choices']:
                    ai_content = ai_result['choices'][0]['message']['content'].strip()
                    logger.info(f"AI response: {ai_content}")

                    # Extract number from response
                    number_match = re.match(r'^(\d+)[:.\s]', ai_content)
                    if number_match:
                        selected_idx = int(number_match.group(1)) - 1

                        if 0 <= selected_idx < len(results):
                            best_match = results[selected_idx]
                            logger.info(f"✅ AI selected best match: {best_match.get('name')} (TMDB: {best_match.get('id')})")
                            return enrich_with_imdb_id(best_match)

                    logger.warning("Could not parse AI selection")

            except Exception as e:
                logger.warning(f"AI matching failed: {e}")

        # Fallback: Return first result
        logger.info(f"Using first match as fallback: {results[0].get('name')} (TMDB: {results[0].get('id')})")
        return enrich_with_imdb_id(results[0])

    except Exception as e:
        logger.error(f"Error searching TMDB: {e}")
        return None


def mark_series_failed(series_id: int) -> None:
    """
    Mark series as failed AI matching (gpt = 0)

    Args:
        series_id: Series database ID
    """
    conn = get_connection()
    if not conn:
        return

    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE series SET gpt = 0 WHERE id = %s', (series_id,))
        conn.commit()
        logger.info(f"✓ Marked series {series_id} as failed (gpt=0)")
    except Exception as e:
        logger.error(f"Error marking series failed: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def create_seasons_from_tmdb(series_id: int, tmdb_id: int, seasons_data: list) -> int:
    """
    Create season records from TMDB data

    Args:
        series_id: Series database ID
        tmdb_id: TMDB series ID
        seasons_data: List of season dicts from TMDB

    Returns:
        Number of seasons created
    """
    if not seasons_data:
        logger.info("  📺 No seasons data from TMDB")
        return 0

    conn = get_connection()
    if not conn:
        return 0

    cursor = conn.cursor(dictionary=True)

    try:
        created = 0
        updated = 0

        for season in seasons_data:
            season_number = season.get('season_number')
            if not season_number or season_number < 1:
                continue  # Skip specials (season 0)

            # Extract year from air_date
            year = None
            air_date = season.get('air_date')
            if air_date:
                try:
                    year = int(air_date[:4])
                except (ValueError, TypeError):
                    pass

            episode_count = season.get('episode_count', 0)

            # Check if season exists
            cursor.execute('''
                SELECT id FROM seasons
                WHERE series_id = %s AND season_number = %s
            ''', (series_id, season_number))

            existing = cursor.fetchone()

            if existing:
                # Update episode count if different
                cursor.execute('''
                    UPDATE seasons
                    SET episode_count = %s
                    WHERE id = %s
                ''', (episode_count, existing['id']))
                updated += 1
                logger.debug(f"  Updated season {season_number}: {episode_count} episodes")
            else:
                # Create new season
                cursor.execute('''
                    INSERT INTO seasons (series_id, season_number, year, episode_count)
                    VALUES (%s, %s, %s, %s)
                ''', (series_id, season_number, year, episode_count))
                created += 1
                logger.info(f"  ✓ Created season {season_number}: {episode_count} episodes")

        conn.commit()
        logger.info(f"  📊 Seasons: {created} created, {updated} updated")
        return created

    except Exception as e:
        logger.error(f"Error creating seasons: {e}")
        conn.rollback()
        return 0

    finally:
        cursor.close()
        conn.close()


def update_series_with_tmdb(series_id: int, tmdb_data: Dict) -> bool:
    """
    Update series table with comprehensive metadata from IMDB and TMDB

    Fetches:
    - IMDB details (cast, directors, writers, genres, etc.)
    - TMDB details (status, networks, production companies, etc.)
    - TMDB videos (trailer)

    Args:
        series_id: Series database ID
        tmdb_data: TMDB series data (from search or AI match)

    Returns:
        True if update succeeded
    """
    tmdb_id = tmdb_data.get('id')
    imdb_id = tmdb_data.get('imdb_id')

    if not tmdb_id:
        logger.warning("No TMDB ID in data, skipping comprehensive metadata fetch")
        return False

    logger.info(f"📊 Fetching comprehensive metadata for TMDB ID: {tmdb_id}")

    # Step 1: Fetch full IMDB details (if we have imdb_id)
    imdb_details = None
    if imdb_id:
        logger.info(f"  🎬 Fetching IMDB details for: {imdb_id}")
        imdb_details = fetch_imdb_details(imdb_id)
        if imdb_details:
            logger.info(f"  ✓ IMDB details fetched")
        else:
            logger.warning(f"  ⚠ IMDB details fetch failed for {imdb_id}")

    # Step 2: Fetch full TMDB details (status, networks, production companies, etc.)
    logger.info(f"  📺 Fetching TMDB extended details")
    tmdb_details = fetch_tmdb_details(tmdb_id, 'tv')
    if tmdb_details:
        logger.info(f"  ✓ TMDB extended details fetched")

    # Step 3: Fetch trailer from TMDB
    logger.info(f"  🎥 Fetching trailer")
    trailer_key = fetch_tmdb_videos(tmdb_id, 'tv')
    if trailer_key:
        tmdb_details = tmdb_details or {}
        tmdb_details['trailer_key'] = trailer_key
        logger.info(f"  ✓ Trailer found: {trailer_key}")

    # Step 4: Parse all data into our format
    logger.info(f"  🔄 Parsing comprehensive metadata")
    metadata = parse_imdb_data(imdb_details, tmdb_data, tmdb_details)

    # Always include tmdb_id and gpt flag
    metadata['tmdb_id'] = tmdb_id
    metadata['gpt'] = 1  # Mark as successfully matched

    # Step 5: Update database with all metadata
    logger.info(f"  💾 Updating database with {len(metadata)} fields")
    result = update_series_metadata(series_id, metadata)

    if result:
        # Log what was updated
        updates = []
        for key, value in metadata.items():
            if value is not None and key not in ['gpt']:
                display_val = str(value)[:50] + '...' if len(str(value)) > 50 else value
                updates.append(f"    {key}: {display_val}")

        if updates:
            logger.info(f"✓ Updated series {series_id} with metadata:")
            for update in updates[:15]:  # Show first 15 fields
                logger.info(update)
            if len(updates) > 15:
                logger.info(f"    ... and {len(updates) - 15} more fields")

        # Step 6: Create/update seasons from TMDB data
        if tmdb_details and 'seasons' in tmdb_details:
            logger.info(f"  📺 Creating/updating seasons from TMDB...")
            create_seasons_from_tmdb(series_id, tmdb_id, tmdb_details['seasons'])

        # Step 7: Download poster and backdrop images
        logger.info(f"  📥 Downloading images...")

        # Fetch original_poster_url from database for fallback validation
        original_poster_url = None
        try:
            conn = get_connection()
            if conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT original_poster_url FROM series WHERE id = %s', (series_id,))
                result = cursor.fetchone()
                if result:
                    original_poster_url = result.get('original_poster_url')
                cursor.close()
                conn.close()
        except Exception as e:
            logger.warning(f"Could not fetch original_poster_url: {e}")

        series_data = {
            'name': metadata.get('name'),
            'title': metadata.get('name'),
            'year': metadata.get('year'),
            'poster_url': metadata.get('poster_url'),
            'imdb_poster_url': metadata.get('imdb_poster_url'),  # IMDB poster from RapidAPI
            'original_poster_url': original_poster_url,  # Include for fallback validation
            'backdrop_url': metadata.get('backdrop_url')
        }
        image_paths = download_series_images(series_id, series_data)

        if image_paths.get('poster_path') or image_paths.get('cover_path'):
            update_series_image_paths(series_id, image_paths)

    return result


def match_series_with_ai(series_id: int, dry_run: bool = False) -> bool:
    """
    Match a series to TMDB using AI vision poster analysis

    Main workflow function similar to renaming.php

    Args:
        series_id: Series database ID to match
        dry_run: If True, don't make changes

    Returns:
        True if matching succeeded
    """
    conn = get_connection()
    if not conn:
        return False

    cursor = conn.cursor(dictionary=True)

    try:
        # Get series info
        cursor.execute('''
            SELECT id, title, name, year, poster_url, original_poster_url
            FROM series
            WHERE id = %s
        ''', (series_id,))

        series = cursor.fetchone()
        if not series:
            logger.error(f"Series {series_id} not found")
            return False

        series_name = series.get('name') or series.get('title') or 'Unknown'
        year = series.get('year')
        # Use original_poster_url for AI analysis (never changes), fallback to poster_url
        poster_url = series.get('original_poster_url') or series.get('poster_url')

        # Clean the series name for TMDB search
        clean_name = clean_series_name(series_name)

        print(f"\n{'='*80}")
        print(f"🎬 PROCESSING: {series_name}")
        print(f"{'='*80}")
        print(f"Series ID: {series.get('id')}")
        print(f"Title: {series_name}")
        if clean_name != series_name:
            print(f"Cleaned: {clean_name}")
        print(f"Year: {year}")
        print(f"Poster URL: {poster_url}\n")
        print(f"{'='*80}")
        print(f"Series ID: {series.get('id')}")
        print(f"Title: {series_name}")
        print(f"Year: {year}")
        print(f"Poster URL: {poster_url}\n")

        if dry_run:
            print("[DRY RUN] Skipping actual matching")
            return True

        # Check if poster URL exists
        if not poster_url:
            logger.warning("⚠️  No poster_url available - skipping AI analysis")
            mark_series_failed(series_id)
            return False

        # Step 1: Download and analyze poster
        print("🔍 STEP 1: Poster Analysis with AI")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Generate cache path for poster
        poster_hash = hashlib.md5(poster_url.encode()).hexdigest()
        cache_path = os.path.join(POSTER_CACHE_DIR, f"series_{series_id}_{poster_hash}.jpg")

        # Download poster
        if not os.path.exists(cache_path):
            if not download_poster(poster_url, cache_path):
                mark_series_failed(series_id)
                return False

        # Analyze with AI
        poster_context = analyze_poster_with_ai(cache_path, series_name)

        if not poster_context:
            logger.warning("⚠️  Could not analyze poster with AI")
            # Clean up cache
            if os.path.exists(cache_path):
                os.remove(cache_path)
            mark_series_failed(series_id)
            return False

        # Check if gpt-5-nano found IDs directly
        tmdb_data = None
        if poster_context.get('tmdb_id'):
            logger.info(f"✅ GPT-5-nano found TMDB ID directly: {poster_context['tmdb_id']}")
            tmdb_data = {
                'id': poster_context['tmdb_id'],
                'imdb_id': poster_context.get('imdb_id'),
                'name': series_name,
                'gpt_nano_match': True
            }
            print("\n✅ IDs found by GPT-5-nano - skipping TMDB search")

        # Step 2: Search TMDB with poster context (if no IDs from gpt-5-nano)
        if not tmdb_data:
            print("\n🔍 STEP 2: TMDB Search with Poster Context")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            tmdb_data = search_tmdb_with_context(clean_name, year, poster_context)

        if not tmdb_data:
            logger.warning("⚠️  No TMDB match found with gpt-5-nano")

            # Fallback: Try GPT-5.2 for direct ID lookup
            print("\n🔍 STEP 2b: Fallback - GPT-5.2 Direct ID Lookup")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            tmdb_data = find_ids_with_gpt52(cache_path, series_name)

            if not tmdb_data:
                logger.warning("⚠️  GPT-5.2 fallback also failed")
                mark_series_failed(series_id)
                return False

        # Step 3: Update database
        print("\n🔍 STEP 3: Update Database")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        if update_series_with_tmdb(series_id, tmdb_data):
            logger.info(f"✅ SUCCESS: Matched '{series_name}' to TMDB ID {tmdb_data.get('id')}")
            return True
        else:
            logger.error("❌ Failed to update series")
            mark_series_failed(series_id)
            return False

    except Exception as e:
        logger.error(f"Error in match_series_with_ai: {e}")
        mark_series_failed(series_id)
        return False

    finally:
        cursor.close()
        conn.close()


def match_all_series_with_ai(dry_run: bool = False) -> Dict:
    """
    Match all series without TMDB IDs using AI

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
        # Find series with original_poster_url but no tmdb_id
        # Use original_poster_url (never changes) instead of poster_url (can be updated by TMDB)
        cursor.execute('''
            SELECT id, title, name, year, poster_url, original_poster_url
            FROM series
            WHERE tmdb_id IS NULL
            AND (original_poster_url IS NOT NULL AND original_poster_url != '')
            ORDER BY id
        ''')

        series_list = cursor.fetchall()

        if not series_list:
            logger.info("No series found with poster_url but no tmdb_id")
            return {
                'total': 0,
                'matched': 0,
                'failed': 0
            }

        logger.info(f"Found {len(series_list)} series to match with AI")

        matched = 0
        failed = 0

        for idx, series in enumerate(series_list, 1):
            series_id = series['id']
            series_name = series.get('name') or series.get('title', 'Unknown')

            print(f"\n\n╔{'='*78}╗")
            print(f"║ {idx}/{len(series_list)}: {series_name} {' '*(76-len(str(idx)) - len(series_name))}║")
            print(f"╚{'='*78}╝")

            if match_series_with_ai(series_id, dry_run):
                matched += 1
            else:
                failed += 1

        return {
            'total': len(series_list),
            'matched': matched,
            'failed': failed
        }

    except Exception as e:
        logger.error(f"Error in match_all_series_with_ai: {e}")
        return {'error': str(e)}

    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Match series to TMDB using AI vision')
    parser.add_argument('--series-id', type=int, help='Match specific series ID')
    parser.add_argument('--all', action='store_true', help='Match all series without TMDB IDs')
    parser.add_argument('--dry-run', action='store_true', help='Dry run - no changes')

    args = parser.parse_args()

    if args.series_id:
        match_series_with_ai(args.series_id, args.dry_run)
    elif args.all:
        results = match_all_series_with_ai(args.dry_run)
        if 'error' not in results:
            print(f"\n{'='*80}")
            print("SUMMARY")
            print(f"{'='*80}")
            print(f"Total series: {results['total']}")
            print(f"Matched: ✓ {results['matched']}")
            print(f"Failed: ✗ {results['failed']}")
            print(f"{'='*80}\n")
    else:
        parser.print_help()
