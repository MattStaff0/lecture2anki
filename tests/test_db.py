import json
import sqlite3

import pytest

from src.db import (
    add_segment,
    create_card,
    create_course,
    create_lecture,
    create_unit,
    get_cards_for_lecture,
    get_course_by_id,
    get_courses,
    get_deck_path_for_lecture,
    get_lecture_by_id,
    get_lectures_for_unit,
    get_segments_for_lecture,
    get_units_for_course,
    get_unsynced_cards,
    init_db,
    mark_card_synced,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()


# --- Courses ---


class TestCourses:
    def test_create_course(self, db):
        course = create_course(db, "AI")
        assert course.id is not None
        assert course.name == "AI"
        assert course.created_at is not None

    def test_get_courses(self, db):
        create_course(db, "AI")
        create_course(db, "OS")
        courses = get_courses(db)
        assert len(courses) == 2
        names = [c.name for c in courses]
        assert "AI" in names
        assert "OS" in names

    def test_get_course_by_id(self, db):
        created = create_course(db, "Nutrition")
        fetched = get_course_by_id(db, created.id)
        assert fetched is not None
        assert fetched.name == "Nutrition"
        assert fetched.id == created.id

    def test_get_course_by_id_not_found(self, db):
        result = get_course_by_id(db, 999)
        assert result is None

    def test_duplicate_course_raises_error(self, db):
        create_course(db, "AI")
        with pytest.raises(sqlite3.IntegrityError):
            create_course(db, "AI")


# --- Units ---


class TestUnits:
    def test_create_unit(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        assert unit.id is not None
        assert unit.course_id == course.id
        assert unit.name == "Midterm 1"
        assert unit.sort_order == 0

    def test_create_unit_with_sort_order(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1", sort_order=1)
        assert unit.sort_order == 1

    def test_get_units_for_course(self, db):
        course = create_course(db, "AI")
        create_unit(db, course.id, "Final", sort_order=2)
        create_unit(db, course.id, "Midterm 1", sort_order=0)
        create_unit(db, course.id, "Midterm 2", sort_order=1)

        units = get_units_for_course(db, course.id)
        assert len(units) == 3
        assert units[0].name == "Midterm 1"
        assert units[1].name == "Midterm 2"
        assert units[2].name == "Final"

    def test_duplicate_unit_same_course_raises_error(self, db):
        course = create_course(db, "AI")
        create_unit(db, course.id, "Midterm 1")
        with pytest.raises(sqlite3.IntegrityError):
            create_unit(db, course.id, "Midterm 1")

    def test_same_unit_name_different_courses(self, db):
        ai = create_course(db, "AI")
        os_course = create_course(db, "OS")
        unit1 = create_unit(db, ai.id, "Midterm 1")
        unit2 = create_unit(db, os_course.id, "Midterm 1")
        assert unit1.id != unit2.id


# --- Lectures ---


class TestLectures:
    def test_create_lecture(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id, title="Intro to ML")
        assert lecture.id is not None
        assert lecture.unit_id == unit.id
        assert lecture.title == "Intro to ML"
        assert lecture.recorded_at is not None

    def test_create_lecture_no_title(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        assert lecture.title is None

    def test_get_lectures_for_unit(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        create_lecture(db, unit.id, title="Lecture 1")
        create_lecture(db, unit.id, title="Lecture 2")

        lectures = get_lectures_for_unit(db, unit.id)
        assert len(lectures) == 2

    def test_get_lecture_by_id(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        created = create_lecture(db, unit.id, title="Lecture 1")
        fetched = get_lecture_by_id(db, created.id)
        assert fetched is not None
        assert fetched.title == "Lecture 1"

    def test_get_lecture_by_id_not_found(self, db):
        result = get_lecture_by_id(db, 999)
        assert result is None


# --- Segments ---


class TestSegments:
    def test_add_segment(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        segment = add_segment(db, lecture.id, 0.0, 15.5, "Hello class")
        assert segment.id is not None
        assert segment.lecture_id == lecture.id
        assert segment.start_time == 0.0
        assert segment.end_time == 15.5
        assert segment.text == "Hello class"

    def test_get_segments_for_lecture(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        add_segment(db, lecture.id, 30.0, 45.0, "Second segment")
        add_segment(db, lecture.id, 0.0, 15.0, "First segment")
        add_segment(db, lecture.id, 15.0, 30.0, "Middle segment")

        segments = get_segments_for_lecture(db, lecture.id)
        assert len(segments) == 3
        assert segments[0].text == "First segment"
        assert segments[1].text == "Middle segment"
        assert segments[2].text == "Second segment"


# --- Cards ---


class TestCards:
    def test_create_card(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        card = create_card(
            db, lecture.id, "What is ML?", "Machine learning is...", ["ai", "ml"]
        )
        assert card.id is not None
        assert card.front == "What is ML?"
        assert card.back == "Machine learning is..."
        assert card.tags == ["ai", "ml"]
        assert card.synced_to_anki is False
        assert card.anki_note_id is None

    def test_get_cards_for_lecture(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        create_card(db, lecture.id, "Q1", "A1", ["tag1"])
        create_card(db, lecture.id, "Q2", "A2", ["tag2"])

        cards = get_cards_for_lecture(db, lecture.id)
        assert len(cards) == 2

    def test_get_unsynced_cards(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        card1 = create_card(db, lecture.id, "Q1", "A1", ["tag1"])
        create_card(db, lecture.id, "Q2", "A2", ["tag2"])
        mark_card_synced(db, card1.id, anki_note_id=12345)

        unsynced = get_unsynced_cards(db)
        assert len(unsynced) == 1
        assert unsynced[0].front == "Q2"

    def test_mark_card_synced(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        card = create_card(db, lecture.id, "Q1", "A1", ["tag1"])

        mark_card_synced(db, card.id, anki_note_id=12345)

        cards = get_cards_for_lecture(db, lecture.id)
        assert cards[0].synced_to_anki is True
        assert cards[0].anki_note_id == 12345


# --- Helpers ---


class TestHelpers:
    def test_get_deck_path_for_lecture(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 2")
        lecture = create_lecture(db, unit.id)

        path = get_deck_path_for_lecture(db, lecture.id)
        assert path == "AI::Midterm 2"
