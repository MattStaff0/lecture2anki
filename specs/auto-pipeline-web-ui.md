# Auto-Pipeline in Web UI

## Summary

Add an optional auto-process mode to the web UI so that after a lecture is created through browser recording or file upload, the frontend can automatically:

1. start transcription
2. wait for transcription to finish
3. start card generation
4. wait for card generation to finish
5. open the card review panel

The implementation must reuse one shared frontend job helper so transcription and generation do not drift into separate orchestration paths.

## Goals

- Reduce manual clicks in the capture flow.
- Keep manual lecture actions unchanged.
- Reuse one shared frontend job helper for transcription and generation.
- Preserve clear failure handling and manual recovery when any step fails.

## Non-Goals

- No backend API changes.
- No changes to lecture-list manual actions beyond refactoring them onto shared helpers.
- No per-row progress UI beyond the existing lecture busy-state styling.
- No changes to transcript or card-generation business logic.

## UX

### Capture Toggle

Add a checkbox in the capture panel between the recording form and upload form.

Label:
`Auto-process after capture (transcribe -> generate cards)`

Behavior:
- Default checked.
- Persist preference in `localStorage`.
- Applies to both browser recording and file upload.

### Auto Pipeline Flow

When the toggle is enabled and a new lecture is created:
- the lecture enters a busy state
- transcription starts automatically
- generation starts automatically after transcription succeeds
- the card review panel opens after generation succeeds

When the toggle is disabled:
- the existing behavior remains
- the upload or recording flow ends at `Lecture saved`

## Implementation Design

### Files

- `src/web_static/index.html`
- `src/web_static/app.js`
- `src/web_static/styles.css`

### Shared Lecture Job Helper

Introduce `runLectureJob(endpoint, lectureId, options = {})`.

Required behavior:
- POST to the given endpoint
- wrap `pollJob()` in a promise
- reject on:
  - initial POST failure
  - job polling failure
  - backend job failure
- return stage-aware errors
- call `loadBootstrap()` after success
- optionally manage `busyLectures`

Options:
- `manageBusy` default `true`
- `stageName` for stage-aware error messages
- `startStatus` optional in-progress status text

Constraints:
- do not set final success status text
- do not navigate to transcript view
- do not navigate to cards view

### Manual Actions

Refactor manual actions to use `runLectureJob(...)`.

`transcribeLecture(lectureId)`:
- run transcription with `manageBusy: true`
- on success, call `showTranscript(lectureId)`
- then set `Transcription complete`

`generateCards(lectureId)`:
- run generation with `manageBusy: true`
- on success, call `showCards(lectureId)`
- then set `Card generation complete`

### Upload Flow

Change `uploadAudioFile(file, durationSeconds)` so it:
- uploads the lecture
- resets form state
- refreshes bootstrap data
- returns the created `lectureId`

It must not inspect the auto-pipeline toggle or start any post-upload flow.

The callers (`uploadRecordedBlob()` and `handleUpload()`) decide whether to:
- call `runAutoPipeline(lectureId)`, or
- set `Lecture saved`

### Auto Pipeline Orchestrator

Add `runAutoPipeline(lectureId)`.

Required behavior:
- add `lectureId` to `state.busyLectures`
- call `render()`
- use `try/finally` so cleanup always runs
- run transcription via `runLectureJob(..., { manageBusy: false })`
- run generation via `runLectureJob(..., { manageBusy: false })`
- call `showCards(lectureId)` after generation succeeds
- set final status to `Cards ready for review` after `showCards()`

Failure behavior:
- if transcription fails, show transcription-specific error and do not attempt generation
- if generation fails, show generation-specific error
- unlock the lecture for manual retry in all failure cases

### Busy-State Semantics

Manual actions:
- use `manageBusy: true`
- lock only the selected lecture for one action

Auto pipeline:
- owns busy-state at the orchestrator level
- uses `manageBusy: false` for individual steps
- keeps the lecture locked across the full chain
- does not block unrelated lectures

## Error Handling

- Transcription POST or job failure:
  - show a transcription-specific error
  - unlock the lecture
  - allow manual retry
- Generation POST or job failure:
  - preserve transcription state
  - show a generation-specific error
  - unlock the lecture
  - allow manual retry
- Zero cards generated:
  - still open the cards panel
  - rely on the existing empty-state message

## Backend Assumptions

No backend changes are required.

Existing endpoints are sufficient:
- `POST /api/lectures/upload`
- `POST /api/lectures/{lecture_id}/transcribe`
- `POST /api/lectures/{lecture_id}/generate`
- `GET /api/jobs/{job_id}`
- `GET /api/lectures/{lecture_id}/cards`
- `GET /api/lectures/{lecture_id}/segments`

The upload response already includes `lecture.id`.

## Acceptance Criteria

- A new checkbox appears in the capture panel and defaults to checked.
- The checkbox state persists across page reloads.
- Recording with auto mode on triggers upload, transcription, generation, and card review automatically.
- File upload with auto mode on behaves the same way.
- With auto mode off, upload or recording ends at `Lecture saved`.
- Manual `Transcribe` still opens transcript view on success.
- Manual `Generate cards` still opens card review on success.
- A lecture in auto pipeline is visually locked for the full pipeline duration.
- Other lectures remain interactive while one lecture is auto-processing.
- Failures identify the stage that failed and leave the lecture recoverable through manual actions.

## Verification

1. Record a short lecture with auto mode on.
Expected: upload succeeds, transcription runs, generation runs, cards panel opens.

2. Upload an audio file with auto mode on.
Expected: same as recording flow.

3. Disable auto mode, reload, and upload again.
Expected: lecture is saved and no automatic transcription or generation starts.

4. Use manual `Transcribe` on an existing lecture.
Expected: transcript panel opens as before.

5. Use manual `Generate cards` on an existing transcribed lecture.
Expected: cards panel opens as before.

6. Trigger a transcription failure.
Expected: transcription-specific error status and lecture unlock.

7. Trigger a generation failure after successful transcription.
Expected: transcription remains available, a generation-specific error is shown, and manual retry remains possible.

8. Start auto pipeline on one lecture and interact with another lecture.
Expected: only the busy lecture is locked.

9. Run `pytest`.
Expected: no backend regressions.
