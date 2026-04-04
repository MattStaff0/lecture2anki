import sqlite3
from pathlib import Path

from src.db import create_course, create_unit, init_db
from src.recorder import build_recording_path, record_lecture, save_uploaded_audio


class TestRecorder:
    def test_build_recording_path_uses_wav_suffix(self, tmp_path):
        path = build_recording_path(42, recordings_dir=tmp_path)

        assert path.parent == tmp_path
        assert path.name.startswith("lecture-42-")
        assert path.suffix == ".wav"

    def test_build_recording_path_supports_custom_suffix(self, tmp_path):
        path = build_recording_path(42, recordings_dir=tmp_path, suffix=".webm")

        assert path.parent == tmp_path
        assert path.name.startswith("lecture-42-")
        assert path.suffix == ".webm"

    def test_record_lecture_creates_file_and_updates_duration(self, tmp_path):
        conn = sqlite3.connect(":memory:")
        init_db(conn)
        course = create_course(conn, "AI")
        unit = create_unit(conn, course.id, "Midterm 1")

        def fake_recorder(
            output_path: Path,
            sample_rate: int,
            channels: int,
            duration_limit: float | None,
        ) -> float:
            output_path.write_bytes(b"fake wav bytes")
            assert sample_rate == 16_000
            assert channels == 1
            assert duration_limit == 30.0
            return 12.5

        result = record_lecture(
            conn,
            unit.id,
            title="Intro to ML",
            recorder=fake_recorder,
            recordings_dir=tmp_path / "recordings",
            duration_limit=30.0,
        )

        assert result.audio_path.exists()
        assert result.audio_path.read_bytes() == b"fake wav bytes"
        assert result.lecture.title == "Intro to ML"
        assert result.lecture.duration_seconds == 12.5

    def test_save_uploaded_audio_persists_browser_recording(self, tmp_path):
        conn = sqlite3.connect(":memory:")
        init_db(conn)
        course = create_course(conn, "AI")
        unit = create_unit(conn, course.id, "Midterm 1")

        result = save_uploaded_audio(
            conn,
            unit.id,
            b"webm bytes",
            ".webm",
            title="Browser capture",
            recordings_dir=tmp_path / "recordings",
            duration_seconds=9.25,
        )

        assert result.audio_path.exists()
        assert result.audio_path.read_bytes() == b"webm bytes"
        assert result.audio_path.suffix == ".webm"
        assert result.lecture.title == "Browser capture"
        assert result.lecture.duration_seconds == 9.25
