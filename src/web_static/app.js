const state = {
  courses: [],
  lectures: [],
  activeLectureId: null,
  mediaRecorder: null,
  mediaStream: null,
  audioChunks: [],
  startedAt: null,
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
};

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
  if (seconds === null || seconds === undefined) {
    return "duration unknown";
  }
  const totalSeconds = Math.round(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const remainder = totalSeconds % 60;
  return `${minutes}m ${remainder}s`;
}

function formatUnitLabel(course, unit) {
  return `${course.name} / ${unit.name}`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `Request failed with ${response.status}`);
  }
  return payload;
}

async function loadBootstrap() {
  const payload = await requestJson("/api/bootstrap");
  state.courses = payload.courses;
  state.lectures = payload.lectures;
  render();
}

function renderCourseOptions() {
  const courseOptions = state.courses
    .map((course) => `<option value="${course.id}">${escapeHtml(course.name)}</option>`)
    .join("");

  elements.unitCourse.innerHTML = courseOptions || '<option value="">Add a course first</option>';

  const unitOptions = state.courses
    .flatMap((course) =>
      course.units.map(
        (unit) =>
          `<option value="${unit.id}">${escapeHtml(formatUnitLabel(course, unit))}</option>`,
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
      (course) => `
        <article class="course-card">
          <h3>${escapeHtml(course.name)}</h3>
          <div class="unit-chip-row">
            ${
              course.units.length
                ? course.units
                    .map(
                      (unit) =>
                        `<span class="unit-chip">${escapeHtml(unit.name)} <strong>#${unit.sort_order}</strong></span>`,
                    )
                    .join("")
                : '<span class="unit-chip">No units yet</span>'
            }
          </div>
        </article>
      `,
    )
    .join("");
}

function renderLectures() {
  if (!state.lectures.length) {
    elements.lectureList.innerHTML =
      '<div class="empty-state">No lectures saved yet. Record in the browser or upload an audio file.</div>';
    return;
  }

  elements.lectureList.innerHTML = state.lectures
    .map(
      (lecture) => `
        <article class="lecture-card">
          <div>
            <h3>${escapeHtml(lecture.title)}</h3>
            <p>${escapeHtml(lecture.course_name)} / ${escapeHtml(lecture.unit_name)}</p>
          </div>
          <div class="lecture-meta">
            <span class="lecture-chip">${escapeHtml(lecture.recorded_at)}</span>
            <span class="lecture-chip">${escapeHtml(formatDuration(lecture.duration_seconds))}</span>
            <span class="lecture-chip">${lecture.segment_count} transcript segments</span>
            <span class="lecture-chip">${lecture.has_recording ? "audio saved" : "audio missing"}</span>
          </div>
          <div class="lecture-actions">
            <button type="button" data-action="transcribe" data-lecture-id="${lecture.id}">Transcribe</button>
            <button type="button" class="button-muted" data-action="segments" data-lecture-id="${lecture.id}">
              View transcript
            </button>
          </div>
        </article>
      `,
    )
    .join("");
}

function render() {
  renderCourseOptions();
  renderCourses();
  renderLectures();
}

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

function preferredMimeType() {
  if (!window.MediaRecorder) {
    return null;
  }
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find((value) => MediaRecorder.isTypeSupported(value)) || "";
}

function fileExtensionForMimeType(mimeType) {
  if (mimeType.includes("mp4")) {
    return ".m4a";
  }
  if (mimeType.includes("ogg")) {
    return ".ogg";
  }
  if (mimeType.includes("wav")) {
    return ".wav";
  }
  return ".webm";
}

async function startRecording() {
  if (!elements.recordingUnit.value) {
    throw new Error("Add a unit before recording.");
  }
  if (!window.MediaRecorder) {
    throw new Error("This browser does not support in-browser audio recording.");
  }

  state.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  state.audioChunks = [];
  state.startedAt = performance.now();
  const mimeType = preferredMimeType();
  state.mediaRecorder = mimeType
    ? new MediaRecorder(state.mediaStream, { mimeType })
    : new MediaRecorder(state.mediaStream);

  state.mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) {
      state.audioChunks.push(event.data);
    }
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
  if (!state.mediaRecorder) {
    return;
  }

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
  state.mediaStream.getTracks().forEach((track) => track.stop());
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
  if (durationSeconds !== null) {
    formData.append("duration_seconds", String(durationSeconds));
  }
  formData.append("audio", file, file.name);

  await requestJson("/api/lectures/upload", {
    method: "POST",
    body: formData,
  });

  elements.recordingTitle.value = "";
  elements.uploadForm.reset();
  await loadBootstrap();
  setStatus("Lecture saved");
}

async function handleUpload(event) {
  event.preventDefault();
  const [file] = elements.uploadAudio.files;
  if (!file) {
    throw new Error("Choose an audio file first.");
  }
  setStatus("Uploading audio...", "busy");
  await uploadAudioFile(file);
}

async function transcribeLecture(lectureId) {
  setStatus(`Transcribing lecture ${lectureId}...`, "busy");
  await requestJson(`/api/lectures/${lectureId}/transcribe`, { method: "POST" });
  await loadBootstrap();
  await showTranscript(lectureId);
  setStatus("Transcription complete");
}

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
      (segment) => `
        <article class="segment-card">
          <div class="segment-time">${segment.start_time.toFixed(1)}s -> ${segment.end_time.toFixed(1)}s</div>
          <p>${escapeHtml(segment.text)}</p>
        </article>
      `,
    )
    .join("");
  setStatus(`Loaded ${payload.segments.length} segments`);
}

function attachEvents() {
  elements.courseForm.addEventListener("submit", (event) => {
    createCourse(event).catch(handleError);
  });
  elements.unitForm.addEventListener("submit", (event) => {
    createUnit(event).catch(handleError);
  });
  elements.recordStart.addEventListener("click", () => {
    startRecording().catch(handleError);
  });
  elements.recordStop.addEventListener("click", () => {
    stopRecording().catch(handleError);
  });
  elements.uploadForm.addEventListener("submit", (event) => {
    handleUpload(event).catch(handleError);
  });
  elements.lectureList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const action = target.dataset.action;
    const lectureId = Number(target.dataset.lectureId);
    if (!action || !lectureId) {
      return;
    }
    if (action === "transcribe") {
      transcribeLecture(lectureId).catch(handleError);
    }
    if (action === "segments") {
      showTranscript(lectureId).catch(handleError);
    }
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
