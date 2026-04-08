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

# Question type prefixes to strip for concept extraction
_QUESTION_PREFIX = re.compile(
    r"(?i)^(what is|what are|what does|what do|define|describe|"
    r"how does|how do|how is|how are|what happens when|"
    r"what occurs when|explain|name)\s+"
)


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, and remove stopwords."""
    text = _PUNCT_RE.sub("", text.lower())
    words = [w for w in _WHITESPACE_RE.split(text) if w and w not in STOPWORDS]
    return " ".join(words)


def _extract_concept(front: str) -> str:
    """Extract the core concept from a question by stripping question prefixes.

    "What is NFS?" -> "nfs"
    "Define NFS." -> "nfs"
    "What does NFS stand for?" -> "nfs stand"
    """
    text = _PUNCT_RE.sub("", front.lower()).strip()
    text = _QUESTION_PREFIX.sub("", text).strip()
    words = [w for w in text.split() if w and w not in STOPWORDS]
    return " ".join(words)


def _content_words(text: str) -> set[str]:
    """Extract content words (non-stopword, len > 2) from text."""
    return {
        w for w in _PUNCT_RE.sub("", text.lower()).split()
        if w not in STOPWORDS and len(w) > 2
    }


def _similarity(a: str, b: str) -> float:
    """Return SequenceMatcher similarity ratio between two strings."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _pick_winner(card_i: RawCard, card_j: RawCard) -> int:
    """Choose which card to keep when duplicates are found.

    Returns the index (0 for i, 1 for j) of the card to KEEP.

    Winner selection order:
    1. Prefer notes over transcript
    2. Prefer longer (more complete) answer
    """
    # Prefer notes-derived cards
    i_is_notes = getattr(card_i, "source_type", "transcript") == "notes"
    j_is_notes = getattr(card_j, "source_type", "transcript") == "notes"
    if i_is_notes and not j_is_notes:
        return 0
    if j_is_notes and not i_is_notes:
        return 1

    # Prefer longer answer
    if len(card_i.back) >= len(card_j.back):
        return 0
    return 1


def deduplicate_cards(
    cards: list[RawCard],
    front_threshold: float = 0.75,
    back_threshold: float = 0.85,
) -> list[RawCard]:
    """Remove duplicate cards using a two-pass approach.

    Pass 1: Near-exact duplicate detection using normalized front/back similarity.
    Pass 2: Concept-aware overlap detection for same-fact cards with different wording.

    When duplicates are found, prefers notes-derived cards, then longer answers.
    Conservative: if uncertain, keeps both cards.
    """
    if len(cards) <= 1:
        return list(cards)

    normalized = [(normalize_text(c.front), normalize_text(c.back)) for c in cards]
    concepts = [_extract_concept(c.front) for c in cards]
    keep = [True] * len(cards)

    # Pass 1: Near-exact duplicate detection (existing behavior, improved winner selection)
    for i in range(len(cards)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(cards)):
            if not keep[j]:
                continue

            front_sim = _similarity(normalized[i][0], normalized[j][0])
            back_sim = _similarity(normalized[i][1], normalized[j][1])

            if front_sim >= front_threshold or back_sim >= back_threshold:
                winner = _pick_winner(cards[i], cards[j])
                if winner == 0:
                    keep[j] = False
                else:
                    keep[i] = False
                    break  # i is removed, stop comparing it

    # Pass 2: Concept-aware overlap detection
    # Only compare cards that survived Pass 1
    for i in range(len(cards)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(cards)):
            if not keep[j]:
                continue

            # Check if concepts match (high similarity after stripping question type)
            concept_sim = _similarity(concepts[i], concepts[j])
            if concept_sim < 0.8:
                continue

            # Concepts are similar — check if answers overlap significantly
            i_words = _content_words(cards[i].back)
            j_words = _content_words(cards[j].back)
            if not i_words or not j_words:
                continue

            # Jaccard similarity on answer content words
            overlap = len(i_words & j_words)
            union = len(i_words | j_words)
            answer_overlap = overlap / union if union else 0.0

            # Only dedup if answer overlap is substantial (conservative)
            if answer_overlap >= 0.5:
                winner = _pick_winner(cards[i], cards[j])
                if winner == 0:
                    keep[j] = False
                else:
                    keep[i] = False
                    break

    return [c for c, k in zip(cards, keep) if k]
