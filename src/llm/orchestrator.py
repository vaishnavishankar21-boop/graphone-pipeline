"""
Multi-tier LLM extraction orchestrator.

Fallback chain design: try each configured tier in order; a tier is
SKIPPED (not retried) if its API key isn't set, and FALLS THROUGH to the
next tier if it's rate limited, erroring, or exhausts its retries.

CRITICAL FIX (added after live testing): when a provider's daily quota is
exhausted, it reports 429s with a very long Retry-After (observed:
100-450+ seconds on Groq's free tier). The retry loop used to sleep
through up to 5 such waits on the SAME tier before ever falling through
to the next one -- meaning a chain with 3 configured tiers could spend
20+ minutes stuck on tier 1 alone, defeating the entire point of having
a fallback chain. Fixed via `giveup_if_delay_exceeds` in
src/utils/retry.py: any wait longer than 30s now gives up on that tier
IMMEDIATELY so the next tier is tried within seconds, not minutes. Short
waits (a few seconds, typical of normal per-minute rate limiting) still
retry normally within the tier.

Free-tier reality check (learned via live testing on this project):
  - Gemini Flash failed 100% of attempts regardless of pacing -- removed
    from the active chain entirely (see commented-out tier below).
  - Groq's free tier enforces a real DAILY request cap (~1,000 req/day
    per model) on top of its per-minute limit.
  - DeepSeek via OpenRouter is configured as the third tier and engages
    properly now that the fast-fallthrough fix is in place.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp

from src.llm.chunking import truncate_for_llm
from src.utils.retry import PermanentError, RetryableError, parse_retry_after, with_retries

logger = logging.getLogger("graphone.llm.orchestrator")


@dataclass
class LLMTier:
    name: str
    base_url: str
    model: str
    api_key_env: str
    extra_headers: Optional[Dict[str, str]] = None


DEFAULT_CHAIN: List[LLMTier] = [
    LLMTier(
        name="Groq GPT-OSS-20B",
        base_url="https://api.groq.com/openai/v1/chat/completions",
        model="openai/gpt-oss-20b",
        api_key_env="GROQ_API_KEY",
    ),
    # Gemini Flash intentionally excluded -- see module docstring above.
    # LLMTier(
    #     name="Gemini Flash",
    #     base_url="https://generativelanguage.googleapis.com/v1beta/chat/completions",
    #     model="gemini-3.6-flash",
    #     api_key_env="GEMINI_API_KEY",
    # ),
    LLMTier(
        name="DeepSeek (via OpenRouter)",
        base_url="https://openrouter.ai/api/v1/chat/completions",
        model="deepseek/deepseek-chat",
        api_key_env="OPENROUTER_API_KEY",
    ),
]


class AllProvidersExhaustedError(Exception):
    """Raised when every tier in the chain failed or was unconfigured."""


class LLMOrchestrator:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        chain: Optional[List[LLMTier]] = None,
        min_call_interval: float = 3.0,
    ):
        self.session = session
        self.chain = chain or DEFAULT_CHAIN
        self.call_sem = asyncio.Semaphore(1)
        self.min_call_interval = min_call_interval

    async def _call_tier(self, tier: LLMTier, system_prompt: str, user_prompt: str) -> str:
        """Make one chat-completion call to a single tier. Raises on failure."""
        api_key = os.getenv(tier.api_key_env)
        if not api_key:
            raise PermanentError(f"{tier.name}: {tier.api_key_env} not set, skipping")

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if tier.extra_headers:
            headers.update(tier.extra_headers)

        payload = {
            "model": tier.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }

        async def _do_call():
            async with self.session.post(
                tier.base_url, headers=headers, json=payload, timeout=30
            ) as resp:
                if resp.status == 429:
                    raise RetryableError(f"{tier.name} rate limited", retry_after=parse_retry_after(resp) or 5)
                if resp.status == 413:
                    raise PermanentError(f"{tier.name}: 413 payload too large despite pre-truncation")
                if resp.status >= 500:
                    raise RetryableError(f"{tier.name} server error {resp.status}")
                if resp.status == 401 or resp.status == 403:
                    raise PermanentError(f"{tier.name}: auth failed ({resp.status}) -- check API key")
                if resp.status != 200:
                    body = await resp.text()
                    raise PermanentError(f"{tier.name} returned {resp.status}: {body[:200]}")
                data = await resp.json()
                return data["choices"][0]["message"]["content"]

        # giveup_if_delay_exceeds=30: a rate-limit wait longer than 30s
        # means this tier is effectively unusable right now (daily quota,
        # not a normal per-minute limit) -- give up on it immediately so
        # the chain falls through to the next tier within seconds.
        return await with_retries(
            _do_call, op_name=tier.name, max_attempts=5, base_delay=3.0,
            giveup_if_delay_exceeds=30.0,
        )

    async def extract_json(
        self, system_prompt: str, user_content: str, max_input_chars: int = 6000
    ) -> Dict[str, Any]:
        """
        Runs `user_content` through the fallback chain and returns parsed
        JSON. Tries each tier in order; falls through to the next tier on
        any failure (missing key, exhausted retries, bad response, or a
        rate-limit wait too long to be worth sitting through).
        """
        safe_content = truncate_for_llm(user_content, max_chars=max_input_chars)

        last_error: Optional[Exception] = None
        async with self.call_sem:
            for tier in self.chain:
                try:
                    raw = await self._call_tier(tier, system_prompt, safe_content)
                    cleaned = raw.strip()
                    if cleaned.startswith("```"):
                        cleaned = cleaned.strip("`")
                        if cleaned.startswith("json"):
                            cleaned = cleaned[4:]
                        cleaned = cleaned.strip()
                    return json.loads(cleaned)
                except (PermanentError, RetryableError, json.JSONDecodeError, KeyError, IndexError) as e:
                    logger.warning(f"Tier '{tier.name}' failed, falling back to next tier: {e}")
                    last_error = e
                    continue
                finally:
                    await asyncio.sleep(self.min_call_interval)

        raise AllProvidersExhaustedError(
            f"All {len(self.chain)} LLM tiers failed or were unconfigured. Last error: {last_error}"
        )