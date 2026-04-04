# CLAUDE.md

## Project: Lecture2Anki

Local-first pipeline that transcribes lectures in near-real-time and generates Anki flashcards using a local LLM. Optimized for M1 MacBook with 8GB unified memory.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLI Interface                            │
│  Select Course → Select Unit → Record → Generate → Sync to Anki │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        SQLite Database                           │
│  courses → units → lectures → segments → cards                   │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Anki Decks                               │
│  AI::Midterm 1, AI::Midterm 2, OS::Final, Nutrition::Exam 1     │
└─────────────────────────────────────────────────────────────────┘
```

## Database Schema

```sql
-- Courses: AI, OS, Nutrition, etc.
CREATE TABLE courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Units: Midterm 1, Midterm 2, Final, etc. (per course)
CREATE TABLE units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id),
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(course_id, name)
);

-- Lectures: individual recordings within a unit
CREATE TABLE lectures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id INTEGER NOT NULL REFERENCES units(id),
    title TEXT,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_seconds REAL
);

-- Segments: timestamped transcript chunks
CREATE TABLE segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lecture_id INTEGER NOT NULL REFERENCES lectures(id),
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    text TEXT NOT NULL
);

-- Cards: generated flashcards
CREATE TABLE cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lecture_id INTEGER NOT NULL REFERENCES lectures(id),
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    tags TEXT,  -- JSON array
    synced_to_anki BOOLEAN DEFAULT FALSE,
    anki_note_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Anki Deck Structure

Cards sync to nested decks based on course and unit:

```
Lectures
├── AI
│   ├── Midterm 1
│   ├── Midterm 2
│   └── Final
├── OS
│   ├── Midterm 1
│   └── Final
└── Nutrition
    ├── Exam 1
    └── Exam 2
```

Deck path format: `{course_name}::{unit_name}`

Example: A card from AI class, Midterm 2 material → deck `AI::Midterm 2`

## Data Flow

### Recording a Lecture

```
1. CLI: Select course (or create new)
2. CLI: Select unit (or create new)
3. System: Create lecture row linked to unit
4. Audio: Mic input → rolling 15-30s chunks
5. Transcription: faster-whisper → segments table
6. Storage: Each segment saved with lecture_id, timestamps, text
```

### Generating Cards

```
1. Chunker: Group segments into 500-1200 word chunks
2. LLM: Send each chunk to Ollama with prompt
3. Parser: Extract JSON cards from response
4. Deduper: Remove similar/duplicate cards
5. Storage: Save cards with lecture_id
```

### Syncing to Anki

```
1. Query: Get unsynced cards with course/unit info
2. Deck: Ensure deck exists (create if needed)
3. Sync: POST each card to AnkiConnect
4. Update: Mark cards as synced, store anki_note_id
```

## CLI Commands

```bash
# Setup
lecture2anki init                    # Create database, default courses

# Course/Unit Management
lecture2anki courses list            # Show all courses
lecture2anki courses add "AI"        # Add new course
lecture2anki units list "AI"         # Show units for AI course
lecture2anki units add "AI" "Final"  # Add Final unit to AI

# Recording
lecture2anki record                  # Interactive: select course → unit → record
lecture2anki record --course AI --unit "Midterm 2"  # Direct
lecture2anki web                     # Local browser UI for capture and transcription

# Processing
lecture2anki generate <lecture_id>   # Generate cards for a lecture
lecture2anki generate --last         # Generate for most recent lecture

# Anki Sync
lecture2anki sync                    # Sync all unsynced cards
lecture2anki sync --lecture <id>     # Sync specific lecture's cards

# Review
lecture2anki cards <lecture_id>      # Show cards for a lecture
lecture2anki lectures                # List recent lectures
```

## Tech Stack

- **Python 3.12+**
- **faster-whisper** — transcription (use `small` or `base` model for 8GB RAM)
- **Ollama** — local LLM inference (use small models: phi3, qwen2:1.5b, gemma:2b)
- **SQLite** — all data storage
- **AnkiConnect** — Anki integration via localhost HTTP
- **Click** — CLI framework
- **Rich** — pretty terminal output
- **pytest** — testing

## Project Structure

```
lecture2anki/
├── src/
│   ├── __init__.py
│   ├── config.py           # Environment-backed settings
│   ├── recorder.py         # Microphone recording workflow
│   ├── db.py               # SQLite operations (courses, units, lectures, segments, cards)
│   ├── models.py           # Dataclasses for Course, Unit, Lecture, Segment, Card
│   ├── transcriber.py      # faster-whisper integration
│   ├── chunker.py          # Transcript segmentation for LLM
│   ├── card_generator.py   # Ollama prompting and response parsing
│   ├── deduplicator.py     # Card deduplication
│   ├── anki_client.py      # AnkiConnect integration
│   └── cli.py              # Click CLI commands
├── tests/
│   ├── __init__.py
│   ├── test_db.py
│   ├── test_models.py
│   ├── test_chunker.py
│   ├── test_card_generator.py
│   ├── test_deduplicator.py
│   ├── test_anki_client.py
│   └── fixtures/
│       ├── sample_transcript.json
│       └── sample_audio.wav
├── claude.md
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
- **feature/\*** — new features (e.g., `feature/db-module`)
- **fix/\*** — bug fixes
- **test/\*** — test additions

### Commit Messages

```
type(scope): short description

