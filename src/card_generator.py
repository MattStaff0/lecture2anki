"""Flashcard generation via a local Ollama model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import requests

from src.chunker import chunk_segments
from src.config import get_config
from src.db import create_card, delete_cards_for_lecture, get_segments_for_lecture
from src.models import Card


@dataclass
class GeneratedCard:
    """A generated flashcard before persistence."""

    front: str
    back: str
    tags: list[str]


GeneratorBackend = Callable[[str], list[GeneratedCard]]


def build_generation_prompt(text: str) -> str:
    """Build the prompt sent to the local LLM."""
    config = get_config()
    return (
        "You create high-quality Anki flashcards from lecture transcripts.\n"
        "Return strict JSON with this shape only:\n"
        '{"cards":[{"front":"question","back":"answer","tags":["tag1","tag2"]}]}\n'
        f"Generate between {config.card_generation.cards_min_per_chunk} and "
        f"{config.card_generation.cards_max_per_chunk} cards.\n"
        "Use concise basic front/back cards only. Avoid cloze cards. "
        "Prefer concept checks, definitions, mechanisms, and important comparisons.\n"
        "Transcript:\n"
        f"{text}"
    )


def generate_cards_from_text(text: str) -> list[GeneratedCard]:
    """Generate flashcards for a chunk of transcript text using Ollama."""
    config = get_config()
    response = requests.post(
        f"{config.ollama.host}/api/generate",
        json={
            "model": config.ollama.model,
            "prompt": build_generation_prompt(text),
            "stream": False,
            "format": "json",
            "options": {"num_ctx": config.ollama.context_size},
        },
        timeout=120,
    )
    response.raise_for_status()

    payload = response.json()
    raw_json = payload.get("response", "{}")
    return parse_generated_cards(raw_json)


def parse_generated_cards(raw_json: str) -> list[GeneratedCard]:
    """Parse strict JSON card output from the LLM."""
    payload = json.loads(raw_json)
    cards = payload.get("cards", [])
    parsed_cards: list[GeneratedCard] = []

    for card in cards:
        front = str(card["front"]).strip()
        back = str(card["back"]).strip()
        tags = [str(tag).strip() for tag in card.get("tags", []) if str(tag).strip()]
        if not front or not back:
            continue
        parsed_cards.append(GeneratedCard(front=front, back=back, tags=tags))

    return parsed_cards


def generate_cards_for_lecture(
    conn,
    lecture_id: int,
    generator: GeneratorBackend | None = None,
) -> list[Card]:
    """Generate cards for a lecture from its transcript segments."""
    config = get_config()
    segments = get_segments_for_lecture(conn, lecture_id)
    if not segments:
        raise ValueError(f"No transcript segments found for lecture {lecture_id}")

    chunks = chunk_segments(
        segments,
        target_words=config.card_generation.chunk_target_words,
        max_words=config.card_generation.chunk_max_words,
    )
    backend = generator or generate_cards_from_text

    delete_cards_for_lecture(conn, lecture_id)
    stored_cards: list[Card] = []
    for chunk in chunks:
        for generated_card in backend(chunk.text):
            stored_cards.append(
                create_card(
                    conn,
                    lecture_id,
                    generated_card.front,
                    generated_card.back,
                    generated_card.tags,
                )
            )

    return stored_cards
