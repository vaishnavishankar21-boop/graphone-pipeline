"""
Entity resolution engine.

Given a raw entity name as it appeared at the source (e.g. "Open AI",
"OpenAI, Inc."), resolves it to a canonical form (e.g. "OpenAI") using:

  1. Exact match (after normalization) against the seed database
     (src/resolution/seed_entities.py).
  2. Fuzzy match (rapidfuzz token_sort_ratio) against the same database,
     for typos, spacing/punctuation differences, or unlisted legal
     suffixes the exact-match normalization didn't anticipate.
  3. If neither matches (the overwhelming majority of real-world names,
     since the seed list is intentionally small), the cleaned/normalized
     version of the raw name becomes its own canonical form -- this is
     correct behavior, not a failure: most startups genuinely aren't in
     a 50-company reference list.

Every resolution decision (raw name, resulting canonical name, method
used, and confidence score) is recorded, which is exactly the "Entity
Mapping Log (Raw vs Canonical names)" tab required in the final
Google Sheet deliverable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz, process

from src.resolution.seed_entities import SEED_ENTITIES

# Legal-entity suffixes stripped during normalization. Deliberately
# conservative -- we do NOT strip generic words like "AI", "Labs", or
# "Technologies" here, since those are often part of a company's actual
# brand name (e.g. "Stability AI"), not a legal wrapper. Stripping them
# broadly would cause false merges between genuinely distinct companies.
_LEGAL_SUFFIXES = re.compile(
    r"[,]?\s*\b(inc\.?|llc\.?|ltd\.?|corp\.?|co\.?|pbc|sas|gmbh|plc|b\.?v\.?)\s*$",
    re.IGNORECASE,
)

FUZZY_MATCH_THRESHOLD = 90  # 0-100 rapidfuzz score; conservative to avoid false merges


def normalize(name: str) -> str:
    """Lowercase, strip legal suffixes, collapse whitespace/punctuation spacing."""
    n = name.strip()
    n = _LEGAL_SUFFIXES.sub("", n).strip()
    n = re.sub(r"[\.\-]", "", n)  # remove periods/hyphens (Open-AI -> OpenAI, Repl.it -> Replit)
    n = re.sub(r"\s+", " ", n).strip()
    return n.lower()


@dataclass
class ResolutionResult:
    raw_name: str
    canonical_name: str
    method: str  # "exact_seed_match" | "fuzzy_seed_match" | "no_seed_match"
    confidence: float  # 0-100; 100 for exact matches, rapidfuzz score for fuzzy, 0 for no-match


class EntityResolver:
    def __init__(self, seed_entities: Optional[dict] = None):
        self.seed_entities = seed_entities or SEED_ENTITIES

        # Build a flat lookup: normalized alias/canonical form -> canonical name
        self._exact_lookup: dict[str, str] = {}
        # Flat list of (normalized_form, canonical_name) for fuzzy matching
        self._fuzzy_candidates: list[tuple[str, str]] = []

        for canonical, aliases in self.seed_entities.items():
            all_forms = [canonical] + aliases
            for form in all_forms:
                norm = normalize(form)
                self._exact_lookup[norm] = canonical
                self._fuzzy_candidates.append((norm, canonical))

        self._fuzzy_choices = [c[0] for c in self._fuzzy_candidates]

    def resolve(self, raw_name: str) -> ResolutionResult:
        """Resolve one raw entity name to its canonical form."""
        norm = normalize(raw_name)

        # 1. Exact match
        if norm in self._exact_lookup:
            return ResolutionResult(
                raw_name=raw_name,
                canonical_name=self._exact_lookup[norm],
                method="exact_seed_match",
                confidence=100.0,
            )

        # 2. Fuzzy match against the seed database
        if self._fuzzy_choices:
            match = process.extractOne(norm, self._fuzzy_choices, scorer=fuzz.token_sort_ratio)
            if match is not None:
                matched_form, score, idx = match
                if score >= FUZZY_MATCH_THRESHOLD:
                    canonical = self._fuzzy_candidates[idx][1]
                    return ResolutionResult(
                        raw_name=raw_name,
                        canonical_name=canonical,
                        method="fuzzy_seed_match",
                        confidence=float(score),
                    )

        # 3. Not in the seed database -- this is the expected outcome for
        # the vast majority of real-world entities. The raw name itself
        # (title-cased for consistency) becomes its own canonical form.
        cleaned = _LEGAL_SUFFIXES.sub("", raw_name.strip()).strip()
        return ResolutionResult(
            raw_name=raw_name,
            canonical_name=cleaned or raw_name,
            method="no_seed_match",
            confidence=0.0,
        )

