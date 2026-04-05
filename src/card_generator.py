"""Flashcard generation using Ollama."""

from __future__ import annotations

import json
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


CARD_GENERATION_PROMPT = """\
You are generating Anki flashcards from lecture notes.

Rules:
- Create only cards for facts that are clearly testable
- Prefer definitions, mechanisms, comparisons, formulas, cause/effect
- Avoid vague or redundant cards
- Keep answers concise (1-3 sentences max)
- Output valid JSON only, no markdown

Transcript chunk:
{chunk_text}

Return JSON array:
[
  {{
    "front": "What is...?",
    "back": "...",
    "tags": ["topic1", "topic2"]
  }}
]
"""


@dataclass
class RawCard:
    """A card parsed from LLM output before persisting."""

    front: str
    back: str
    tags: list[str]


LLMBackend = Callable[[str], str]


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


def generate_cards_for_chunk(
    chunk: TranscriptChunk,
    llm: LLMBackend | None = None,
) -> list[RawCard]:
    """Generate flashcards from a single transcript chunk."""
    prompt = CARD_GENERATION_PROMPT.format(chunk_text=chunk.text)
    backend = llm or _call_ollama
    response_text = backend(prompt)
    return _parse_cards_from_response(response_text)


def generate_cards_for_lecture(
    conn: sqlite3.Connection,
    lecture_id: int,
    llm: LLMBackend | None = None,
) -> list[Card]:
    """Generate and persist flashcards for all transcript chunks of a lecture."""
    config = get_config()
    segments = get_segments_for_lecture(conn, lecture_id)
    if not segments:
        raise ValueError(f"No transcript segments for lecture {lecture_id}")

    chunks = chunk_segments(
        segments,
        target_words=config.card_generation.chunk_target_words,
        max_words=config.card_generation.chunk_max_words,
    )

    delete_cards_for_lecture(conn, lecture_id)

    all_cards: list[Card] = []
    for chunk in chunks:
        raw_cards = generate_cards_for_chunk(chunk, llm=llm)
        for raw in raw_cards:
            card = create_card(
                conn,
                lecture_id=lecture_id,
                front=raw.front,
                back=raw.back,
                tags=raw.tags,
            )
            all_cards.append(card)

    return all_cards
