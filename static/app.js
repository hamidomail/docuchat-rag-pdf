const $ = (s) => document.querySelector(s);
const state = { docs: [], excluded: new Set(), history: [], busy: false, turns: [] };

const SUGGESTIONS = {
  handbook: [
    "How many days of paid vacation do new employees get?",
    "Can I work remotely from another country?",
  ],
  thermostat: [
    "What does error code E4 mean and how do I fix it?",
    "How do I reset the thermostat to factory settings?",
  ],
};
const GENERIC = ["Summarize the key points of these documents.", "What deadlines or dates are mentioned?"];
const STOP = new Set("the and for with that this what how does from are was can about into your have will which when where who why there their them then than also just only very any all each such into over under".split(" "));

const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------------- library ---------------- */
async function loadHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    $("#engine").innerHTML = `Model <b>${esc(h.model)}</b><br>Retrieval <b>${esc(h.retrieval)}</b>`;
  } catch { $("#engine").textContent = "Server unreachable."; }
}

async function loadDocs() {
  state.docs = await (await fetch("/api/documents")).json();
  const list = $("#docs");
  list.innerHTML = "";
  for (const d of state.docs) {
    const li = document.createElement("li");
    li.className = "doc";
    li.innerHTML = `
      <input type="checkbox" ${state.excluded.has(d.id) ? "" : "checked"} aria-label="Use ${esc(d.title)} in answers">
      <div><div class="doc-title">${esc(d.title)}</div>
      <div class="doc-meta">${d.pages} page${d.pages > 1 ? "s" : ""}, ${d.chunks} passages</div></div>
      <button type="button" aria-label="Remove ${esc(d.title)}">Remove</button>`;
    li.querySelector("input").addEventListener("change", (e) => {
      e.target.checked ? state.excluded.delete(d.id) : state.excluded.add(d.id);
    });
    li.querySelector("button").addEventListener("click", async () => {
      if (!confirm(`Remove “${d.title}” from the library?`)) return;
      await fetch(`/api/documents/${d.id}`, { method: "DELETE" });
      state.excluded.delete(d.id);
      loadDocs(); loadHealth();
    });
    list.append(li);
  }
  $("#doc-count").textContent = state.docs.length ? `${state.docs.length} file${state.docs.length > 1 ? "s" : ""}` : "";
  $("#lib-hint").hidden = state.docs.length < 2;
  renderSuggestions();
}

function renderSuggestions() {
  const box = $("#suggestions");
  if (!box) return;
  let qs = [];
  const names = state.docs.map((d) => `${d.name} ${d.title}`.toLowerCase()).join(" ");
  for (const [key, list] of Object.entries(SUGGESTIONS)) if (names.includes(key)) qs.push(...list);
  if (!state.docs.length) { box.innerHTML = `<p>Start by adding a PDF on the left.</p>`; return; }
  if (!qs.length) qs = GENERIC;
  box.innerHTML = "";
  for (const q of qs.slice(0, 4)) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = q;
    b.addEventListener("click", () => ask(q));
    box.append(b);
  }
}

async function upload(files) {
  const status = $("#upload-status");
  status.classList.remove("error");
  for (const file of files) {
    status.textContent = `Reading ${file.name}…`;
    const body = new FormData(); body.append("file", file);
    const res = await fetch("/api/documents", { method: "POST", body });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Upload failed." }));
      status.textContent = err.detail; status.classList.add("error");
      continue;
    }
    const doc = await res.json();
    status.textContent = `Added ${doc.title}: ${doc.pages} pages, ${doc.chunks} passages.`;
  }
  await loadDocs(); loadHealth();
}

const drop = $("#drop");
$("#file").addEventListener("change", (e) => { upload([...e.target.files]); e.target.value = ""; });
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#file").click(); } });
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => upload([...e.dataTransfer.files].filter((f) => f.name.toLowerCase().endsWith(".pdf"))));

/* ---------------- rendering ---------------- */
function inline(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|\W)_(.+?)_(?=\W|$)/g, "$1<em>$2</em>")
    .replace(/\[(\d{1,2})\]/g, '<button type="button" class="cite" data-n="$1" aria-label="Show passage $1">$1</button>');
}

function markdown(text) {
  const out = []; let list = null;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = line.match(/^[-*•]\s+(.*)/);
    const numbered = line.match(/^\d+[.)]\s+(.*)/);
    if (bullet || numbered) {
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tag !== tag) { if (list) out.push(`</${list.tag}>`); out.push(`<${tag}>`); list = { tag }; }
      out.push(`<li>${inline((bullet || numbered)[1])}</li>`);
      continue;
    }
    if (list) { out.push(`</${list.tag}>`); list = null; }
    if (line) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push(`</${list.tag}>`);
  return out.join("");
}

