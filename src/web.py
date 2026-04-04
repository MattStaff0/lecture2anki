"""Local web UI for Lecture2Anki."""

from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from src.config import get_database_path
from src.db import create_course, create_unit, get_courses, get_units_for_course, init_db
from src.recorder import save_uploaded_audio
from src.transcriber import find_recording_for_lecture, transcribe_lecture


STATIC_DIR = Path(__file__).resolve().parent / "web_static"
TRANSCRIBE_ROUTE = re.compile(r"^/api/lectures/(?P<lecture_id>\d+)/transcribe$")
SEGMENTS_ROUTE = re.compile(r"^/api/lectures/(?P<lecture_id>\d+)/segments$")
MIME_TO_SUFFIX = {
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


def _connect(database_path: Path | None = None) -> sqlite3.Connection:
    """Open the configured SQLite database and ensure the schema exists."""
    path = database_path or get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    init_db(conn)
    return conn


def _json_response(start_response, status: str, payload: dict[str, Any]) -> list[bytes]:
    """Return a JSON response."""
    body = json.dumps(payload).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ]
    start_response(status, headers)
    return [body]


def _text_response(start_response, status: str, text: str) -> list[bytes]:
    """Return a plain-text response."""
    body = text.encode("utf-8")
    headers = [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ]
    start_response(status, headers)
    return [body]


def _serve_static(start_response, asset_name: str) -> list[bytes]:
    """Serve a static UI asset from disk."""
    asset_path = STATIC_DIR / asset_name
    if not asset_path.exists():
        return _text_response(start_response, "404 Not Found", "Asset not found.")

    body = asset_path.read_bytes()
    content_type = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ]
    start_response("200 OK", headers)
    return [body]


def _read_json_body(environ) -> dict[str, Any]:
    """Read a JSON request body."""
    try:
        content_length = int(environ.get("CONTENT_LENGTH", "0") or "0")
    except ValueError:
        content_length = 0
    raw_body = environ["wsgi.input"].read(content_length) if content_length else b""
    if not raw_body:
        return {}
    return json.loads(raw_body.decode("utf-8"))


def _read_multipart_form(environ):
    """Parse multipart form data."""
    import cgi

    return cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)


def _float_or_none(value: str | None) -> float | None:
    """Parse an optional float form field."""
    if value in (None, ""):
        return None
    return float(value)


def _audio_suffix(filename: str | None, content_type: str | None) -> str:
    """Resolve an audio file suffix from filename or content type."""
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix:
            return suffix
    if content_type and content_type in MIME_TO_SUFFIX:
        return MIME_TO_SUFFIX[content_type]
    return ".webm"


