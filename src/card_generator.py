"""Flashcard generation using Ollama."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from src.chunker import TranscriptChunk, chunk_segments
from src.config import get_config
from src.db import create_card, delete_cards_for_lecture, get_segments_for_lecture
from src.models import Card

try:
    import ollama as ollama_client
except ModuleNotFoundError:
    ollama_client = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

CARD_GENERATION_PROMPT = """\
You are a professor creating study flashcards for students.

Generate exactly {min_cards} to {max_cards} Anki flashcards from the lecture transcript below.

Card types to use:
- Definitions: "What is X?" / "X is..."
- Comparisons: "How does X differ from Y?"
- Cause/Effect: "What happens when X?"
- Formulas/Steps: "What are the steps for X?"

Rules:
- ONLY use facts stated in the transcript. Do NOT add external knowledge or make up definitions.
- Every question must have a single, specific, factual answer.
- Do NOT ask "Why is X important?" or "What is the significance of X?" — these are too vague.
- Do NOT create cards about opinions, anecdotes, or filler.
- Keep answers to 1-2 sentences (under 30 words).
- Ignore filler words, false starts, and incomplete sentences in the transcript.
- Respond with ONLY a JSON array, no other text.

GOOD example:
{{"front": "What does NFS stand for?", "back": "Network File System.", "tags": ["networking"]}}

BAD example (too vague, do not create cards like this):
{{"front": "Why is NFS important?", "back": "It is important because it enables file sharing.", "tags": ["networking"]}}

--- TRANSCRIPT START ---
{chunk_text}
--- TRANSCRIPT END ---

JSON array:
[
  {{"front": "question", "back": "answer", "tags": ["topic"]}},
  {{"front": "question", "back": "answer", "tags": ["topic"]}}
]
"""

_VALIDATION_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "must",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "and", "but", "or", "not", "so", "it", "its", "this", "that",
    "what", "which", "who", "how", "when", "where", "why",
})

_VAGUE_PATTERNS = re.compile(
    r"(?i)^(why is .+ important|what is the significance|what is the role|"
    r"explain the role|explain the importance|how important)"
)


@dataclass
class RawCard:
    """A card parsed from LLM output before persisting."""

    front: str
    back: str
    tags: list[str]


LLMBackend = Callable[[str], str]
ProgressCallback = Callable[[str, str, str], None]


def _call_ollama(prompt: str) -> str:
    """Call the Ollama API and return the response text."""
    if ollama_client is None:
        raise RuntimeError(
            "Card generation requires the ollama package. "
            "Run `pip install ollama` to install it."
        )
    config = get_config()
    response = ollama_client.generate(
        model=config.ollama.model,
        prompt=prompt,
        options={"num_ctx": config.ollama.context_size},
    )
    return response["response"]


def _parse_cards_from_response(text: str) -> list[RawCard]:
    """Extract card JSON from LLM response text."""
    text = text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        items: list[dict[str, Any]] = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []

    cards: list[RawCard] = []
    for item in items:
        front = (item.get("front") or "").strip()
        back = (item.get("back") or "").strip()
        if not front or not back:
            continue
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        cards.append(RawCard(front=front, back=back, tags=tags))
    return cards


def _validate_raw_cards(cards: list[RawCard], chunk_text: str) -> list[RawCard]:
    """Filter out low-quality cards based on heuristic checks."""
    chunk_words = set(chunk_text.lower().split())
    valid: list[RawCard] = []
    for card in cards:
        front, back = card.front, card.back
        # Too short
        if len(front) < 10 or len(back) < 5:
            logger.debug("Rejected (too short): %s", front)
            continue
        # Missing question mark
        if "?" not in front:
            logger.debug("Rejected (no question mark): %s", front)
            continue
        # Answer too long
        if len(back.split()) > 50:
            logger.debug("Rejected (answer too long): %s", front)
            continue
        # Vague question pattern
        if _VAGUE_PATTERNS.match(front):
            logger.debug("Rejected (vague pattern): %s", front)
            continue
        # Hallucination check: at least one content word from answer must be in chunk
        answer_words = {
            w for w in re.sub(r"[^\w\s]", "", back.lower()).split()
            if w not in _VALIDATION_STOPWORDS and len(w) > 2
        }
        if answer_words and not answer_words & chunk_words:
            logger.debug("Rejected (hallucination): %s", front)
            continue
        valid.append(card)
    return valid


def generate_cards_for_chunk(
    chunk: TranscriptChunk,
    llm: LLMBackend | None = None,
) -> list[RawCard]:
    """Generate flashcards from a single transcript chunk."""
    config = get_config()
    prompt = CARD_GENERATION_PROMPT.format(
        chunk_text=chunk.text,
        min_cards=config.card_generation.cards_min_per_chunk,
        max_cards=config.card_generation.cards_max_per_chunk,
    )
    backend = llm or _call_ollama
    response_text = backend(prompt)
    raw_cards = _parse_cards_from_response(response_text)
    return _validate_raw_cards(raw_cards, chunk.text)


def generate_cards_for_lecture(
    conn: sqlite3.Connection,
    lecture_id: int,
    llm: LLMBackend | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[Card]:
    """Generate and persist flashcards for all transcript chunks of a lecture."""

    def _emit(stage: str, message: str, level: str = "info") -> None:
        logger.log(
            getattr(logging, level.upper(), logging.INFO),
            "lecture=%d stage=%s %s", lecture_id, stage, message,
        )
        if on_progress:
            on_progress(stage, message, level)

    config = get_config()
    _emit("loading_segments", "Loading transcript segments...")
    segments = get_segments_for_lecture(conn, lecture_id)
    if not segments:
        raise ValueError(f"No transcript segments for lecture {lecture_id}")
    _emit("loading_segments", f"Loaded {len(segments)} segments")

    _emit("chunking", "Chunking transcript for LLM...")
    chunks = chunk_segments(
        segments,
        target_words=config.card_generation.chunk_target_words,
        max_words=config.card_generation.chunk_max_words,
    )
    _emit("chunking", f"Created {len(chunks)} chunks (model={config.ollama.model})")

    delete_cards_for_lecture(conn, lecture_id)

    from src.deduplicator import deduplicate_cards

    all_raw: list[RawCard] = []
    for i, chunk in enumerate(chunks, 1):
        _emit("generating", f"Generating cards for chunk {i}/{len(chunks)}...")
        raw_cards = generate_cards_for_chunk(chunk, llm=llm)
        all_raw.extend(raw_cards)
        _emit("generating", f"Chunk {i}/{len(chunks)} done — {len(raw_cards)} cards")

    pre_dedup = len(all_raw)
    all_raw = deduplicate_cards(
        all_raw,
        front_threshold=config.card_generation.dedup_threshold,
    )
    removed = pre_dedup - len(all_raw)
    if removed:
        _emit("dedup", f"Removed {removed} duplicate cards")

    all_cards: list[Card] = []
    for raw in all_raw:
        card = create_card(
            conn,
            lecture_id=lecture_id,
            front=raw.front,
            back=raw.back,
            tags=raw.tags,
        )
        all_cards.append(card)

    _emit("done", f"Generation complete — {len(all_cards)} total cards")
    return all_cards
