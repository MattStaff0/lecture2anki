const state = {
  courses: [],
  lectures: [],
  activeLectureId: null,
  mediaRecorder: null,
  mediaStream: null,
  audioChunks: [],
  startedAt: null,
  activeCards: [],
};

const elements = {
  statusPill: document.getElementById("status-pill"),
  courseForm: document.getElementById("course-form"),
  courseName: document.getElementById("course-name"),
  unitForm: document.getElementById("unit-form"),
  unitCourse: document.getElementById("unit-course"),
  unitName: document.getElementById("unit-name"),
  unitSortOrder: document.getElementById("unit-sort-order"),
  courseList: document.getElementById("course-list"),
  recordingForm: document.getElementById("recording-form"),
  recordingUnit: document.getElementById("recording-unit"),
  recordingTitle: document.getElementById("recording-title"),
  recordStart: document.getElementById("record-start"),
  recordStop: document.getElementById("record-stop"),
  uploadForm: document.getElementById("upload-form"),
  uploadAudio: document.getElementById("upload-audio"),
  lectureList: document.getElementById("lecture-list"),
  transcriptEmpty: document.getElementById("transcript-empty"),
  transcriptView: document.getElementById("transcript-view"),
  cardsEmpty: document.getElementById("cards-empty"),
  cardsView: document.getElementById("cards-view"),
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setStatus(message, tone = "idle") {
  elements.statusPill.textContent = message;
  elements.statusPill.style.background =
    tone === "error" ? "rgba(145, 59, 43, 0.16)" :
    tone === "busy" ? "rgba(123, 91, 0, 0.14)" :
    "rgba(47, 107, 67, 0.12)";
  elements.statusPill.style.color =
    tone === "error" ? "#913b2b" :
    tone === "busy" ? "#7b5b00" :
    "#2f6b43";
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "duration unknown";
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}m ${total % 60}s`;
}

function formatUnitLabel(course, unit) {
  return `${course.name} / ${unit.name}`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.error || `Request failed with ${response.status}`);
  return payload;
}

// ---------------------------------------------------------------------------
// Job polling
// ---------------------------------------------------------------------------

function pollJob(jobId, onDone) {
  const interval = setInterval(async () => {
    try {
      const job = await requestJson(`/api/jobs/${jobId}`);
      if (job.status === "succeeded") {
        clearInterval(interval);
        onDone(null, job);
      } else if (job.status === "failed") {
        clearInterval(interval);
        onDone(new Error(job.message || "Job failed"), job);
      }
    } catch (err) {
      clearInterval(interval);
      onDone(err, null);
    }
  }, 1500);
}

// ---------------------------------------------------------------------------
// Bootstrap + rendering
// ---------------------------------------------------------------------------

async function loadBootstrap() {
  const payload = await requestJson("/api/bootstrap");
  state.courses = payload.courses;
  state.lectures = payload.lectures;
  render();
}

function renderCourseOptions() {
  const courseOptions = state.courses
    .map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`)
    .join("");
  elements.unitCourse.innerHTML = courseOptions || '<option value="">Add a course first</option>';

  const unitOptions = state.courses
    .flatMap((c) =>
      c.units.map(
        (u) => `<option value="${u.id}">${escapeHtml(formatUnitLabel(c, u))}</option>`,
      ),
    )
    .join("");
  elements.recordingUnit.innerHTML = unitOptions || '<option value="">Add a unit first</option>';
}

