const API = "/api";

const state = {
  documents: [],   // {doc_id, name, source_type, num_chunks}
  activeDocId: null,
  lastSources: [],  // sources returned by the most recent /ask call
};

// ---------- DOM refs ----------
const uploadZone   = document.getElementById("uploadZone");
const fileInput    = document.getElementById("fileInput");
const browseBtn    = document.getElementById("browseBtn");
const urlForm      = document.getElementById("urlForm");
const urlInput     = document.getElementById("urlInput");
const shelfList    = document.getElementById("shelfList");

const emptyState   = document.getElementById("emptyState");
const docView      = document.getElementById("docView");
const docTitle     = document.getElementById("docTitle");
const docType      = document.getElementById("docType");
const summaryStyle = document.getElementById("summaryStyle");
const summarizeBtn = document.getElementById("summarizeBtn");
const summaryBlock = document.getElementById("summaryBlock");

const qaThread  = document.getElementById("qaThread");
const qaForm    = document.getElementById("qaForm");
const qaInput   = document.getElementById("qaInput");
const askBtn    = document.getElementById("askBtn");

const sourceList = document.getElementById("sourceList");
const toast       = document.getElementById("toast");

// ---------- helpers ----------
function showToast(message, isError = false) {
  toast.textContent = message;
  toast.hidden = false;
  toast.style.background = isError ? "#7A3B2E" : "#211F1C";
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => (toast.hidden = true), 4500);
}

async function apiCall(path, options = {}) {
  const res = await fetch(`${API}${path}`, options);
  let data;
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return data;
}

function setLoading(button, loading, loadingText, normalText) {
  button.disabled = loading;
  button.textContent = loading ? loadingText : normalText;
}

// ---------- shelf rendering ----------
function renderShelf() {
  if (state.documents.length === 0) {
    shelfList.innerHTML = `<li class="empty-note">Nothing here yet. Upload a document to begin.</li>`;
    return;
  }
  shelfList.innerHTML = "";
  state.documents.forEach((doc, i) => {
    const li = document.createElement("li");
    li.className = "shelf-item" + (doc.doc_id === state.activeDocId ? " active" : "");
    const icon =
  doc.source_type === "pdf" ? "📕" :
  doc.source_type === "docx" ? "📘" :
  doc.source_type === "url" ? "🌐" :
  "📄";

li.innerHTML = `
  <span class="shelf-item-index">${String(i + 1).padStart(2, "0")}</span>

  <span class="shelf-item-icon">${icon}</span>

  <span class="shelf-item-name" title="${escapeHtml(doc.name)}">
    ${escapeHtml(doc.name)}
  </span>
`;
    li.addEventListener("click", () => selectDocument(doc.doc_id));
    shelfList.appendChild(li);
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---------- selecting / opening a document ----------
function selectDocument(docId) {
  state.activeDocId = docId;
  const doc = state.documents.find((d) => d.doc_id === docId);
  if (!doc) return;

  emptyState.hidden = true;
  docView.hidden = false;

  docTitle.textContent = doc.name;
  docType.textContent = doc.source_type.toUpperCase() + " · " + doc.num_chunks + " chunks";

  summaryBlock.innerHTML = `<p class="placeholder-text">No summary yet — click <strong>Summarize</strong> above.</p>`;
  qaThread.innerHTML = "";
  sourceList.innerHTML = `<p class="placeholder-text">Citations from your answers will appear here — click any [n] to jump to it.</p>`;

  renderShelf();
}

// ---------- upload flow ----------
async function handleFiles(files) {
  for (const file of files) {
    const formData = new FormData();
    formData.append("file", file);
    try {
      showToast(`Reading "${file.name}"…`);
      const data = await apiCall("/upload/file", { method: "POST", body: formData });
      state.documents.push({
        doc_id: data.doc_id,
        name: data.name,
        source_type: guessTypeFromName(data.name),
        num_chunks: data.num_chunks,
      });
      renderShelf();
      selectDocument(data.doc_id);
      showToast(`"${file.name}" is ready.`);
    } catch (err) {
      showToast(err.message, true);
    }
  }
}

function guessTypeFromName(name) {
  const ext = name.split(".").pop().toLowerCase();
  if (ext === "pdf") return "pdf";
  if (["doc", "docx"].includes(ext)) return "docx";
  return "txt";
}

browseBtn.addEventListener("click", () => fileInput.click());
uploadZone.addEventListener("click", (e) => {
  if (e.target === browseBtn) return;
  fileInput.click();
});
fileInput.addEventListener("change", (e) => handleFiles(e.target.files));

["dragenter", "dragover"].forEach((evt) =>
  uploadZone.addEventListener(evt, (e) => {
    e.preventDefault();
    uploadZone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((evt) =>
  uploadZone.addEventListener(evt, (e) => {
    e.preventDefault();
    uploadZone.classList.remove("dragover");
  })
);
uploadZone.addEventListener("drop", (e) => {
  const files = e.dataTransfer.files;
  if (files.length) handleFiles(files);
});

urlForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;
  try {
    showToast(`Fetching page…`);
    const data = await apiCall("/upload/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    state.documents.push({
      doc_id: data.doc_id,
      name: data.name,
      source_type: "url",
      num_chunks: data.num_chunks,
    });
    urlInput.value = "";
    renderShelf();
    selectDocument(data.doc_id);
    showToast(`Page added.`);
  } catch (err) {
    showToast(err.message, true);
  }
});

// ---------- paste text ----------
const showPasteBtn = document.getElementById("showPasteBtn");
const pasteForm = document.getElementById("pasteForm");
const pasteInput = document.getElementById("pasteInput");

showPasteBtn.addEventListener("click", () => {
  pasteForm.hidden = !pasteForm.hidden;
  showPasteBtn.textContent = pasteForm.hidden ? "or paste text directly" : "hide paste box";
});

pasteForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = pasteInput.value.trim();
  if (!text) return;
  try {
    showToast("Processing pasted text…");
    const data = await apiCall("/upload/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, name: `Pasted text (${new Date().toLocaleTimeString()})` }),
    });
    state.documents.push({
      doc_id: data.doc_id,
      name: data.name,
      source_type: "text",
      num_chunks: data.num_chunks,
    });
    pasteInput.value = "";
    pasteForm.hidden = true;
    showPasteBtn.textContent = "or paste text directly";
    renderShelf();
    selectDocument(data.doc_id);
    showToast("Pasted text added.");
  } catch (err) {
    showToast(err.message, true);
  }
});

