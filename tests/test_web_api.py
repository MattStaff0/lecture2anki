"""Tests for the FastAPI web API."""

import sqlite3
import time
from unittest.mock import patch

import pytest

from src.db import (
    add_segment,
    approve_card,
    create_card,
    create_course,
    create_lecture,
    create_unit,
    init_db,
)

# Import after patching to avoid heavy dependency loads
from src.web import app, _connect, _database_path

try:
    from fastapi.testclient import TestClient
except ImportError:
    pytest.skip("fastapi not installed", allow_module_level=True)


@pytest.fixture
def db_path(tmp_path):
    """Create a temp database and configure the web module to use it."""
    import src.web as web_mod

    path = tmp_path / "test.db"
    web_mod._database_path = path
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    yield path
    web_mod._database_path = None


@pytest.fixture
def client(db_path):
    return TestClient(app)


@pytest.fixture
def seeded_db(db_path):
    """Return a connection to the temp db with a course, unit, and lecture."""
    conn = sqlite3.connect(db_path)
    init_db(conn)
    return conn


class TestBootstrap:
    def test_bootstrap_empty(self, client):
        resp = client.get("/api/bootstrap")
        assert resp.status_code == 200
        data = resp.json()
        assert data["courses"] == []
        assert data["lectures"] == []

    def test_bootstrap_with_data(self, client, seeded_db):
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        create_lecture(seeded_db, unit.id, title="Lec 1")
        seeded_db.close()

        resp = client.get("/api/bootstrap")
        data = resp.json()
        assert len(data["courses"]) == 1
        assert data["courses"][0]["name"] == "AI"
        assert len(data["lectures"]) == 1


