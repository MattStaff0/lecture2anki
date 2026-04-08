"""FastAPI-based local web UI for Lecture2Anki."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import get_database_path, get_recordings_path
from src.db import (
    add_job_event,
    approve_card,
    create_course,
    create_job_run,
    create_unit,
    delete_card,
    delete_course,
    delete_lecture,
    delete_unit,
    get_active_job_for_lecture,
    get_approved_unsynced_cards,
    get_card_by_id,
    get_cards_for_lecture,
    get_course_by_id,
    get_courses,
    get_job_events,
    get_job_run,
    get_jobs_for_lecture,
    get_latest_job_event,
    get_recent_jobs,
    get_unit_by_name,
    get_units_for_course,
    init_db,
    update_job_stage,
    update_job_status,
)
from src.recorder import save_uploaded_audio
from src.transcriber import find_recording_for_lecture, transcribe_lecture

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "web_static"

MIME_TO_SUFFIX = {
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


# ---------------------------------------------------------------------------
# Database connection helper
# ---------------------------------------------------------------------------

_database_path: Path | None = None


def _connect() -> sqlite3.Connection:
    path = _database_path or get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    init_db(conn)
    return conn


def _recordings_path() -> Path:
    """Resolve the recordings directory for the active web database path."""
    return get_recordings_path(_database_path)


# ---------------------------------------------------------------------------
# Background job runner (now backed by SQLite)
# ---------------------------------------------------------------------------

# In-memory set of currently running job IDs (for thread safety)
_running_jobs: set[int] = set()
_running_lock = threading.Lock()


def _make_progress_callback(job_id: int):
    """Create a progress callback that writes events to the database."""
    def callback(stage: str, message: str, level: str = "info") -> None:
        try:
            conn = _connect()
            try:
                update_job_stage(conn, job_id, stage)
                add_job_event(conn, job_id, stage, message, level)
            finally:
                conn.close()
        except Exception:
            logger.exception("Failed to write job event for job %d", job_id)
    return callback


def _run_job_in_background(
    job_id: int,
    lecture_id: int,
    target: Any,
    args: tuple = (),
) -> None:
    """Run target in a daemon thread, updating durable job state."""

    def _wrapper() -> None:
        conn = _connect()
        try:
            update_job_status(conn, job_id, "running", current_stage="starting")
            add_job_event(conn, job_id, "starting", "Job started")
        finally:
            conn.close()

        try:
            result = target(*args)
            details = result if isinstance(result, dict) else {}
            conn = _connect()
            try:
                update_job_status(
                    conn, job_id, "succeeded",
                    current_stage="done",
                    details_json=details,
                )
                add_job_event(conn, job_id, "done", "Job completed successfully")
            finally:
                conn.close()
        except Exception as exc:
            logger.exception("Job %d failed", job_id)
            conn = _connect()
            try:
                update_job_status(
                    conn, job_id, "failed",
                    current_stage="error",
                    error_message=str(exc),
                )
                add_job_event(conn, job_id, "error", f"Job failed: {exc}", "error")
            finally:
                conn.close()
        finally:
            with _running_lock:
                _running_jobs.discard(job_id)

    with _running_lock:
        _running_jobs.add(job_id)

    t = threading.Thread(target=_wrapper, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _audio_suffix(filename: str | None, content_type: str | None) -> str:
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix:
            return suffix
    if content_type and content_type in MIME_TO_SUFFIX:
        return MIME_TO_SUFFIX[content_type]
    return ".webm"


def _serialize_job_run(conn, job) -> dict[str, Any]:
    """Serialize a JobRun with its latest event for the API."""
    latest = get_latest_job_event(conn, job.id)
    return {
        "id": job.id,
        "job_type": job.job_type,
        "lecture_id": job.lecture_id,
        "status": job.status,
        "current_stage": job.current_stage,
        "started_at": str(job.started_at) if job.started_at else None,
        "finished_at": str(job.finished_at) if job.finished_at else None,
        "error_message": job.error_message,
        "details": job.details_json,
        "latest_event": latest.message if latest else None,
        "latest_event_stage": latest.stage if latest else None,
    }


def _serialize_bootstrap(conn: sqlite3.Connection) -> dict[str, Any]:
    courses_out: list[dict[str, Any]] = []
    for course in get_courses(conn):
        courses_out.append(
            {
                "id": course.id,
                "name": course.name,
                "units": [
                    {"id": u.id, "name": u.name, "sort_order": u.sort_order}
                    for u in get_units_for_course(conn, course.id)
                ],
            }
        )

    lecture_rows = conn.execute(
        "SELECT l.id, COALESCE(l.title, 'Untitled lecture') AS title, l.recorded_at, "
        "l.duration_seconds, u.id AS unit_id, u.name AS unit_name, "
        "c.id AS course_id, c.name AS course_name, "
        "(SELECT COUNT(*) FROM segments s WHERE s.lecture_id = l.id) AS segment_count, "
        "(SELECT COUNT(*) FROM cards cd WHERE cd.lecture_id = l.id) AS card_count, "
        "(SELECT COUNT(*) FROM cards cd WHERE cd.lecture_id = l.id "
        " AND cd.status = 'approved') AS approved_count, "
        "(SELECT COUNT(*) FROM cards cd WHERE cd.lecture_id = l.id "
        " AND cd.synced_to_anki = 1) AS synced_count "
        "FROM lectures l "
        "JOIN units u ON l.unit_id = u.id "
        "JOIN courses c ON u.course_id = c.id "
        "ORDER BY l.recorded_at DESC"
    ).fetchall()

    lectures_out: list[dict[str, Any]] = []
    for row in lecture_rows:
        lecture_id = row[0]
        try:
            find_recording_for_lecture(lecture_id, recordings_dir=_recordings_path())
            has_recording = True
        except FileNotFoundError:
            has_recording = False

        # Active job info
        active_job = get_active_job_for_lecture(conn, lecture_id)
        active_job_info = None
        if active_job:
            latest = get_latest_job_event(conn, active_job.id)
            active_job_info = {
                "job_id": active_job.id,
                "job_type": active_job.job_type,
                "status": active_job.status,
                "current_stage": active_job.current_stage,
                "latest_event": latest.message if latest else None,
            }

        # Last error from most recent failed job
        last_failed = conn.execute(
            "SELECT id, error_message FROM job_runs "
            "WHERE lecture_id = ? AND status = 'failed' "
            "ORDER BY id DESC LIMIT 1",
            (lecture_id,),
        ).fetchone()
        last_error = None
        if last_failed:
            last_error = {
                "job_id": last_failed[0],
                "error_message": last_failed[1],
            }

        lectures_out.append(
            {
                "id": lecture_id,
                "title": row[1],
                "recorded_at": row[2],
                "duration_seconds": row[3],
                "unit_id": row[4],
                "unit_name": row[5],
                "course_id": row[6],
                "course_name": row[7],
                "segment_count": row[8],
                "card_count": row[9],
                "approved_count": row[10],
                "synced_count": row[11],
                "has_recording": has_recording,
                "active_job": active_job_info,
                "last_error": last_error,
            }
        )

    return {"courses": courses_out, "lectures": lectures_out}


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Lecture2Anki", docs_url=None, redoc_url=None)


# --- Bootstrap ---


@app.get("/api/bootstrap")
def api_bootstrap() -> dict[str, Any]:
    conn = _connect()
    try:
        return _serialize_bootstrap(conn)
    finally:
        conn.close()


# --- Courses ---


@app.post("/api/courses", status_code=201)
def api_create_course(body: dict[str, Any]) -> dict[str, Any]:
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Course name is required.")
    conn = _connect()
    try:
        course = create_course(conn, name)
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Course already exists: {name}")
    finally:
        conn.close()
    return {"course": {"id": course.id, "name": course.name}}


@app.patch("/api/courses/{course_id}")
def api_rename_course(course_id: int, body: dict[str, Any]) -> dict[str, Any]:
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Course name is required.")
    conn = _connect()
    try:
        course = get_course_by_id(conn, course_id)
        if course is None:
            raise HTTPException(404, "Course not found.")
        conn.execute("UPDATE courses SET name = ? WHERE id = ?", (name, course_id))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Course name already taken: {name}")
    finally:
        conn.close()
    return {"course": {"id": course_id, "name": name}}


@app.delete("/api/courses/{course_id}")
def api_delete_course(course_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        course = get_course_by_id(conn, course_id)
        if course is None:
            raise HTTPException(404, "Course not found.")
        delete_course(conn, course_id)
    finally:
        conn.close()
    return {"deleted": True}


# --- Units ---


@app.post("/api/units", status_code=201)
def api_create_unit(body: dict[str, Any]) -> dict[str, Any]:
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Unit name is required.")
    try:
        course_id = int(body.get("course_id"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise HTTPException(400, "A valid course_id is required.")
    sort_order = int(body.get("sort_order") or 0)
    conn = _connect()
    try:
        unit = create_unit(conn, course_id, name, sort_order=sort_order)
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Unit already exists for this course: {name}")
    finally:
        conn.close()
    return {
        "unit": {
            "id": unit.id,
            "course_id": unit.course_id,
            "name": unit.name,
            "sort_order": unit.sort_order,
        }
    }


@app.patch("/api/units/{unit_id}")
def api_update_unit(unit_id: int, body: dict[str, Any]) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, course_id, name, sort_order FROM units WHERE id = ?", (unit_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Unit not found.")
        name = (body.get("name") or "").strip() or row[2]
        sort_order = body.get("sort_order", row[3])
        conn.execute(
            "UPDATE units SET name = ?, sort_order = ? WHERE id = ?",
            (name, int(sort_order), unit_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Unit name already taken in this course: {name}")
    finally:
        conn.close()
    return {"unit": {"id": unit_id, "name": name, "sort_order": sort_order}}


@app.delete("/api/units/{unit_id}")
def api_delete_unit(unit_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM units WHERE id = ?", (unit_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Unit not found.")
        delete_unit(conn, unit_id)
    finally:
        conn.close()
    return {"deleted": True}


# --- Lectures ---


@app.get("/api/lectures")
def api_list_lectures() -> dict[str, Any]:
    conn = _connect()
    try:
        data = _serialize_bootstrap(conn)
    finally:
        conn.close()
    return {"lectures": data["lectures"]}


@app.post("/api/lectures/upload", status_code=201)
async def api_upload_lecture(
    unit_id: int = Form(...),
    title: str = Form(""),
    duration_seconds: float | None = Form(None),
    audio: UploadFile = File(...),
) -> dict[str, Any]:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(400, "Uploaded audio file is empty.")
    suffix = _audio_suffix(audio.filename, audio.content_type)
    clean_title = title.strip() or None
    conn = _connect()
    try:
        result = save_uploaded_audio(
            conn,
            unit_id=unit_id,
            audio_bytes=audio_bytes,
            suffix=suffix,
            title=clean_title,
            recordings_dir=_recordings_path(),
            duration_seconds=duration_seconds,
        )
    finally:
        conn.close()
    return {
        "lecture": {
            "id": result.lecture.id,
            "title": result.lecture.title,
            "duration_seconds": result.duration_seconds,
        }
    }


@app.get("/api/lectures/{lecture_id}")
def api_lecture_detail(lecture_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT l.id, COALESCE(l.title, 'Untitled lecture'), l.recorded_at, "
            "l.duration_seconds, u.name, c.name "
            "FROM lectures l JOIN units u ON l.unit_id = u.id "
            "JOIN courses c ON u.course_id = c.id WHERE l.id = ?",
            (lecture_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Lecture not found.")
        segment_count = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE lecture_id = ?", (lecture_id,)
        ).fetchone()[0]
        card_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE lecture_id = ?", (lecture_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "lecture": {
            "id": row[0],
            "title": row[1],
            "recorded_at": row[2],
            "duration_seconds": row[3],
            "unit_name": row[4],
            "course_name": row[5],
            "segment_count": segment_count,
            "card_count": card_count,
        }
    }


@app.delete("/api/lectures/{lecture_id}")
def api_delete_lecture(lecture_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Lecture not found.")
        delete_lecture(conn, lecture_id)
    finally:
        conn.close()
    return {"deleted": True}


# --- Lecture status ---


@app.get("/api/lectures/{lecture_id}/status")
def api_lecture_status(lecture_id: int) -> dict[str, Any]:
    """Rich status summary for a single lecture."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT l.id, COALESCE(l.title, 'Untitled'), l.recorded_at, "
            "l.duration_seconds, u.name, c.name "
            "FROM lectures l JOIN units u ON l.unit_id = u.id "
            "JOIN courses c ON u.course_id = c.id WHERE l.id = ?",
            (lecture_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Lecture not found.")

        try:
            find_recording_for_lecture(lecture_id, recordings_dir=_recordings_path())
            has_recording = True
        except FileNotFoundError:
            has_recording = False

        segment_count = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE lecture_id = ?", (lecture_id,)
        ).fetchone()[0]
        card_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE lecture_id = ?", (lecture_id,)
        ).fetchone()[0]
        approved_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE lecture_id = ? AND status = 'approved'",
            (lecture_id,),
        ).fetchone()[0]
        synced_count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE lecture_id = ? AND synced_to_anki = 1",
            (lecture_id,),
        ).fetchone()[0]

        active_job = get_active_job_for_lecture(conn, lecture_id)
        active_job_info = None
        if active_job:
            active_job_info = _serialize_job_run(conn, active_job)

        recent_jobs = get_jobs_for_lecture(conn, lecture_id, limit=5)
        jobs_out = [_serialize_job_run(conn, j) for j in recent_jobs]
    finally:
        conn.close()

    return {
        "lecture_id": lecture_id,
        "title": row[1],
        "recorded_at": row[2],
        "duration_seconds": row[3],
        "unit_name": row[4],
        "course_name": row[5],
        "has_recording": has_recording,
        "segment_count": segment_count,
        "card_count": card_count,
        "approved_count": approved_count,
        "synced_count": synced_count,
        "active_job": active_job_info,
        "recent_jobs": jobs_out,
    }


