from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Course:
    id: int
    name: str
    created_at: datetime


@dataclass
class Unit:
    id: int
    course_id: int
    name: str
    sort_order: int
    created_at: datetime

    def deck_path(self, course_name: str) -> str:
        """Get the Anki deck path for this unit."""
        return f"{course_name}::{self.name}"


@dataclass
class Lecture:
    id: int
    unit_id: int
    title: str | None
    recorded_at: datetime
    duration_seconds: float | None


@dataclass
class Segment:
    id: int
    lecture_id: int
    start_time: float
    end_time: float
    text: str


@dataclass
class Card:
    id: int
    lecture_id: int
    front: str
    back: str
    tags: list[str]
    status: str  # "pending", "approved", "rejected"
    synced_to_anki: bool
    anki_note_id: int | None
    created_at: datetime


@dataclass
class JobRun:
    """A durable record of a background job."""

    id: int
    job_type: str  # "transcription", "generation", "sync"
    lecture_id: int
    status: str  # "queued", "running", "succeeded", "failed", "cancelled"
    current_stage: str
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    details_json: dict | None
    created_at: datetime


@dataclass
class JobEvent:
    """A milestone or heartbeat event within a job."""

    id: int
    job_id: int
    stage: str
    level: str  # "info", "warning", "error"
    message: str
    created_at: datetime
