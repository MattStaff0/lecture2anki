"""Whisper-backed transcription helpers."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegment:
    """A raw transcript segment returned by the transcriber."""

    start_time: float
    end_time: float
    text: str


TranscriberBackend = Callable[[Path], list[TranscriptSegment]]
ProgressCallback = Callable[[str, str, str], None]


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


def delete_recordings_for_lecture(
    lecture_id: int,
    recordings_dir: Path | None = None,
) -> int:
    """Delete any saved recording files for a lecture and return the count removed."""
    directory = recordings_dir or get_recordings_path()
    deleted = 0
    for path in directory.glob(f"lecture-{lecture_id}-*"):
        if path.is_file():
            path.unlink()
            deleted += 1
    return deleted


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
    on_progress: ProgressCallback | None = None,
) -> list[Segment]:
    """Transcribe a lecture recording and store the resulting segments."""

    def _emit(stage: str, message: str, level: str = "info") -> None:
        logger.log(
            getattr(logging, level.upper(), logging.INFO),
            "lecture=%d stage=%s %s", lecture_id, stage, message,
        )
        if on_progress:
            on_progress(stage, message, level)

    lecture = get_lecture_by_id(conn, lecture_id)
    if lecture is None:
        raise ValueError(f"Lecture {lecture_id} not found")

    _emit("locate_recording", "Locating audio recording...")
    audio_path = find_recording_for_lecture(lecture_id, recordings_dir=recordings_dir)
    file_size_mb = audio_path.stat().st_size / (1024 * 1024)
    _emit(
        "locate_recording",
        f"Found recording: {audio_path.name} ({file_size_mb:.1f} MB, suffix={audio_path.suffix})",
    )

    config = get_config()
    _emit("load_model", f"Loading Whisper model '{config.whisper.model}' (language={config.whisper.language})...")

    backend = transcriber or transcribe_audio_file
    _emit("transcribing", "Transcription started...")
    raw_segments = backend(audio_path)
    _emit("transcribing", f"Transcription finished — {len(raw_segments)} raw segments")

    _emit("saving_segments", "Saving segments to database...")
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
    _emit("saving_segments", f"Saved {len(stored_segments)} segments")

    _emit("cleanup", "Cleaning up raw recording files...")
    deleted_count = delete_recordings_for_lecture(lecture_id, recordings_dir=recordings_dir)
    _emit("cleanup", f"Removed {deleted_count} recording file(s)")

    _emit("done", f"Transcription complete — {len(stored_segments)} segments stored")
    return stored_segments