# --- Transcription ---


@app.post("/api/lectures/{lecture_id}/transcribe")
def api_transcribe(lecture_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Lecture not found.")
        try:
            find_recording_for_lecture(lecture_id, recordings_dir=_recordings_path())
        except FileNotFoundError:
            raise HTTPException(400, "No recording found for this lecture.")

        job = create_job_run(conn, "transcription", lecture_id)
        logger.info("Starting transcription job %d for lecture %d", job.id, lecture_id)
    finally:
        conn.close()

    def _do_transcribe() -> dict[str, Any]:
        c = _connect()
        try:
            on_progress = _make_progress_callback(job.id)
            segs = transcribe_lecture(
                c, lecture_id,
                recordings_dir=_recordings_path(),
                on_progress=on_progress,
            )
            return {"lecture_id": lecture_id, "segment_count": len(segs)}
        finally:
            c.close()

    _run_job_in_background(job.id, lecture_id, _do_transcribe)
    return {"job_id": job.id}


@app.get("/api/lectures/{lecture_id}/segments")
def api_segments(lecture_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Lecture not found.")
        rows = conn.execute(
            "SELECT id, start_time, end_time, text "
            "FROM segments WHERE lecture_id = ? ORDER BY start_time",
            (lecture_id,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "lecture_id": lecture_id,
        "segments": [
            {"id": r[0], "start_time": r[1], "end_time": r[2], "text": r[3]}
            for r in rows
        ],
    }


# --- Card generation ---


@app.post("/api/lectures/{lecture_id}/generate")
def api_generate(lecture_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Lecture not found.")
        seg_count = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE lecture_id = ?", (lecture_id,)
        ).fetchone()[0]
        if seg_count == 0:
            raise HTTPException(400, "No transcript segments. Transcribe first.")

        job = create_job_run(conn, "generation", lecture_id)
        logger.info("Starting generation job %d for lecture %d", job.id, lecture_id)
    finally:
        conn.close()

    def _do_generate() -> dict[str, Any]:
        from src.card_generator import generate_cards_for_lecture

        c = _connect()
        try:
            on_progress = _make_progress_callback(job.id)
            cards = generate_cards_for_lecture(
                c, lecture_id,
                on_progress=on_progress,
            )
            return {"lecture_id": lecture_id, "card_count": len(cards)}
        finally:
            c.close()

    _run_job_in_background(job.id, lecture_id, _do_generate)
    return {"job_id": job.id}


# --- Cards ---


@app.get("/api/lectures/{lecture_id}/cards")
def api_cards(lecture_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Lecture not found.")
        cards = get_cards_for_lecture(conn, lecture_id)
    finally:
        conn.close()
    return {
        "lecture_id": lecture_id,
        "cards": [
            {
                "id": c.id,
                "front": c.front,
                "back": c.back,
                "tags": c.tags,
                "status": c.status,
                "synced_to_anki": c.synced_to_anki,
            }
            for c in cards
        ],
    }


@app.post("/api/cards/{card_id}/approve")
def api_approve_card(card_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        card = get_card_by_id(conn, card_id)
        if card is None:
            raise HTTPException(404, "Card not found.")
        approve_card(conn, card_id)
    finally:
        conn.close()
    return {"card_id": card_id, "status": "approved"}


@app.delete("/api/cards/{card_id}")
def api_reject_card(card_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        card = get_card_by_id(conn, card_id)
        if card is None:
            raise HTTPException(404, "Card not found.")
        delete_card(conn, card_id)
    finally:
        conn.close()
    return {"card_id": card_id, "deleted": True}


# --- Anki sync ---


@app.post("/api/lectures/{lecture_id}/sync")
def api_sync(lecture_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Lecture not found.")
        approved = get_approved_unsynced_cards(conn, lecture_id)
        if not approved:
            raise HTTPException(400, "No approved unsynced cards for this lecture.")

        job = create_job_run(conn, "sync", lecture_id)
        logger.info("Starting sync job %d for lecture %d", job.id, lecture_id)
    finally:
        conn.close()

    def _do_sync() -> dict[str, Any]:
        from src.anki_client import sync_lecture

        c = _connect()
        try:
            on_progress = _make_progress_callback(job.id)
            result = sync_lecture(c, lecture_id, on_progress=on_progress)
            return {"synced": result.synced, "failed": result.failed, "errors": result.errors}
        finally:
            c.close()

    _run_job_in_background(job.id, lecture_id, _do_sync)
    return {"job_id": job.id}


# --- Jobs ---


@app.get("/api/jobs/{job_id}")
def api_job_status(job_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        job = get_job_run(conn, job_id)
        if job is None:
            raise HTTPException(404, "Job not found.")
        return _serialize_job_run(conn, job)
    finally:
        conn.close()


@app.get("/api/jobs/{job_id}/events")
def api_job_events(job_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        job = get_job_run(conn, job_id)
        if job is None:
            raise HTTPException(404, "Job not found.")
        events = get_job_events(conn, job_id)
    finally:
        conn.close()
    return {
        "job_id": job_id,
        "events": [
            {
                "id": e.id,
                "stage": e.stage,
                "level": e.level,
                "message": e.message,
                "created_at": str(e.created_at),
            }
            for e in events
        ],
    }


@app.get("/api/jobs")
def api_recent_jobs() -> dict[str, Any]:
    conn = _connect()
    try:
        jobs = get_recent_jobs(conn, limit=20)
        return {
            "jobs": [_serialize_job_run(conn, j) for j in jobs],
        }
    finally:
        conn.close()


# --- Static files (must be last) ---

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Serve index.html at root
@app.get("/")
def index() -> Any:
    from fastapi.responses import FileResponse

    return FileResponse(STATIC_DIR / "index.html")


# ---------------------------------------------------------------------------
# Entry point for CLI
# ---------------------------------------------------------------------------


def run_web_app(
    host: str = "127.0.0.1",
    port: int = 8000,
    database_path: Path | None = None,
) -> None:
    """Run the FastAPI app with uvicorn."""
    global _database_path
    _database_path = database_path

    import uvicorn

    uvicorn.run("src.web:app", host=host, port=port, log_level="info")
