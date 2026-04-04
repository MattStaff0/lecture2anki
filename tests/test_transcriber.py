import sqlite3

from src.db import (
    add_segment,
    create_course,
    create_lecture,
    create_unit,
    get_segments_for_lecture,
    init_db,
)
from src.transcriber import TranscriptSegment, find_recording_for_lecture, transcribe_lecture


class TestTranscriber:
    def test_find_recording_for_lecture_returns_latest_match(self, tmp_path):
        first = tmp_path / "lecture-7-20260101-100000.wav"
        second = tmp_path / "lecture-7-20260101-110000.webm"
        first.write_bytes(b"1")
        second.write_bytes(b"2")

        result = find_recording_for_lecture(7, recordings_dir=tmp_path)

        assert result == second

    def test_transcribe_lecture_replaces_existing_segments(self, tmp_path):
        conn = sqlite3.connect(":memory:")
        init_db(conn)
        course = create_course(conn, "AI")
        unit = create_unit(conn, course.id, "Midterm 1")
        lecture = create_lecture(conn, unit.id, title="Intro to ML")
        recording = tmp_path / f"lecture-{lecture.id}-20260101-100000.wav"
        recording.write_bytes(b"audio")
        add_segment(conn, lecture.id, 0.0, 1.0, "old segment")

        def fake_transcriber(_audio_path):
            return [
                TranscriptSegment(0.0, 5.0, "First segment"),
                TranscriptSegment(5.0, 10.0, "Second segment"),
            ]

        stored_segments = transcribe_lecture(
            conn,
            lecture.id,
            transcriber=fake_transcriber,
            recordings_dir=tmp_path,
        )

        refreshed_segments = get_segments_for_lecture(conn, lecture.id)

        assert [segment.text for segment in stored_segments] == [
            "First segment",
            "Second segment",
        ]
        assert [segment.text for segment in refreshed_segments] == [
            "First segment",
            "Second segment",
        ]