// ---------- summarize ----------
summarizeBtn.addEventListener("click", async () => {
  if (!state.activeDocId) return;
  setLoading(summarizeBtn, true, "Summarizing…", "Summarize");
  try {
    const data = await apiCall(`/documents/${state.activeDocId}/summarize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ style: summaryStyle.value }),
    });
    renderSummary(data.summary);
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setLoading(summarizeBtn, false, "Summarizing…", "Summarize");
  }
});

function renderSummary(text) {
  if (summaryStyle.value === "bullets") {
    const items = text
      .split("\n")
      .map((l) => l.replace(/^-\s*/, "").trim())
      .filter(Boolean);
    summaryBlock.innerHTML = `<ul>${items.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`;
  } else {
    summaryBlock.innerHTML = text
      .split("\n\n")
      .map((p) => `<p>${escapeHtml(p)}</p>`)
      .join("");
  }
}

// ---------- ask ----------
qaForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = qaInput.value.trim();
  if (!question || !state.activeDocId) return;

  qaInput.value = "";
  setLoading(askBtn, true, "Asking…", "Ask");

  try {
    const data = await apiCall(`/documents/${state.activeDocId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k: 5 }),
    });
    state.lastSources = data.sources;
    appendQaPair(question, data.answer);
    renderSources(data.sources);
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setLoading(askBtn, false, "Asking…", "Ask");
  }
});

function appendQaPair(question, answer) {
  const wrap = document.createElement("div");
  wrap.className = "qa-pair";

  const q = document.createElement("p");
  q.className = "qa-question";
  q.textContent = question;

  const a = document.createElement("p");
  a.className = "qa-answer";
  a.innerHTML = linkifyCitations(answer);

  wrap.appendChild(q);
  wrap.appendChild(a);
  qaThread.appendChild(wrap);
  wrap.scrollIntoView({ behavior: "smooth", block: "end" });
}

// turns "[1]" or "[1][3]" style citations into clickable tags
function linkifyCitations(text) {
  const escaped = escapeHtml(text);
  return escaped.replace(/\[(\d+)\]/g, (match, num) => {
    return `<a href="#source-${num}" class="cite-tag" data-cite="${num}">[${num}]</a>`;
  });
}

qaThread.addEventListener("click", (e) => {
  const tag = e.target.closest(".cite-tag");
  if (!tag) return;
  e.preventDefault();
  const num = tag.dataset.cite;
  const card = document.getElementById(`source-${num}`);
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.add("flash");
    setTimeout(() => card.classList.remove("flash"), 1400);
  }
});

// ---------- source panel ----------
function renderSources(sources) {
  if (!sources.length) {
    sourceList.innerHTML = `<p class="placeholder-text">No matching passages were found for that question.</p>`;
    return;
  }
  sourceList.innerHTML = sources
    .map(
      (s) => `
      <div class="source-card" id="source-${s.rank}">
        <div class="source-card-head">
          <span class="source-card-num">[${s.rank}]</span>
          <span>similarity ${s.score}</span>
        </div>
        <div>${escapeHtml(truncate(s.text, 320))}</div>
      </div>
    `
    )
    .join("");
}

function truncate(text, max) {
  return text.length > max ? text.slice(0, max).trim() + "…" : text;
}

// ---------- init: load any documents already on the server ----------
(async function init() {
  try {
    const data = await apiCall("/documents");
    state.documents = data.documents.map((d) => ({
      doc_id: d.doc_id,
      name: d.name,
      source_type: d.source_type,
      num_chunks: d.num_chunks,
    }));
    renderShelf();
  } catch {
    // backend not reachable yet — shelf just stays empty, no need to alarm the user
  }
})();
