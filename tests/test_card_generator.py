import json
import sqlite3

import pytest

from src.card_generator import (
    RawCard,
    _parse_cards_from_response,
    generate_cards_for_chunk,
    generate_cards_for_lecture,
)
from src.chunker import TranscriptChunk
from src.db import add_segment, create_course, create_lecture, create_unit, get_cards_for_lecture, init_db


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()


class TestParseCardsFromResponse:
    def test_valid_json_array(self):
        text = json.dumps([
            {"front": "What is X?", "back": "X is Y.", "tags": ["t1"]},
            {"front": "Define Z.", "back": "Z means W.", "tags": []},
        ])
        cards = _parse_cards_from_response(text)
        assert len(cards) == 2
        assert cards[0].front == "What is X?"
        assert cards[1].tags == []

    def test_json_with_surrounding_text(self):
        text = 'Here are the cards:\n[{"front":"Q","back":"A","tags":[]}]\nDone.'
        cards = _parse_cards_from_response(text)
        assert len(cards) == 1

    def test_invalid_json(self):
        assert _parse_cards_from_response("not json") == []

    def test_skips_empty_front_back(self):
        text = json.dumps([
            {"front": "", "back": "A", "tags": []},
            {"front": "Q", "back": "", "tags": []},
            {"front": "Q", "back": "A", "tags": []},
        ])
        cards = _parse_cards_from_response(text)
        assert len(cards) == 1

    def test_string_tags_converted_to_list(self):
        text = json.dumps([{"front": "Q", "back": "A", "tags": "single"}])
        cards = _parse_cards_from_response(text)
        assert cards[0].tags == ["single"]


class TestGenerateCardsForChunk:
    def test_uses_llm_backend(self):
        chunk = TranscriptChunk(text="ML is...", start_time=0, end_time=10, segment_count=1)

        def fake_llm(prompt: str) -> str:
            return json.dumps([{"front": "What is ML?", "back": "ML is...", "tags": ["ml"]}])

        cards = generate_cards_for_chunk(chunk, llm=fake_llm)
        assert len(cards) == 1
        assert cards[0].front == "What is ML?"


class TestGenerateCardsForLecture:
    def test_generates_and_persists_cards(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        add_segment(db, lecture.id, 0, 10, "Machine learning is a field of study.")
        add_segment(db, lecture.id, 10, 20, "It involves training models on data.")

        def fake_llm(prompt: str) -> str:
            return json.dumps([
                {"front": "What is ML?", "back": "A field of study.", "tags": ["ml"]},
            ])

        cards = generate_cards_for_lecture(db, lecture.id, llm=fake_llm)
        assert len(cards) >= 1
        assert cards[0].status == "pending"

        persisted = get_cards_for_lecture(db, lecture.id)
        assert len(persisted) == len(cards)

    def test_regeneration_replaces_prior_cards(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        add_segment(db, lecture.id, 0, 10, "Some content about ML.")

        def fake_v1(prompt: str) -> str:
            return json.dumps([{"front": "V1 Q", "back": "V1 A", "tags": []}])

        def fake_v2(prompt: str) -> str:
            return json.dumps([{"front": "V2 Q", "back": "V2 A", "tags": []}])

        # First generation
        cards1 = generate_cards_for_lecture(db, lecture.id, llm=fake_v1)
        assert len(cards1) == 1
        assert cards1[0].front == "V1 Q"

        # Second generation should replace
        cards2 = generate_cards_for_lecture(db, lecture.id, llm=fake_v2)
        assert len(cards2) == 1
        assert cards2[0].front == "V2 Q"

        # Only v2 cards remain
        persisted = get_cards_for_lecture(db, lecture.id)
        assert len(persisted) == 1
        assert persisted[0].front == "V2 Q"

    def test_raises_on_no_segments(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)

        with pytest.raises(ValueError, match="No transcript segments"):
            generate_cards_for_lecture(db, lecture.id)
