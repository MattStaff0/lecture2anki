"""Command-line interface for Lecture2Anki."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import click

from src.config import get_database_path, get_recordings_path
from src.db import (
    create_course,
    create_unit,
    get_course_by_name,
    get_courses,
    get_unit_by_name,
    get_units_for_course,
    init_db,
)
from src.recorder import record_lecture
from src.transcriber import transcribe_lecture


def _connect(database_path: Path | None = None) -> tuple[sqlite3.Connection, Path]:
    """Open the configured SQLite database and ensure the schema exists."""
    path = database_path or get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    init_db(conn)
    return conn, path


def _recordings_dir(database_path: Path | None) -> Path:
    """Resolve the recordings directory for the active database path."""
    return get_recordings_path(database_path)


def _course_or_exit(conn: sqlite3.Connection, course_name: str):
    """Return a course or exit with a usage error."""
    course = get_course_by_name(conn, course_name)
    if course is None:
        raise click.ClickException(f"Course not found: {course_name}")
    return course


def _unit_or_exit(conn: sqlite3.Connection, course_id: int, unit_name: str):
    """Return a unit or exit with a usage error."""
    unit = get_unit_by_name(conn, course_id, unit_name)
    if unit is None:
        raise click.ClickException(f"Unit not found: {unit_name}")
    return unit


@click.group()
@click.option(
    "--database-path",
    type=click.Path(path_type=Path, dir_okay=False, resolve_path=True),
    default=None,
    help="Override the SQLite database path.",
)
@click.pass_context
def main(ctx: click.Context, database_path: Path | None) -> None:
    """Manage local lecture transcription and Anki card generation."""
    ctx.ensure_object(dict)
    ctx.obj["database_path"] = database_path


@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Create the database and initialize the schema."""
    conn, path = _connect(ctx.obj["database_path"])
    conn.close()
    click.echo(f"Initialized database at {path}")


@main.group()
def courses() -> None:
    """Manage courses."""


@courses.command("list")
@click.pass_context
def list_courses(ctx: click.Context) -> None:
    """List all configured courses."""
    conn, _ = _connect(ctx.obj["database_path"])
    try:
        courses = get_courses(conn)
    finally:
        conn.close()

    if not courses:
        click.echo("No courses found.")
        return

    for course in courses:
        click.echo(course.name)


@courses.command("add")
@click.argument("name")
@click.pass_context
def add_course(ctx: click.Context, name: str) -> None:
    """Add a new course."""
    conn, _ = _connect(ctx.obj["database_path"])
    try:
        course = create_course(conn, name)
    except sqlite3.IntegrityError as exc:
        conn.close()
        raise click.ClickException(f"Course already exists: {name}") from exc
    else:
        conn.close()

    click.echo(f"Added course {course.name} (id={course.id})")


@main.group()
def units() -> None:
    """Manage units within courses."""


@units.command("list")
@click.argument("course_name")
@click.pass_context
def list_units(ctx: click.Context, course_name: str) -> None:
    """List units for a course."""
    conn, _ = _connect(ctx.obj["database_path"])
    try:
        course = _course_or_exit(conn, course_name)
        units = get_units_for_course(conn, course.id)
    finally:
        conn.close()

    if not units:
        click.echo(f"No units found for {course.name}.")
        return

    for unit in units:
        click.echo(f"{unit.sort_order}: {unit.name}")


@units.command("add")
@click.argument("course_name")
@click.argument("unit_name")
@click.option("--sort-order", default=0, show_default=True, type=int)
@click.pass_context
def add_unit(ctx: click.Context, course_name: str, unit_name: str, sort_order: int) -> None:
    """Add a unit to a course."""
    conn, _ = _connect(ctx.obj["database_path"])
    try:
        course = _course_or_exit(conn, course_name)
        unit = create_unit(conn, course.id, unit_name, sort_order=sort_order)
    except sqlite3.IntegrityError as exc:
        conn.close()
        raise click.ClickException(
            f"Unit already exists for course {course_name}: {unit_name}"
        ) from exc
    else:
        conn.close()

    click.echo(f"Added unit {unit.name} to {course.name} (id={unit.id})")


