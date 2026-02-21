/**
 * app.js — Outremer explorer + Human-in-the-Loop adjudication
 *
 * Decisions are persisted in localStorage under key STORAGE_KEY.
 * Format:  { "docId::person::outremer_id": { decision, comment, ts } }
 */

// ── Storage ────────────────────────────────────────────────────────────────

const STORAGE_KEY = "outremer_decisions_v1";

function loadDecisions() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveDecisions(d) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(d));
}

function decisionKey(docId, person, outremer_id) {
  return `${docId}::${person}::${outremer_id}`;
}

// ── DOM helpers ────────────────────────────────────────────────────────────

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

function badge(text, cls) {
  return `<span class="badge ${cls}">${esc(text)}</span>`;
}

// ── Fetch ──────────────────────────────────────────────────────────────────

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Fetch failed: ${url} (${res.status})`);
  return res.json();
}

// ── State ──────────────────────────────────────────────────────────────────

let currentDoc = null;   // full doc JSON
let currentFilter = "all";

// ── Stats ──────────────────────────────────────────────────────────────────

function updateStats() {
  if (!currentDoc) return;
  const decisions = loadDecisions();
  const links = currentDoc.links || [];
  const docId = currentDoc.doc_id;

  let total = 0, reviewed = 0, accepted = 0, rejected = 0, flagged = 0;

  for (const link of links) {
    for (const c of link.candidates || []) {
      total++;
      const k = decisionKey(docId, link.person, c.outremer_id);
      const d = decisions[k];
      if (d) {
        reviewed++;
        if (d.decision === "accept") accepted++;
        else if (d.decision === "reject") rejected++;
        else if (d.decision === "flag") flagged++;
      }
    }
    // also count no_match items
    if (!link.candidates || link.candidates.length === 0) {
      total++;
      const k = decisionKey(docId, link.person, "__none__");
      if (decisions[k]) reviewed++;
    }
  }

  document.getElementById("statReviewed").textContent =
    `${reviewed} / ${total} reviewed`;
  document.getElementById("statAcceptedN").textContent = accepted;
  document.getElementById("statRejectedN").textContent = rejected;
  document.getElementById("statFlaggedN").textContent = flagged;

  document.getElementById("statsBar").classList.remove("hidden");
  document.getElementById("filterBar").classList.remove("hidden");
}

// ── Filter ─────────────────────────────────────────────────────────────────

function setFilter(f) {
  currentFilter = f;
  document.querySelectorAll(".filter-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.filter === f);
  });
  renderLinks(currentDoc);
}

function linkMatchesFilter(link, decisions, docId) {
  if (currentFilter === "all") return true;
  if (currentFilter === "no_match") return link.status === "no_match";

  const candidates = link.candidates || [];
  for (const c of candidates) {
    const k = decisionKey(docId, link.person, c.outremer_id);
    const d = decisions[k];
    if (currentFilter === "unreviewed" && !d) return true;
    if (currentFilter === "accepted" && d?.decision === "accept") return true;
    if (currentFilter === "rejected" && d?.decision === "reject") return true;
    if (currentFilter === "flagged" && d?.decision === "flag") return true;
  }
  if (currentFilter === "unreviewed" && candidates.length === 0) return true;
  return false;
}

// ── Persons section ────────────────────────────────────────────────────────

function renderPersons(doc) {
  const container = document.getElementById("persons");
  container.innerHTML = "";
  const persons = doc.persons || [];

  document.getElementById("personCount").textContent = persons.length;

  if (!persons.length) {
    container.textContent = "No persons extracted.";
    return;
  }

  for (const p of persons) {
    const card = el("div", "card");

    const confPct = Math.round((p.confidence ?? 0) * 100);
    const confCls = confPct >= 70 ? "conf-high" : confPct >= 40 ? "conf-med" : "conf-low";

    let pills = "";
    if (p.group)    pills += badge("group", "pill-group");
    if (p.title)    pills += badge(p.title, "pill-neutral");
    if (p.toponym)  pills += badge("📍 " + p.toponym, "pill-neutral");
    if (p.role)     pills += badge(p.role, "pill-neutral");
    if (p.gender && p.gender !== "unknown") pills += badge(p.gender, "pill-neutral");

    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">${esc(p.name)}</span>
        <span class="conf-badge ${confCls}">${confPct}%</span>
      </div>
      ${pills ? `<div class="pills">${pills}</div>` : ""}
      ${p.context ? `<div class="context">"…${esc(p.context)}…"</div>` : ""}
    `;
    container.appendChild(card);
  }
}

// ── Links + adjudication ───────────────────────────────────────────────────

