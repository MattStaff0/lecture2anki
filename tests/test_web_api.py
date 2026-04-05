"""Tests for the FastAPI web application."""

import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.db import (
    add_segment,
    create_card,
    create_course,
    create_lecture,
    create_unit,
    init_db,
)
from src.web import create_app


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    app = create_app(database_path=db_path)
    return TestClient(app)


@pytest.fixture
def seeded(db_path):
    """Seed with a course, unit, and lecture for reuse."""
    conn = sqlite3.connect(db_path)
    init_db(conn)
    course = create_course(conn, "AI")
    unit = create_unit(conn, course.id, "Midterm 1")
    lecture = create_lecture(conn, unit.id, title="Intro")
    conn.close()
    return {"course_id": course.id, "unit_id": unit.id, "lecture_id": lecture.id}


# --- Bootstrap ---


class TestBootstrap:
    def test_returns_empty_state(self, client):
        resp = client.get("/api/bootstrap")
        assert resp.status_code == 200
        data = resp.json()
        assert data["courses"] == []
        assert data["lectures"] == []

    def test_returns_seeded_data(self, client, seeded):
        resp = client.get("/api/bootstrap")
        data = resp.json()
        assert len(data["courses"]) == 1
        assert data["courses"][0]["name"] == "AI"
        assert len(data["courses"][0]["units"]) == 1


# --- Courses ---


class TestCourses:
    def test_create_course(self, client):
        resp = client.post("/api/courses", json={"name": "OS"})
        assert resp.status_code == 201
        assert resp.json()["course"]["name"] == "OS"

    def test_create_course_empty_name(self, client):
        resp = client.post("/api/courses", json={"name": ""})
        assert resp.status_code == 400

    def test_create_duplicate_course(self, client, seeded):
        resp = client.post("/api/courses", json={"name": "AI"})
        assert resp.status_code == 409


# --- Units ---


class TestUnits:
    def test_create_unit(self, client, seeded):
        resp = client.post(
            "/api/units",
            json={"course_id": seeded["course_id"], "name": "Final", "sort_order": 2},
        )
        assert resp.status_code == 201
        assert resp.json()["unit"]["name"] == "Final"

    def test_create_unit_missing_name(self, client, seeded):
        resp = client.post("/api/units", json={"course_id": seeded["course_id"], "name": ""})
        assert resp.status_code == 400

    def test_create_unit_missing_course(self, client):
        resp = client.post("/api/units", json={"course_id": 999, "name": "Final"})
        assert resp.status_code == 404

    def test_create_duplicate_unit(self, client, seeded):
        resp = client.post(
            "/api/units",
            json={"course_id": seeded["course_id"], "name": "Midterm 1"},
        )
        assert resp.status_code == 409


# --- Segments ---


class TestSegments:
    def test_get_segments(self, client, seeded, db_path):
        conn = sqlite3.connect(db_path)
        init_db(conn)
        add_segment(conn, seeded["lecture_id"], 0.0, 5.0, "Hello")
        add_segment(conn, seeded["lecture_id"], 5.0, 10.0, "World")
        conn.close()

        resp = client.get(f"/api/lectures/{seeded['lecture_id']}/segments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["segments"]) == 2
        assert data["segments"][0]["text"] == "Hello"

    def test_get_segments_lecture_not_found(self, client):
        resp = client.get("/api/lectures/999/segments")
        assert resp.status_code == 404


# --- Cards ---


class TestCards:
    def test_get_cards(self, client, seeded, db_path):
        conn = sqlite3.connect(db_path)
        init_db(conn)
        create_card(conn, seeded["lecture_id"], "Q1", "A1", ["t"])
        conn.close()

        resp = client.get(f"/api/lectures/{seeded['lecture_id']}/cards")
        assert resp.status_code == 200
        cards = resp.json()["cards"]
        assert len(cards) == 1
        assert cards[0]["status"] == "pending"

    def test_get_cards_lecture_not_found(self, client):
        resp = client.get("/api/lectures/999/cards")
        assert resp.status_code == 404

    def test_approve_card(self, client, seeded, db_path):
        conn = sqlite3.connect(db_path)
        init_db(conn)
        card = create_card(conn, seeded["lecture_id"], "Q1", "A1", [])
        conn.close()

        resp = client.post(f"/api/cards/{card.id}/approve")
        assert resp.status_code == 200
        assert resp.json()["card"]["status"] == "approved"

    def test_approve_card_not_found(self, client):
        resp = client.post("/api/cards/999/approve")
        assert resp.status_code == 404

    def test_delete_card(self, client, seeded, db_path):
        conn = sqlite3.connect(db_path)
        init_db(conn)
        card = create_card(conn, seeded["lecture_id"], "Q1", "A1", [])
        conn.close()

        resp = client.delete(f"/api/cards/{card.id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # Verify it's gone
        resp = client.get(f"/api/lectures/{seeded['lecture_id']}/cards")
        assert len(resp.json()["cards"]) == 0

    def test_delete_card_not_found(self, client):
        resp = client.delete("/api/cards/999")
        assert resp.status_code == 404


# --- Transcription ---


class TestTranscription:
    def test_transcribe_lecture_not_found(self, client):
        resp = client.post("/api/lectures/999/transcribe")
        assert resp.status_code == 404

    def test_transcribe_no_recording(self, client, seeded):
        with patch(
            "src.web.find_recording_for_lecture",
            side_effect=FileNotFoundError("No recording found"),
        ):
            resp = client.post(f"/api/lectures/{seeded['lecture_id']}/transcribe")
        assert resp.status_code == 400
        assert "No recording" in resp.json()["detail"]


# --- Jobs ---


class TestJobs:
    def test_job_not_found(self, client):
        resp = client.get("/api/jobs/nonexistent")
        assert resp.status_code == 404


# --- Static ---


class TestStatic:
    def test_index_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Lecture2Anki" in resp.text

    def test_static_app_js(self, client):
        resp = client.get("/static/app.js")
        assert resp.status_code == 200

    def test_static_styles_css(self, client):
        resp = client.get("/static/styles.css")
        assert resp.status_code == 200