@main.command("lectures")
@click.option("--course", "course_name", default=None, help="Filter lectures by course name.")
@click.option("--unit", "unit_name", default=None, help="Filter lectures by unit name.")
@click.pass_context
def list_lectures(ctx: click.Context, course_name: str | None, unit_name: str | None) -> None:
    """List saved lectures."""
    conn, _ = _connect(ctx.obj["database_path"])
    try:
        rows = conn.execute(
            "SELECT l.id, COALESCE(l.title, 'Untitled lecture'), u.name, c.name, l.recorded_at "
            "FROM lectures l "
            "JOIN units u ON l.unit_id = u.id "
            "JOIN courses c ON u.course_id = c.id "
            "WHERE (? IS NULL OR c.name = ?) AND (? IS NULL OR u.name = ?) "
            "ORDER BY l.recorded_at DESC",
            (course_name, course_name, unit_name, unit_name),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        click.echo("No lectures found.")
        return

    for lecture_id, title, unit, course, recorded_at in rows:
        click.echo(f"{lecture_id}: {course} / {unit} / {title} ({recorded_at})")


@main.command("record")
@click.option("--course", "course_name", required=True, help="Course name for the lecture.")
@click.option("--unit", "unit_name", required=True, help="Unit name for the lecture.")
@click.option("--title", default=None, help="Optional lecture title.")
@click.option(
    "--duration-limit",
    type=float,
    default=None,
    help="Optional auto-stop duration in seconds.",
)
@click.pass_context
def record_command(
    ctx: click.Context,
    course_name: str,
    unit_name: str,
    title: str | None,
    duration_limit: float | None,
) -> None:
    """Record audio for a lecture and save it locally."""
    conn, _ = _connect(ctx.obj["database_path"])
    try:
        course = _course_or_exit(conn, course_name)
        unit = _unit_or_exit(conn, course.id, unit_name)
        click.echo(f"Recording lecture for {course.name} / {unit.name}")
        result = record_lecture(
            conn,
            unit.id,
            title=title,
            recordings_dir=_recordings_dir(ctx.obj["database_path"]),
            duration_limit=duration_limit,
        )
    finally:
        conn.close()

    click.echo(f"Saved recording to {result.audio_path}")
    click.echo(f"Lecture {result.lecture.id} duration: {result.duration_seconds:.1f}s")


@main.command("transcribe")
@click.argument("lecture_id", type=int)
@click.pass_context
def transcribe_command(ctx: click.Context, lecture_id: int) -> None:
    """Transcribe a recorded lecture into timestamped segments."""
    conn, _ = _connect(ctx.obj["database_path"])
    try:
        segments = transcribe_lecture(
            conn,
            lecture_id,
            recordings_dir=_recordings_dir(ctx.obj["database_path"]),
        )
    finally:
        conn.close()

    click.echo(f"Stored {len(segments)} segments for lecture {lecture_id}")


@main.command("generate")
@click.argument("lecture_id", type=int)
@click.pass_context
def generate_command(ctx: click.Context, lecture_id: int) -> None:
    """Generate flashcards from a transcribed lecture."""
    from src.card_generator import generate_cards_for_lecture

    conn, _ = _connect(ctx.obj["database_path"])
    try:
        cards = generate_cards_for_lecture(conn, lecture_id)
    finally:
        conn.close()

    click.echo(f"Generated {len(cards)} cards for lecture {lecture_id}")


@main.command("sync")
@click.argument("lecture_id", type=int)
@click.pass_context
def sync_command(ctx: click.Context, lecture_id: int) -> None:
    """Sync approved cards for a lecture to Anki."""
    from src.anki_client import sync_lecture

    conn, _ = _connect(ctx.obj["database_path"])
    try:
        result = sync_lecture(conn, lecture_id)
    finally:
        conn.close()

    click.echo(f"Synced {result.synced} cards, {result.failed} failed")
    for error in result.errors:
        click.echo(f"  Error: {error}")


@main.command("cards")
@click.argument("lecture_id", type=int)
@click.pass_context
def cards_command(ctx: click.Context, lecture_id: int) -> None:
    """Show cards for a lecture."""
    from src.db import get_cards_for_lecture

    conn, _ = _connect(ctx.obj["database_path"])
    try:
        cards = get_cards_for_lecture(conn, lecture_id)
    finally:
        conn.close()

    if not cards:
        click.echo("No cards found.")
        return

    for card in cards:
        status = f"[{card.status}]"
        if card.synced_to_anki:
            status = "[synced]"
        click.echo(f"{card.id}: {status} Q: {card.front}")
        click.echo(f"         A: {card.back}")


@main.command("approve")
@click.argument("card_ids", type=int, nargs=-1, required=True)
@click.pass_context
def approve_command(ctx: click.Context, card_ids: tuple[int, ...]) -> None:
    """Approve one or more cards by ID."""
    from src.db import approve_card, get_card_by_id

    conn, _ = _connect(ctx.obj["database_path"])
    try:
        for card_id in card_ids:
            card = get_card_by_id(conn, card_id)
            if card is None:
                click.echo(f"Card {card_id} not found, skipping.")
                continue
            approve_card(conn, card_id)
            click.echo(f"Approved card {card_id}")
    finally:
        conn.close()


@main.command("reject")
@click.argument("card_ids", type=int, nargs=-1, required=True)
@click.pass_context
def reject_command(ctx: click.Context, card_ids: tuple[int, ...]) -> None:
    """Reject (delete) one or more cards by ID."""
    from src.db import delete_card, get_card_by_id

    conn, _ = _connect(ctx.obj["database_path"])
    try:
        for card_id in card_ids:
            card = get_card_by_id(conn, card_id)
            if card is None:
                click.echo(f"Card {card_id} not found, skipping.")
                continue
            delete_card(conn, card_id)
            click.echo(f"Rejected card {card_id}")
    finally:
        conn.close()


@main.command("web")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host for the local web UI.")
@click.option("--port", default=8000, show_default=True, type=int, help="Port for the local web UI.")
@click.pass_context
def web_command(ctx: click.Context, host: str, port: int) -> None:
    """Run the local browser UI."""
    from src.web import run_web_app

    click.echo(f"Serving Lecture2Anki UI at http://{host}:{port}")
    run_web_app(host=host, port=port, database_path=ctx.obj["database_path"])


if __name__ == "__main__":
    main()
