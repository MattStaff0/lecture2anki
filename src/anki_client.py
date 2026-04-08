"""AnkiConnect client for syncing flashcards to Anki."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

import requests

from src.config import get_config
from src.db import get_approved_unsynced_cards, get_deck_path_for_lecture, mark_card_synced
from src.models import Card

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str, str], None]


@dataclass
class SyncResult:
    """Summary of an Anki sync operation."""

    synced: int
    failed: int
    errors: list[str]


def _anki_request(action: str, **params: Any) -> Any:
    """Send a request to AnkiConnect and return the result."""
    config = get_config()
    payload: dict[str, Any] = {"action": action, "version": 6}
    if params:
        payload["params"] = params
    response = requests.post(config.anki.connect_url, json=payload, timeout=10)
    response.raise_for_status()
    body = response.json()
    if body.get("error"):
        raise RuntimeError(f"AnkiConnect error: {body['error']}")
    return body.get("result")


def check_connection() -> bool:
    """Check if AnkiConnect is reachable."""
    try:
        _anki_request("version")
        return True
    except Exception:
        return False


def ensure_deck(deck_name: str) -> None:
    """Create a deck if it doesn't exist."""
    _anki_request("createDeck", deck=deck_name)


def add_note(deck_name: str, card: Card) -> int:
    """Add a card as a note to Anki and return the note ID."""
    config = get_config()
    note_id = _anki_request(
        "addNote",
        note={
            "deckName": deck_name,
            "modelName": config.anki.note_type,
            "fields": {"Front": card.front, "Back": card.back},
            "tags": card.tags + ["lecture2anki"],
        },
    )
    return note_id


def sync_lecture(
    conn: sqlite3.Connection,
    lecture_id: int,
    on_progress: ProgressCallback | None = None,
) -> SyncResult:
    """Sync all approved unsynced cards for a lecture to Anki."""

    def _emit(stage: str, message: str, level: str = "info") -> None:
        logger.log(
            getattr(logging, level.upper(), logging.INFO),
            "lecture=%d stage=%s %s", lecture_id, stage, message,
        )
        if on_progress:
            on_progress(stage, message, level)

    cards = get_approved_unsynced_cards(conn, lecture_id)
    if not cards:
        raise ValueError(f"No approved unsynced cards for lecture {lecture_id}")
    _emit("preparing", f"Found {len(cards)} approved unsynced cards")

    deck_path = get_deck_path_for_lecture(conn, lecture_id)
    config = get_config()
    full_deck = config.anki.get_deck_path(
        deck_path.split("::")[0],
        deck_path.split("::")[1],
    ) if "::" in deck_path else deck_path
    _emit("preparing", f"Resolved deck: {full_deck}")

    _emit("creating_deck", f"Ensuring deck exists: {full_deck}")
    ensure_deck(full_deck)

    synced = 0
    failed = 0
    errors: list[str] = []

    for i, card in enumerate(cards, 1):
        try:
            note_id = add_note(full_deck, card)
            mark_card_synced(conn, card.id, note_id)
            synced += 1
        except Exception as exc:
            failed += 1
            errors.append(f"Card {card.id}: {exc}")
            _emit("syncing", f"Card {card.id} failed: {exc}", "warning")

        if i % 5 == 0 or i == len(cards):
            _emit("syncing", f"Progress: {i}/{len(cards)} cards processed ({synced} synced, {failed} failed)")

    _emit("done", f"Sync complete — {synced} synced, {failed} failed")
    return SyncResult(synced=synced, failed=failed, errors=errors)
