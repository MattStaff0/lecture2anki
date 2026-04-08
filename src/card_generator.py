"""Flashcard generation using Ollama."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from src.chunker import TranscriptChunk, chunk_segments, chunk_text
from src.config import get_config
from src.db import create_card, delete_cards_for_lecture, get_lecture_by_id, get_segments_for_lecture
from src.models import Card

try:
    import ollama as ollama_client
except ModuleNotFoundError:
    ollama_client = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

CARD_GENERATION_PROMPT = """\
You are a careful professor creating high-quality Anki study flashcards from a lecture transcript.

Your job is to extract the most testable, concrete, high-yield facts a student would likely need for an exam.

Generate between {min_cards} and {max_cards} flashcards from the transcript below.

PRIORITIES:
- Prefer facts that are likely to appear on quizzes, exams, or study guides.
- Prioritize:
  - definitions
  - terminology
  - distinctions and comparisons
  - mechanisms
  - cause/effect relationships
  - formulas
  - ordered steps or processes
  - named concepts, models, systems, or methods
- Ignore:
  - filler
  - false starts
  - repeated points
  - jokes
  - anecdotes
  - motivational comments
  - broad commentary without a specific factual takeaway
  - incomplete or unclear statements

ALLOWED CARD TYPES:
- Definition:
  "What is X?"
  "X is..."
- Terminology:
  "What does X stand for?"
- Comparison:
  "How does X differ from Y?"
- Cause/Effect:
  "What happens when X?"
  "What causes X?"
- Process/Steps:
  "What are the steps in X?"
  "What happens first in X?"
- Formula/Rule:
  "What is the formula for X?"
  "What rule describes X?"

STRICT RULES:
- ONLY use facts explicitly stated in the transcript.
- Do NOT add outside knowledge.
- Do NOT infer missing textbook facts unless the transcript directly states them.
- Do NOT make up definitions or fill in gaps.
- Every card must have a single, specific, factual answer.
- Do NOT create vague cards.
- Do NOT ask:
  - "Why is X important?"
  - "What is the significance of X?"
  - "What is the role of X?"
  - "What should you know about X?"
  - "Describe X broadly."
- Do NOT create cards about opinions, anecdotes, or filler.
- Do NOT create duplicate or near-duplicate cards.
- Do NOT create cards whose answer is too broad or subjective.
- If the transcript is noisy, mentally clean it before extracting facts.
- If there are fewer than {min_cards} strong facts in this chunk, return fewer cards rather than weak cards.

QUALITY BAR:
A good card:
- tests one idea
- has one correct answer
- is specific enough for retrieval practice
- is concise and unambiguous
- would help a student study efficiently

A bad card:
- is vague
- is open-ended
- repeats another card
- asks for an opinion
- uses knowledge not stated in the transcript

ANSWER RULES:
- Keep each "back" under 30 words.
- Prefer 1 sentence.
- Use 2 short sentences only if necessary for clarity.
- Use plain, direct wording.
- Preserve technical accuracy.

TAG RULES:
- "tags" must be an array of 1 to 3 short lowercase topic tags.

OUTPUT RULES:
- Respond with ONLY a valid JSON array.
- No markdown.
- No code fences.
- No explanation before or after the JSON.
- Each item must contain exactly these keys:
  - "front"
  - "back"
  - "tags"

OUTPUT EXAMPLE:
[
  {{"front": "What does NFS stand for?", "back": "Network File System.", "tags": ["networking"]}},
  {{"front": "How does SRAM differ from DRAM?", "back": "SRAM does not require refresh, while DRAM must be periodically refreshed.", "tags": ["memory", "hardware"]}}
]

--- TRANSCRIPT START ---
{chunk_text}
--- TRANSCRIPT END ---
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
    r"(?i)^("
    r"why is .+ important|"
    r"what is the significance|"
    r"what is the role|"
    r"explain the role|"
    r"explain the importance|"
    r"how important|"
    r"why does .+ matter|"
    r"what should you know about|"
    r"describe .+ broadly|"
    r"what is the main idea of"
    r")"
)


@dataclass
class RawCard:
    """A card parsed from LLM output before persisting."""

    front: str
    back: str
    tags: list[str]
    source_type: str = "transcript"  # "transcript" or "notes"


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
    generate_kwargs: dict[str, Any] = {
        "model": config.ollama.model,
        "prompt": prompt,
        "options": {
            "num_ctx": config.ollama.context_size,
            "temperature": 0.2,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "num_predict": 1200,
        },
    }

    try:
        response = ollama_client.generate(format="json", **generate_kwargs)
    except TypeError:
        response = ollama_client.generate(**generate_kwargs)
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
    """Generate flashcards from a single transcript or notes chunk."""
    config = get_config()
    prompt = CARD_GENERATION_PROMPT.format(
        chunk_text=chunk.text,
        min_cards=config.card_generation.cards_min_per_chunk,
        max_cards=config.card_generation.cards_max_per_chunk,
    )
    backend = llm or _call_ollama
    response_text = backend(prompt)
    raw_cards = _parse_cards_from_response(response_text)
    validated = _validate_raw_cards(raw_cards, chunk.text)
    # Tag each card with the chunk's source type
    for card in validated:
        card.source_type = chunk.source_type
    return validated


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

    # Load transcript segments
    _emit("loading_segments", "Loading transcript segments...")
    segments = get_segments_for_lecture(conn, lecture_id)
    _emit("loading_segments", f"Loaded {len(segments)} segments")

    # Load lecture notes
    lecture = get_lecture_by_id(conn, lecture_id)
    has_notes = bool(lecture and lecture.notes_text and lecture.notes_text.strip())

    if not segments and not has_notes:
        raise ValueError(f"No transcript segments or notes for lecture {lecture_id}")

    # Build transcript chunks
    chunks: list[TranscriptChunk] = []
    if segments:
        _emit("chunking", "Chunking transcript for LLM...")
        transcript_chunks = chunk_segments(
            segments,
            target_words=config.card_generation.chunk_target_words,
            max_words=config.card_generation.chunk_max_words,
        )
        chunks.extend(transcript_chunks)
        _emit("chunking", f"Created {len(transcript_chunks)} transcript chunks")

    # Build notes chunks
    if has_notes:
        _emit("chunking", "Chunking lecture notes...")
        notes_chunks = chunk_text(
            lecture.notes_text,
            target_words=config.card_generation.chunk_target_words,
            max_words=config.card_generation.chunk_max_words,
        )
        chunks.extend(notes_chunks)
        _emit("chunking", f"Added {len(notes_chunks)} notes chunks")

    _emit("chunking", f"Total: {len(chunks)} chunks (model={config.ollama.model})")

    delete_cards_for_lecture(conn, lecture_id)

    from src.deduplicator import deduplicate_cards

    all_raw: list[RawCard] = []
    for i, chunk in enumerate(chunks, 1):
        source_label = chunk.source_type
        _emit("generating", f"Generating cards for {source_label} chunk {i}/{len(chunks)}...")
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