class TestCourses:
    def test_create_course(self, client):
        resp = client.post("/api/courses", json={"name": "AI"})
        assert resp.status_code == 201
        assert resp.json()["course"]["name"] == "AI"

    def test_create_duplicate_course(self, client):
        client.post("/api/courses", json={"name": "AI"})
        resp = client.post("/api/courses", json={"name": "AI"})
        assert resp.status_code == 409

    def test_create_course_empty_name(self, client):
        resp = client.post("/api/courses", json={"name": ""})
        assert resp.status_code == 400

    def test_rename_course(self, client):
        resp = client.post("/api/courses", json={"name": "AI"})
        course_id = resp.json()["course"]["id"]
        resp = client.patch(f"/api/courses/{course_id}", json={"name": "ML"})
        assert resp.status_code == 200
        assert resp.json()["course"]["name"] == "ML"

    def test_delete_course(self, client):
        resp = client.post("/api/courses", json={"name": "AI"})
        course_id = resp.json()["course"]["id"]
        resp = client.delete(f"/api/courses/{course_id}")
        assert resp.status_code == 200

    def test_delete_course_cascades_units(self, client):
        resp = client.post("/api/courses", json={"name": "AI"})
        course_id = resp.json()["course"]["id"]
        client.post("/api/units", json={"name": "Mid", "course_id": course_id})
        resp = client.delete(f"/api/courses/{course_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        bootstrap = client.get("/api/bootstrap").json()
        assert all(c["name"] != "AI" for c in bootstrap["courses"])


class TestUnits:
    def test_create_unit(self, client):
        resp = client.post("/api/courses", json={"name": "AI"})
        course_id = resp.json()["course"]["id"]
        resp = client.post("/api/units", json={"name": "Midterm 1", "course_id": course_id})
        assert resp.status_code == 201
        assert resp.json()["unit"]["name"] == "Midterm 1"

    def test_create_unit_missing_course(self, client):
        resp = client.post("/api/units", json={"name": "Midterm 1"})
        assert resp.status_code == 400

    def test_rename_unit(self, client):
        resp = client.post("/api/courses", json={"name": "AI"})
        course_id = resp.json()["course"]["id"]
        resp = client.post("/api/units", json={"name": "Mid", "course_id": course_id})
        unit_id = resp.json()["unit"]["id"]
        resp = client.patch(f"/api/units/{unit_id}", json={"name": "Final"})
        assert resp.status_code == 200
        assert resp.json()["unit"]["name"] == "Final"

    def test_delete_unit(self, client):
        resp = client.post("/api/courses", json={"name": "AI"})
        course_id = resp.json()["course"]["id"]
        resp = client.post("/api/units", json={"name": "Mid", "course_id": course_id})
        unit_id = resp.json()["unit"]["id"]
        resp = client.delete(f"/api/units/{unit_id}")
        assert resp.status_code == 200


class TestUpload:
    def test_upload_audio(self, client):
        resp = client.post("/api/courses", json={"name": "AI"})
        course_id = resp.json()["course"]["id"]
        resp = client.post("/api/units", json={"name": "Mid", "course_id": course_id})
        unit_id = resp.json()["unit"]["id"]

        resp = client.post(
            "/api/lectures/upload",
            data={"unit_id": str(unit_id), "title": "Test Lecture"},
            files={"audio": ("test.webm", b"fake audio data", "audio/webm")},
        )
        assert resp.status_code == 201
        assert resp.json()["lecture"]["title"] == "Test Lecture"

    def test_upload_empty_audio(self, client):
        resp = client.post("/api/courses", json={"name": "AI"})
        course_id = resp.json()["course"]["id"]
        resp = client.post("/api/units", json={"name": "Mid", "course_id": course_id})
        unit_id = resp.json()["unit"]["id"]

        resp = client.post(
            "/api/lectures/upload",
            data={"unit_id": str(unit_id)},
            files={"audio": ("test.webm", b"", "audio/webm")},
        )
        assert resp.status_code == 400


class TestTranscription:
    def test_transcribe_no_recording(self, client, seeded_db):
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        lecture = create_lecture(seeded_db, unit.id)
        seeded_db.close()

        with patch(
            "src.web.find_recording_for_lecture",
            side_effect=FileNotFoundError("No recording"),
        ):
            resp = client.post(f"/api/lectures/{lecture.id}/transcribe")
            assert resp.status_code == 400

    def test_transcribe_not_found(self, client):
        resp = client.post("/api/lectures/9999/transcribe")
        assert resp.status_code == 404


class TestSegments:
    def test_get_segments(self, client, seeded_db):
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        lecture = create_lecture(seeded_db, unit.id)
        add_segment(seeded_db, lecture.id, 0, 10, "Hello")
        add_segment(seeded_db, lecture.id, 10, 20, "World")
        seeded_db.close()

        resp = client.get(f"/api/lectures/{lecture.id}/segments")
        assert resp.status_code == 200
        assert len(resp.json()["segments"]) == 2

    def test_get_segments_not_found(self, client):
        resp = client.get("/api/lectures/9999/segments")
        assert resp.status_code == 404


class TestGenerate:
    def test_generate_no_segments(self, client, seeded_db):
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        lecture = create_lecture(seeded_db, unit.id)
        seeded_db.close()

        resp = client.post(f"/api/lectures/{lecture.id}/generate")
        assert resp.status_code == 400

    def test_generate_not_found(self, client):
        resp = client.post("/api/lectures/9999/generate")
        assert resp.status_code == 404


class TestCards:
    def test_get_cards(self, client, seeded_db):
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        lecture = create_lecture(seeded_db, unit.id)
        create_card(seeded_db, lecture.id, "Q1", "A1", ["t"])
        seeded_db.close()

        resp = client.get(f"/api/lectures/{lecture.id}/cards")
        assert resp.status_code == 200
        cards = resp.json()["cards"]
        assert len(cards) == 1
        assert cards[0]["status"] == "pending"

    def test_get_cards_not_found(self, client):
        resp = client.get("/api/lectures/9999/cards")
        assert resp.status_code == 404

    def test_approve_card(self, client, seeded_db):
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        lecture = create_lecture(seeded_db, unit.id)
        card = create_card(seeded_db, lecture.id, "Q1", "A1", [])
        seeded_db.close()

        resp = client.post(f"/api/cards/{card.id}/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_reject_card(self, client, seeded_db):
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        lecture = create_lecture(seeded_db, unit.id)
        card = create_card(seeded_db, lecture.id, "Q1", "A1", [])
        seeded_db.close()

        resp = client.delete(f"/api/cards/{card.id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_approve_nonexistent_card(self, client):
        resp = client.post("/api/cards/9999/approve")
        assert resp.status_code == 404

    def test_reject_nonexistent_card(self, client):
        resp = client.delete("/api/cards/9999")
        assert resp.status_code == 404


class TestSync:
    def test_sync_no_approved_cards(self, client, seeded_db):
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        lecture = create_lecture(seeded_db, unit.id)
        create_card(seeded_db, lecture.id, "Q1", "A1", [])
        seeded_db.close()

        resp = client.post(f"/api/lectures/{lecture.id}/sync")
        assert resp.status_code == 400

    def test_sync_not_found(self, client):
        resp = client.post("/api/lectures/9999/sync")
        assert resp.status_code == 404


class TestJobs:
    def test_job_not_found(self, client):
        resp = client.get("/api/jobs/9999")
        assert resp.status_code == 404


class TestStaticFiles:
    def test_index(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Lecture2Anki" in resp.text


class TestBootstrapCardCounts:
    def test_bootstrap_includes_card_counts(self, client, seeded_db):
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        lecture = create_lecture(seeded_db, unit.id, title="Lec")
        create_card(seeded_db, lecture.id, "Q1", "A1", [])
        card2 = create_card(seeded_db, lecture.id, "Q2", "A2", [])
        approve_card(seeded_db, card2.id)
        seeded_db.close()

        resp = client.get("/api/bootstrap")
        lec = resp.json()["lectures"][0]
        assert lec["card_count"] == 2
        assert lec["approved_count"] == 1
        assert lec["synced_count"] == 0


class TestRegenerationReplacesCards:
    def test_regeneration_deletes_prior_cards(self, client, seeded_db):
        """generate_cards_for_lecture deletes old cards before creating new ones."""
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        lecture = create_lecture(seeded_db, unit.id)
        add_segment(seeded_db, lecture.id, 0, 10, "Machine learning is about models.")
        # Create a pre-existing card that should be replaced
        create_card(seeded_db, lecture.id, "Old Q", "Old A", [])
        seeded_db.close()

        import json

        def fake_llm(prompt: str) -> str:
            return json.dumps([
                {"front": "What is machine learning?", "back": "Machine learning is about models.", "tags": ["ml"]},
                {"front": "What do models learn from?", "back": "Models learn from machine data.", "tags": []},
            ])

        with patch("src.card_generator._call_ollama", side_effect=fake_llm):
            from src.card_generator import generate_cards_for_lecture
            conn = sqlite3.connect(seeded_db.database if hasattr(seeded_db, 'database') else str(client.app))
            # Use web module's connect to get to the test db
            import src.web as web_mod
            conn = sqlite3.connect(web_mod._database_path)
            init_db(conn)
            cards = generate_cards_for_lecture(conn, lecture.id, llm=fake_llm)
            conn.close()

        # Old card should be gone, only new cards remain
        resp = client.get(f"/api/lectures/{lecture.id}/cards")
        cards_data = resp.json()["cards"]
        assert len(cards_data) == 2
        fronts = [c["front"] for c in cards_data]
        assert "Old Q" not in fronts
        assert "What is machine learning?" in fronts
        assert "What do models learn from?" in fronts


class TestSyncViaAPI:
    def test_sync_returns_job_id(self, client, seeded_db):
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        lecture = create_lecture(seeded_db, unit.id)
        card = create_card(seeded_db, lecture.id, "Q1", "A1", [])
        approve_card(seeded_db, card.id)
        seeded_db.close()

        resp = client.post(f"/api/lectures/{lecture.id}/sync")
        assert resp.status_code == 200
        assert "job_id" in resp.json()

    def test_sync_rejects_no_approved(self, client, seeded_db):
        course = create_course(seeded_db, "AI")
        unit = create_unit(seeded_db, course.id, "Midterm 1")
        lecture = create_lecture(seeded_db, unit.id)
        create_card(seeded_db, lecture.id, "Q1", "A1", [])  # pending only
        seeded_db.close()

        resp = client.post(f"/api/lectures/{lecture.id}/sync")
        assert resp.status_code == 400
