# Lecture2Anki

Transcribe lectures and automatically generate Anki flashcards using local AI. No cloud APIs, everything runs on your machine.

## Features

- **Near-real-time transcription** using faster-whisper
- **Local LLM card generation** using Ollama
- **Automatic Anki import** via AnkiConnect
- **Optimized for M1 Mac** with 8GB RAM

## Requirements

- Python 3.10+
- [Ollama](https://ollama.ai) with a small model (phi3, qwen2:1.5b, or gemma:2b)
- [Anki](https://apps.ankiweb.net/) with [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on

## Installation

```bash
# Clone the repo
git clone https://github.com/yourusername/lecture2anki.git
cd lecture2anki

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

## Setup

### Ollama

```bash
brew install ollama
ollama serve          # keep running in a terminal
ollama pull phi3      # or another small model
```

### Anki

1. Install [Anki](https://apps.ankiweb.net/)
2. Go to Tools → Add-ons → Get Add-ons
3. Enter code: `2055492159`
4. Restart Anki (keep it open while using this tool)

## Usage

```bash
# Transcribe a lecture recording
lecture2anki transcribe lecture.mp3

# Generate flashcards from transcript
lecture2anki generate --input transcript.db

# Full pipeline: audio → cards → Anki
lecture2anki process lecture.mp3
```

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=src

# Lint and format
ruff check .
ruff format .

# Type check
mypy src
```

## Architecture

```
Audio → faster-whisper → SQLite → Chunker → Ollama → Cards → AnkiConnect
```

See [CLAUDE.md](CLAUDE.md) for detailed architecture and development guidelines.

## License

MIT