function highlight(text, question) {
  const terms = [...new Set((question.toLowerCase().match(/[\p{L}\p{N}]+/gu) || []).filter((w) => w.length > 3 && !STOP.has(w)))];
  let html = esc(text);
  if (!terms.length) return html;
  const re = new RegExp(`\\b(${terms.map((t) => t.replace(/s$/, "")).join("|")})\\w*`, "giu");
  return html.replace(re, "<mark>$&</mark>");
}

const docTitle = (s) => state.docs.find((d) => d.id === s.doc_id)?.title || s.doc_name;

function renderSources(turn, focusN) {
  const list = $("#sources");
  list.innerHTML = "";
  $("#passages-empty").hidden = turn.sources.length > 0;
  if (!turn.sources.length) $("#passages-empty").textContent = "No passage matched this question.";
  for (const s of turn.sources) {
    const li = document.createElement("li");
    li.className = "source"; li.id = `src-${s.n}`;
    li.innerHTML = `
      <header><span class="num">${s.n}</span><span class="where" title="${esc(s.doc_name)}">${esc(docTitle(s))}</span><span class="page">page ${s.page}</span></header>
      <blockquote>${highlight(s.text, turn.question)}</blockquote>
      <button type="button" class="more">Show full passage</button>`;
    li.querySelector(".more").addEventListener("click", (e) => {
      li.classList.toggle("open");
      e.target.textContent = li.classList.contains("open") ? "Show less" : "Show full passage";
    });
    list.append(li);
  }
  if (focusN) focusSource(focusN);
}

function focusSource(n) {
  document.querySelectorAll(".source.focus").forEach((el) => el.classList.remove("focus"));
  const el = document.getElementById(`src-${n}`);
  if (el) { el.classList.add("focus", "open"); el.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
}

$("#thread").addEventListener("click", (e) => {
  const btn = e.target.closest(".cite");
  if (!btn) return;
  const turn = state.turns[Number(btn.closest(".turn").dataset.turn)];
  renderSources(turn, Number(btn.dataset.n));
});

/* ---------------- chat ---------------- */
async function ask(question) {
  question = question.trim();
  if (!question || state.busy) return;
  state.busy = true; $("#send").disabled = true;
  $("#empty")?.remove();

  const idx = state.turns.length;
  const turn = { question, sources: [], answer: "" };
  state.turns.push(turn);

  const thread = $("#thread");
  const userEl = document.createElement("div");
  userEl.className = "turn user"; userEl.innerHTML = `<p>${esc(question)}</p>`;
  const botEl = document.createElement("div");
  botEl.className = "turn bot"; botEl.dataset.turn = idx;
  botEl.innerHTML = `<div class="answer cursor"></div>`;
  thread.append(userEl, botEl);
  userEl.scrollIntoView({ behavior: "smooth", block: "start" });
  const answerEl = botEl.querySelector(".answer");

  const docIds = state.excluded.size ? state.docs.filter((d) => !state.excluded.has(d.id)).map((d) => d.id) : null;
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history: state.history.slice(-6), doc_ids: docIds }),
    });
    if (!res.ok) throw new Error(`The server returned ${res.status}.`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut); buffer = buffer.slice(cut + 2);
        const data = block.split("\n").find((l) => l.startsWith("data:"));
        if (!data) continue;
        const ev = JSON.parse(data.slice(5));
        if (ev.type === "sources") { turn.sources = ev.sources; renderSources(turn); }
        else if (ev.type === "token") { turn.answer += ev.text; answerEl.innerHTML = markdown(turn.answer); }
        else if (ev.type === "error") { answerEl.classList.add("error"); answerEl.textContent = `The language model failed: ${ev.message}`; }
      }
    }
  } catch (err) {
    answerEl.classList.add("error");
    answerEl.textContent = `${err.message} Check that the server is running and try again.`;
  }
  answerEl.classList.remove("cursor");
  if (turn.answer) state.history.push({ role: "user", content: question }, { role: "assistant", content: turn.answer });
  state.busy = false; $("#send").disabled = false;
}

const q = $("#question");
$("#composer").addEventListener("submit", (e) => { e.preventDefault(); const v = q.value; q.value = ""; q.style.height = ""; ask(v); });
q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); } });
q.addEventListener("input", () => { q.style.height = "auto"; q.style.height = `${q.scrollHeight}px`; });

loadHealth();
loadDocs();
