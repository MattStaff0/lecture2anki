"""Configuration loading for Lecture2Anki."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv() -> bool:
        """Fallback when python-dotenv is not installed."""
        return False

load_dotenv()


def _get_int(key: str, default: int) -> int:
    """Read an integer setting from the environment."""
    return int(os.getenv(key, str(default)))


def _get_path(key: str, default: str) -> Path:
    """Read a filesystem path from the environment."""
    return Path(os.getenv(key, default)).expanduser()


@dataclass
class OllamaConfig:
    """Ollama LLM settings."""

    host: str = field(default_factory=lambda: os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "phi3"))
    context_size: int = field(default_factory=lambda: _get_int("OLLAMA_CONTEXT_SIZE", 2048))


@dataclass
class WhisperConfig:
    """Whisper transcription settings."""

    model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "small"))
    language: str | None = field(default_factory=lambda: os.getenv("WHISPER_LANGUAGE", "en") or None)


@dataclass
class RecordingConfig:
    """Recording settings."""

    chunk_interval_seconds: int = field(
        default_factory=lambda: _get_int("CHUNK_INTERVAL_SECONDS", 30)
    )


@dataclass
class CardGenerationConfig:
    """Card generation settings."""

    chunk_target_words: int = field(default_factory=lambda: _get_int("CHUNK_TARGET_WORDS", 800))
    chunk_max_words: int = field(default_factory=lambda: _get_int("CHUNK_MAX_WORDS", 1200))
    cards_min_per_chunk: int = field(default_factory=lambda: _get_int("CARDS_MIN_PER_CHUNK", 3))
    cards_max_per_chunk: int = field(default_factory=lambda: _get_int("CARDS_MAX_PER_CHUNK", 8))


@dataclass
class AnkiConfig:
    """Anki/AnkiConnect settings."""

    connect_url: str = field(default_factory=lambda: os.getenv("ANKI_CONNECT_URL", "http://localhost:8765"))
    root_deck: str = field(default_factory=lambda: os.getenv("ANKI_ROOT_DECK", "Lectures"))
    note_type: str = field(default_factory=lambda: os.getenv("ANKI_NOTE_TYPE", "Basic"))

    def get_deck_path(self, course_name: str, unit_name: str) -> str:
        """Build the deck path for a course and unit."""
        if self.root_deck:
            return f"{self.root_deck}::{course_name}::{unit_name}"
        return f"{course_name}::{unit_name}"


@dataclass
class StorageConfig:
    """Storage settings."""

    database_path: Path = field(
        default_factory=lambda: _get_path("DATABASE_PATH", "~/.lecture2anki/lecture2anki.db")
    )
    recordings_path: Path | None = field(default=None)

    def __post_init__(self) -> None:
        recordings = os.getenv("RECORDINGS_PATH", "")
        if recordings:
            self.recordings_path = Path(recordings).expanduser()

        self.database_path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class LoggingConfig:
    """Logging settings."""

    level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


@dataclass
class Config:
    """Application configuration container."""

    ollama: OllamaConfig
    whisper: WhisperConfig
    recording: RecordingConfig
    card_generation: CardGenerationConfig
    anki: AnkiConfig
    storage: StorageConfig
    logging: LoggingConfig

    @classmethod
    def load(cls) -> Config:
        """Load configuration from environment variables."""
        return cls(
            ollama=OllamaConfig(),
            whisper=WhisperConfig(),
            recording=RecordingConfig(),
            card_generation=CardGenerationConfig(),
            anki=AnkiConfig(),
            storage=StorageConfig(),
            logging=LoggingConfig(),
        )

_config: Config | None = None


def get_config() -> Config:
    """Return the lazily loaded application config."""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def reset_config() -> None:
    """Clear the cached config so tests can reload environment overrides."""
    global _config
    _config = None


def get_database_path() -> Path:
    """Get the configured SQLite database path."""
    return get_config().storage.database_path


def get_deck_path(course_name: str, unit_name: str) -> str:
    """Get the full deck path for a course and unit."""
    return get_config().anki.get_deck_path(course_name, unit_name)
