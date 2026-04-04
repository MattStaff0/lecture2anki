import sqlite3
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import src.cli as cli_module
from src.cli import main
from src.config import reset_config
from src.db import create_course, create_lecture, create_unit, init_db


@pytest.fixture(autouse=True)
def reset_cached_config():
    reset_config()
    yield
    reset_config()


@pytest.fixture
def runner():
    return CliRunner()


class TestInit:
    def test_init_creates_database(self, runner, tmp_path):
        database_path = tmp_path / "lecture2anki.db"

        result = runner.invoke(main, ["--database-path", str(database_path), "init"])

        assert result.exit_code == 0
        assert database_path.exists()
        assert "Initialized database" in result.output


class TestCourses:
    def test_courses_add_and_list(self, runner, tmp_path):
        database_path = tmp_path / "lecture2anki.db"

        add_result = runner.invoke(
            main,
            ["--database-path", str(database_path), "courses", "add", "AI"],
        )
        list_result = runner.invoke(
            main,
            ["--database-path", str(database_path), "courses", "list"],
        )

        assert add_result.exit_code == 0
        assert "Added course AI" in add_result.output
        assert list_result.exit_code == 0
        assert list_result.output.strip() == "AI"

    def test_courses_add_duplicate_fails(self, runner, tmp_path):
        database_path = tmp_path / "lecture2anki.db"
        runner.invoke(main, ["--database-path", str(database_path), "courses", "add", "AI"])

        result = runner.invoke(
            main,
            ["--database-path", str(database_path), "courses", "add", "AI"],
        )

        assert result.exit_code != 0
        assert "Course already exists" in result.output


class TestUnits:
    def test_units_add_and_list(self, runner, tmp_path):
        database_path = tmp_path / "lecture2anki.db"
        runner.invoke(main, ["--database-path", str(database_path), "courses", "add", "AI"])

        add_result = runner.invoke(
            main,
            [
                "--database-path",
                str(database_path),
                "units",
                "add",
                "AI",
                "Midterm 1",
                "--sort-order",
                "2",
            ],
        )
        list_result = runner.invoke(
            main,
            ["--database-path", str(database_path), "units", "list", "AI"],
        )

        assert add_result.exit_code == 0
        assert "Added unit Midterm 1" in add_result.output
        assert list_result.exit_code == 0
        assert list_result.output.strip() == "2: Midterm 1"

    def test_units_list_missing_course_fails(self, runner, tmp_path):
        database_path = tmp_path / "lecture2anki.db"

        result = runner.invoke(
            main,
            ["--database-path", str(database_path), "units", "list", "Unknown"],
        )

        assert result.exit_code != 0
        assert "Course not found" in result.output


class TestLectures:
    def test_lectures_lists_saved_lectures(self, runner, tmp_path):
        database_path = tmp_path / "lecture2anki.db"
        conn = sqlite3.connect(database_path)
        init_db(conn)
        course = create_course(conn, "AI")
        unit = create_unit(conn, course.id, "Midterm 1")
        create_lecture(conn, unit.id, title="Intro to ML")
        conn.close()

        result = runner.invoke(main, ["--database-path", str(database_path), "lectures"])

        assert result.exit_code == 0
        assert "AI / Midterm 1 / Intro to ML" in result.output

    def test_lectures_support_course_filter(self, runner, tmp_path):
        database_path = tmp_path / "lecture2anki.db"
        conn = sqlite3.connect(database_path)
        init_db(conn)
        ai = create_course(conn, "AI")
        os_course = create_course(conn, "OS")
        ai_unit = create_unit(conn, ai.id, "Midterm 1")
        os_unit = create_unit(conn, os_course.id, "Final")
        create_lecture(conn, ai_unit.id, title="Intro to ML")
        create_lecture(conn, os_unit.id, title="Scheduling")
        conn.close()

        result = runner.invoke(
            main,
            ["--database-path", str(database_path), "lectures", "--course", "AI"],
        )

        assert result.exit_code == 0
        assert "Intro to ML" in result.output
        assert "Scheduling" not in result.output


class TestRecord:
    def test_record_command_resolves_course_and_unit(self, runner, tmp_path, monkeypatch):
        database_path = tmp_path / "lecture2anki.db"
        conn = sqlite3.connect(database_path)
        init_db(conn)
        course = create_course(conn, "AI")
        unit = create_unit(conn, course.id, "Midterm 1")
        conn.close()

        def fake_record_lecture(conn, unit_id, title=None, duration_limit=None):
            assert unit_id == unit.id
            assert title == "Intro to ML"
            assert duration_limit == 30.0
            return SimpleNamespace(
                audio_path=tmp_path / "recordings" / "lecture-1.wav",
                lecture=SimpleNamespace(id=1),
                duration_seconds=12.5,
            )

        monkeypatch.setattr(cli_module, "record_lecture", fake_record_lecture)

        result = runner.invoke(
            main,
            [
                "--database-path",
                str(database_path),
                "record",
                "--course",
                "AI",
                "--unit",
                "Midterm 1",
                "--title",
                "Intro to ML",
                "--duration-limit",
                "30",
            ],
        )

        assert result.exit_code == 0
        assert "Recording lecture for AI / Midterm 1" in result.output
        assert "Saved recording to" in result.output


class TestTranscribe:
    def test_transcribe_command_stores_segments(self, runner, tmp_path, monkeypatch):
        database_path = tmp_path / "lecture2anki.db"
        conn = sqlite3.connect(database_path)
        init_db(conn)
        course = create_course(conn, "AI")
        unit = create_unit(conn, course.id, "Midterm 1")
        lecture = create_lecture(conn, unit.id, title="Intro to ML")
        conn.close()

        def fake_transcribe_lecture(conn, lecture_id):
            assert lecture_id == lecture.id
            return [SimpleNamespace(id=1), SimpleNamespace(id=2)]

        monkeypatch.setattr(cli_module, "transcribe_lecture", fake_transcribe_lecture)

        result = runner.invoke(
            main,
            ["--database-path", str(database_path), "transcribe", str(lecture.id)],
        )

        assert result.exit_code == 0
        assert "Stored 2 segments" in result.output


class TestWeb:
    def test_web_command_starts_local_ui(self, runner, tmp_path, monkeypatch):
        database_path = tmp_path / "lecture2anki.db"
        started = {}

        def fake_run_web_app(host, port, database_path=None):
            started["host"] = host
            started["port"] = port
            started["database_path"] = database_path

        import src.web as web_module

        monkeypatch.setattr(web_module, "run_web_app", fake_run_web_app)

        result = runner.invoke(
            main,
            [
                "--database-path",
                str(database_path),
                "web",
                "--host",
                "127.0.0.1",
                "--port",
                "8123",
            ],
        )

        assert result.exit_code == 0
        assert "Serving Lecture2Anki UI" in result.output
        assert started == {
            "host": "127.0.0.1",
            "port": 8123,
            "database_path": database_path,
        }
