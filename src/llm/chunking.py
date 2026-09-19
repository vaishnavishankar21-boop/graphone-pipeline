"""
Payload chunking utility.

Purpose: guarantee LLM extraction calls never trigger a 413 (Payload Too
Large) error, while keeping the most information-dense part of the text.

Strategy: character-budget truncation (a simple, dependency-free proxy for
token count -- roughly 4 characters per token for English text, so a
budget of e.g. 6000 chars keeps us safely under most providers' smaller
context windows even before accounting for the prompt template itself).

For long documents (e.g. full-text news articles in Phase II), we take
the head + tail of the text rather than a blind head-truncation, since
articles often put key context in the opening paragraph AND a concluding
summary -- naively cutting the tail loses information a plain head-cut
would keep, and vice versa.
"""

from __future__ import annotations

CHARS_PER_TOKEN_ESTIMATE = 4


def truncate_for_llm(text: str, max_chars: int = 6000, keep_head_ratio: float = 0.7) -> str:
    """
    Truncate `text` to at most `max_chars` characters, preserving both the
    beginning and end of the text (head + tail split by `keep_head_ratio`)
    since both often carry distinct, non-redundant information.

    Returns the text unchanged if it's already within budget.
    """
    if len(text) <= max_chars:
        return text

    head_chars = int(max_chars * keep_head_ratio)
    tail_chars = max_chars - head_chars - len(" ...[truncated]... ")
    tail_chars = max(0, tail_chars)

    head = text[:head_chars]
    tail = text[-tail_chars:] if tail_chars > 0 else ""
    return f"{head} ...[truncated]... {tail}"


def estimate_tokens(text: str) -> int:
    """Rough token count estimate, used to decide if chunking is needed at all."""
    return len(text) // CHARS_PER_TOKEN_ESTIMATE

