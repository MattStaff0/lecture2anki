"""Local web UI for Lecture2Anki — FastAPI backend."""

from __future__ import annotations

import sqlite3
import threading
import uuid
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
    get_approved_unsynced_cards_for_lecture,
    get_card_by_id,
    get_cards_for_lecture,
    get_course_by_id,
    get_courses,
    get_lecture_by_id,
    get_segments_for_lecture,
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
# In-memory job registry
# ---------------------------------------------------------------------------

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _create_job(job_type: str, lecture_id: int) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "type": job_type,
            "lecture_id": lecture_id,
            "status": "queued",
            "result": None,
            "error": None,
        }
    return job_id


def _update_job(job_id: str, **kwargs: Any) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def _get_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        return _jobs.get(job_id, None)


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


def _serialize_card(card: Any) -> dict[str, Any]:
    return {
        "id": card.id,
        "lecture_id": card.lecture_id,
        "front": card.front,
        "back": card.back,
        "tags": card.tags,
        "status": card.status,
        "synced_to_anki": card.synced_to_anki,
        "anki_note_id": card.anki_note_id,
    }


def _serialize_bootstrap(conn: sqlite3.Connection) -> dict[str, Any]:
    courses = []
    for course in get_courses(conn):
        courses.append(
            {
                "id": course.id,
                "name": course.name,
                "units": [
                    {
                        "id": unit.id,
                        "name": unit.name,
                        "sort_order": unit.sort_order,
                    }
                    for unit in get_units_for_course(conn, course.id)
                ],
            }
        )

    lecture_rows = conn.execute(
        "SELECT l.id, COALESCE(l.title, 'Untitled lecture') AS title, l.recorded_at, "
        "l.duration_seconds, u.id AS unit_id, u.name AS unit_name, "
        "c.id AS course_id, c.name AS course_name, "
        "COUNT(s.id) AS segment_count "
        "FROM lectures l "
        "JOIN units u ON l.unit_id = u.id "
        "JOIN courses c ON u.course_id = c.id "
        "LEFT JOIN segments s ON s.lecture_id = l.id "
        "GROUP BY l.id, u.id, c.id "
        "ORDER BY l.recorded_at DESC"
    ).fetchall()

    lectures = []
    for row in lecture_rows:
        lecture_id = row[0]
        try:
            recording_path = find_recording_for_lecture(lecture_id)
        except FileNotFoundError:
            recording_name = None
            has_recording = False
        else:
            recording_name = recording_path.name
            has_recording = True

        # Count cards per lecture
        card_rows = conn.execute(
            "SELECT "
            "COUNT(*) AS total, "
            "SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved, "
            "SUM(CASE WHEN synced_to_anki = 1 THEN 1 ELSE 0 END) AS synced "
            "FROM cards WHERE lecture_id = ?",
            (lecture_id,),
        ).fetchone()

        lectures.append(
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
                "has_recording": has_recording,
                "recording_name": recording_name,
                "card_count": card_rows[0] if card_rows else 0,
                "approved_count": card_rows[1] if card_rows else 0,
                "synced_count": card_rows[2] if card_rows else 0,
            }
        )

    return {"courses": courses, "lectures": lectures}


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


