import json
import sqlite3
from datetime import datetime
from pathlib import Path

from src.models import Card, Course, JobEvent, JobRun, Lecture, Segment, Unit


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables with foreign keys enabled."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL REFERENCES courses(id),
            name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_id, name)
        );

        CREATE TABLE IF NOT EXISTS lectures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id INTEGER NOT NULL REFERENCES units(id),
            title TEXT,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_seconds REAL,
            notes_text TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lecture_id INTEGER NOT NULL REFERENCES lectures(id),
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lecture_id INTEGER NOT NULL REFERENCES lectures(id),
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            tags TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            synced_to_anki BOOLEAN DEFAULT FALSE,
            anki_note_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS job_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            lecture_id INTEGER NOT NULL REFERENCES lectures(id),
            status TEXT NOT NULL DEFAULT 'queued',
            current_stage TEXT NOT NULL DEFAULT '',
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            error_message TEXT,
            details_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL REFERENCES job_runs(id),
            stage TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Idempotent migration for existing databases
    try:
        conn.execute("ALTER TABLE lectures ADD COLUMN notes_text TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists


def _parse_datetime(value: str | None) -> datetime:
    """Parse a SQLite timestamp string into a datetime."""
    if value is None:
        return datetime.now()
    return datetime.fromisoformat(value)


# --- Courses ---


def create_course(conn: sqlite3.Connection, name: str) -> Course:
    """Create a new course."""
    cursor = conn.execute(
        "INSERT INTO courses (name) VALUES (?)", (name,)
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, name, created_at FROM courses WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return Course(id=row[0], name=row[1], created_at=_parse_datetime(row[2]))


def get_courses(conn: sqlite3.Connection) -> list[Course]:
    """Get all courses."""
    rows = conn.execute("SELECT id, name, created_at FROM courses").fetchall()
    return [
        Course(id=r[0], name=r[1], created_at=_parse_datetime(r[2]))
        for r in rows
    ]


def get_course_by_id(conn: sqlite3.Connection, course_id: int) -> Course | None:
    """Get a course by ID, or None if not found."""
    row = conn.execute(
        "SELECT id, name, created_at FROM courses WHERE id = ?", (course_id,)
    ).fetchone()
    if row is None:
        return None
    return Course(id=row[0], name=row[1], created_at=_parse_datetime(row[2]))


def get_course_by_name(conn: sqlite3.Connection, name: str) -> Course | None:
    """Get a course by name, or None if not found."""
    row = conn.execute(
        "SELECT id, name, created_at FROM courses WHERE name = ?",
        (name,),
    ).fetchone()
    if row is None:
        return None
    return Course(id=row[0], name=row[1], created_at=_parse_datetime(row[2]))


# --- Units ---


def create_unit(
    conn: sqlite3.Connection,
    course_id: int,
    name: str,
    sort_order: int = 0,
) -> Unit:
    """Create a new unit in a course."""
    cursor = conn.execute(
        "INSERT INTO units (course_id, name, sort_order) VALUES (?, ?, ?)",
        (course_id, name, sort_order),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, course_id, name, sort_order, created_at FROM units WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return Unit(
        id=row[0], course_id=row[1], name=row[2],
        sort_order=row[3], created_at=_parse_datetime(row[4]),
    )


def get_units_for_course(conn: sqlite3.Connection, course_id: int) -> list[Unit]:
    """Get all units for a course, ordered by sort_order."""
    rows = conn.execute(
        "SELECT id, course_id, name, sort_order, created_at "
        "FROM units WHERE course_id = ? ORDER BY sort_order",
        (course_id,),
    ).fetchall()
    return [
        Unit(
            id=r[0], course_id=r[1], name=r[2],
            sort_order=r[3], created_at=_parse_datetime(r[4]),
        )
        for r in rows
    ]


def get_unit_by_name(conn: sqlite3.Connection, course_id: int, name: str) -> Unit | None:
    """Get a unit by course and name, or None if not found."""
    row = conn.execute(
        "SELECT id, course_id, name, sort_order, created_at "
        "FROM units WHERE course_id = ? AND name = ?",
        (course_id, name),
    ).fetchone()
    if row is None:
        return None
    return Unit(
        id=row[0],
        course_id=row[1],
        name=row[2],
        sort_order=row[3],
        created_at=_parse_datetime(row[4]),
    )


# --- Lectures ---


def create_lecture(
    conn: sqlite3.Connection,
    unit_id: int,
    title: str | None = None,
) -> Lecture:
    """Create a new lecture in a unit."""
    cursor = conn.execute(
        "INSERT INTO lectures (unit_id, title) VALUES (?, ?)",
        (unit_id, title),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, unit_id, title, recorded_at, duration_seconds, notes_text "
        "FROM lectures WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return _row_to_lecture(row)


def _row_to_lecture(row: tuple) -> Lecture:
    """Convert a lecture row to a Lecture object."""
    return Lecture(
        id=row[0], unit_id=row[1], title=row[2],
        recorded_at=_parse_datetime(row[3]), duration_seconds=row[4],
        notes_text=row[5] if len(row) > 5 and row[5] else "",
    )


def get_lectures_for_unit(conn: sqlite3.Connection, unit_id: int) -> list[Lecture]:
    """Get all lectures for a unit."""
    rows = conn.execute(
        "SELECT id, unit_id, title, recorded_at, duration_seconds, notes_text "
        "FROM lectures WHERE unit_id = ? ORDER BY recorded_at",
        (unit_id,),
    ).fetchall()
    return [_row_to_lecture(r) for r in rows]


def get_lecture_by_id(conn: sqlite3.Connection, lecture_id: int) -> Lecture | None:
    """Get a lecture by ID, or None if not found."""
    row = conn.execute(
        "SELECT id, unit_id, title, recorded_at, duration_seconds, notes_text "
        "FROM lectures WHERE id = ?",
        (lecture_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_lecture(row)


def update_lecture_duration(
    conn: sqlite3.Connection, lecture_id: int, duration_seconds: float
) -> None:
    """Update the recorded duration for a lecture."""
    conn.execute(
        "UPDATE lectures SET duration_seconds = ? WHERE id = ?",
        (duration_seconds, lecture_id),
    )
    conn.commit()


def update_lecture_notes(
    conn: sqlite3.Connection, lecture_id: int, notes_text: str
) -> None:
    """Update the notes text for a lecture."""
    conn.execute(
        "UPDATE lectures SET notes_text = ? WHERE id = ?",
        (notes_text, lecture_id),
    )
    conn.commit()


def get_lecture_notes(conn: sqlite3.Connection, lecture_id: int) -> str:
    """Get the notes text for a lecture."""
    row = conn.execute(
        "SELECT notes_text FROM lectures WHERE id = ?",
        (lecture_id,),
    ).fetchone()
    if row is None:
        return ""
    return row[0] or ""


# --- Segments ---


def add_segment(
    conn: sqlite3.Connection,
    lecture_id: int,
    start_time: float,
    end_time: float,
    text: str,
) -> Segment:
    """Add a transcript segment to a lecture."""
    cursor = conn.execute(
        "INSERT INTO segments (lecture_id, start_time, end_time, text) "
        "VALUES (?, ?, ?, ?)",
        (lecture_id, start_time, end_time, text),
    )
    conn.commit()
    return Segment(
        id=cursor.lastrowid,
        lecture_id=lecture_id,
        start_time=start_time,
        end_time=end_time,
        text=text,
    )


def get_segments_for_lecture(
    conn: sqlite3.Connection, lecture_id: int
) -> list[Segment]:
    """Get all segments for a lecture, ordered by start_time."""
    rows = conn.execute(
        "SELECT id, lecture_id, start_time, end_time, text "
        "FROM segments WHERE lecture_id = ? ORDER BY start_time",
        (lecture_id,),
    ).fetchall()
    return [
        Segment(id=r[0], lecture_id=r[1], start_time=r[2], end_time=r[3], text=r[4])
        for r in rows
    ]


def delete_segments_for_lecture(conn: sqlite3.Connection, lecture_id: int) -> None:
    """Delete all transcript segments for a lecture."""
    conn.execute("DELETE FROM segments WHERE lecture_id = ?", (lecture_id,))
    conn.commit()


# --- Cards ---


_CARD_COLS = (
    "id, lecture_id, front, back, tags, status, synced_to_anki, anki_note_id, created_at"
)


def create_card(
    conn: sqlite3.Connection,
    lecture_id: int,
    front: str,
    back: str,
    tags: list[str],
    status: str = "pending",
) -> Card:
    """Create a flashcard for a lecture."""
    tags_json = json.dumps(tags)
    cursor = conn.execute(
        "INSERT INTO cards (lecture_id, front, back, tags, status) VALUES (?, ?, ?, ?, ?)",
        (lecture_id, front, back, tags_json, status),
    )
    conn.commit()
    row = conn.execute(
        f"SELECT {_CARD_COLS} FROM cards WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return _row_to_card(row)


def get_cards_for_lecture(conn: sqlite3.Connection, lecture_id: int) -> list[Card]:
    """Get all cards for a lecture."""
    rows = conn.execute(
        f"SELECT {_CARD_COLS} FROM cards WHERE lecture_id = ?",
        (lecture_id,),
    ).fetchall()
    return [_row_to_card(r) for r in rows]


def get_cards_for_lecture_by_status(
    conn: sqlite3.Connection, lecture_id: int, status: str
) -> list[Card]:
    """Get cards for a lecture filtered by status."""
    rows = conn.execute(
        f"SELECT {_CARD_COLS} FROM cards WHERE lecture_id = ? AND status = ?",
        (lecture_id, status),
    ).fetchall()
    return [_row_to_card(r) for r in rows]


def get_approved_unsynced_cards(
    conn: sqlite3.Connection, lecture_id: int
) -> list[Card]:
    """Get approved cards not yet synced to Anki for a lecture."""
    rows = conn.execute(
        f"SELECT {_CARD_COLS} FROM cards "
        "WHERE lecture_id = ? AND status = 'approved' AND synced_to_anki = 0",
        (lecture_id,),
    ).fetchall()
    return [_row_to_card(r) for r in rows]


def get_unsynced_cards(conn: sqlite3.Connection) -> list[Card]:
    """Get all approved cards not yet synced to Anki."""
    rows = conn.execute(
        f"SELECT {_CARD_COLS} FROM cards "
        "WHERE status = 'approved' AND synced_to_anki = 0",
    ).fetchall()
    return [_row_to_card(r) for r in rows]


def approve_card(conn: sqlite3.Connection, card_id: int) -> None:
    """Set a card's status to approved."""
    conn.execute("UPDATE cards SET status = 'approved' WHERE id = ?", (card_id,))
    conn.commit()


def delete_card(conn: sqlite3.Connection, card_id: int) -> None:
    """Delete a card (reject)."""
    conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    conn.commit()


def delete_cards_for_lecture(conn: sqlite3.Connection, lecture_id: int) -> None:
    """Delete all cards for a lecture (used before regeneration)."""
    conn.execute("DELETE FROM cards WHERE lecture_id = ?", (lecture_id,))
    conn.commit()


def get_card_by_id(conn: sqlite3.Connection, card_id: int) -> Card | None:
    """Get a card by ID."""
    row = conn.execute(
        f"SELECT {_CARD_COLS} FROM cards WHERE id = ?", (card_id,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_card(row)


def mark_card_synced(
    conn: sqlite3.Connection, card_id: int, anki_note_id: int
) -> None:
    """Mark a card as synced to Anki."""
    conn.execute(
        "UPDATE cards SET synced_to_anki = 1, anki_note_id = ? WHERE id = ?",
        (anki_note_id, card_id),
    )
    conn.commit()


def _row_to_card(row: tuple) -> Card:
    """Convert a database row to a Card dataclass."""
    return Card(
        id=row[0],
        lecture_id=row[1],
        front=row[2],
        back=row[3],
        tags=json.loads(row[4]) if row[4] else [],
        status=row[5],
        synced_to_anki=bool(row[6]),
        anki_note_id=row[7],
        created_at=_parse_datetime(row[8]),
    )


# --- Job Runs ---


_JOB_COLS = (
    "id, job_type, lecture_id, status, current_stage, "
    "started_at, finished_at, error_message, details_json, created_at"
)


def _row_to_job_run(row: tuple) -> JobRun:
    """Convert a database row to a JobRun dataclass."""
    return JobRun(
        id=row[0],
        job_type=row[1],
        lecture_id=row[2],
        status=row[3],
        current_stage=row[4],
        started_at=_parse_datetime(row[5]) if row[5] else None,
        finished_at=_parse_datetime(row[6]) if row[6] else None,
        error_message=row[7],
        details_json=json.loads(row[8]) if row[8] else None,
        created_at=_parse_datetime(row[9]),
    )


def create_job_run(
    conn: sqlite3.Connection,
    job_type: str,
    lecture_id: int,
) -> JobRun:
    """Create a new job run in queued state."""
    cursor = conn.execute(
        "INSERT INTO job_runs (job_type, lecture_id, status, current_stage) "
        "VALUES (?, ?, 'queued', '')",
        (job_type, lecture_id),
    )
    conn.commit()
    row = conn.execute(
        f"SELECT {_JOB_COLS} FROM job_runs WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return _row_to_job_run(row)


def update_job_status(
    conn: sqlite3.Connection,
    job_id: int,
    status: str,
    current_stage: str = "",
    error_message: str | None = None,
    details_json: dict | None = None,
) -> None:
    """Update a job's status and optional fields."""
    sets = ["status = ?", "current_stage = ?"]
    params: list = [status, current_stage]

    if status == "running":
        sets.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
    if status in ("succeeded", "failed", "cancelled"):
        sets.append("finished_at = CURRENT_TIMESTAMP")
    if error_message is not None:
        sets.append("error_message = ?")
        params.append(error_message)
    if details_json is not None:
        sets.append("details_json = ?")
        params.append(json.dumps(details_json))

    params.append(job_id)
    conn.execute(f"UPDATE job_runs SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()


def update_job_stage(
    conn: sqlite3.Connection,
    job_id: int,
    stage: str,
) -> None:
    """Update only the current_stage of a running job."""
    conn.execute(
        "UPDATE job_runs SET current_stage = ? WHERE id = ?",
        (stage, job_id),
    )
    conn.commit()


def get_job_run(conn: sqlite3.Connection, job_id: int) -> JobRun | None:
    """Get a job run by ID."""
    row = conn.execute(
        f"SELECT {_JOB_COLS} FROM job_runs WHERE id = ?", (job_id,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_job_run(row)


def get_active_job_for_lecture(
    conn: sqlite3.Connection, lecture_id: int
) -> JobRun | None:
    """Get the most recent running or queued job for a lecture."""
    row = conn.execute(
        f"SELECT {_JOB_COLS} FROM job_runs "
        "WHERE lecture_id = ? AND status IN ('queued', 'running') "
        "ORDER BY id DESC LIMIT 1",
        (lecture_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_job_run(row)


def get_recent_jobs(
    conn: sqlite3.Connection, limit: int = 20
) -> list[JobRun]:
    """Get recent job runs across all lectures."""
    rows = conn.execute(
        f"SELECT {_JOB_COLS} FROM job_runs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_row_to_job_run(r) for r in rows]


def get_jobs_for_lecture(
    conn: sqlite3.Connection, lecture_id: int, limit: int = 10
) -> list[JobRun]:
    """Get recent job runs for a specific lecture."""
    rows = conn.execute(
        f"SELECT {_JOB_COLS} FROM job_runs "
        "WHERE lecture_id = ? ORDER BY id DESC LIMIT ?",
        (lecture_id, limit),
    ).fetchall()
    return [_row_to_job_run(r) for r in rows]


# --- Job Events ---


def add_job_event(
    conn: sqlite3.Connection,
    job_id: int,
    stage: str,
    message: str,
    level: str = "info",
) -> JobEvent:
    """Add an event to a job run."""
    cursor = conn.execute(
        "INSERT INTO job_events (job_id, stage, level, message) "
        "VALUES (?, ?, ?, ?)",
        (job_id, stage, level, message),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, job_id, stage, level, message, created_at "
        "FROM job_events WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return JobEvent(
        id=row[0], job_id=row[1], stage=row[2],
        level=row[3], message=row[4], created_at=_parse_datetime(row[5]),
    )


def get_job_events(
    conn: sqlite3.Connection, job_id: int
) -> list[JobEvent]:
    """Get all events for a job, ordered chronologically."""
    rows = conn.execute(
        "SELECT id, job_id, stage, level, message, created_at "
        "FROM job_events WHERE job_id = ? ORDER BY id",
        (job_id,),
    ).fetchall()
    return [
        JobEvent(
            id=r[0], job_id=r[1], stage=r[2],
            level=r[3], message=r[4], created_at=_parse_datetime(r[5]),
        )
        for r in rows
    ]


def get_latest_job_event(
    conn: sqlite3.Connection, job_id: int
) -> JobEvent | None:
    """Get the most recent event for a job."""
    row = conn.execute(
        "SELECT id, job_id, stage, level, message, created_at "
        "FROM job_events WHERE job_id = ? ORDER BY id DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    return JobEvent(
        id=row[0], job_id=row[1], stage=row[2],
        level=row[3], message=row[4], created_at=_parse_datetime(row[5]),
    )


# --- Deletions (cascade) ---


def _database_path_for_connection(conn: sqlite3.Connection) -> Path | None:
    """Return the on-disk path for the main SQLite database when available."""
    row = conn.execute("PRAGMA database_list").fetchone()
    if row is None:
        return None
    db_path = row[2]
    if not db_path:
        return None
    return Path(db_path)


def _delete_recording_files(conn: sqlite3.Connection, lecture_id: int) -> None:
    """Remove audio recording files for a lecture from disk."""
    from src.config import get_recordings_path

    directory = get_recordings_path(_database_path_for_connection(conn))
    for path in directory.glob(f"lecture-{lecture_id}-*"):
        if path.is_file():
            path.unlink()


def delete_lecture(conn: sqlite3.Connection, lecture_id: int) -> None:
    """Delete a lecture and its segments, cards, jobs, and recording files."""
    _delete_recording_files(conn, lecture_id)
    # Delete job events for all jobs of this lecture
    job_ids = [
        r[0] for r in conn.execute(
            "SELECT id FROM job_runs WHERE lecture_id = ?", (lecture_id,)
        ).fetchall()
    ]
    for jid in job_ids:
        conn.execute("DELETE FROM job_events WHERE job_id = ?", (jid,))
    conn.execute("DELETE FROM job_runs WHERE lecture_id = ?", (lecture_id,))
    conn.execute("DELETE FROM cards WHERE lecture_id = ?", (lecture_id,))
    conn.execute("DELETE FROM segments WHERE lecture_id = ?", (lecture_id,))
    conn.execute("DELETE FROM lectures WHERE id = ?", (lecture_id,))
    conn.commit()


def delete_unit(conn: sqlite3.Connection, unit_id: int) -> None:
    """Delete a unit and all its lectures, segments, cards, and recordings."""
    lecture_ids = [
        r[0] for r in conn.execute(
            "SELECT id FROM lectures WHERE unit_id = ?", (unit_id,)
        ).fetchall()
    ]
    for lid in lecture_ids:
        _delete_recording_files(conn, lid)
        job_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM job_runs WHERE lecture_id = ?", (lid,)
            ).fetchall()
        ]
        for jid in job_ids:
            conn.execute("DELETE FROM job_events WHERE job_id = ?", (jid,))
        conn.execute("DELETE FROM job_runs WHERE lecture_id = ?", (lid,))
        conn.execute("DELETE FROM cards WHERE lecture_id = ?", (lid,))
        conn.execute("DELETE FROM segments WHERE lecture_id = ?", (lid,))
    conn.execute("DELETE FROM lectures WHERE unit_id = ?", (unit_id,))
    conn.execute("DELETE FROM units WHERE id = ?", (unit_id,))
    conn.commit()


def delete_course(conn: sqlite3.Connection, course_id: int) -> None:
    """Delete a course and all its units, lectures, segments, cards, and recordings."""
    unit_ids = [
        r[0] for r in conn.execute(
            "SELECT id FROM units WHERE course_id = ?", (course_id,)
        ).fetchall()
    ]
    for uid in unit_ids:
        lecture_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM lectures WHERE unit_id = ?", (uid,)
            ).fetchall()
        ]
        for lid in lecture_ids:
            _delete_recording_files(conn, lid)
            job_ids = [
                r[0] for r in conn.execute(
                    "SELECT id FROM job_runs WHERE lecture_id = ?", (lid,)
                ).fetchall()
            ]
            for jid in job_ids:
                conn.execute("DELETE FROM job_events WHERE job_id = ?", (jid,))
            conn.execute("DELETE FROM job_runs WHERE lecture_id = ?", (lid,))
            conn.execute("DELETE FROM cards WHERE lecture_id = ?", (lid,))
            conn.execute("DELETE FROM segments WHERE lecture_id = ?", (lid,))
        conn.execute("DELETE FROM lectures WHERE unit_id = ?", (uid,))
    conn.execute("DELETE FROM units WHERE course_id = ?", (course_id,))
    conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
    conn.commit()


# --- Helpers ---


def get_deck_path_for_lecture(conn: sqlite3.Connection, lecture_id: int) -> str:
    """Get the Anki deck path (e.g., 'AI::Midterm 2') for a lecture."""
    row = conn.execute(
        "SELECT c.name, u.name "
        "FROM lectures l "
        "JOIN units u ON l.unit_id = u.id "
        "JOIN courses c ON u.course_id = c.id "
        "WHERE l.id = ?",
        (lecture_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Lecture {lecture_id} not found")
    return f"{row[0]}::{row[1]}"
