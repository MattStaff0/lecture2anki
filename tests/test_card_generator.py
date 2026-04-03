import sqlite3

import pytest

from src.card_generator import GeneratedCard, generate_cards_for_lecture, parse_generated_cards
from src.config import reset_config
from src.db import (
    add_segment,
    create_card,
    create_course,
    create_lecture,
    create_unit,
    get_cards_for_lecture,
    init_db,
)


@pytest.fixture(autouse=True)
def reset_cached_config():
    reset_config()
    yield
    reset_config()


class TestCardParsing:
    def test_parse_generated_cards_filters_blank_fields(self):
        cards = parse_generated_cards(
            '{"cards":['
            '{"front":"Q1","back":"A1","tags":["ai"]},'
            '{"front":"","back":"skip","tags":[]}'
            "]}"
        )

        assert cards == [GeneratedCard(front="Q1", back="A1", tags=["ai"])]


class TestCardGeneration:
    def test_generate_cards_for_lecture_replaces_existing_cards(self, monkeypatch):
        monkeypatch.setenv("CHUNK_TARGET_WORDS", "4")
        monkeypatch.setenv("CHUNK_MAX_WORDS", "5")
        monkeypatch.setenv("DATABASE_PATH", "/tmp/lecture2anki-test.db")

        conn = sqlite3.connect(":memory:")
        init_db(conn)
        course = create_course(conn, "AI")
        unit = create_unit(conn, course.id, "Midterm 1")
        lecture = create_lecture(conn, unit.id, title="Intro to ML")
        add_segment(conn, lecture.id, 0.0, 5.0, "one two")
        add_segment(conn, lecture.id, 5.0, 10.0, "three four")
        add_segment(conn, lecture.id, 10.0, 15.0, "five six seven")
        create_card(conn, lecture.id, "old", "card", ["stale"])

        def fake_generator(chunk_text: str):
            return [
                GeneratedCard(
                    front=f"Question about {chunk_text.split()[0]}",
                    back="Answer",
                    tags=["generated"],
                )
            ]

        cards = generate_cards_for_lecture(conn, lecture.id, generator=fake_generator)
        stored_cards = get_cards_for_lecture(conn, lecture.id)

        assert len(cards) == 2
        assert len(stored_cards) == 2
        assert all(card.tags == ["generated"] for card in stored_cards)
        assert all(card.front != "old" for card in stored_cards)