def create_app(database_path: Path | None = None) -> FastAPI:
    global _database_path
    _database_path = database_path

    app = FastAPI(title="Lecture2Anki", version="0.1.0")

    # --- Integrity / validation error handlers ---

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error_handler(request: Any, exc: sqlite3.IntegrityError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": str(exc)})

    # --- Bootstrap ---

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, Any]:
        conn = _connect()
        try:
            return _serialize_bootstrap(conn)
        finally:
            conn.close()

    # --- Courses ---

    @app.post("/api/courses", status_code=201)
    def create_course_endpoint(body: dict[str, Any]) -> dict[str, Any]:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Course name is required.")
        conn = _connect()
        try:
            course = create_course(conn, name)
        finally:
            conn.close()
        return {"course": {"id": course.id, "name": course.name}}

    # --- Units ---

    @app.post("/api/units", status_code=201)
    def create_unit_endpoint(body: dict[str, Any]) -> dict[str, Any]:
        unit_name = (body.get("name") or "").strip()
        if not unit_name:
            raise HTTPException(status_code=400, detail="Unit name is required.")
        try:
            course_id = int(body.get("course_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="A valid course_id is required.")
        conn = _connect()
        try:
            course = get_course_by_id(conn, course_id)
            if course is None:
                raise HTTPException(status_code=404, detail=f"Course {course_id} not found.")
            sort_order = int(body.get("sort_order") or 0)
            unit = create_unit(conn, course_id, unit_name, sort_order=sort_order)
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

    # --- Lecture upload ---

    @app.post("/api/lectures/upload", status_code=201)
    async def upload_lecture(
        unit_id: int = Form(...),
        audio: UploadFile = File(...),
        title: str = Form(""),
        duration_seconds: float | None = Form(None),
    ) -> dict[str, Any]:
        conn = _connect()
        try:
            # Validate unit exists
            row = conn.execute("SELECT id FROM units WHERE id = ?", (unit_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Unit {unit_id} not found.")

            audio_bytes = await audio.read()
            if not audio_bytes:
                raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

            suffix = _audio_suffix(audio.filename, audio.content_type)
            title_clean = title.strip() or None

            result = save_uploaded_audio(
                conn,
                unit_id=unit_id,
                audio_bytes=audio_bytes,
                suffix=suffix,
                title=title_clean,
                duration_seconds=duration_seconds,
            )
        finally:
            conn.close()

        return {
            "lecture": {
                "id": result.lecture.id,
                "title": result.lecture.title,
                "duration_seconds": result.duration_seconds,
                "audio_path": str(result.audio_path),
            }
        }

    # --- Transcription ---

    @app.post("/api/lectures/{lecture_id}/transcribe")
    def transcribe_endpoint(lecture_id: int) -> dict[str, Any]:
        conn = _connect()
        try:
            lecture = get_lecture_by_id(conn, lecture_id)
            if lecture is None:
                raise HTTPException(status_code=404, detail=f"Lecture {lecture_id} not found.")
            try:
                find_recording_for_lecture(lecture_id)
            except FileNotFoundError:
                raise HTTPException(
                    status_code=400,
                    detail=f"No recording found for lecture {lecture_id}. Upload audio first.",
                )

            # Run transcription as a background job
            job_id = _create_job("transcribe", lecture_id)

            def _run() -> None:
                c = _connect()
                try:
                    _update_job(job_id, status="running")
                    segments = transcribe_lecture(c, lecture_id)
                    _update_job(
                        job_id,
                        status="succeeded",
                        result={"segment_count": len(segments)},
                    )
                except Exception as exc:
                    _update_job(job_id, status="failed", error=str(exc))
                finally:
                    c.close()

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
        finally:
            conn.close()

        return {"job_id": job_id, "lecture_id": lecture_id}

    # --- Segments ---

    @app.get("/api/lectures/{lecture_id}/segments")
    def segments_endpoint(lecture_id: int) -> dict[str, Any]:
        conn = _connect()
        try:
            lecture = get_lecture_by_id(conn, lecture_id)
            if lecture is None:
                raise HTTPException(status_code=404, detail=f"Lecture {lecture_id} not found.")
            segments = get_segments_for_lecture(conn, lecture_id)
        finally:
            conn.close()
        return {
            "lecture_id": lecture_id,
            "segments": [
                {
                    "id": s.id,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "text": s.text,
                }
                for s in segments
            ],
        }

    # --- Cards ---

    @app.get("/api/lectures/{lecture_id}/cards")
    def cards_endpoint(lecture_id: int) -> dict[str, Any]:
        conn = _connect()
        try:
            lecture = get_lecture_by_id(conn, lecture_id)
            if lecture is None:
                raise HTTPException(status_code=404, detail=f"Lecture {lecture_id} not found.")
            cards = get_cards_for_lecture(conn, lecture_id)
        finally:
            conn.close()
        return {
            "lecture_id": lecture_id,
            "cards": [_serialize_card(c) for c in cards],
        }

    @app.post("/api/cards/{card_id}/approve")
    def approve_card_endpoint(card_id: int) -> dict[str, Any]:
        conn = _connect()
        try:
            existing = get_card_by_id(conn, card_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"Card {card_id} not found.")
            card = approve_card(conn, card_id)
        finally:
            conn.close()
        return {"card": _serialize_card(card)}

    @app.delete("/api/cards/{card_id}")
    def delete_card_endpoint(card_id: int) -> dict[str, Any]:
        conn = _connect()
        try:
            existing = get_card_by_id(conn, card_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"Card {card_id} not found.")
            delete_card(conn, card_id)
        finally:
            conn.close()
        return {"deleted": True, "card_id": card_id}

    # --- Jobs ---

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        job = _get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
        return job

    # --- Static files (must come last) ---

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Serve index.html at root
    from fastapi.responses import FileResponse

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def run_web_app(
    host: str = "127.0.0.1", port: int = 8000, database_path: Path | None = None
) -> None:
    """Run the local web app until interrupted."""
    import uvicorn

    global _database_path
    _database_path = database_path
    app = create_app(database_path=database_path)
    uvicorn.run(app, host=host, port=port)
