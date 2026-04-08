const state = {
  courses: [],
  lectures: [],
  activeLectureId: null,
  mediaRecorder: null,
  mediaStream: null,
  audioChunks: [],
  startedAt: null,
  activeCards: [],
  // Job polling: map of job_id -> { lectureId, interval, type }
  activePolls: {},
  // Expanded event log panels: set of lecture IDs
  expandedLogs: new Set(),
  // Expanded job event details: set of job IDs
  expandedJobEvents: new Set(),
  // Expanded notes editors: set of lecture IDs
  expandedNotes: new Set(),
  // Pagination
  segmentsAll: [],
  segmentsShown: 0,
  cardsShown: 0,
};

const PAGE_SIZE = 20;

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
  autoPipeline: document.getElementById("auto-pipeline"),
  lectureList: document.getElementById("lecture-list"),
  activityPanel: document.getElementById("activity-panel"),
  activityList: document.getElementById("activity-list"),
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

function timeAgo(dateStr) {
  if (!dateStr) return "";
  const utcStr = dateStr.endsWith("Z") ? dateStr : dateStr + "Z";
  const diff = (Date.now() - new Date(utcStr).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.error || `Request failed with ${response.status}`);
  return payload;
}

// ---------------------------------------------------------------------------
// Job polling (durable, SQLite-backed)
// ---------------------------------------------------------------------------

function pollJob(jobId, lectureId, onDone) {
  // Clear any existing poll for this job
  if (state.activePolls[jobId]) {
    clearInterval(state.activePolls[jobId].interval);
  }

  const intervalId = setInterval(async () => {
    try {
      const job = await requestJson(`/api/jobs/${jobId}`);

      // Update the lecture's active job display
      const lec = state.lectures.find((l) => l.id === lectureId);
      if (lec) {
        if (job.status === "running" || job.status === "queued") {
          lec.active_job = {
            job_id: jobId,
            job_type: job.job_type,
            status: job.status,
            current_stage: job.current_stage,
            latest_event: job.latest_event,
          };
          renderLectures();
        }
      }

      if (job.status === "succeeded") {
        clearInterval(intervalId);
        delete state.activePolls[jobId];
        onDone(null, job);
      } else if (job.status === "failed") {
        clearInterval(intervalId);
        delete state.activePolls[jobId];
        onDone(new Error(job.error_message || job.latest_event || "Job failed"), job);
      }
    } catch (err) {
      clearInterval(intervalId);
      delete state.activePolls[jobId];
      onDone(err, null);
    }
  }, 2000);

  state.activePolls[jobId] = { lectureId, interval: intervalId, type: "job" };
}

function wrapStageError(stageName, error) {
  const message = error instanceof Error ? error.message : String(error || "Job failed");
  return new Error(`${stageName} failed: ${message}`);
}

// ---------------------------------------------------------------------------
// Shared lecture job helper
// ---------------------------------------------------------------------------

