# CLAUDE.md

## Project: Lecture2Anki

Local-first pipeline that transcribes lectures in near-real-time and generates Anki flashcards using a local LLM. Optimized for M1 MacBook with 8GB unified memory.

## Architecture

```
Mic input
  → rolling audio chunks (15-30s)
  → faster-whisper transcription
  → transcript store (SQLite)

transcript store
  → chunker (500-1200 words or 60-120s)
  → Ollama prompt per chunk
  → JSON cards
  → deduplicator
  → AnkiConnect
```

## Tech Stack

- **Python 3.12+**
- **faster-whisper** — transcription (use `small` or `base` model for 8GB RAM)
- **Ollama** — local LLM inference (use small models: phi3, qwen2:1.5b, gemma:2b)
- **SQLite** — transcript and card storage
- **AnkiConnect** — Anki integration via localhost HTTP
- **pytest** — testing framework

## Project Structure

```
lecture2anki/
├── src/
│   ├── __init__.py
│   ├── transcriber.py      # faster-whisper integration
│   ├── chunker.py          # transcript segmentation
│   ├── card_generator.py   # Ollama prompting
│   ├── deduplicator.py     # card deduplication
│   ├── anki_client.py      # AnkiConnect integration
│   ├── db.py               # SQLite operations
│   └── cli.py              # command-line interface
├── tests/
│   ├── __init__.py
│   ├── test_transcriber.py
│   ├── test_chunker.py
│   ├── test_card_generator.py
│   ├── test_deduplicator.py
│   ├── test_anki_client.py
│   └── fixtures/           # test audio files, sample transcripts
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .gitignore
└── .env.example
```

## Development Practices

### TDD Workflow

1. Write a failing test first
2. Implement minimum code to pass
3. Refactor
4. Commit with descriptive message

### Git Workflow

- **main** — stable, working code only
- **feature/\*** — new features (e.g., `feature/chunker`)
- **fix/\*** — bug fixes
- **test/\*** — test additions

### Commit Messages

```
type(scope): short description

- type: feat, fix, test, refactor, docs, chore
- scope: transcriber, chunker, cards, anki, db, cli
```

Examples:

- `feat(transcriber): add VAD-based silence detection`
- `test(chunker): add tests for edge cases`
- `fix(anki): handle connection timeout`

### Pull Requests

- One feature per PR
- All tests must pass
- Include test coverage for new code
- Update README if adding user-facing features

### Issues

- Use labels: `bug`, `feature`, `enhancement`, `documentation`
- Reference issues in commits: `fix(anki): handle timeout (#12)`

## Coding Conventions

### Python Style

- Follow PEP 8
- Use type hints for all function signatures
- Docstrings for public functions (Google style)
- Max line length: 100 chars

### Example Function

```python
def chunk_transcript(
    segments: list[TranscriptSegment],
    max_words: int = 1000,
    max_duration_seconds: float = 120.0
) -> list[Chunk]:
    """
    Split transcript segments into chunks suitable for LLM processing.

    Args:
        segments: List of transcribed segments with timestamps.
        max_words: Maximum words per chunk.
        max_duration_seconds: Maximum duration per chunk.

    Returns:
        List of chunks ready for card generation.
    """
    ...
```

### Error Handling

- Use custom exceptions in `src/exceptions.py`
- Never silently catch exceptions
- Log errors with context

### Configuration

- Use environment variables for paths and API settings
- Default to sensible values for M1/8GB
- Store in `.env`, load with `python-dotenv`

## Memory Constraints

This runs on 8GB unified memory. Always:

- Use Whisper `small` or `base` model, not `medium` or `large`
- Use Ollama models ≤3B parameters
- Process audio in chunks, never load full lecture into memory
- Keep Ollama context size modest (2048-4096 tokens)
- Don't run transcription and LLM inference simultaneously

## Testing

### Run Tests

```bash
pytest                      # all tests
pytest tests/test_chunker.py  # specific file
pytest -v                   # verbose
pytest --cov=src            # with coverage
```

### Test Fixtures

- Store sample audio in `tests/fixtures/audio/`
- Store sample transcripts in `tests/fixtures/transcripts/`
- Keep fixtures small (<1MB)

### Mocking

- Mock Ollama calls in card generator tests
- Mock AnkiConnect in anki client tests
- Use real faster-whisper for transcriber tests (with tiny audio samples)

## Key Commands

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Transcribe a file (after implementation)
python -m lecture2anki transcribe lecture.mp3

# Generate cards from transcript
python -m lecture2anki generate --input transcript.db

# Full pipeline
python -m lecture2anki process lecture.mp3 --output cards.json
```

## AnkiConnect Setup

1. Install Anki
2. Install AnkiConnect add-on (code: 2055492159)
3. Restart Anki
4. AnkiConnect runs on http://localhost:8765

Test connection:

```bash
curl http://localhost:8765 -X POST -d '{"action": "version", "version": 6}'
```

## Ollama Setup

```bash
# Install
brew install ollama

# Start server
ollama serve

# Pull a small model
ollama pull phi3          # or qwen2:1.5b, gemma:2b

# Test
ollama run phi3 "Say hello"
```

## Definition of Done

A feature is done when:

- [ ] Tests written and passing
- [ ] Code reviewed (self-review for solo)
- [ ] No linting errors
- [ ] Works on 8GB M1 Mac without memory pressure
- [ ] README updated if user-facing
- [ ] Committed to feature branch
- [ ] PR merged to main