Types: feat, fix, test, refactor, docs, chore
Scopes: db, models, transcriber, chunker, cards, anki, cli
```

Examples:

- `feat(db): add courses and units tables`
- `test(chunker): add tests for word-based splitting`
- `fix(anki): handle missing deck gracefully`

### Pull Requests

- One feature per PR
- All tests must pass
- Include test coverage for new code
- Update README if adding user-facing features

## Coding Conventions

### Python Style

- Follow PEP 8
- Use type hints for all function signatures
- Docstrings for public functions (Google style)
- Max line length: 100 chars

### Data Classes

```python
from dataclasses import dataclass
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

    # Computed property for Anki deck path
    def deck_path(self, course_name: str) -> str:
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
    synced_to_anki: bool
    anki_note_id: int | None
    created_at: datetime
```

### Database Functions Pattern

```python
def create_course(db: sqlite3.Connection, name: str) -> Course:
    """Create a new course."""
    ...

def get_courses(db: sqlite3.Connection) -> list[Course]:
    """Get all courses."""
    ...

def get_units_for_course(db: sqlite3.Connection, course_id: int) -> list[Unit]:
    """Get all units for a course, ordered by sort_order."""
    ...

def create_lecture(db: sqlite3.Connection, unit_id: int, title: str | None = None) -> Lecture:
    """Create a new lecture in a unit."""
    ...

def get_deck_path_for_lecture(db: sqlite3.Connection, lecture_id: int) -> str:
    """Get the Anki deck path (e.g., 'AI::Midterm 2') for a lecture."""
    ...
```

### Error Handling

- Use custom exceptions in `src/exceptions.py`
- Never silently catch exceptions
- Log errors with context

## Memory Constraints

This runs on 8GB unified memory. Always:

- Use Whisper `small` or `base` model, not `medium` or `large`
- Use Ollama models ≤3B parameters
- Process audio in chunks, never load full lecture into memory
- Keep Ollama context size modest (2048-4096 tokens)
- Don't run transcription and LLM inference simultaneously

## LLM Prompt for Card Generation

```
You are generating Anki flashcards from lecture notes.

Rules:
- Create only cards for facts that are clearly testable
- Prefer definitions, mechanisms, comparisons, formulas, cause/effect
- Avoid vague or redundant cards
- Keep answers concise (1-3 sentences max)
- Output valid JSON only, no markdown

Transcript chunk:
{chunk_text}

Return JSON array:
[
  {
    "front": "What is...?",
    "back": "...",
    "tags": ["topic1", "topic2"]
  }
]
```

## Testing

### Run Tests

```bash
pytest                          # all tests
pytest tests/test_db.py         # specific file
pytest -v                       # verbose
pytest --cov=src                # with coverage
```

### Test Database

Tests use an in-memory SQLite database:

```python
@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()
```

## Key Commands

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Development
pytest                          # run tests
ruff check .                    # lint
ruff format .                   # format
mypy src                        # type check

# First run
cp .env.example .env
lecture2anki init
```

## AnkiConnect Reference

Base URL: `http://localhost:8765`

```python
# Create deck
{"action": "createDeck", "version": 6, "params": {"deck": "AI::Midterm 1"}}

# Add note
{
    "action": "addNote",
    "version": 6,
    "params": {
        "note": {
            "deckName": "AI::Midterm 1",
            "modelName": "Basic",
            "fields": {"Front": "...", "Back": "..."},
            "tags": ["lecture", "ai"]
        }
    }
}

# Check connection
{"action": "version", "version": 6}
```

## Build Order (Recommended)

1. **PR #1: Database foundation**
   - `src/db.py` — all table creation and CRUD operations
   - `src/models.py` — dataclasses
   - `tests/test_db.py`

2. **PR #2: CLI setup**
   - `src/cli.py` — course/unit management commands
   - Basic `init`, `courses`, `units` commands

3. **PR #3: Transcription**
   - `src/transcriber.py`
   - Integration with faster-whisper
   - `record` command

4. **PR #4: Card generation**
   - `src/chunker.py`
   - `src/card_generator.py`
   - `src/deduplicator.py`
   - `generate` command

5. **PR #5: Anki sync**
   - `src/anki_client.py`
   - `sync` command

## Definition of Done

A feature is done when:

- [ ] Tests written and passing
- [ ] Code reviewed (self-review for solo)
- [ ] No linting errors
- [ ] Works on 8GB M1 Mac without memory pressure
- [ ] README updated if user-facing
- [ ] Committed to feature branch
- [ ] PR merged to main
