"""Lightweight card deduplication using string similarity."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.card_generator import RawCard

STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "about",
    "and", "but", "or", "nor", "not", "so", "yet",
    "it", "its", "this", "that", "these", "those",
    "what", "which", "who", "whom", "how", "when", "where", "why",
})

_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, and remove stopwords."""
    text = _PUNCT_RE.sub("", text.lower())
    words = [w for w in _WHITESPACE_RE.split(text) if w and w not in STOPWORDS]
    return " ".join(words)


def _similarity(a: str, b: str) -> float:
    """Return SequenceMatcher similarity ratio between two strings."""
    return SequenceMatcher(None, a, b).ratio()


def deduplicate_cards(
    cards: list[RawCard],
    front_threshold: float = 0.75,
    back_threshold: float = 0.85,
) -> list[RawCard]:
    """Remove near-duplicate cards based on front or back similarity.

    When two cards are similar, the one with the longer answer is kept.
    """
    if len(cards) <= 1:
        return list(cards)

    normalized = [(normalize_text(c.front), normalize_text(c.back)) for c in cards]
    keep = [True] * len(cards)

    for i in range(len(cards)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(cards)):
            if not keep[j]:
                continue

            front_sim = _similarity(normalized[i][0], normalized[j][0])
            back_sim = _similarity(normalized[i][1], normalized[j][1])

            if front_sim >= front_threshold or back_sim >= back_threshold:
                # Keep the card with the longer answer
                if len(cards[i].back) >= len(cards[j].back):
                    keep[j] = False
                else:
                    keep[i] = False
                    break  # i is removed, stop comparing it

    return [c for c, k in zip(cards, keep) if k]
