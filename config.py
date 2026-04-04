"""
Configuration management for Lecture2Anki.

Loads settings from environment variables with sensible defaults.
Users configure via .env file (copy from .env.example).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()


def _get_bool(key: str, default: bool = False) -> bool:
    """Get boolean from environment variable."""
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def _get_int(key: str, default: int) -> int:
    """Get integer from environment variable."""
    return int(os.getenv(key, str(default)))


def _get_path(key: str, default: str) -> Path:
    """Get path from environment variable, expanding ~."""
    return Path(os.getenv(key, default)).expanduser()


@dataclass
class OllamaConfig:
    """Ollama LLM settings."""
    host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model: str = os.getenv("OLLAMA_MODEL", "phi3")
    context_size: int = _get_int("OLLAMA_CONTEXT_SIZE", 2048)


@dataclass
class WhisperConfig:
    """Whisper transcription settings."""
    model: str = os.getenv("WHISPER_MODEL", "small")
    language: str | None = os.getenv("WHISPER_LANGUAGE", "en") or None


@dataclass
class RecordingConfig:
    """Recording settings."""
    chunk_interval_seconds: int = _get_int("CHUNK_INTERVAL_SECONDS", 30)


@dataclass
class CardGenerationConfig:
    """Card generation settings."""
    chunk_target_words: int = _get_int("CHUNK_TARGET_WORDS", 800)
    chunk_max_words: int = _get_int("CHUNK_MAX_WORDS", 1200)
    cards_min_per_chunk: int = _get_int("CARDS_MIN_PER_CHUNK", 3)
    cards_max_per_chunk: int = _get_int("CARDS_MAX_PER_CHUNK", 8)


@dataclass
class AnkiConfig:
    """Anki/AnkiConnect settings."""
    connect_url: str = os.getenv("ANKI_CONNECT_URL", "http://localhost:8765")
    root_deck: str = os.getenv("ANKI_ROOT_DECK", "Lectures")
    note_type: str = os.getenv("ANKI_NOTE_TYPE", "Basic")

    def get_deck_path(self, course_name: str, unit_name: str) -> str:
        """
        Build full Anki deck path.
        
        Examples:
            - With root: "Lectures::AI::Midterm 1"
            - Without root: "AI::Midterm 1"
        """
        if self.root_deck:
            return f"{self.root_deck}::{course_name}::{unit_name}"
        return f"{course_name}::{unit_name}"


@dataclass
class StorageConfig:
    """Storage settings."""
    database_path: Path = _get_path("DATABASE_PATH", "~/.lecture2anki/lecture2anki.db")
    recordings_path: Path | None = None

    def __post_init__(self):
        recordings = os.getenv("RECORDINGS_PATH", "")
        if recordings:
            self.recordings_path = Path(recordings).expanduser()
        
        # Ensure database directory exists
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class LoggingConfig:
    """Logging settings."""
    level: str = os.getenv("LOG_LEVEL", "INFO")


@dataclass
class Config:
    """Main configuration container."""
    ollama: OllamaConfig
    whisper: WhisperConfig
    recording: RecordingConfig
    card_generation: CardGenerationConfig
    anki: AnkiConfig
    storage: StorageConfig
    logging: LoggingConfig

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from environment."""
        return cls(
            ollama=OllamaConfig(),
            whisper=WhisperConfig(),
            recording=RecordingConfig(),
            card_generation=CardGenerationConfig(),
            anki=AnkiConfig(),
            storage=StorageConfig(),
            logging=LoggingConfig(),
        )


# Global config instance — import this
config = Config.load()


# Convenience exports
def get_database_path() -> Path:
    """Get the database file path."""
    return config.storage.database_path


def get_deck_path(course_name: str, unit_name: str) -> str:
    """Get full Anki deck path for a course/unit."""
    return config.anki.get_deck_path(course_name, unit_name)