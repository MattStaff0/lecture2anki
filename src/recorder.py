"""Lecture recording helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from src.config import get_recordings_path
from src.db import create_lecture, get_lecture_by_id, update_lecture_duration
from src.models import Lecture

try:
    import sounddevice as sd
    import soundfile as sf
except ModuleNotFoundError:
    sd = None
    sf = None


RecorderBackend = Callable[[Path, int, int, float | None], float]


@dataclass
class RecordingResult:
    """Result metadata for a finished recording."""

    lecture: Lecture
    audio_path: Path
    duration_seconds: float | None


def build_recording_path(
    lecture_id: int,
    recordings_dir: Path | None = None,
    suffix: str = ".wav",
) -> Path:
    """Build a deterministic path for a lecture recording."""
    directory = recordings_dir or get_recordings_path()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return directory / f"lecture-{lecture_id}-{timestamp}{normalized_suffix}"


def record_microphone_to_wav(
    output_path: Path,
    sample_rate: int = 16_000,
    channels: int = 1,
    duration_limit: float | None = None,
) -> float:
    """Record microphone audio to a WAV file and return the duration in seconds."""
    if sd is None or sf is None:
        raise RuntimeError(
            "Microphone recording requires sounddevice and soundfile. "
            "Run `./venv/bin/pip install -e '.[dev]'` after adding those dependencies."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if duration_limit is not None:
        frames = sd.rec(
            int(duration_limit * sample_rate),
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
        )
        sd.wait()
        sf.write(output_path, frames, sample_rate)
        return duration_limit

    captured_frames: list[np.ndarray] = []

    def callback(indata, _frames, _time, status) -> None:
        if status:
            return
        captured_frames.append(indata.copy())

    started_at = time.monotonic()
    try:
        with sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            callback=callback,
        ):
            while True:
                sd.sleep(250)
    except KeyboardInterrupt:
        pass

    duration = time.monotonic() - started_at
    if not captured_frames:
        raise RuntimeError("Recording stopped before any audio was captured.")

    audio = np.concatenate(captured_frames, axis=0)
    sf.write(output_path, audio, sample_rate)
    return duration


def record_lecture(
    conn,
    unit_id: int,
    title: str | None = None,
    recorder: RecorderBackend | None = None,
    recordings_dir: Path | None = None,
    duration_limit: float | None = None,
) -> RecordingResult:
    """Create a lecture, record audio, and persist the lecture duration."""
    lecture = create_lecture(conn, unit_id, title=title)
    audio_path = build_recording_path(lecture.id, recordings_dir=recordings_dir)
    audio_path.parent.mkdir(parents=True, exist_ok=True)

    backend = recorder or record_microphone_to_wav
    duration_seconds = backend(audio_path, 16_000, 1, duration_limit)
    update_lecture_duration(conn, lecture.id, duration_seconds)

    updated_lecture = get_lecture_by_id(conn, lecture.id)
    if updated_lecture is None:
        raise RuntimeError(f"Lecture {lecture.id} disappeared after recording.")

    return RecordingResult(
        lecture=updated_lecture,
        audio_path=audio_path,
        duration_seconds=duration_seconds,
    )


def save_uploaded_audio(
    conn,
    unit_id: int,
    audio_bytes: bytes,
    suffix: str,
    title: str | None = None,
    recordings_dir: Path | None = None,
    duration_seconds: float | None = None,
) -> RecordingResult:
    """Persist uploaded audio for a lecture and optionally store its duration."""
    lecture = create_lecture(conn, unit_id, title=title)
    audio_path = build_recording_path(lecture.id, recordings_dir=recordings_dir, suffix=suffix)
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(audio_bytes)

    if duration_seconds is not None:
        update_lecture_duration(conn, lecture.id, duration_seconds)

    updated_lecture = get_lecture_by_id(conn, lecture.id)
    if updated_lecture is None:
        raise RuntimeError(f"Lecture {lecture.id} disappeared after saving audio.")

    return RecordingResult(
        lecture=updated_lecture,
        audio_path=audio_path,
        duration_seconds=updated_lecture.duration_seconds,
    )
