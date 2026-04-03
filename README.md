# 🎓 Lecture2Anki

> Turn your lectures into Anki flashcards automatically — 100% local, no cloud APIs.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

Record your lectures, get AI-generated flashcards organized by course and exam. Everything runs locally on your machine — your data never leaves your laptop.

## ✨ Features

- **🎤 Live transcription** — Records and transcribes lectures in real-time using Whisper
- **🤖 AI-powered cards** — Generates high-quality flashcards using local LLMs via Ollama
- **📚 Smart organization** — Cards automatically sorted by Course → Unit (Midterm 1, Final, etc.)
- **🔗 Anki integration** — Syncs directly to Anki via AnkiConnect
- **💻 Runs locally** — No internet required, no API costs, your data stays private
- **⚡ Memory optimized** — Works on 8GB RAM MacBooks

## 🎯 Who is this for?

- Students who want to study smarter, not harder
- Anyone who learns from lectures, podcasts, or video courses
- People who love Anki but hate making cards manually

## 📋 Requirements

- **Python 3.10+**
- **[Ollama](https://ollama.ai)** — Local LLM runtime
- **[Anki](https://apps.ankiweb.net/)** with [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on
- **8GB+ RAM** (16GB recommended for faster processing)

## 🚀 Quick Start

### 1. Install dependencies

```bash
# Install Ollama
brew install ollama  # macOS
# See https://ollama.ai for other platforms

# Start Ollama and download a model
ollama serve  # keep running in a terminal
ollama pull phi3  # ~2GB, good for 8GB RAM
```

### 2. Set up Anki

1. Install [Anki](https://apps.ankiweb.net/)
2. Go to **Tools → Add-ons → Get Add-ons**
3. Enter code: `2055492159` (AnkiConnect)
4. Restart Anki — keep it open while using Lecture2Anki

### 3. Install Lecture2Anki

```bash
# Clone the repo
git clone https://github.com/MattStaff0/lecture2anki.git
cd lecture2anki

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install
pip install -e ".[dev]"

# Configure (edit .env with your preferences)
cp .env.example .env

# Initialize database
lecture2anki init
```

### 4. Set up your courses

```bash
# Add your courses
lecture2anki courses add "AI"
lecture2anki courses add "Operating Systems"
lecture2anki courses add "Nutrition"

# Add units (exam periods) to each course
lecture2anki units add "AI" "Midterm 1"
lecture2anki units add "AI" "Midterm 2"
lecture2anki units add "AI" "Final"
```

### 5. Record a lecture

```bash
lecture2anki record
# Select your course and unit, then start recording!
```

### 6. Generate cards and sync to Anki

```bash
# Generate flashcards from your last lecture
lecture2anki generate --last

# Sync to Anki
lecture2anki sync
```

Your cards appear in Anki under `Lectures::AI::Midterm 1` (or whatever course/unit you selected).

## 📖 Usage

### Recording

```bash
# Interactive mode (recommended)
lecture2anki record

# Direct mode
lecture2anki record --course "AI" --unit "Midterm 1"
```

### Managing courses and units

```bash
# List all courses
lecture2anki courses list

# List units for a course
lecture2anki units list "AI"

# Add a new unit
lecture2anki units add "AI" "Quiz 3"
```

### Generating and syncing cards

```bash
# Generate cards for a specific lecture
lecture2anki generate 42

# Generate for most recent lecture
lecture2anki generate --last

# Sync all unsynced cards to Anki
lecture2anki sync

# View cards before syncing
lecture2anki cards 42
```

## ⚙️ Configuration

Copy `.env.example` to `.env` and customize:

| Setting            | Default    | Description                              |
| ------------------ | ---------- | ---------------------------------------- |
| `OLLAMA_MODEL`     | `phi3`     | LLM for card generation                  |
| `WHISPER_MODEL`    | `small`    | Transcription model size                 |
| `ANKI_ROOT_DECK`   | `Lectures` | Parent deck for all courses              |
| `WHISPER_LANGUAGE` | `en`       | Language code (or empty for auto-detect) |

See `.env.example` for all options with detailed comments.

### Memory recommendations

| Your RAM | Whisper Model     | Ollama Model            |
| -------- | ----------------- | ----------------------- |
| 8GB      | `small` or `base` | `phi3`, `qwen2:1.5b`    |
| 16GB     | `medium`          | `llama3`, `mistral`     |
| 32GB+    | `large`           | `llama3:70b`, `mixtral` |

## 🏗️ How it works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Record    │ ──▶ │ Transcribe  │ ──▶ │   Chunk     │
│   Audio     │     │  (Whisper)  │     │   Text      │
└─────────────┘     └─────────────┘     └─────────────┘
                                               │
                                               ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    Anki     │ ◀── │  Dedupe &   │ ◀── │  Generate   │
│    Sync     │     │   Clean     │     │   Cards     │
└─────────────┘     └─────────────┘     └─────────────┘
```

1. **Record** — Captures audio from your microphone in chunks
2. **Transcribe** — Whisper converts speech to text locally
3. **Chunk** — Splits transcript into LLM-friendly pieces
4. **Generate** — Ollama creates flashcards from each chunk
5. **Dedupe** — Removes duplicate/similar cards
6. **Sync** — Pushes cards to Anki via AnkiConnect

## 🗂️ Project structure

```
lecture2anki/
├── src/
│   ├── config.py          # Environment-backed settings
│   ├── recorder.py        # Microphone recording workflow
│   ├── db.py              # Database operations
│   ├── models.py          # Data models
│   ├── transcriber.py     # Whisper integration
│   ├── chunker.py         # Text chunking
│   ├── card_generator.py  # Ollama integration
│   ├── deduplicator.py    # Card deduplication
│   ├── anki_client.py     # AnkiConnect client
│   └── cli.py             # Command-line interface
├── tests/                 # Test suite
├── claude.md              # AI assistant context
├── .env.example           # Configuration template
└── pyproject.toml         # Project config
```

## 🤝 Contributing

Contributions are welcome! This project follows TDD practices.

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Write tests first, then implement
4. Run tests: `pytest`
5. Submit a PR

See [claude.md](claude.md) for coding conventions and architecture details.

## 🐛 Troubleshooting

### "Connection refused" when syncing to Anki

Make sure Anki is running with AnkiConnect installed. Test with:

```bash
curl http://localhost:8765 -X POST -d '{"action": "version", "version": 6}'
```

### Transcription is slow

Try a smaller Whisper model:

```bash
# In .env
WHISPER_MODEL=base  # faster than "small"
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
ollama list  # Should show your model
curl http://localhost:11434/api/tags  # Should return JSON
```

## 📜 License

MIT — do whatever you want with it.

## 🙏 Acknowledgments

- [faster-whisper](https://github.com/guillaumekln/faster-whisper) — Fast Whisper inference
- [Ollama](https://ollama.ai) — Local LLM runtime
- [AnkiConnect](https://github.com/FooSoft/anki-connect) — Anki API

---

**Made with ☕ by students, for students.**
