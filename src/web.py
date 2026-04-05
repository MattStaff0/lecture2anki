"""FastAPI-based local web UI for Lecture2Anki."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import get_database_path
from src.db import (
    approve_card,
    create_course,
    create_unit,
    delete_card,
    get_approved_unsynced_cards,
    get_card_by_id,
    get_cards_for_lecture,
    get_course_by_id,
    get_courses,
    get_unit_by_name,
    get_units_for_course,
    init_db,
)
from src.recorder import save_uploaded_audio
from src.transcriber import find_recording_for_lecture, transcribe_lecture

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


# ---------------------------------------------------------------------------
# Background job registry
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


@dataclass
class Job:
    id: str
    type: str
    status: JobStatus = JobStatus.queued
    message: str = ""
    result: dict[str, Any] = field(default_factory=dict)


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def _create_job(job_type: str) -> Job:
    job_id = uuid.uuid4().hex[:12]
    job = Job(id=job_id, type=job_type)
    with _jobs_lock:
        _jobs[job_id] = job
    return job


def _get_job(job_id: str) -> Job | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def _run_in_background(job: Job, target: Any, args: tuple = ()) -> None:
    """Run *target* in a daemon thread, updating job status on completion."""

    def _wrapper() -> None:
        job.status = JobStatus.running
        try:
            result = target(*args)
            job.result = result if isinstance(result, dict) else {}
            job.status = JobStatus.succeeded
            job.message = "Done"
        except Exception as exc:
            job.status = JobStatus.failed
            job.message = str(exc)

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
            find_recording_for_lecture(lecture_id)
            has_recording = True
        except FileNotFoundError:
            has_recording = False

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
        units = get_units_for_course(conn, course_id)
        if units:
            raise HTTPException(
                409, "Cannot delete course with existing units. Delete units first."
            )
        conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        conn.commit()
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
        lectures = conn.execute(
            "SELECT id FROM lectures WHERE unit_id = ?", (unit_id,)
        ).fetchall()
        if lectures:
            raise HTTPException(
                409, "Cannot delete unit with existing lectures."
            )
        conn.execute("DELETE FROM units WHERE id = ?", (unit_id,))
        conn.commit()
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


# --- Transcription ---


@app.post("/api/lectures/{lecture_id}/transcribe")
def api_transcribe(lecture_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Lecture not found.")
        try:
            find_recording_for_lecture(lecture_id)
        except FileNotFoundError:
            raise HTTPException(400, "No recording found for this lecture.")
    finally:
        conn.close()

    job = _create_job("transcription")

    def _do_transcribe() -> dict[str, Any]:
        c = _connect()
        try:
            segs = transcribe_lecture(c, lecture_id)
            return {"lecture_id": lecture_id, "segment_count": len(segs)}
        finally:
            c.close()

    _run_in_background(job, _do_transcribe)
    return {"job_id": job.id}


@app.get("/api/lectures/{lecture_id}/segments")
def api_segments(lecture_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
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
    finally:
        conn.close()

    job = _create_job("generation")

    def _do_generate() -> dict[str, Any]:
        from src.card_generator import generate_cards_for_lecture

        c = _connect()
        try:
            cards = generate_cards_for_lecture(c, lecture_id)
            return {"lecture_id": lecture_id, "card_count": len(cards)}
        finally:
            c.close()

    _run_in_background(job, _do_generate)
    return {"job_id": job.id}


# --- Cards ---


@app.get("/api/lectures/{lecture_id}/cards")
def api_cards(lecture_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
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
    finally:
        conn.close()

    job = _create_job("sync")

    def _do_sync() -> dict[str, Any]:
        from src.anki_client import sync_lecture

        c = _connect()
        try:
            result = sync_lecture(c, lecture_id)
            return {"synced": result.synced, "failed": result.failed, "errors": result.errors}
        finally:
            c.close()

    _run_in_background(job, _do_sync)
    return {"job_id": job.id}


# --- Jobs ---


@app.get("/api/jobs/{job_id}")
def api_job_status(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return {
        "job_id": job.id,
        "type": job.type,
        "status": job.status.value,
        "message": job.message,
        "result": job.result,
    }


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

    uvicorn.run(app, host=host, port=port, log_level="info")
