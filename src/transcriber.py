"""Whisper-backed transcription helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.config import get_config, get_recordings_path
from src.db import add_segment, delete_segments_for_lecture, get_lecture_by_id
from src.models import Segment

try:
    from faster_whisper import WhisperModel
except ModuleNotFoundError:
    WhisperModel = None


@dataclass
class TranscriptSegment:
    """A raw transcript segment returned by the transcriber."""

    start_time: float
    end_time: float
    text: str


TranscriberBackend = Callable[[Path], list[TranscriptSegment]]


def find_recording_for_lecture(lecture_id: int, recordings_dir: Path | None = None) -> Path:
    """Locate the most recent saved recording for a lecture."""
    directory = recordings_dir or get_recordings_path()
    candidates = sorted(
        path
        for path in directory.glob(f"lecture-{lecture_id}-*")
        if path.is_file()
    )
    if not candidates:
        raise FileNotFoundError(f"No recording found for lecture {lecture_id}")
    return candidates[-1]


def transcribe_audio_file(audio_path: Path) -> list[TranscriptSegment]:
    """Transcribe an audio file with faster-whisper."""
    if WhisperModel is None:
        raise RuntimeError(
            "Transcription requires faster-whisper. "
            "Run `./venv/bin/pip install -e '.[dev]'` to install dependencies."
        )

    config = get_config()
    model = WhisperModel(config.whisper.model)
    segments, _info = model.transcribe(
        str(audio_path),
        language=config.whisper.language,
    )
    return [
        TranscriptSegment(
            start_time=segment.start,
            end_time=segment.end,
            text=segment.text.strip(),
        )
        for segment in segments
        if segment.text.strip()
    ]


def transcribe_lecture(
    conn,
    lecture_id: int,
    transcriber: TranscriberBackend | None = None,
    recordings_dir: Path | None = None,
) -> list[Segment]:
    """Transcribe a lecture recording and store the resulting segments."""
    lecture = get_lecture_by_id(conn, lecture_id)
    if lecture is None:
        raise ValueError(f"Lecture {lecture_id} not found")

    audio_path = find_recording_for_lecture(lecture_id, recordings_dir=recordings_dir)
    backend = transcriber or transcribe_audio_file
    raw_segments = backend(audio_path)

    delete_segments_for_lecture(conn, lecture_id)
    stored_segments: list[Segment] = []
    for segment in raw_segments:
        stored_segments.append(
            add_segment(
                conn,
                lecture_id,
                segment.start_time,
                segment.end_time,
                segment.text,
            )
        )

    return stored_segments
