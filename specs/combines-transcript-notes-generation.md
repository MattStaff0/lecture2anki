# Combined Transcript + Notes Card Generation

## Summary

Add lecture notes as a first-class input for flashcard generation. A lecture should be able to generate cards from transcript segments, pasted notes, or both. When both sources are present, the generation pipeline
must combine them and run a single lecture-level deduplication pass so overlapping material does not produce duplicate cards.

This feature is primarily for the web UI. Users should be able to paste lecture notes or slide text onto a lecture, save them, and regenerate cards later using both the saved notes and any available transcript.

## Goals

- Let users save pasted lecture notes on a lecture.
- Allow card generation from:
  - transcript only
  - notes only
  - transcript and notes together
- Prevent duplicate cards when transcript and notes cover the same material.
- Reuse the existing lecture/job/generation workflow.
- Preserve manual regeneration so users can update notes and rerun generation later.

## Non-Goals

- No rich-text editor or file upload support for notes in v1.
- No per-card persisted provenance in v1.
- No LLM-based duplicate judge.
- No CLI notes support in v1.

## Product Behavior

### Lecture Notes

Each lecture has one saved plain-text notes blob.

Users can:

- open a notes editor for a lecture
- paste or edit notes
- save notes without generating cards
- return later and regenerate cards

Saving notes overwrites the previous saved notes for that lecture.

### Generation Eligibility

`Generate cards` should be allowed when at least one of these is true:

- the lecture has transcript segments
- the lecture has saved notes

Generation should fail only when both transcript and notes are absent.

### Combined Generation

When both transcript and notes are present:

- transcript segments are chunked as they are today
- notes are chunked using paragraph-aware text chunking
- all generated candidates are pooled together
- one final lecture-level dedup pass runs across the combined pool
- deduped cards are persisted as the lecture’s regenerated cards

### Duplicate Handling

Transcript and notes often restate the same fact with different wording. The system must remove cross-source duplicates before saving cards.

Dedup should be conservative:

- remove duplicates when two cards clearly test the same fact
- keep both cards when they are meaningfully different

When duplicate candidates compete, prefer:

1. notes-derived card
2. more specific answer
3. cleaner question wording
4. longer answer as final tiebreaker

## Data Model

### Database

Add to `lectures`:

- `notes_text TEXT NOT NULL DEFAULT ''`

This field stores the lecture’s current saved notes.

### Model

Update `Lecture` to include:

- `notes_text: str`

## Backend Design

### DB Layer

In `src/db.py`:

- add idempotent migration support for `lectures.notes_text`
- include `notes_text` in lecture row mapping
- add `update_lecture_notes(conn, lecture_id, notes_text) -> None`

### Chunking

In `src/chunker.py`:

- add a text chunking path for notes
- split notes on paragraph boundaries first
