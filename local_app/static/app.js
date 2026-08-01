const form = document.querySelector("#upload-form");
const fileInput = document.querySelector("#pdf-file");
const dropZone = document.querySelector("#drop-zone");
const selectedFile = document.querySelector("#selected-file");
const uploadError = document.querySelector("#upload-error");
const jobsTable = document.querySelector("#jobs-table");
const jobsBody = document.querySelector("#jobs-body");
const jobsEmpty = document.querySelector("#jobs-empty");
const refreshButton = document.querySelector("#refresh-jobs");

let polling = null;

function setError(message) {
  uploadError.textContent = message || "";
  uploadError.hidden = !message;
}

function formatBytes(value) {
  if (!Number.isFinite(value)) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function statusClass(status) {
  return `status-pill status-${status}`;
}

function progressText(job) {
  if (job.progress_total > 0) {
    return `${job.progress_done || 0} / ${job.progress_total}`;
  }
  if (job.pages) {
    return `${job.pages} pages`;
  }
  return "Waiting";
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = "Request failed.";
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return response.json();
}

async function loadJobs() {
  const data = await requestJson("/api/jobs");
  renderJobs(data.jobs || []);
}

function renderJobs(jobs) {
  jobsBody.replaceChildren();
  jobsEmpty.hidden = jobs.length > 0;
  jobsTable.hidden = jobs.length === 0;

  for (const job of jobs) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>
        <p class="job-title"></p>
        <p class="job-meta"></p>
      </td>
      <td>
        <span class="${statusClass(job.status)}"></span>
        <p class="job-message"></p>
      </td>
      <td><p class="progress"></p></td>
      <td><div class="actions"></div></td>
    `;

    row.querySelector(".job-title").textContent = job.title || job.source_filename;
    row.querySelector(".job-meta").textContent = `${job.source_filename} · ${formatBytes(job.size_bytes)}`;
    row.querySelector(".status-pill").textContent = job.status;
    row.querySelector(".job-message").textContent = `${job.stage}${job.message ? ` · ${job.message}` : ""}`;
    row.querySelector(".progress").textContent = progressText(job);

    const actions = row.querySelector(".actions");
    if (job.has_epub) {
      const download = document.createElement("a");
      download.href = `/api/jobs/${job.id}/download`;
      download.textContent = "Download";
      actions.append(download);
    }
    if (job.status === "queued" || job.status === "running") {
      actions.append(actionButton("Cancel", "secondary", () => postAction(job.id, "cancel")));
    }
    if (job.status === "failed" || job.status === "canceled") {
      actions.append(actionButton("Retry", "", () => postAction(job.id, "retry")));
    }
    actions.append(actionButton("Delete", "danger", () => deleteJob(job.id)));
    jobsBody.append(row);
  }
}

function actionButton(label, className, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  if (className) button.className = className;
  button.addEventListener("click", handler);
  return button;
}

async function postAction(jobId, action) {
  await requestJson(`/api/jobs/${jobId}/${action}`, { method: "POST" });
  await loadJobs();
}

async function deleteJob(jobId) {
  if (!confirm("Delete this job and its local files?")) return;
  await requestJson(`/api/jobs/${jobId}`, { method: "DELETE" });
  await loadJobs();
}

if (fileInput) {
  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    selectedFile.textContent = file ? `${file.name} · ${formatBytes(file.size)}` : "Drop a file here or select one.";
    if (file && !document.querySelector("#title").value) {
      document.querySelector("#title").value = file.name.replace(/\.pdf$/i, "");
    }
  });
}

if (dropZone) {
  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragging");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragging");
    });
  });
  dropZone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (!file) return;
    fileInput.files = event.dataTransfer.files;
    fileInput.dispatchEvent(new Event("change"));
  });
}

if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setError("");
    const submit = form.querySelector("button[type='submit']");
    submit.disabled = true;
    try {
      const formData = new FormData(form);
      await requestJson("/api/jobs", { method: "POST", body: formData });
      form.reset();
      selectedFile.textContent = "Drop a file here or select one.";
      await loadJobs();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      submit.disabled = false;
    }
  });
}

refreshButton?.addEventListener("click", () => loadJobs().catch((error) => setError(error.message)));

loadJobs().catch((error) => setError(error.message));
polling = setInterval(() => loadJobs().catch(() => {}), 2500);
window.addEventListener("beforeunload", () => {
  if (polling) clearInterval(polling);
});
