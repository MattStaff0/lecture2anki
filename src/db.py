import json
import sqlite3
from datetime import datetime

from src.models import Card, Course, Lecture, Segment, Unit


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
            duration_seconds REAL
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
            synced_to_anki BOOLEAN DEFAULT FALSE,
            anki_note_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)


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
        "SELECT id, unit_id, title, recorded_at, duration_seconds "
        "FROM lectures WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return Lecture(
        id=row[0], unit_id=row[1], title=row[2],
        recorded_at=_parse_datetime(row[3]), duration_seconds=row[4],
    )


def get_lectures_for_unit(conn: sqlite3.Connection, unit_id: int) -> list[Lecture]:
    """Get all lectures for a unit."""
    rows = conn.execute(
        "SELECT id, unit_id, title, recorded_at, duration_seconds "
        "FROM lectures WHERE unit_id = ? ORDER BY recorded_at",
        (unit_id,),
    ).fetchall()
    return [
        Lecture(
            id=r[0], unit_id=r[1], title=r[2],
            recorded_at=_parse_datetime(r[3]), duration_seconds=r[4],
        )
        for r in rows
    ]


def get_lecture_by_id(conn: sqlite3.Connection, lecture_id: int) -> Lecture | None:
    """Get a lecture by ID, or None if not found."""
    row = conn.execute(
        "SELECT id, unit_id, title, recorded_at, duration_seconds "
        "FROM lectures WHERE id = ?",
        (lecture_id,),
    ).fetchone()
    if row is None:
        return None
    return Lecture(
        id=row[0], unit_id=row[1], title=row[2],
        recorded_at=_parse_datetime(row[3]), duration_seconds=row[4],
    )


def update_lecture_duration(
    conn: sqlite3.Connection, lecture_id: int, duration_seconds: float
) -> None:
    """Update the recorded duration for a lecture."""
    conn.execute(
        "UPDATE lectures SET duration_seconds = ? WHERE id = ?",
        (duration_seconds, lecture_id),
    )
    conn.commit()


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


# --- Cards ---


def create_card(
    conn: sqlite3.Connection,
    lecture_id: int,
    front: str,
    back: str,
    tags: list[str],
) -> Card:
    """Create a flashcard for a lecture."""
    tags_json = json.dumps(tags)
    cursor = conn.execute(
        "INSERT INTO cards (lecture_id, front, back, tags) VALUES (?, ?, ?, ?)",
        (lecture_id, front, back, tags_json),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, lecture_id, front, back, tags, synced_to_anki, "
        "anki_note_id, created_at FROM cards WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return _row_to_card(row)


def get_cards_for_lecture(conn: sqlite3.Connection, lecture_id: int) -> list[Card]:
    """Get all cards for a lecture."""
    rows = conn.execute(
        "SELECT id, lecture_id, front, back, tags, synced_to_anki, "
        "anki_note_id, created_at FROM cards WHERE lecture_id = ?",
        (lecture_id,),
    ).fetchall()
    return [_row_to_card(r) for r in rows]


def get_unsynced_cards(conn: sqlite3.Connection) -> list[Card]:
    """Get all cards not yet synced to Anki."""
    rows = conn.execute(
        "SELECT id, lecture_id, front, back, tags, synced_to_anki, "
        "anki_note_id, created_at FROM cards WHERE synced_to_anki = 0",
    ).fetchall()
    return [_row_to_card(r) for r in rows]


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
        synced_to_anki=bool(row[5]),
        anki_note_id=row[6],
        created_at=_parse_datetime(row[7]),
    )


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
