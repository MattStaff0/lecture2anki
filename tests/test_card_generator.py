import json
import sqlite3

import pytest

from src.card_generator import (
    RawCard,
    _parse_cards_from_response,
    _validate_raw_cards,
    generate_cards_for_chunk,
    generate_cards_for_lecture,
)
from src.chunker import TranscriptChunk
from src.db import add_segment, create_course, create_lecture, create_unit, get_cards_for_lecture, init_db, update_lecture_notes


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


class TestValidateRawCards:
    def test_rejects_short_front(self):
        cards = [RawCard(front="Q?", back="Answer here.", tags=[])]
        assert _validate_raw_cards(cards, "some chunk text answer here") == []

    def test_rejects_missing_question_mark(self):
        cards = [RawCard(front="What is machine learning", back="A field of study.", tags=[])]
        assert _validate_raw_cards(cards, "machine learning field study") == []

    def test_rejects_long_answer(self):
        long_back = " ".join(["word"] * 51)
        cards = [RawCard(front="What is this concept?", back=long_back, tags=[])]
        assert _validate_raw_cards(cards, "word concept") == []

    def test_rejects_vague_pattern(self):
        cards = [RawCard(front="Why is NFS important?", back="Because it shares files.", tags=[])]
        assert _validate_raw_cards(cards, "nfs shares files") == []

    def test_rejects_hallucination(self):
        cards = [RawCard(front="What is SFTP?", back="Secure browser protocol.", tags=[])]
        # "browser" and "protocol" and "secure" not in chunk
        assert _validate_raw_cards(cards, "nfs network file system") == []

    def test_keeps_valid_card(self):
        cards = [RawCard(front="What is NFS?", back="Network File System.", tags=["net"])]
        result = _validate_raw_cards(cards, "NFS is a network file system for sharing")
        assert len(result) == 1


class TestGenerateCardsForChunk:
    def test_uses_llm_backend(self):
        chunk = TranscriptChunk(
            text="Machine learning is a field of study involving models.",
            start_time=0, end_time=10, segment_count=1,
        )

        def fake_llm(prompt: str) -> str:
            return json.dumps([
                {"front": "What is machine learning?", "back": "A field of study involving models.", "tags": ["ml"]},
            ])

        cards = generate_cards_for_chunk(chunk, llm=fake_llm)
        assert len(cards) == 1
        assert cards[0].front == "What is machine learning?"


class TestGenerateCardsForLecture:
    def test_generates_and_persists_cards(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        add_segment(db, lecture.id, 0, 10, "Machine learning is a field of study.")
        add_segment(db, lecture.id, 10, 20, "It involves training models on data.")

        def fake_llm(prompt: str) -> str:
            return json.dumps([
                {"front": "What is machine learning?", "back": "A field of study involving training models.", "tags": ["ml"]},
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
        add_segment(db, lecture.id, 0, 10, "Some content about machine learning models.")

        def fake_v1(prompt: str) -> str:
            return json.dumps([
                {"front": "What is machine learning?", "back": "Content about models.", "tags": []},
            ])

        def fake_v2(prompt: str) -> str:
            return json.dumps([
                {"front": "What are machine learning models?", "back": "Models trained on content.", "tags": []},
            ])

        cards1 = generate_cards_for_lecture(db, lecture.id, llm=fake_v1)
        assert len(cards1) == 1

        cards2 = generate_cards_for_lecture(db, lecture.id, llm=fake_v2)
        assert len(cards2) == 1

        persisted = get_cards_for_lecture(db, lecture.id)
        assert len(persisted) == 1
        assert persisted[0].front == cards2[0].front

    def test_deduplication_across_chunks(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        add_segment(db, lecture.id, 0, 10, "NFS is a network file system for sharing files.")
        add_segment(db, lecture.id, 10, 20, "NFS stands for network file system protocol.")

        def fake_llm(prompt: str) -> str:
            return json.dumps([
                {"front": "What is NFS?", "back": "Network file system for sharing files.", "tags": ["net"]},
            ])

        cards = generate_cards_for_lecture(db, lecture.id, llm=fake_llm)
        # Two chunks produce same card, dedup should remove one
        assert len(cards) == 1

    def test_raises_on_no_segments_and_no_notes(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)

        with pytest.raises(ValueError, match="No transcript segments"):
            generate_cards_for_lecture(db, lecture.id)

    def test_notes_only_generation(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        update_lecture_notes(db, lecture.id, "NFS is a network file system for sharing files across machines.")

        def fake_llm(prompt: str) -> str:
            return json.dumps([
                {"front": "What is NFS?", "back": "A network file system for sharing files.", "tags": ["net"]},
            ])

        cards = generate_cards_for_lecture(db, lecture.id, llm=fake_llm)
        assert len(cards) >= 1
        persisted = get_cards_for_lecture(db, lecture.id)
        assert len(persisted) == len(cards)

    def test_combined_transcript_and_notes(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        add_segment(db, lecture.id, 0, 10, "Machine learning uses training data.")
        update_lecture_notes(db, lecture.id, "NFS is a network file system for sharing files.")

        call_count = [0]

        def fake_llm(prompt: str) -> str:
            call_count[0] += 1
            if "machine learning" in prompt.lower():
                return json.dumps([
                    {"front": "What does machine learning use?", "back": "Training data.", "tags": ["ml"]},
                ])
            return json.dumps([
                {"front": "What is NFS?", "back": "A network file system for sharing files.", "tags": ["net"]},
            ])

        cards = generate_cards_for_lecture(db, lecture.id, llm=fake_llm)
        assert call_count[0] == 2  # one transcript chunk + one notes chunk
        assert len(cards) == 2

    def test_cross_source_dedup(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        add_segment(db, lecture.id, 0, 10, "NFS is a network file system for sharing files.")
        update_lecture_notes(db, lecture.id, "NFS is a network file system for sharing files across machines.")

        def fake_llm(prompt: str) -> str:
            return json.dumps([
                {"front": "What is NFS?", "back": "Network file system for sharing files.", "tags": ["net"]},
            ])

        cards = generate_cards_for_lecture(db, lecture.id, llm=fake_llm)
        # Both sources produce the same card, dedup should collapse to 1
        assert len(cards) == 1