function runLectureJob(endpoint, lectureId, { stageName = "Job", startStatus = null } = {}) {
  if (startStatus) setStatus(startStatus, "busy");

  return new Promise((resolve, reject) => {
    requestJson(endpoint, { method: "POST" })
      .then((resp) => {
        const jobId = resp.job_id;
        // Update lecture to show active job immediately
        const lec = state.lectures.find((l) => l.id === lectureId);
        if (lec) {
          lec.active_job = {
            job_id: jobId,
            job_type: stageName.toLowerCase(),
            status: "queued",
            current_stage: "",
            latest_event: "Starting...",
          };
          renderLectures();
        }

        pollJob(jobId, lectureId, async (err, job) => {
          if (err) {
            reject(wrapStageError(stageName, err));
            await loadBootstrap();
            return;
          }
          try {
            await loadBootstrap();
            resolve(job);
          } catch (loadErr) {
            reject(loadErr);
          }
        });
      })
      .catch((err) => reject(wrapStageError(stageName, err)));
  });
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
          <div class="course-card-head">
            <h3>${escapeHtml(c.name)}</h3>
            <button type="button" class="button-delete" data-delete="course" data-id="${c.id}" data-name="${escapeHtml(c.name)}" title="Delete course">Delete</button>
          </div>
          <div class="unit-chip-row">
            ${c.units.length
              ? c.units.map((u) => `<span class="unit-chip">${escapeHtml(u.name)} <strong>#${u.sort_order}</strong> <button type="button" class="chip-delete" data-delete="unit" data-id="${u.id}" data-name="${escapeHtml(u.name)}" title="Delete unit">&times;</button></span>`).join("")
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

function renderActiveJobBanner(lec) {
  if (!lec.active_job) return "";
  const job = lec.active_job;
  const typeLabel = job.job_type === "transcription" ? "Transcribing" :
                    job.job_type === "generation" ? "Generating cards" :
                    job.job_type === "sync" ? "Syncing to Anki" : job.job_type;
  const event = job.latest_event ? escapeHtml(job.latest_event) : "Starting...";
  return `
    <div class="job-banner job-banner-active">
      <div class="job-banner-header">
        <span class="job-spinner"></span>
        <strong>${typeLabel}</strong>
        <span class="job-stage-chip">${escapeHtml(job.current_stage || "starting")}</span>
      </div>
      <div class="job-banner-detail">${event}</div>
    </div>`;
}

function renderErrorBanner(lec) {
  if (!lec.last_error) return "";
  if (lec.active_job) return ""; // Don't show old error while a new job is running
  return `
    <div class="job-banner job-banner-error">
      <div class="job-banner-header">
        <strong>Last job failed</strong>
        <button type="button" class="chip-delete" data-action="dismiss-error" data-lecture-id="${lec.id}" title="Dismiss">&times;</button>
      </div>
      <div class="job-banner-detail">${escapeHtml(lec.last_error.error_message || "Unknown error")}</div>
    </div>`;
}

function renderLectures() {
  if (!state.lectures.length) {
    elements.lectureList.innerHTML =
      '<div class="empty-state">No lectures saved yet. Record in the browser or upload an audio file.</div>';
    return;
  }
  elements.lectureList.innerHTML = state.lectures
    .map(
      (lec) => {
        const busy = !!lec.active_job;
        const expanded = state.expandedLogs.has(lec.id);
        return `
        <article class="lecture-card${busy ? " lecture-busy-styled" : ""}">
          <div>
            <h3>${escapeHtml(lec.title)}</h3>
            <p>${escapeHtml(lec.course_name)} / ${escapeHtml(lec.unit_name)}</p>
          </div>
          ${renderActiveJobBanner(lec)}
          ${renderErrorBanner(lec)}
          <div class="lecture-meta">
            <span class="lecture-chip">${escapeHtml(lec.recorded_at)}</span>
            <span class="lecture-chip">${escapeHtml(formatDuration(lec.duration_seconds))}</span>
            ${lectureStatusChips(lec).map((c) => `<span class="lecture-chip">${escapeHtml(c)}</span>`).join("")}
            ${lec.has_notes ? '<span class="lecture-chip">notes saved</span>' : ""}
          </div>
          <div class="lecture-actions">
            <button type="button" data-action="transcribe" data-lecture-id="${lec.id}"
              ${!lec.has_recording || busy ? "disabled" : ""}>Transcribe</button>
            <button type="button" class="button-muted" data-action="segments" data-lecture-id="${lec.id}"
              ${lec.segment_count === 0 ? "disabled" : ""}>View transcript</button>
            <button type="button" class="button-muted" data-action="toggle-notes" data-lecture-id="${lec.id}">Notes</button>
            <button type="button" data-action="generate" data-lecture-id="${lec.id}"
              ${(lec.segment_count === 0 && !lec.has_notes) || busy ? "disabled" : ""}>Generate cards</button>
            <button type="button" class="button-muted" data-action="cards" data-lecture-id="${lec.id}"
              ${lec.card_count === 0 ? "disabled" : ""}>Review cards</button>
            <button type="button" data-action="sync" data-lecture-id="${lec.id}"
              ${lec.approved_count === 0 || lec.approved_count === lec.synced_count || busy ? "disabled" : ""}>Sync to Anki</button>
            <button type="button" class="button-muted" data-action="toggle-log" data-lecture-id="${lec.id}">
              ${expanded ? "Hide log" : "Show log"}</button>
            <button type="button" class="button-danger" data-action="delete" data-lecture-id="${lec.id}"
              data-lecture-title="${escapeHtml(lec.title)}" ${busy ? "disabled" : ""}>Delete</button>
          </div>
          ${expanded ? `<div class="job-event-log" id="job-log-${lec.id}"><div class="empty-state">Loading...</div></div>` : ""}
          ${state.expandedNotes.has(lec.id) ? `
            <div class="notes-editor" id="notes-editor-${lec.id}">
              <textarea class="notes-textarea" id="notes-text-${lec.id}" placeholder="Paste lecture notes or slide text here..."
                rows="8"></textarea>
              <div class="notes-actions">
                <button type="button" data-action="save-notes" data-lecture-id="${lec.id}">Save Notes</button>
                <span class="notes-status" id="notes-status-${lec.id}"></span>
              </div>
            </div>` : ""}
        </article>`;
      },
    )
    .join("");

  // Load event logs for expanded lectures
  for (const lecId of state.expandedLogs) {
    loadLectureJobLog(lecId);
  }
}

async function loadLectureJobLog(lectureId) {
  const container = document.getElementById(`job-log-${lectureId}`);
  if (!container) return;
  try {
    const status = await requestJson(`/api/lectures/${lectureId}/status`);
    if (!status.recent_jobs || !status.recent_jobs.length) {
      container.innerHTML = '<div class="empty-state">No job history for this lecture.</div>';
      return;
    }
    let html = "";
    for (const job of status.recent_jobs) {
      const statusClass = job.status === "succeeded" ? "job-status-ok" :
                          job.status === "failed" ? "job-status-fail" :
                          job.status === "running" ? "job-status-running" : "";
      html += `<div class="job-log-entry">
        <div class="job-log-header">
          <span class="job-log-type">${escapeHtml(job.job_type)}</span>
          <span class="job-log-status ${statusClass}">${escapeHtml(job.status)}</span>
          ${job.started_at ? `<span class="job-log-time">${escapeHtml(timeAgo(job.started_at))}</span>` : ""}
          <button type="button" class="chip-delete" data-action="show-events" data-job-id="${job.id}" title="Show events">details</button>
        </div>
        ${job.error_message ? `<div class="job-log-error">${escapeHtml(job.error_message)}</div>` : ""}
        ${job.latest_event ? `<div class="job-log-detail">${escapeHtml(job.latest_event)}</div>` : ""}
        <div class="job-events-container" id="job-events-${job.id}"></div>
      </div>`;
    }
    container.innerHTML = html;
    // Restore expanded job event details
    for (const jobId of state.expandedJobEvents) {
      loadJobEvents(jobId);
    }
  } catch (err) {
    container.innerHTML = `<div class="empty-state">Failed to load: ${escapeHtml(err.message)}</div>`;
  }
}

async function showJobEvents(jobId) {
  const container = document.getElementById(`job-events-${jobId}`);
  if (!container) return;
  if (state.expandedJobEvents.has(jobId)) {
    state.expandedJobEvents.delete(jobId);
    container.innerHTML = "";
    return;
  }
  state.expandedJobEvents.add(jobId);
  await loadJobEvents(jobId);
}

async function loadJobEvents(jobId) {
  const container = document.getElementById(`job-events-${jobId}`);
  if (!container) return;
  try {
    const data = await requestJson(`/api/jobs/${jobId}/events`);
    if (!data.events.length) {
      container.innerHTML = '<div class="job-event-item">No events recorded.</div>';
      return;
    }
    container.innerHTML = data.events.map((e) => {
      const levelClass = e.level === "error" ? "event-error" : e.level === "warning" ? "event-warn" : "";
      return `<div class="job-event-item ${levelClass}">
        <span class="event-stage">${escapeHtml(e.stage)}</span>
        <span class="event-msg">${escapeHtml(e.message)}</span>
      </div>`;
    }).join("");
  } catch (err) {
    container.innerHTML = `<div class="job-event-item event-error">${escapeHtml(err.message)}</div>`;
  }
}

function render() {
  renderCourseOptions();
  renderCourses();
  renderLectures();
}

// ---------------------------------------------------------------------------
// Course / Unit creation + deletion
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

async function deleteCourse(courseId, courseName) {
  if (!confirm(`Delete course "${courseName}" and all its units, lectures, and cards?`)) return;
  setStatus("Deleting course...", "busy");
  await requestJson(`/api/courses/${courseId}`, { method: "DELETE" });
  await loadBootstrap();
  setStatus("Course deleted");
}

async function deleteUnit(unitId, unitName) {
  if (!confirm(`Delete unit "${unitName}" and all its lectures and cards?`)) return;
  setStatus("Deleting unit...", "busy");
  await requestJson(`/api/units/${unitId}`, { method: "DELETE" });
  await loadBootstrap();
  setStatus("Unit deleted");
}

async function deleteLecture(lectureId, lectureTitle) {
  if (!confirm(`Delete lecture "${lectureTitle}" and all its segments, cards, and recordings?`)) return;
  setStatus("Deleting lecture...", "busy");
  await requestJson(`/api/lectures/${lectureId}`, { method: "DELETE" });
  state.expandedLogs.delete(lectureId);
  await loadBootstrap();
  setStatus("Lecture deleted");
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
  const lectureId = await uploadAudioFile(file, durationSeconds);
  if (elements.autoPipeline.checked) {
    runAutoPipeline(lectureId).catch(handleError);
  } else {
    setStatus("Lecture saved");
  }
}

async function stopRecording() {
  if (!state.mediaRecorder) return;
  setStatus("Saving recording...", "busy");

  const recorder = state.mediaRecorder;
  const mimeType = recorder.mimeType || "audio/webm";
  const finished = new Promise((resolve) => {
    recorder.addEventListener(
      "stop",
      () => resolve(new Blob(state.audioChunks, { type: mimeType })),
      { once: true },
    );
  });

  recorder.stop();
  state.mediaStream.getTracks().forEach((t) => t.stop());

  try {
    const blob = await finished;
    await uploadRecordedBlob(blob);
  } finally {
    state.mediaRecorder = null;
    state.mediaStream = null;
    state.audioChunks = [];
    state.startedAt = null;
    elements.recordStart.disabled = false;
    elements.recordStop.disabled = true;
  }
}

async function uploadAudioFile(file, durationSeconds = null) {
  const formData = new FormData();
  formData.append("unit_id", elements.recordingUnit.value);
  formData.append("title", elements.recordingTitle.value.trim());
  if (durationSeconds !== null) formData.append("duration_seconds", String(durationSeconds));
  formData.append("audio", file, file.name);

  const result = await requestJson("/api/lectures/upload", { method: "POST", body: formData });
  const lectureId = result.lecture.id;
  elements.recordingTitle.value = "";
  elements.uploadForm.reset();
  await loadBootstrap();
  return lectureId;
}

async function handleUpload(event) {
  event.preventDefault();
  const [file] = elements.uploadAudio.files;
  if (!file) throw new Error("Choose an audio file first.");
  setStatus("Uploading audio...", "busy");
  const lectureId = await uploadAudioFile(file);
  if (elements.autoPipeline.checked) {
    runAutoPipeline(lectureId).catch(handleError);
  } else {
    setStatus("Lecture saved");
  }
}

// ---------------------------------------------------------------------------
// Auto-pipeline orchestrator
// ---------------------------------------------------------------------------

async function runAutoPipeline(lectureId) {
  try {
    setStatus("Auto-pipeline: transcribing...", "busy");
    await runLectureJob(`/api/lectures/${lectureId}/transcribe`, lectureId, {
      stageName: "Transcription",
    });

    setStatus("Auto-pipeline: generating cards...", "busy");
    await runLectureJob(`/api/lectures/${lectureId}/generate`, lectureId, {
      stageName: "Generation",
    });

    await showCards(lectureId);
    setStatus("Cards ready for review");
  } catch (err) {
    handleError(err);
  }
}

// ---------------------------------------------------------------------------
// Transcription (manual)
// ---------------------------------------------------------------------------

async function transcribeLecture(lectureId) {
  try {
    await runLectureJob(`/api/lectures/${lectureId}/transcribe`, lectureId, {
      stageName: "Transcription",
      startStatus: `Transcribing lecture ${lectureId}...`,
    });
    await showTranscript(lectureId);
    setStatus("Transcription complete");
  } catch (err) {
    handleError(err);
  }
}

// ---------------------------------------------------------------------------
// Transcript viewer
// ---------------------------------------------------------------------------

async function showTranscript(lectureId) {
  setStatus(`Loading transcript ${lectureId}...`, "busy");
  const payload = await requestJson(`/api/lectures/${lectureId}/segments`);
  state.activeLectureId = lectureId;
  state.segmentsAll = payload.segments;
  state.segmentsShown = 0;

  if (!payload.segments.length) {
    elements.transcriptEmpty.style.display = "block";
    elements.transcriptView.innerHTML = "";
    elements.transcriptEmpty.textContent = "No segments saved for this lecture yet.";
    setStatus("No transcript segments yet");
    return;
  }

  elements.transcriptEmpty.style.display = "none";
  elements.transcriptView.innerHTML = "";
  showMoreSegments();
  document.querySelector(".transcript-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  setStatus(`Loaded ${payload.segments.length} segments`);
}

function showMoreSegments() {
  const next = state.segmentsAll.slice(state.segmentsShown, state.segmentsShown + PAGE_SIZE);
  state.segmentsShown += next.length;

  // Remove existing "show more" button
  const existing = elements.transcriptView.querySelector(".show-more-btn");
  if (existing) existing.remove();

  const fragment = document.createDocumentFragment();
  for (const s of next) {
    const article = document.createElement("article");
    article.className = "segment-card";
    article.innerHTML = `
      <div class="segment-time">${s.start_time.toFixed(1)}s -> ${s.end_time.toFixed(1)}s</div>
      <p>${escapeHtml(s.text)}</p>`;
    fragment.appendChild(article);
  }
  elements.transcriptView.appendChild(fragment);

  if (state.segmentsShown < state.segmentsAll.length) {
    const remaining = state.segmentsAll.length - state.segmentsShown;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "show-more-btn button-muted";
    btn.textContent = `Show more (${remaining} remaining)`;
    btn.addEventListener("click", () => showMoreSegments());
    elements.transcriptView.appendChild(btn);
  }
}

// ---------------------------------------------------------------------------
// Card generation (manual)
// ---------------------------------------------------------------------------

async function generateCards(lectureId) {
  try {
    await runLectureJob(`/api/lectures/${lectureId}/generate`, lectureId, {
      stageName: "Generation",
      startStatus: `Generating cards for lecture ${lectureId}...`,
    });
    await showCards(lectureId);
    setStatus("Card generation complete");
  } catch (err) {
    handleError(err);
  }
}

// ---------------------------------------------------------------------------
// Card review
// ---------------------------------------------------------------------------

async function showCards(lectureId) {
  setStatus(`Loading cards for lecture ${lectureId}...`, "busy");
  const payload = await requestJson(`/api/lectures/${lectureId}/cards`);
  state.activeLectureId = lectureId;
  state.activeCards = payload.cards;
  state.cardsShown = 0;

  if (!payload.cards.length) {
    elements.cardsEmpty.style.display = "block";
    elements.cardsView.innerHTML = "";
    elements.cardsEmpty.textContent = "No cards for this lecture yet.";
    document.getElementById("cards-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    setStatus("No cards");
    return;
  }

  elements.cardsEmpty.style.display = "none";
  renderCards();
  document.getElementById("cards-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  setStatus(`Loaded ${payload.cards.length} cards`);
}

function renderCardHtml(c) {
  return `
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
    </article>`;
}

function renderCards() {
  const pendingCards = state.activeCards.filter((c) => c.status === "pending");
  const approveAllHtml = pendingCards.length > 1
    ? `<div class="cards-batch-actions"><button type="button" id="approve-all-btn">Approve all ${pendingCards.length} pending</button></div>`
    : "";

  const visible = state.activeCards.slice(0, state.cardsShown || PAGE_SIZE);
  state.cardsShown = visible.length;
  const remaining = state.activeCards.length - state.cardsShown;

  const showMoreHtml = remaining > 0
    ? `<button type="button" class="show-more-btn button-muted" id="show-more-cards">Show more (${remaining} remaining)</button>`
    : "";

  elements.cardsView.innerHTML = approveAllHtml
    + visible.map(renderCardHtml).join("")
    + showMoreHtml;
}

function showMoreCards() {
  const next = state.activeCards.slice(state.cardsShown, state.cardsShown + PAGE_SIZE);
  state.cardsShown += next.length;

  // Remove existing "show more" button
  const existing = document.getElementById("show-more-cards");
  if (existing) existing.remove();

  const container = elements.cardsView;
  const fragment = document.createDocumentFragment();
  const wrapper = document.createElement("div");
  wrapper.innerHTML = next.map(renderCardHtml).join("");
  while (wrapper.firstChild) {
    fragment.appendChild(wrapper.firstChild);
  }
  container.appendChild(fragment);

  const remaining = state.activeCards.length - state.cardsShown;
  if (remaining > 0) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "show-more-btn button-muted";
    btn.id = "show-more-cards";
    btn.textContent = `Show more (${remaining} remaining)`;
    btn.addEventListener("click", () => showMoreCards());
    container.appendChild(btn);
  }
}

async function approveCard(cardId) {
  await requestJson(`/api/cards/${cardId}/approve`, { method: "POST" });
  const card = state.activeCards.find((c) => c.id === cardId);
  if (card) card.status = "approved";
  renderCards();
  await loadBootstrap();
  setStatus("Card approved");
}

async function approveAllPending() {
  const pending = state.activeCards.filter((c) => c.status === "pending");
  if (!pending.length) return;
  setStatus(`Approving ${pending.length} cards...`, "busy");
  for (const card of pending) {
    await requestJson(`/api/cards/${card.id}/approve`, { method: "POST" });
    card.status = "approved";
  }
  renderCards();
  await loadBootstrap();
  setStatus(`Approved ${pending.length} cards`);
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
  try {
    const job = await runLectureJob(`/api/lectures/${lectureId}/sync`, lectureId, {
      stageName: "Sync",
      startStatus: `Syncing lecture ${lectureId} to Anki...`,
    });
    if (state.activeLectureId === lectureId) await showCards(lectureId);
    const r = job.result || job.details || {};
    setStatus(`Synced ${r.synced || 0} cards${r.failed ? `, ${r.failed} failed` : ""}`);
  } catch (err) {
    handleError(err);
  }
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

function attachEvents() {
  // Auto-pipeline toggle persistence
  elements.autoPipeline.checked = localStorage.getItem("autoPipeline") !== "false";
  elements.autoPipeline.addEventListener("change", () => {
    localStorage.setItem("autoPipeline", elements.autoPipeline.checked);
  });

  elements.courseForm.addEventListener("submit", (e) => createCourse(e).catch(handleError));
  elements.unitForm.addEventListener("submit", (e) => createUnit(e).catch(handleError));
  elements.recordStart.addEventListener("click", () => startRecording().catch(handleError));
  elements.recordStop.addEventListener("click", () => stopRecording().catch(handleError));
  elements.uploadForm.addEventListener("submit", (e) => handleUpload(e).catch(handleError));

  elements.courseList.addEventListener("click", (e) => {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;
    const deleteType = target.dataset.delete;
    if (!deleteType) return;
    const id = Number(target.dataset.id);
    const name = target.dataset.name;
    if (deleteType === "course") deleteCourse(id, name).catch(handleError);
    if (deleteType === "unit") deleteUnit(id, name).catch(handleError);
  });

  elements.lectureList.addEventListener("click", (e) => {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;
    const action = target.dataset.action;
    const lectureId = Number(target.dataset.lectureId);
    const jobId = Number(target.dataset.jobId);

    if (action === "show-events" && jobId) {
      showJobEvents(jobId).catch(handleError);
      return;
    }
    if (action === "dismiss-error" && lectureId) {
      const lec = state.lectures.find((l) => l.id === lectureId);
      if (lec) { lec.last_error = null; renderLectures(); }
      return;
    }
    if (action === "toggle-log" && lectureId) {
      if (state.expandedLogs.has(lectureId)) {
        state.expandedLogs.delete(lectureId);
      } else {
        state.expandedLogs.add(lectureId);
      }
      renderLectures();
      return;
    }
    if (action === "toggle-notes" && lectureId) {
      if (state.expandedNotes.has(lectureId)) {
        state.expandedNotes.delete(lectureId);
      } else {
        state.expandedNotes.add(lectureId);
      }
      renderLectures();
      if (state.expandedNotes.has(lectureId)) {
        loadNotesForLecture(lectureId);
      }
      return;
    }
    if (action === "save-notes" && lectureId) {
      saveNotesForLecture(lectureId).catch(handleError);
      return;
    }

    if (!action || !lectureId) return;
    if (action === "transcribe") transcribeLecture(lectureId).catch(handleError);
    if (action === "segments") showTranscript(lectureId).catch(handleError);
    if (action === "generate") generateCards(lectureId).catch(handleError);
    if (action === "cards") showCards(lectureId).catch(handleError);
    if (action === "sync") syncLecture(lectureId).catch(handleError);
    if (action === "delete") deleteLecture(lectureId, target.dataset.lectureTitle).catch(handleError);
  });

  elements.cardsView.addEventListener("click", (e) => {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.id === "approve-all-btn") return approveAllPending().catch(handleError);
    if (target.id === "show-more-cards") return showMoreCards();
    const action = target.dataset.cardAction;
    const cardId = Number(target.dataset.cardId);
    if (!action || !cardId) return;
    if (action === "approve") approveCard(cardId).catch(handleError);
    if (action === "reject") rejectCard(cardId).catch(handleError);
  });
}

async function loadNotesForLecture(lectureId) {
  const textarea = document.getElementById(`notes-text-${lectureId}`);
  if (!textarea) return;
  try {
    const data = await requestJson(`/api/lectures/${lectureId}/notes`);
    textarea.value = data.notes_text || "";
  } catch (err) {
    console.error("Failed to load notes:", err);
  }
}

async function saveNotesForLecture(lectureId) {
  const textarea = document.getElementById(`notes-text-${lectureId}`);
  const statusEl = document.getElementById(`notes-status-${lectureId}`);
  if (!textarea) return;
  const notesText = textarea.value;
  try {
    const result = await requestJson(`/api/lectures/${lectureId}/notes`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes_text: notesText }),
    });
    // Update local state
    const lec = state.lectures.find((l) => l.id === lectureId);
    if (lec) lec.has_notes = result.has_notes;
    if (statusEl) {
      statusEl.textContent = "Saved!";
      setTimeout(() => { if (statusEl) statusEl.textContent = ""; }, 2000);
    }
    renderLectures();
    // Re-load notes into the textarea since render rebuilds DOM
    if (state.expandedNotes.has(lectureId)) {
      const newTextarea = document.getElementById(`notes-text-${lectureId}`);
      if (newTextarea) newTextarea.value = notesText;
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = "Save failed!";
    throw err;
  }
}

function handleError(error) {
  console.error(error);
  setStatus(error.message || "Something went wrong", "error");
}

// ---------------------------------------------------------------------------
// Init: check for active jobs on page load (recovery after restart)
// ---------------------------------------------------------------------------

async function recoverActiveJobs() {
  for (const lec of state.lectures) {
    if (lec.active_job && (lec.active_job.status === "running" || lec.active_job.status === "queued")) {
      // Resume polling this job
      pollJob(lec.active_job.job_id, lec.id, async (err, job) => {
        await loadBootstrap();
        if (err) {
          setStatus(`Job failed: ${err.message}`, "error");
        }
      });
    }
  }
}

attachEvents();
loadBootstrap()
  .then(() => {
    recoverActiveJobs();
    setStatus("Ready");
  })
  .catch(handleError);
