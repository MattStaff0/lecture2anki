from pathlib import Path

from src.config import Config


class TestConfig:
    def test_load_defaults(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "lecture2anki.db"))
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        monkeypatch.delenv("OLLAMA_CONTEXT_SIZE", raising=False)
        monkeypatch.delenv("WHISPER_MODEL", raising=False)
        monkeypatch.delenv("ANKI_ROOT_DECK", raising=False)
        monkeypatch.delenv("WHISPER_LANGUAGE", raising=False)
        monkeypatch.delenv("CHUNK_TARGET_WORDS", raising=False)
        monkeypatch.delenv("CHUNK_MAX_WORDS", raising=False)
        monkeypatch.delenv("CARDS_MIN_PER_CHUNK", raising=False)
        monkeypatch.delenv("CARDS_MAX_PER_CHUNK", raising=False)

        config = Config.load()

        assert config.ollama.model == "qwen3.5:4b"
        assert config.ollama.context_size == 4096
        assert config.card_generation.chunk_target_words == 700
        assert config.card_generation.chunk_max_words == 900
        assert config.card_generation.cards_min_per_chunk == 5
        assert config.card_generation.cards_max_per_chunk == 10
        assert config.anki.root_deck == "Lectures"
        assert config.whisper.language == "en"
        assert config.storage.database_path == tmp_path / "lecture2anki.db"

    def test_load_environment_overrides(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OLLAMA_MODEL", "llama3")
        monkeypatch.setenv("WHISPER_LANGUAGE", "")
        monkeypatch.setenv("ANKI_ROOT_DECK", "")
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "data" / "app.db"))
        monkeypatch.setenv("RECORDINGS_PATH", str(tmp_path / "recordings"))

        config = Config.load()

        assert config.ollama.model == "llama3"
        assert config.whisper.language is None
        assert config.anki.get_deck_path("AI", "Midterm 1") == "AI::Midterm 1"
        assert config.storage.recordings_path == Path(tmp_path / "recordings")
        assert config.storage.database_path.parent.exists()
