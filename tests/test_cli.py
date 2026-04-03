import sqlite3

import pytest
from click.testing import CliRunner

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
