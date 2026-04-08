"""Tests for durable job tracking (job_runs, job_events)."""

import sqlite3
import time
from unittest.mock import patch

import pytest

from src.db import (
    add_job_event,
    create_course,
    create_job_run,
    create_lecture,
    create_unit,
    get_active_job_for_lecture,
    get_job_events,
    get_job_run,
    get_jobs_for_lecture,
    get_latest_job_event,
    get_recent_jobs,
    init_db,
    update_job_stage,
    update_job_status,
    add_segment,
    delete_lecture,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def lecture(db):
    """Create a course, unit, and lecture for job tests."""
    course = create_course(db, "AI")
    unit = create_unit(db, course.id, "Final")
    return create_lecture(db, unit.id, title="Test Lecture")


# --- Job Run CRUD ---


class TestJobRunCRUD:
    def test_create_job_run(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        assert job.id is not None
        assert job.job_type == "transcription"
        assert job.lecture_id == lecture.id
        assert job.status == "queued"
        assert job.current_stage == ""
        assert job.started_at is None
        assert job.finished_at is None
        assert job.error_message is None

    def test_get_job_run(self, db, lecture):
        created = create_job_run(db, "generation", lecture.id)
        fetched = get_job_run(db, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.job_type == "generation"

    def test_get_job_run_not_found(self, db):
        assert get_job_run(db, 9999) is None

    def test_update_job_status_to_running(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        update_job_status(db, job.id, "running", current_stage="loading_model")

        fetched = get_job_run(db, job.id)
        assert fetched.status == "running"
        assert fetched.current_stage == "loading_model"
        assert fetched.started_at is not None

    def test_update_job_status_to_succeeded(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        update_job_status(db, job.id, "running")
        update_job_status(
            db, job.id, "succeeded",
            current_stage="done",
            details_json={"segment_count": 42},
        )

        fetched = get_job_run(db, job.id)
        assert fetched.status == "succeeded"
        assert fetched.finished_at is not None
        assert fetched.details_json == {"segment_count": 42}

    def test_update_job_status_to_failed(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        update_job_status(db, job.id, "running")
        update_job_status(
            db, job.id, "failed",
            current_stage="error",
            error_message="Whisper model not found",
        )

        fetched = get_job_run(db, job.id)
        assert fetched.status == "failed"
        assert fetched.error_message == "Whisper model not found"
        assert fetched.finished_at is not None

    def test_update_job_stage(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        update_job_status(db, job.id, "running")
        update_job_stage(db, job.id, "transcribing")

        fetched = get_job_run(db, job.id)
        assert fetched.current_stage == "transcribing"


# --- Active Job Queries ---


class TestActiveJobQueries:
    def test_get_active_job_for_lecture(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        update_job_status(db, job.id, "running", current_stage="transcribing")

        active = get_active_job_for_lecture(db, lecture.id)
        assert active is not None
        assert active.id == job.id

    def test_get_active_job_returns_none_when_completed(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        update_job_status(db, job.id, "succeeded")

        active = get_active_job_for_lecture(db, lecture.id)
        assert active is None

    def test_get_active_job_returns_most_recent(self, db, lecture):
        job1 = create_job_run(db, "transcription", lecture.id)
        update_job_status(db, job1.id, "failed")
        job2 = create_job_run(db, "transcription", lecture.id)

        active = get_active_job_for_lecture(db, lecture.id)
        assert active is not None
        assert active.id == job2.id

    def test_get_recent_jobs(self, db, lecture):
        create_job_run(db, "transcription", lecture.id)
        create_job_run(db, "generation", lecture.id)
        create_job_run(db, "sync", lecture.id)

        jobs = get_recent_jobs(db, limit=10)
        assert len(jobs) == 3
        # Most recent first
        assert jobs[0].job_type == "sync"
        assert jobs[2].job_type == "transcription"

    def test_get_jobs_for_lecture(self, db, lecture):
        create_job_run(db, "transcription", lecture.id)
        create_job_run(db, "generation", lecture.id)

        # Create a second lecture with a job
        course = create_course(db, "OS")
        unit = create_unit(db, course.id, "Mid")
        other_lecture = create_lecture(db, unit.id)
        create_job_run(db, "transcription", other_lecture.id)

        jobs = get_jobs_for_lecture(db, lecture.id)
        assert len(jobs) == 2
        assert all(j.lecture_id == lecture.id for j in jobs)


# --- Job Events ---


class TestJobEvents:
    def test_add_job_event(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        event = add_job_event(db, job.id, "loading_model", "Loading Whisper small model")
        assert event.id is not None
        assert event.job_id == job.id
        assert event.stage == "loading_model"
        assert event.level == "info"
        assert event.message == "Loading Whisper small model"

    def test_add_event_with_level(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        event = add_job_event(db, job.id, "error", "Model not found", level="error")
        assert event.level == "error"

    def test_get_job_events(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        add_job_event(db, job.id, "starting", "Job started")
        add_job_event(db, job.id, "loading_model", "Loading model")
        add_job_event(db, job.id, "transcribing", "Transcription started")

        events = get_job_events(db, job.id)
        assert len(events) == 3
        assert events[0].stage == "starting"
        assert events[2].stage == "transcribing"

    def test_get_latest_job_event(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        add_job_event(db, job.id, "starting", "First event")
        add_job_event(db, job.id, "loading", "Second event")
        add_job_event(db, job.id, "done", "Third event")

        latest = get_latest_job_event(db, job.id)
        assert latest is not None
        assert latest.message == "Third event"
        assert latest.stage == "done"

    def test_get_latest_event_none(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        latest = get_latest_job_event(db, job.id)
        assert latest is None


# --- Cascade Deletion ---


class TestJobCascadeDeletion:
    def test_delete_lecture_removes_jobs_and_events(self, db, lecture):
        job = create_job_run(db, "transcription", lecture.id)
        add_job_event(db, job.id, "starting", "Started")
        add_job_event(db, job.id, "done", "Done")

        delete_lecture(db, lecture.id)

        assert get_job_run(db, job.id) is None
        assert get_job_events(db, job.id) == []


# --- Web API Job Endpoints ---

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

from src.web import app


@pytest.fixture
def db_path(tmp_path):
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
    if TestClient is None:
        pytest.skip("fastapi not installed")
    return TestClient(app)


@pytest.fixture
def seeded_lecture(db_path):
    """Create a course+unit+lecture in the test database."""
    conn = sqlite3.connect(db_path)
    init_db(conn)
    course = create_course(conn, "AI")
    unit = create_unit(conn, course.id, "Final")
    lecture = create_lecture(conn, unit.id, title="Test")
    conn.close()
    return lecture


class TestWebJobEndpoints:
    def test_get_job_not_found(self, client):
        resp = client.get("/api/jobs/9999")
        assert resp.status_code == 404

    def test_job_created_on_transcribe(self, client, seeded_lecture, db_path):
        # Create a fake recording file
        import src.web as web_mod
        from src.config import get_recordings_path
        rec_dir = get_recordings_path(db_path)
        rec_dir.mkdir(parents=True, exist_ok=True)
        (rec_dir / f"lecture-{seeded_lecture.id}-test.webm").write_bytes(b"fake")

        with patch("src.web.transcribe_lecture") as mock_transcribe:
            mock_transcribe.return_value = []
            resp = client.post(f"/api/lectures/{seeded_lecture.id}/transcribe")
            assert resp.status_code == 200
            job_id = resp.json()["job_id"]
            assert isinstance(job_id, int)

            # Job should exist in the database
            resp = client.get(f"/api/jobs/{job_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["job_type"] == "transcription"
            assert data["lecture_id"] == seeded_lecture.id

    def test_job_events_endpoint(self, client, db_path, seeded_lecture):
        conn = sqlite3.connect(db_path)
        init_db(conn)
        job = create_job_run(conn, "transcription", seeded_lecture.id)
        add_job_event(conn, job.id, "starting", "Job started")
        add_job_event(conn, job.id, "loading", "Loading model")
        conn.close()

        resp = client.get(f"/api/jobs/{job.id}/events")
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) == 2
        assert events[0]["stage"] == "starting"
        assert events[1]["message"] == "Loading model"

    def test_recent_jobs_endpoint(self, client, db_path, seeded_lecture):
        conn = sqlite3.connect(db_path)
        init_db(conn)
        create_job_run(conn, "transcription", seeded_lecture.id)
        create_job_run(conn, "generation", seeded_lecture.id)
        conn.close()

        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        assert len(jobs) == 2

    def test_lecture_status_endpoint(self, client, db_path, seeded_lecture):
        conn = sqlite3.connect(db_path)
        init_db(conn)
        add_segment(conn, seeded_lecture.id, 0, 10, "Hello")
        job = create_job_run(conn, "transcription", seeded_lecture.id)
        update_job_status(conn, job.id, "running", current_stage="transcribing")
        add_job_event(conn, job.id, "transcribing", "Transcription in progress")
        conn.close()

        resp = client.get(f"/api/lectures/{seeded_lecture.id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["segment_count"] == 1
        assert data["active_job"] is not None
        assert data["active_job"]["status"] == "running"
        assert data["active_job"]["current_stage"] == "transcribing"
        assert len(data["recent_jobs"]) == 1

    def test_bootstrap_includes_active_job(self, client, db_path, seeded_lecture):
        conn = sqlite3.connect(db_path)
        init_db(conn)
        job = create_job_run(conn, "generation", seeded_lecture.id)
        update_job_status(conn, job.id, "running", current_stage="generating")
        add_job_event(conn, job.id, "generating", "Chunk 1/3")
        conn.close()

        resp = client.get("/api/bootstrap")
        assert resp.status_code == 200
        lectures = resp.json()["lectures"]
        assert len(lectures) == 1
        lec = lectures[0]
        assert lec["active_job"] is not None
        assert lec["active_job"]["job_type"] == "generation"
        assert lec["active_job"]["current_stage"] == "generating"
        assert lec["active_job"]["latest_event"] == "Chunk 1/3"

    def test_bootstrap_includes_last_error(self, client, db_path, seeded_lecture):
        conn = sqlite3.connect(db_path)
        init_db(conn)
        job = create_job_run(conn, "transcription", seeded_lecture.id)
        update_job_status(
            conn, job.id, "failed",
            error_message="Model not found",
        )
        conn.close()

        resp = client.get("/api/bootstrap")
        lec = resp.json()["lectures"][0]
        assert lec["last_error"] is not None
        assert lec["last_error"]["error_message"] == "Model not found"

    def test_bootstrap_no_active_job_when_completed(self, client, db_path, seeded_lecture):
        conn = sqlite3.connect(db_path)
        init_db(conn)
        job = create_job_run(conn, "transcription", seeded_lecture.id)
        update_job_status(conn, job.id, "succeeded", current_stage="done")
        conn.close()

        resp = client.get("/api/bootstrap")
        lec = resp.json()["lectures"][0]
        assert lec["active_job"] is None
