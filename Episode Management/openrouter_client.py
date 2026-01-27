#!/usr/bin/env python3
"""
OpenRouter AI client for episode number validation

Uses GPT-5-nano via OpenRouter API to validate and correct episode numbers
extracted from video filenames.
"""

import os
import sys
import re
import json
import requests
from pathlib import Path
from typing import Optional, Tuple

# Add parent directories to path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))

from logger import get_logger
from config import get_config

logger = get_logger(__name__)


class OpenRouterClient:
    """Client for OpenRouter API using GPT-5-nano model"""

    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str = None, model: str = None):
        """
        Initialize OpenRouter client

        Args:
            api_key: OpenRouter API key (default: from config or OPENROUTER_API_KEY env)
            model: Model to use (default: from config or openai/gpt-4o-mini)
        """
        # Try to get config first
        try:
            config = get_config()
            self.api_key = api_key or config.get('openrouter', {}).get('api_key') or os.environ.get('OPENROUTER_API_KEY')
            self.model = model or config.get('openrouter', {}).get('model') or 'openai/gpt-5-nano'
            self.timeout = config.get('openrouter', {}).get('timeout', 30)
        except Exception:
            # Fallback to environment variables
            self.api_key = api_key or os.environ.get('OPENROUTER_API_KEY')
            self.model = model or os.environ.get('OPENROUTER_MODEL', 'openai/gpt-5-nano')
            self.timeout = 30

        if not self.api_key:
            logger.warning("OpenRouter API key not set - AI validation disabled")

    def is_available(self) -> bool:
        """Check if client is properly configured"""
        return bool(self.api_key)

    def validate_episode_number(
        self,
        filename: str,
        series_name: str,
        extracted_season: int,
        extracted_episode: Optional[int],
        context: str = ""
    ) -> Tuple[int, Optional[int]]:
        """
        Use AI to validate and correct episode number from filename

        Args:
            filename: Full video filename
            series_name: Name of the TV series
            extracted_season: Season number extracted by regex
            extracted_episode: Episode number extracted by regex (may be None)
            context: Additional context (torrent name, folder name, etc.)

        Returns:
            Tuple of (season_number, episode_number) where episode_number may be None if uncertain
        """
        if not self.is_available():
            logger.debug("OpenRouter not available, using extracted values")
            return extracted_season, extracted_episode

        # Build prompt for AI
        prompt = self._build_validation_prompt(
            filename, series_name, extracted_season, extracted_episode, context
        )

        try:
            response = requests.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/webseries-scraper",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are an expert at parsing TV episode filenames. "
                            "Extract season and episode numbers accurately. Respond only with valid JSON."
                        },
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,  # Low temperature for consistent results
                    "max_tokens": 10000,  # Reasoning models like gpt-5-nano need more tokens
                },
                timeout=30
            )

            response.raise_for_status()
            data = response.json()

            # Extract AI response - check content first, then reasoning for reasoning models
            message = data.get('choices', [{}])[0].get('message', {})
            content = message.get('content', '')

            # For reasoning models like gpt-5-nano, content may be empty and output is in reasoning
            if not content and message.get('reasoning'):
                # Try to extract JSON from reasoning text
                reasoning_text = message.get('reasoning', '')
                json_match = re.search(r'\{[^{}]*"season"[^{}]*\}', reasoning_text)
                if json_match:
                    content = json_match.group(0)
            logger.debug(f"AI response: {content}")

            # Parse JSON response
            ai_result = json.loads(content)

            season = ai_result.get('season')
            episode = ai_result.get('episode')
            confidence = ai_result.get('confidence', 0.0)

            # Only use AI result if confidence is high enough
            if confidence >= 0.7:
                ep_str = f"E{episode:02d}" if episode else "E??"
                logger.info(
                    f"AI corrected: {filename} -> S{season:02d}{ep_str} "
                    f"(confidence: {confidence:.0%})"
                )
                return season, episode
            else:
                logger.debug(
                    f"AI confidence too low ({confidence:.0%}), using extracted values"
                )
                return extracted_season, extracted_episode

        except requests.RequestException as e:
            error_detail = str(e)
            if "401" in error_detail or "Unauthorized" in error_detail:
                logger.warning(f"OpenRouter authentication failed - check API key or account balance")
            else:
                logger.error(f"OpenRouter API error: {e}")
            return extracted_season, extracted_episode
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse AI response: {e}")
            return extracted_season, extracted_episode

    def _build_validation_prompt(
        self,
        filename: str,
        series_name: str,
        extracted_season: int,
        extracted_episode: Optional[int],
        context: str
    ) -> str:
        """Build the validation prompt for the AI"""

        prompt = f"""Analyze this TV episode filename and extract the correct season and episode numbers.

Filename: {filename}
Series: {series_name}
Context: {context if context else "None"}

Regex initially found:
- Season: {extracted_season}
- Episode: {extracted_episode if extracted_episode else "Not detected"}

Common patterns in filenames:
- S01E01 or S01E01-E02 (Season 1, Episode 1 or 1-2)
- S01 EP01 or S01 EP (01-05) (Season 1, Episode 1 or batch)
- 1x01 (Season 1, Episode 1)
- EP01 alone (defaults to Season 1, Episode 1)
- Episode numbers in parentheses like (01), (02)

Special cases:
- "EP" alone might mean all episodes or a batch
- Numbers like 01-05 mean episodes 1 through 5
- Sometimes episode is written as "Ep.1" or "Epi 01"

Return a JSON object with this exact format:
{{
    "season": <integer season number>,
    "episode": <integer episode number or null if batch/no specific episode>,
    "confidence": <float 0.0 to 1.0>,
    "reasoning": "<brief explanation of your analysis>"
}}

Only return the JSON, nothing else."""

        return prompt

    def validate_batch(
        self,
        items: list[dict],
        show_progress: bool = True
    ) -> list[dict]:
        """
        Validate multiple episode filenames in batch

        Args:
            items: List of dicts with keys: filename, series_name, season, episode, context
            show_progress: Whether to show progress messages

        Returns:
            List of dicts with validated/corrected season and episode numbers
        """
        if not self.is_available():
            logger.warning("OpenRouter not available, returning original values")
            return items

        results = []
        corrected = 0

        for i, item in enumerate(items):
            if show_progress and (i + 1) % 10 == 0:
                logger.info(f"Validating {i + 1}/{len(items)}...")

            season, episode = self.validate_episode_number(
                filename=item['filename'],
                series_name=item['series_name'],
                extracted_season=item['season'],
                extracted_episode=item.get('episode'),
                context=item.get('context', '')
            )

            result = item.copy()
            result['season'] = season
            result['episode'] = episode

            # Check if values changed
            if season != item['season'] or episode != item.get('episode'):
                corrected += 1
                result['corrected'] = True
            else:
                result['corrected'] = False

            results.append(result)

        logger.info(f"Validation complete: {corrected}/{len(items)} corrected by AI")
        return results


# Singleton instance
_client = None


def get_client(api_key: str = None, model: str = None) -> OpenRouterClient:
    """
    Get or create OpenRouter client singleton

    Args:
        api_key: API key (uses env if not provided)
        model: Model name

    Returns:
        OpenRouterClient instance
    """
    global _client
    if _client is None:
        _client = OpenRouterClient(api_key=api_key, model=model)
    return _client