def _serialize_bootstrap(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the data required to render the UI."""
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
        "c.id AS course_id, c.name AS course_name, COUNT(s.id) AS segment_count "
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
            }
        )

    return {
        "courses": courses,
        "lectures": lectures,
    }


def _serialize_segments(conn: sqlite3.Connection, lecture_id: int) -> list[dict[str, Any]]:
    """Return transcript segments for a lecture."""
    rows = conn.execute(
        "SELECT id, start_time, end_time, text "
        "FROM segments WHERE lecture_id = ? ORDER BY start_time",
        (lecture_id,),
    ).fetchall()
    return [
        {
            "id": row[0],
            "start_time": row[1],
            "end_time": row[2],
            "text": row[3],
        }
        for row in rows
    ]


class Lecture2AnkiWebApp:
    """Minimal WSGI app for the local browser UI."""

    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path

    def __call__(self, environ, start_response) -> list[bytes]:
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")

        try:
            if method == "GET" and path == "/":
                return _serve_static(start_response, "index.html")
            if method == "GET" and path == "/static/app.js":
                return _serve_static(start_response, "app.js")
            if method == "GET" and path == "/static/styles.css":
                return _serve_static(start_response, "styles.css")
            if method == "GET" and path == "/api/bootstrap":
                return self._bootstrap(start_response)
            if method == "POST" and path == "/api/courses":
                return self._create_course(environ, start_response)
            if method == "POST" and path == "/api/units":
                return self._create_unit(environ, start_response)
            if method == "POST" and path == "/api/lectures/upload":
                return self._upload_lecture(environ, start_response)

            transcribe_match = TRANSCRIBE_ROUTE.match(path)
            if method == "POST" and transcribe_match:
                lecture_id = int(transcribe_match.group("lecture_id"))
                return self._transcribe_lecture(start_response, lecture_id)

            segments_match = SEGMENTS_ROUTE.match(path)
            if method == "GET" and segments_match:
                lecture_id = int(segments_match.group("lecture_id"))
                return self._segments(start_response, lecture_id)

            return _text_response(start_response, "404 Not Found", "Route not found.")
        except sqlite3.IntegrityError as exc:
            return _json_response(start_response, "409 Conflict", {"error": str(exc)})
        except ValueError as exc:
            return _json_response(start_response, "400 Bad Request", {"error": str(exc)})
        except FileNotFoundError as exc:
            return _json_response(start_response, "404 Not Found", {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - defensive fallback
            return _json_response(start_response, "500 Internal Server Error", {"error": str(exc)})

    def _bootstrap(self, start_response) -> list[bytes]:
        conn = _connect(self.database_path)
        try:
            payload = _serialize_bootstrap(conn)
        finally:
            conn.close()
        return _json_response(start_response, "200 OK", payload)

    def _create_course(self, environ, start_response) -> list[bytes]:
        body = _read_json_body(environ)
        name = (body.get("name") or "").strip()
        if not name:
            raise ValueError("Course name is required.")

        conn = _connect(self.database_path)
        try:
            course = create_course(conn, name)
        finally:
            conn.close()

        return _json_response(
            start_response,
            "201 Created",
            {"course": {"id": course.id, "name": course.name}},
        )

    def _create_unit(self, environ, start_response) -> list[bytes]:
        body = _read_json_body(environ)
        unit_name = (body.get("name") or "").strip()
        if not unit_name:
            raise ValueError("Unit name is required.")

        try:
            course_id = int(body.get("course_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("A valid course is required.") from exc

        sort_order = int(body.get("sort_order") or 0)

        conn = _connect(self.database_path)
        try:
            unit = create_unit(conn, course_id, unit_name, sort_order=sort_order)
        finally:
            conn.close()

        return _json_response(
            start_response,
            "201 Created",
            {
                "unit": {
                    "id": unit.id,
                    "course_id": unit.course_id,
                    "name": unit.name,
                    "sort_order": unit.sort_order,
                }
            },
        )

    def _upload_lecture(self, environ, start_response) -> list[bytes]:
        form = _read_multipart_form(environ)
        try:
            unit_id = int(form.getfirst("unit_id", ""))
        except ValueError as exc:
            raise ValueError("A valid unit is required.") from exc

        title = (form.getfirst("title", "") or "").strip() or None
        duration_seconds = _float_or_none(form.getfirst("duration_seconds"))

        if "audio" not in form:
            raise ValueError("Audio upload is required.")

        upload = form["audio"]
        audio_bytes = upload.file.read()
        if not audio_bytes:
            raise ValueError("Uploaded audio file is empty.")

        suffix = _audio_suffix(upload.filename, upload.type)

        conn = _connect(self.database_path)
        try:
            result = save_uploaded_audio(
                conn,
                unit_id=unit_id,
                audio_bytes=audio_bytes,
                suffix=suffix,
                title=title,
                duration_seconds=duration_seconds,
            )
        finally:
            conn.close()

        return _json_response(
            start_response,
            "201 Created",
            {
                "lecture": {
                    "id": result.lecture.id,
                    "title": result.lecture.title,
                    "duration_seconds": result.duration_seconds,
                    "audio_path": str(result.audio_path),
                }
            },
        )

    def _transcribe_lecture(self, start_response, lecture_id: int) -> list[bytes]:
        conn = _connect(self.database_path)
        try:
            segments = transcribe_lecture(conn, lecture_id)
        finally:
            conn.close()

        return _json_response(
            start_response,
            "200 OK",
            {"lecture_id": lecture_id, "segment_count": len(segments)},
        )

    def _segments(self, start_response, lecture_id: int) -> list[bytes]:
        conn = _connect(self.database_path)
        try:
            payload = {"lecture_id": lecture_id, "segments": _serialize_segments(conn, lecture_id)}
        finally:
            conn.close()
        return _json_response(start_response, "200 OK", payload)


def run_web_app(host: str = "127.0.0.1", port: int = 8000, database_path: Path | None = None) -> None:
    """Run the local web app until interrupted."""
    app = Lecture2AnkiWebApp(database_path=database_path)
    with make_server(host, port, app) as server:
        server.serve_forever()