function renderCourses() {
  if (!state.courses.length) {
    elements.courseList.innerHTML =
      '<div class="empty-state">No courses yet. Add one to start organizing lectures.</div>';
    return;
  }
  elements.courseList.innerHTML = state.courses
    .map(
      (c) => `
        <article class="course-card">
          <h3>${escapeHtml(c.name)}</h3>
          <div class="unit-chip-row">
            ${c.units.length
              ? c.units.map((u) => `<span class="unit-chip">${escapeHtml(u.name)} <strong>#${u.sort_order}</strong></span>`).join("")
              : '<span class="unit-chip">No units yet</span>'}
          </div>
        </article>`,
    )
    .join("");
}

function lectureStatusChips(lec) {
  const chips = [];
  chips.push(lec.has_recording ? "audio saved" : "audio missing");
  if (lec.segment_count > 0) {
    chips.push(`${lec.segment_count} segments`);
  } else {
    chips.push("no transcript");
  }
  if (lec.card_count > 0) {
    chips.push(`${lec.card_count} cards (${lec.approved_count} approved)`);
  }
  if (lec.synced_count > 0) {
    chips.push(`${lec.synced_count} synced`);
  }
  return chips;
}

function renderLectures() {
  if (!state.lectures.length) {
    elements.lectureList.innerHTML =
      '<div class="empty-state">No lectures saved yet. Record in the browser or upload an audio file.</div>';
    return;
  }
  elements.lectureList.innerHTML = state.lectures
    .map(
      (lec) => `
        <article class="lecture-card">
          <div>
            <h3>${escapeHtml(lec.title)}</h3>
            <p>${escapeHtml(lec.course_name)} / ${escapeHtml(lec.unit_name)}</p>
          </div>
          <div class="lecture-meta">
            <span class="lecture-chip">${escapeHtml(lec.recorded_at)}</span>
            <span class="lecture-chip">${escapeHtml(formatDuration(lec.duration_seconds))}</span>
            ${lectureStatusChips(lec).map((c) => `<span class="lecture-chip">${escapeHtml(c)}</span>`).join("")}
          </div>
          <div class="lecture-actions">
            <button type="button" data-action="transcribe" data-lecture-id="${lec.id}"
              ${!lec.has_recording ? "disabled" : ""}>Transcribe</button>
            <button type="button" class="button-muted" data-action="segments" data-lecture-id="${lec.id}"
              ${lec.segment_count === 0 ? "disabled" : ""}>View transcript</button>
            <button type="button" data-action="generate" data-lecture-id="${lec.id}"
              ${lec.segment_count === 0 ? "disabled" : ""}>Generate cards</button>
            <button type="button" class="button-muted" data-action="cards" data-lecture-id="${lec.id}"
              ${lec.card_count === 0 ? "disabled" : ""}>Review cards</button>
            <button type="button" data-action="sync" data-lecture-id="${lec.id}"
              ${lec.approved_count === 0 || lec.approved_count === lec.synced_count ? "disabled" : ""}>Sync to Anki</button>
          </div>
        </article>`,
    )
    .join("");
}

function render() {
  renderCourseOptions();
  renderCourses();
  renderLectures();
}

// ---------------------------------------------------------------------------
// Course / Unit creation
// ---------------------------------------------------------------------------

async function createCourse(event) {
  event.preventDefault();
  setStatus("Adding course...", "busy");
  await requestJson("/api/courses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: elements.courseName.value.trim() }),
  });
  elements.courseForm.reset();
  await loadBootstrap();
  setStatus("Course added");
}

async function createUnit(event) {
  event.preventDefault();
  setStatus("Adding unit...", "busy");
  await requestJson("/api/units", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      course_id: Number(elements.unitCourse.value),
      name: elements.unitName.value.trim(),
      sort_order: Number(elements.unitSortOrder.value || 0),
    }),
  });
  elements.unitName.value = "";
  elements.unitSortOrder.value = "0";
  await loadBootstrap();
  setStatus("Unit added");
}

// ---------------------------------------------------------------------------
// Recording + Upload
// ---------------------------------------------------------------------------

function preferredMimeType() {
  if (!window.MediaRecorder) return null;
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find((v) => MediaRecorder.isTypeSupported(v)) || "";
}

function fileExtensionForMimeType(mimeType) {
  if (mimeType.includes("mp4")) return ".m4a";
  if (mimeType.includes("ogg")) return ".ogg";
  if (mimeType.includes("wav")) return ".wav";
  return ".webm";
}

async function startRecording() {
  if (!elements.recordingUnit.value) throw new Error("Add a unit before recording.");
  if (!window.MediaRecorder) throw new Error("This browser does not support in-browser audio recording.");

  state.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  state.audioChunks = [];
  state.startedAt = performance.now();
  const mimeType = preferredMimeType();
  state.mediaRecorder = mimeType
    ? new MediaRecorder(state.mediaStream, { mimeType })
    : new MediaRecorder(state.mediaStream);

  state.mediaRecorder.addEventListener("dataavailable", (e) => {
    if (e.data.size > 0) state.audioChunks.push(e.data);
  });

  state.mediaRecorder.start();
  elements.recordStart.disabled = true;
  elements.recordStop.disabled = false;
  setStatus("Recording in browser...", "busy");
}

async function uploadRecordedBlob(blob) {
  const durationSeconds = (performance.now() - state.startedAt) / 1000;
  const file = new File(
    [blob],
    `lecture${fileExtensionForMimeType(blob.type || "audio/webm")}`,
    { type: blob.type || "audio/webm" },
  );
  await uploadAudioFile(file, durationSeconds);
}

async function stopRecording() {
  if (!state.mediaRecorder) return;
  setStatus("Saving recording...", "busy");

  const finished = new Promise((resolve) => {
    state.mediaRecorder.addEventListener(
      "stop",
      async () => {
        const blob = new Blob(state.audioChunks, { type: state.mediaRecorder.mimeType || "audio/webm" });
        await uploadRecordedBlob(blob);
        resolve();
      },
      { once: true },
    );
  });

  state.mediaRecorder.stop();
  state.mediaStream.getTracks().forEach((t) => t.stop());
  await finished;

  state.mediaRecorder = null;
  state.mediaStream = null;
  state.audioChunks = [];
  state.startedAt = null;
  elements.recordStart.disabled = false;
  elements.recordStop.disabled = true;
}

async function uploadAudioFile(file, durationSeconds = null) {
  const formData = new FormData();
  formData.append("unit_id", elements.recordingUnit.value);
  formData.append("title", elements.recordingTitle.value.trim());
  if (durationSeconds !== null) formData.append("duration_seconds", String(durationSeconds));
  formData.append("audio", file, file.name);

  await requestJson("/api/lectures/upload", { method: "POST", body: formData });
  elements.recordingTitle.value = "";
  elements.uploadForm.reset();
  await loadBootstrap();
  setStatus("Lecture saved");
}

async function handleUpload(event) {
  event.preventDefault();
  const [file] = elements.uploadAudio.files;
  if (!file) throw new Error("Choose an audio file first.");
  setStatus("Uploading audio...", "busy");
  await uploadAudioFile(file);
}

// ---------------------------------------------------------------------------
// Transcription (background job)
// ---------------------------------------------------------------------------

async function transcribeLecture(lectureId) {
  setStatus(`Transcribing lecture ${lectureId}...`, "busy");
  const resp = await requestJson(`/api/lectures/${lectureId}/transcribe`, { method: "POST" });
  pollJob(resp.job_id, async (err) => {
    if (err) return handleError(err);
    await loadBootstrap();
    await showTranscript(lectureId);
    setStatus("Transcription complete");
  });
}

// ---------------------------------------------------------------------------
// Transcript viewer
// ---------------------------------------------------------------------------

async function showTranscript(lectureId) {
  setStatus(`Loading transcript ${lectureId}...`, "busy");
  const payload = await requestJson(`/api/lectures/${lectureId}/segments`);
  state.activeLectureId = lectureId;

  if (!payload.segments.length) {
    elements.transcriptEmpty.style.display = "block";
    elements.transcriptView.innerHTML = "";
    elements.transcriptEmpty.textContent = "No segments saved for this lecture yet.";
    setStatus("No transcript segments yet");
    return;
  }

  elements.transcriptEmpty.style.display = "none";
  elements.transcriptView.innerHTML = payload.segments
    .map(
      (s) => `
        <article class="segment-card">
          <div class="segment-time">${s.start_time.toFixed(1)}s -> ${s.end_time.toFixed(1)}s</div>
          <p>${escapeHtml(s.text)}</p>
        </article>`,
    )
    .join("");
  setStatus(`Loaded ${payload.segments.length} segments`);
}

// ---------------------------------------------------------------------------
// Card generation (background job)
// ---------------------------------------------------------------------------

async function generateCards(lectureId) {
  setStatus(`Generating cards for lecture ${lectureId}...`, "busy");
  const resp = await requestJson(`/api/lectures/${lectureId}/generate`, { method: "POST" });
  pollJob(resp.job_id, async (err) => {
    if (err) return handleError(err);
    await loadBootstrap();
    await showCards(lectureId);
    setStatus("Card generation complete");
  });
}

// ---------------------------------------------------------------------------
// Card review
// ---------------------------------------------------------------------------

async function showCards(lectureId) {
  setStatus(`Loading cards for lecture ${lectureId}...`, "busy");
  const payload = await requestJson(`/api/lectures/${lectureId}/cards`);
  state.activeLectureId = lectureId;
  state.activeCards = payload.cards;

  if (!payload.cards.length) {
    elements.cardsEmpty.style.display = "block";
    elements.cardsView.innerHTML = "";
    elements.cardsEmpty.textContent = "No cards for this lecture yet.";
    setStatus("No cards");
    return;
  }

  elements.cardsEmpty.style.display = "none";
  renderCards();
  setStatus(`Loaded ${payload.cards.length} cards`);
}

function renderCards() {
  elements.cardsView.innerHTML = state.activeCards
    .map(
      (c) => `
        <article class="card-review ${c.status === 'approved' ? 'card-approved' : ''} ${c.synced_to_anki ? 'card-synced' : ''}">
          <div class="card-content">
            <div class="card-front"><strong>Q:</strong> ${escapeHtml(c.front)}</div>
            <div class="card-back"><strong>A:</strong> ${escapeHtml(c.back)}</div>
            ${c.tags.length ? `<div class="card-tags">${c.tags.map((t) => `<span class="unit-chip">${escapeHtml(t)}</span>`).join("")}</div>` : ""}
          </div>
          <div class="card-actions">
            <span class="card-status-label">${c.synced_to_anki ? "synced" : c.status}</span>
            ${c.status === "pending" ? `
              <button type="button" data-card-action="approve" data-card-id="${c.id}">Approve</button>
              <button type="button" class="button-danger" data-card-action="reject" data-card-id="${c.id}">Reject</button>
            ` : ""}
          </div>
        </article>`,
    )
    .join("");
}

async function approveCard(cardId) {
  await requestJson(`/api/cards/${cardId}/approve`, { method: "POST" });
  const card = state.activeCards.find((c) => c.id === cardId);
  if (card) card.status = "approved";
  renderCards();
  await loadBootstrap();
  setStatus("Card approved");
}

async function rejectCard(cardId) {
  await requestJson(`/api/cards/${cardId}`, { method: "DELETE" });
  state.activeCards = state.activeCards.filter((c) => c.id !== cardId);
  renderCards();
  await loadBootstrap();
  setStatus("Card rejected");
}

// ---------------------------------------------------------------------------
// Anki sync (background job)
// ---------------------------------------------------------------------------

async function syncLecture(lectureId) {
  setStatus(`Syncing lecture ${lectureId} to Anki...`, "busy");
  const resp = await requestJson(`/api/lectures/${lectureId}/sync`, { method: "POST" });
  pollJob(resp.job_id, async (err, job) => {
    if (err) return handleError(err);
    await loadBootstrap();
    if (state.activeLectureId === lectureId) await showCards(lectureId);
    const r = job.result || {};
    setStatus(`Synced ${r.synced || 0} cards${r.failed ? `, ${r.failed} failed` : ""}`);
  });
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

function attachEvents() {
  elements.courseForm.addEventListener("submit", (e) => createCourse(e).catch(handleError));
  elements.unitForm.addEventListener("submit", (e) => createUnit(e).catch(handleError));
  elements.recordStart.addEventListener("click", () => startRecording().catch(handleError));
  elements.recordStop.addEventListener("click", () => stopRecording().catch(handleError));
  elements.uploadForm.addEventListener("submit", (e) => handleUpload(e).catch(handleError));

  elements.lectureList.addEventListener("click", (e) => {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;
    const action = target.dataset.action;
    const lectureId = Number(target.dataset.lectureId);
    if (!action || !lectureId) return;
    if (action === "transcribe") transcribeLecture(lectureId).catch(handleError);
    if (action === "segments") showTranscript(lectureId).catch(handleError);
    if (action === "generate") generateCards(lectureId).catch(handleError);
    if (action === "cards") showCards(lectureId).catch(handleError);
    if (action === "sync") syncLecture(lectureId).catch(handleError);
  });

  elements.cardsView.addEventListener("click", (e) => {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;
    const action = target.dataset.cardAction;
    const cardId = Number(target.dataset.cardId);
    if (!action || !cardId) return;
    if (action === "approve") approveCard(cardId).catch(handleError);
    if (action === "reject") rejectCard(cardId).catch(handleError);
  });
}

function handleError(error) {
  console.error(error);
  setStatus(error.message || "Something went wrong", "error");
}

attachEvents();
loadBootstrap()
  .then(() => setStatus("Ready"))
  .catch(handleError);
