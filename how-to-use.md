# How to Use Lecture2Anki (Web UI)

## Prerequisites

Before launching the UI, make sure these are running:

1. **Ollama** — should already be running in the background (verify with `ollama list`)
2. **Anki** — open the desktop app with the AnkiConnect add-on installed (only needed for syncing cards)

## Starting the UI

```bash
cd ~/Desktop/flashcard_lecture
source venv/bin/activate
lecture2anki web
```

Open your browser to **http://127.0.0.1:8000**

## Step-by-Step Walkthrough

### 1. Create a Course and Unit

In the **Setup** panel at the top:

- Type a course name (e.g., `Web Tech`) and click **Add course**
- Select the course from the dropdown, type a unit name (e.g., `Final`), and click **Add unit**

You only need to do this once per course/unit. They persist in the database.

### 2. Record or Upload a Lecture

In the **Capture** panel:

- Select the unit from the **Lecture unit** dropdown
- Optionally type a **Lecture title**
- Either:
  - Click **Start browser recording** to record from your mic, then **Stop and save** when done
  - Or use **Upload existing recording** to upload an audio file (.wav, .mp3, .m4a, .webm, .mp4)

### 3. Auto-Pipeline (Default)

If the **Auto-process after capture** checkbox is checked (it is by default), the system will automatically:

1. **Transcribe** the recording using Whisper
2. **Generate flashcards** using the local LLM (Mistral)
3. **Scroll to the card review panel** when done

The status pill at the top shows which step is running:
- "Auto-pipeline: transcribing..."
- "Auto-pipeline: generating cards..."
- "Cards ready for review"

If you uncheck this box, each step becomes manual (see Manual Mode below).

### 4. Review Cards

Once cards are generated, the **Flashcards** panel shows each card with:

- **Q:** the question (front of card)
- **A:** the answer (back of card)
- **Approve** — marks the card as ready to sync to Anki
- **Reject** — deletes the card

Use **Approve all N pending** to bulk-approve if the cards look good.

### 5. Sync to Anki

After approving cards, go back to the **Lecture Log** and click **Sync to Anki** on that lecture. Cards will appear in Anki under the deck `Lectures::Web Tech::Final`.

Make sure Anki is open before syncing.

## Manual Mode

Uncheck **Auto-process after capture** to control each step yourself. After recording/uploading, use the buttons on each lecture card in the **Lecture Log**:

| Button | What it does |
|---|---|
| **Transcribe** | Runs Whisper on the recording |
| **View transcript** | Shows the timestamped transcript segments |
| **Generate cards** | Sends transcript chunks to the LLM |
| **Review cards** | Opens the card review panel |
| **Sync to Anki** | Sends approved cards to Anki |
| **Delete** | Removes the lecture, segments, cards, and recording file |

## Deleting Data

You can delete at any level from the **Setup** panel:

- **Delete a course** — click the Delete button on the course card (removes all units, lectures, and cards under it)
- **Delete a unit** — click the x on the unit chip (removes all lectures and cards under it)
- **Delete a lecture** — click the Delete button on a lecture card in the Lecture Log

All deletes include a confirmation prompt and also remove recording files from disk.

## Tips

- **Longer lectures take longer** — a 30-minute lecture may take a few minutes each for transcription and card generation
- **Keep your laptop open** — the server stops if the lid closes
- **No internet needed** — everything runs locally
- **Anki only needed for sync** — you can record, transcribe, and generate cards without Anki open
- **Toggle preference is saved** — the auto-process checkbox remembers your choice across page reloads