function renderCandidateRow(link, candidate, docId, decisions) {
  const k = decisionKey(docId, link.person, candidate.outremer_id);
  const stored = decisions[k];
  const decision = stored?.decision || null;
  const comment = stored?.comment || "";

  const scorePct = Math.round((candidate.score ?? 0) * 100);
  const statusCls = candidate.score >= 0.9 ? "status-high"
                  : candidate.score >= 0.75 ? "status-med"
                  : "status-low";

  const row = el("div", "candidate-row");
  row.dataset.key = k;
  if (decision) row.dataset.decision = decision;

  row.innerHTML = `
    <div class="candidate-info">
      <span class="candidate-name">${esc(candidate.outremer_name)}</span>
      <span class="score-badge ${statusCls}">${scorePct}%</span>
      <span class="match-type">${esc(candidate.match_type)}</span>
      <span class="candidate-type muted">${esc(candidate.type)}</span>
      <span class="outremer-id muted">${esc(candidate.outremer_id)}</span>
    </div>
    <div class="adjudication">
      <button class="adj-btn accept ${decision === "accept" ? "active" : ""}"
              data-action="accept" data-key="${esc(k)}"
              title="Accept this link">✅</button>
      <button class="adj-btn reject ${decision === "reject" ? "active" : ""}"
              data-action="reject" data-key="${esc(k)}"
              title="Reject this link">❌</button>
      <button class="adj-btn flag ${decision === "flag" ? "active" : ""}"
              data-action="flag" data-key="${esc(k)}"
              title="Flag for review">🚩</button>
      <input  class="comment-input" type="text" placeholder="Comment…"
              data-key="${esc(k)}" value="${esc(comment)}" />
    </div>
  `;

  // Button handlers
  row.querySelectorAll(".adj-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.action;
      const key = btn.dataset.key;
      const d = loadDecisions();
      const prev = d[key]?.decision;

      if (prev === action) {
        // Toggle off
        delete d[key];
        btn.classList.remove("active");
        row.removeAttribute("data-decision");
      } else {
        d[key] = { decision: action, comment: d[key]?.comment || "", ts: new Date().toISOString() };
        row.querySelectorAll(".adj-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        row.dataset.decision = action;
      }
      saveDecisions(d);
      updateStats();
    });
  });

  // Comment handler
  const commentInput = row.querySelector(".comment-input");
  commentInput.addEventListener("change", () => {
    const key = commentInput.dataset.key;
    const d = loadDecisions();
    if (!d[key]) d[key] = { decision: null, comment: "", ts: new Date().toISOString() };
    d[key].comment = commentInput.value.trim();
    d[key].ts = new Date().toISOString();
    saveDecisions(d);
  });

  return row;
}

function renderLinks(doc) {
  if (!doc) return;
  const container = document.getElementById("links");
  container.innerHTML = "";
  const links = doc.links || [];
  const docId = doc.doc_id;
  const decisions = loadDecisions();

  const visible = links.filter(l => linkMatchesFilter(l, decisions, docId));

  if (!visible.length) {
    container.textContent = currentFilter === "all"
      ? "No links found."
      : `No ${currentFilter} links.`;
    return;
  }

  for (const link of visible) {
    const card = el("div", "card link-card");
    card.dataset.status = link.status;

    const statusLabel = {
      high: badge("high confidence", "status-high"),
      medium: badge("medium confidence", "status-med"),
      low: badge("low confidence", "status-low"),
      no_match: badge("no match", "status-none"),
    }[link.status] || "";

    const groupIcon = link.person_group ? " 👥" : "";

    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">${esc(link.person)}${groupIcon}</span>
        ${statusLabel}
        <span class="muted" style="font-size:.8em">${link.candidates?.length || 0} candidate(s)</span>
      </div>
    `;

    if (!link.candidates || link.candidates.length === 0) {
      card.innerHTML += `<div class="no-match-note muted">No authority match found (score below threshold).</div>`;
    } else {
      const candidatesEl = el("div", "candidates");
      for (const c of link.candidates) {
        candidatesEl.appendChild(renderCandidateRow(link, c, docId, decisions));
      }
      card.appendChild(candidatesEl);
    }

    container.appendChild(card);
  }
}

// ── Document loading ───────────────────────────────────────────────────────

async function loadDoc(filename) {
  const doc = await fetchJson(`./data/${filename}`);
  currentDoc = doc;

  // Metadata panel
  const metaEl = document.getElementById("docMeta");
  metaEl.textContent = JSON.stringify({
    doc_id: doc.doc_id,
    source_file: doc.source_file,
    input_type: doc.input_type,
    extraction_mode: doc.extraction_mode || "unknown",
    metadata: doc.metadata,
  }, null, 2);

  renderPersons(doc);
  renderLinks(doc);
  updateStats();

  // Raw JSON (hidden by default)
  document.getElementById("raw").textContent = JSON.stringify(doc, null, 2);
}

async function loadIndex() {
  const idx = await fetchJson("./index.json");

  const sel = document.getElementById("docSelect");
  sel.innerHTML = "";
  for (const name of (idx.documents || [])) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  }

  if ((idx.documents || []).length) {
    await loadDoc(idx.documents[0]);
  } else {
    document.getElementById("docMeta").textContent =
      "No documents found. Add .txt/.pdf files to data/raw and run the pipeline.";
  }
}

// ── Export ─────────────────────────────────────────────────────────────────

function exportDecisions() {
  const d = loadDecisions();
  const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `outremer-decisions-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ── Init ───────────────────────────────────────────────────────────────────

document.getElementById("loadBtn").addEventListener("click", () => {
  loadDoc(document.getElementById("docSelect").value);
});

document.getElementById("exportBtn").addEventListener("click", exportDecisions);

document.getElementById("toggleRaw").addEventListener("click", function () {
  const raw = document.getElementById("raw");
  const hidden = raw.classList.toggle("hidden");
  this.textContent = hidden ? "show" : "hide";
});

document.querySelectorAll(".filter-btn").forEach(btn => {
  btn.addEventListener("click", () => setFilter(btn.dataset.filter));
});

loadIndex().catch(err => {
  document.getElementById("docMeta").textContent = String(err);
});
