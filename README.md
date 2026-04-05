# Lecture2Anki

> Turn your lectures into Anki flashcards automatically — 100% local, no cloud APIs.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

Record your lectures, get AI-generated flashcards organized by course and exam. Everything runs locally on your machine — your data never leaves your laptop.

## Features

- **Live transcription** — Records and transcribes lectures using Whisper
- **AI-powered cards** — Generates high-quality flashcards using local LLMs via Ollama
- **Smart organization** — Cards automatically sorted by Course > Unit (Midterm 1, Final, etc.)
- **Anki integration** — Syncs directly to Anki via AnkiConnect
- **Browser UI** — Record, transcribe, generate, review, and sync from a local web app
- **Card review** — Approve or reject generated cards before syncing
- **Runs locally** — No internet required, no API costs, your data stays private
- **Memory optimized** — Works on 8GB RAM MacBooks

## Who is this for?

- Students who want to study smarter, not harder
- Anyone who learns from lectures, podcasts, or video courses
- People who love Anki but hate making cards manually

## Requirements

- **Python 3.10+**
- **[Ollama](https://ollama.ai)** — Local LLM runtime (for card generation)
- **[Anki](https://apps.ankiweb.net/)** with [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on (for syncing)
- **8GB+ RAM** (16GB recommended for faster processing)

## Quick Start

### 1. Install Lecture2Anki

```bash
git clone https://github.com/MattStaff0/lecture2anki.git
cd lecture2anki

python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

pip install -e ".[dev]"

cp .env.example .env
lecture2anki init
```

### 2. Install Whisper (transcription)

faster-whisper is included as a Python dependency. On first use it will download the model you've configured. The default is `small` (~461MB).

No extra install steps are needed — just make sure your `.env` has:

```bash
WHISPER_MODEL=small    # or "base" for less RAM usage
WHISPER_LANGUAGE=en    # or leave empty for auto-detect
```

### 3. Install Ollama (card generation)

```bash
# macOS
brew install ollama

# Then start the server (keep running in a separate terminal)
ollama serve

# Pull a model — pick one that fits your RAM (see table below)
ollama pull phi3
```

### 4. Set up Anki (card sync)

1. Install [Anki](https://apps.ankiweb.net/)
2. Go to **Tools > Add-ons > Get Add-ons**
3. Enter code: `2055492159` (AnkiConnect)
4. Restart Anki — keep it open while syncing cards

### 5. Run the web UI

```bash
source venv/bin/activate
lecture2anki web
```

Open `http://127.0.0.1:8000` in your browser. From there you can:

1. **Create courses and units** (e.g. AI > Midterm 1)
2. **Record from browser mic** or upload an audio file
3. **Transcribe** the lecture locally with Whisper (runs as a background job)
4. **Generate flashcards** from the transcript using Ollama (background job)
5. **Review cards** — approve or reject each one
6. **Sync approved cards to Anki** — creates the deck automatically

## CLI Usage

The web UI is the primary way to run the full lecture-to-Anki workflow, including card review.
The CLI is available for setup, course and unit management, recording, transcription, inspection,
and optional direct generation and sync commands:

```bash
# Setup
lecture2anki init                    # Create database

# Course/Unit Management
lecture2anki courses list            # Show all courses
lecture2anki courses add "AI"        # Add new course
lecture2anki units list "AI"         # Show units for AI course
lecture2anki units add "AI" "Final"  # Add Final unit to AI

# Recording
lecture2anki record --course AI --unit "Midterm 2"

# Transcription
lecture2anki transcribe <lecture_id>

# Card generation
lecture2anki generate <lecture_id>   # Generate flashcards from transcript

# Card review
lecture2anki cards <lecture_id>      # Inspect generated cards and approval status

# Anki sync
lecture2anki sync <lecture_id>       # Sync approved cards to Anki

# List lectures
lecture2anki lectures
lecture2anki lectures --course AI

# Web UI
lecture2anki web                     # Default: 127.0.0.1:8000
lecture2anki web --port 3000         # Custom port
```

Approve/reject review happens in the browser UI. The CLI can inspect cards and run direct
generation or sync commands, but the browser app is the primary interface for the full v1 flow.

## Configuration

Copy `.env.example` to `.env` and customize:

| Setting              | Default                          | Description                              |
| -------------------- | -------------------------------- | ---------------------------------------- |
| `WHISPER_MODEL`      | `small`                          | Transcription model size                 |
| `WHISPER_LANGUAGE`   | `en`                             | Language code (or empty for auto-detect) |
| `OLLAMA_MODEL`       | `phi3`                           | LLM for card generation                  |
| `OLLAMA_HOST`        | `http://localhost:11434`         | Ollama server URL                        |
| `OLLAMA_CONTEXT_SIZE`| `2048`                           | LLM context window                       |
| `ANKI_ROOT_DECK`     | `Lectures`                       | Parent deck for all courses              |
| `ANKI_CONNECT_URL`   | `http://localhost:8765`          | AnkiConnect URL                          |
| `DATABASE_PATH`      | `~/.lecture2anki/lecture2anki.db` | SQLite database location                 |

See `.env.example` for all options with detailed comments.

### Model recommendations by RAM

| Your RAM | Whisper Model     | Ollama Model              |
| -------- | ----------------- | ------------------------- |
| 8GB      | `small` or `base` | `phi3`, `qwen2:1.5b`     |
| 16GB     | `medium`          | `llama3`, `mistral`       |
| 32GB+    | `large`           | `llama3:70b`, `mixtral`   |

## How it works

```
Record/Upload  -->  Transcribe (Whisper)  -->  Chunk text
                                                    |
                                                    v
Sync to Anki   <--  Review (approve/reject)  <--  Generate cards (Ollama)
```

1. **Record** — Capture audio from browser mic or upload a file
2. **Transcribe** — faster-whisper converts speech to timestamped text segments
3. **Chunk** — Segments are grouped into 500-1200 word blocks for the LLM
4. **Generate** — Ollama creates flashcards from each chunk
5. **Review** — Approve or reject each card in the web UI
6. **Sync** — Approved cards are pushed to Anki via AnkiConnect

Cards land in Anki under `Lectures::CourseName::UnitName` (e.g. `Lectures::AI::Midterm 1`).

## Project structure

```
lecture2anki/
├── src/
│   ├── config.py          # Environment-backed settings
│   ├── db.py              # SQLite operations
│   ├── models.py          # Data models (Course, Unit, Lecture, Segment, Card)
│   ├── recorder.py        # Recording + audio upload
│   ├── transcriber.py     # Whisper integration
│   ├── chunker.py         # Text chunking for LLM
│   ├── card_generator.py  # Ollama card generation
│   ├── anki_client.py     # AnkiConnect sync client
│   ├── web.py             # FastAPI web app + background jobs
│   ├── web_static/        # HTML/CSS/JS frontend
│   └── cli.py             # Click CLI
├── tests/                 # Test suite (103 tests)
├── CLAUDE.md              # AI assistant context
├── .env.example           # Configuration template
└── pyproject.toml         # Project config
```

## Development

```bash
source venv/bin/activate
pytest                  # Run all tests
pytest -v               # Verbose
pytest --cov=src        # With coverage
ruff check .            # Lint
ruff format .           # Format
```

## Contributing

Contributions are welcome! This project follows TDD practices.

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Write tests first, then implement
4. Run tests: `pytest`
5. Submit a PR

See [CLAUDE.md](CLAUDE.md) for coding conventions and architecture details.

## Troubleshooting

### "Connection refused" when syncing to Anki

Make sure Anki is running with AnkiConnect installed. Test with:

```bash
curl http://localhost:8765 -X POST -d '{"action": "version", "version": 6}'
```

### Transcription is slow

Try a smaller Whisper model in `.env`:

```bash
WHISPER_MODEL=base
```

### Out of memory errors

Reduce model sizes in `.env`:

```bash
WHISPER_MODEL=base
OLLAMA_MODEL=qwen2:1.5b
OLLAMA_CONTEXT_SIZE=2048
```

### Cards aren't generating

Check Ollama is running:

```bash
ollama list
curl http://localhost:11434/api/tags
```

### Web UI won't start

Make sure you're in the virtual environment:

```bash
source venv/bin/activate
lecture2anki web
```

## License

MIT — do whatever you want with it.

## Acknowledgments

- [faster-whisper](https://github.com/guillaumekln/faster-whisper) — Fast Whisper inference
- [Ollama](https://ollama.ai) — Local LLM runtime
- [AnkiConnect](https://github.com/FooSoft/anki-connect) — Anki API
- [FastAPI](https://fastapi.tiangolo.com/) — Web framework

---

**Made by students, for students.**
