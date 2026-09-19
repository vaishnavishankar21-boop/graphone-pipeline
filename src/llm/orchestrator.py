"""
Multi-tier LLM extraction orchestrator.

Fallback chain design: try each configured tier in order; a tier is
SKIPPED (not retried) if its API key isn't set, and FALLS THROUGH to the
next tier if it's rate limited, erroring, or exhausts its retries.

Free-tier reality check (learned via live testing on this project):
  - Gemini Flash (gemini-3.6-flash, this account's only available free
    model) failed 100% of attempts (5/5 retries exhausted) on every
    single call, regardless of pacing -- pointing to an account-level
    quota of effectively zero, not a timing problem retries could fix.
    It has been REMOVED from the active chain below (see commented tier)
    since every attempt cost ~25s before falling through, actively
    slowing the pipeline for zero benefit.
  - Groq's free tier does work, but enforces a real DAILY request cap
    (~1,000 req/day per model) on top of its per-minute limit -- once
    near that cap, Retry-After values of 100-350+ seconds are normal and
    expected, not a bug. The retry/backoff logic here respects those
    values exactly rather than guessing, so it recovers correctly, just
    slowly, once the daily quota partially resets.
  - DeepSeek via OpenRouter was configured but never had a key set in
    this project's testing; it remains in the chain as a genuine third
    option for anyone who does configure OPENROUTER_API_KEY.

Every request is pre-truncated (chunking.py) to guarantee no 413s
regardless of which tier ends up serving it.
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


# Order matters: this IS the fallback chain.
DEFAULT_CHAIN: List[LLMTier] = [
    LLMTier(
        name="Groq GPT-OSS-20B",
        base_url="https://api.groq.com/openai/v1/chat/completions",
        model="openai/gpt-oss-20b",
        api_key_env="GROQ_API_KEY",
    ),
    # Gemini Flash intentionally excluded from the active chain -- see
    # module docstring above. Left here, commented, as a record of what
    # was tried and why it was removed, and so it's trivial to re-enable
    # for a different account/billing tier:
    #
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
        # A single global semaphore + minimum spacing between calls (across
        # ALL tiers, not per-tier) keeps aggregate request rate predictable
        # regardless of how many extractions are logically "concurrent".
        # 3.0s is tuned for Groq's per-minute limit now that Gemini (which
        # needed much more conservative pacing) is out of the active chain.
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

        return await with_retries(_do_call, op_name=tier.name, max_attempts=5, base_delay=3.0)

    async def extract_json(
        self, system_prompt: str, user_content: str, max_input_chars: int = 6000
    ) -> Dict[str, Any]:
        """
        Runs `user_content` through the fallback chain and returns parsed
        JSON. Tries each tier in order; falls through to the next tier on
        any failure (missing key, exhausted retries, bad response).
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