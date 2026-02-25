/**
 * app.js — Outremer explorer + Human-in-the-Loop adjudication
 *
 * Local decisions  → localStorage (outremer_decisions_v1)
 * Server decisions → POST/DELETE /webhook/outremer-decision  (central store, no login)
 *                    GET  /webhook/outremer-decisions/{doc_id} (community aggregate)
 *
 * An anonymous but stable client_id is generated per browser and stored in
 * localStorage so a user's votes can be upserted without a login system.
 */

// ── Config ─────────────────────────────────────────────────────────────────

const API_BASE    = "http://194.13.80.183/webhook";
const STORAGE_KEY = "outremer_decisions_v1";
const CLIENT_KEY  = "outremer_client_id";

// ── Client ID (anonymous, stable per browser) ──────────────────────────────

function getClientId() {
  let id = localStorage.getItem(CLIENT_KEY);
  if (!id) {
    id = "anon-" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    localStorage.setItem(CLIENT_KEY, id);
  }
  return id;
}

const CLIENT_ID = getClientId();

// ── Scholar display name ────────────────────────────────────────────────────

const SCHOLAR_NAME_KEY = "outremer_scholar_name";
const NAME_PROMPTED_KEY = "outremer_name_prompted";

function getScholarName() {
  return localStorage.getItem(SCHOLAR_NAME_KEY) || "";
}

function setScholarName(name) {
  localStorage.setItem(SCHOLAR_NAME_KEY, name.trim());
  localStorage.setItem(NAME_PROMPTED_KEY, "1");
  updateScholarBadge();
}

function updateScholarBadge() {
  const name = getScholarName();
  const el = document.getElementById("scholarNameDisplay");
  if (el) el.textContent = name || "Anonymous";
}

function initScholarName() {
  // Scholar name entry is handled by inline script in explorer.html.
  // This function is a no-op now but kept for any future use.
}

// ── Entity-level flag toggle ────────────────────────────────────────────────

function toggleEntityFlag(flagType, person, docId) {
  const key = decisionKey(docId, person, `_${flagType}`);
  const d   = loadDecisions();

  if (d[key]?.decision === flagType) {
    // Toggle off — update local state first, then fire-and-forget server call
    delete d[key];
    saveDecisions(d);
    fetch(`${API_BASE}/outremer-decision`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: docId, person, outremer_id: `_${flagType}`,
                             client_id: CLIENT_ID }),
    }).catch(() => {});
  } else {
    // Toggle on — update local state first, then fire-and-forget server call
    d[key] = { decision: flagType, ts: Date.now() };
    saveDecisions(d);
    syncDecisionToServer(docId, person, `_${flagType}`, flagType).catch(() => {});
  }

  // Always re-render immediately from local state (no await)
  renderLinks(currentDoc);
  updateStats();
}

// ── Local decision store ───────────────────────────────────────────────────

function loadDecisions() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); }
  catch { return {}; }
}
function saveDecisions(d) { localStorage.setItem(STORAGE_KEY, JSON.stringify(d)); }

function decisionKey(docId, person, outremer_id) {
  return `${docId}::${person}::${outremer_id}`;
}

// ── Authority file cache ───────────────────────────────────────────────────

let authorityCache = {};   // outremer_id → { bio, roles, places, etc. }

async function fetchAuthorityFile() {
  try {
    const auth = await fetchJson("./data/authority.json");
    for (const person of auth) {
      const id = person.outremer_id || `AUTH:${person.id}`;
      authorityCache[id] = person;
    }
  } catch {
    authorityCache = {};
  }
}

function loadAuthorityData(outremer_id) {
  return authorityCache[outremer_id] || {};
}

// ── Wikidata matches (loaded from site/data/wikidata_matches.json) ─────────

let wikidataMatches = {};   // doc_id → { normalised_name → { person, candidates } }

async function fetchWikidataMatches(docId) {
  try {
    const all = await fetchJson("./data/wikidata_matches.json");
    wikidataMatches = all[docId] || {};
  } catch {
    wikidataMatches = {};
  }
}

function normalise(s) {
  return s.toLowerCase().replace(/[^\w\s]/g,"").replace(/\s+/g," ").trim();
}

function wikidataCandidatesFor(personName) {
  const key = normalise(personName);
  return wikidataMatches[key]?.candidates || [];
}

// ── Context comparison helper ──────────────────────────────────────────────

function buildContextComparison(link, candidate, authData) {
  const parts = [];
  
  // Extract contextual info from the link (extracted person)
  const extractedInfo = {
    date: link.date_mention || link.context_date || null,
    place: link.place_mention || link.toponym || null,
    role: link.role || link.title || null,
  };
  
  // Extract contextual info from authority/Wikidata candidate
  const candidateInfo = {
    date: authData?.birth?.date || authData?.death?.date || authData?.floruit?.start || null,
    place: authData?.birth?.place || authData?.title_seat?.label || null,
    role: authData?.roles?.[0]?.label || authData?.title || null,
  };
  
  // Build comparison rows
  const comparisons = [
    { label: "📅 Date", extracted: extractedInfo.date, candidate: candidateInfo.date },
    { label: "📍 Place", extracted: extractedInfo.place, candidate: candidateInfo.place },
    { label: "👤 Role/Title", extracted: extractedInfo.role, candidate: candidateInfo.role },
  ];
  
  let html = '<div class="context-comparison">';
  for (const comp of comparisons) {
    if (comp.extracted || comp.candidate) {
      const match = comp.extracted && comp.candidate && 
                    normalizeForComparison(comp.extracted) === normalizeForComparison(comp.candidate);
      const matchClass = match ? "context-match" : comp.extracted && comp.candidate ? "context-mismatch" : "context-partial";
      
      html += `<div class="context-row ${matchClass}">`;
      html += `<span class="context-label">${comp.label}</span>`;
      if (comp.extracted) {
        html += `<span class="context-extracted" title="Extracted from text">${esc(comp.extracted)}</span>`;
      } else {
        html += `<span class="context-extracted context-empty">—</span>`;
      }
      html += `<span class="context-arrow">→</span>`;
      if (comp.candidate) {
        html += `<span class="context-candidate" title="From authority file">${esc(comp.candidate)}</span>`;
      } else {
        html += `<span class="context-candidate context-empty">—</span>`;
      }
      html += `</div>`;
    }
  }
  html += '</div>';
  
  return html;
}

function normalizeForComparison(s) {
  if (!s) return "";
  return String(s).toLowerCase().replace(/[^\w\s]/g, "").trim();
}

// ── Wikidata context comparison ────────────────────────────────────────────

function buildWikidataContext(link, wdCandidate) {
  const parts = [];
  
  // Extract contextual info from the link (extracted person)
  const extractedInfo = {
    date: link.date_mention || link.context_date || null,
    place: link.place_mention || link.toponym || null,
    role: link.role || link.title || null,
  };
  
  // Extract contextual info from Wikidata candidate
  const wdInfo = {
    date: wdCandidate.birth_date || wdCandidate.death_date || wdCandidate.floruit || null,
    place: wdCandidate.birth_place || wdCandidate.location || null,
    role: wdCandidate.occupation || wdCandidate.title || null,
  };
  
  // Build comparison rows
  const comparisons = [
    { label: "📅 Date", extracted: extractedInfo.date, candidate: wdInfo.date },
    { label: "📍 Place", extracted: extractedInfo.place, candidate: wdInfo.place },
    { label: "👤 Role/Title", extracted: extractedInfo.role, candidate: wdInfo.role },
  ];
  
  let html = '<div class="context-comparison wd-context">';
  for (const comp of comparisons) {
    if (comp.extracted || comp.candidate) {
      const match = comp.extracted && comp.candidate && 
                    normalizeForComparison(comp.extracted) === normalizeForComparison(comp.candidate);
      const matchClass = match ? "context-match" : comp.extracted && comp.candidate ? "context-mismatch" : "context-partial";
      
      html += `<div class="context-row ${matchClass}">`;
      html += `<span class="context-label">${comp.label}</span>`;
      if (comp.extracted) {
        html += `<span class="context-extracted" title="Extracted from text">${esc(comp.extracted)}</span>`;
      } else {
        html += `<span class="context-extracted context-empty">—</span>`;
      }
      html += `<span class="context-arrow">→</span>`;
      if (comp.candidate) {
        html += `<span class="context-candidate" title="From Wikidata">${esc(comp.candidate)}</span>`;
      } else {
        html += `<span class="context-candidate context-empty">—</span>`;
      }
      html += `</div>`;
    }
  }
  html += '</div>';
  
  return html;
}

// ── Community vote store (fetched from server) ─────────────────────────────

let communityVotes = {};   // key → { accept: n, reject: n, flag: n }

function buildCommunityIndex(serverDecisions) {
  const idx = {};
  for (const d of serverDecisions) {
    const k = decisionKey(d.doc_id, d.person, d.outremer_id);
    if (!idx[k]) idx[k] = { accept: 0, reject: 0, flag: 0, names: { accept: [], reject: [], flag: [] } };
    idx[k][d.decision] = (idx[k][d.decision] || 0) + 1;
    const label = d.scholar_name || "Anon";
    if (!idx[k].names[d.decision].includes(label)) idx[k].names[d.decision].push(label);
  }
  return idx;
}

function isConflict(key) {
  const v = communityVotes[key];
  return v && v.accept > 0 && v.reject > 0;
}

function hasConflictInLink(link, docId) {
  for (const c of link.candidates || []) {
    if (isConflict(decisionKey(docId, link.person, c.outremer_id))) return true;
  }
  return false;
}

async function fetchCommunityVotes(docId) {
  try {
    const res = await fetch(`${API_BASE}/outremer-decisions/${encodeURIComponent(docId)}`,
                            { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    communityVotes = buildCommunityIndex(data);
  } catch {
    communityVotes = {};
  }
}

// ── Server sync ────────────────────────────────────────────────────────────

async function syncDecisionToServer(docId, person, outremer_id, decision, comment) {
  const payload = {
    doc_id: docId, person, outremer_id, decision, comment,
    client_id: CLIENT_ID,
    scholar_name: getScholarName() || null,
  };
  const res = await fetch(`${API_BASE}/outremer-decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Server ${res.status}`);
}

async function deleteDecisionFromServer(docId, person, outremer_id) {
  const payload = { doc_id: docId, person, outremer_id, client_id: CLIENT_ID };
  await fetch(`${API_BASE}/outremer-decision`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// ── DOM helpers ────────────────────────────────────────────────────────────

function esc(s) {
  return String(s ?? "")
    .replaceAll("&","&amp;").replaceAll("<","&lt;")
    .replaceAll(">","&gt;").replaceAll('"',"&quot;");
}
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}
function badge(text, cls) { return `<span class="badge ${cls}">${esc(text)}</span>`; }

// ── Fetch JSON ─────────────────────────────────────────────────────────────

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Fetch failed: ${url} (${res.status})`);
  return res.json();
}

// ── State ──────────────────────────────────────────────────────────────────

let currentDoc    = null;
let currentFilter = "all";

// ── Stats bar ──────────────────────────────────────────────────────────────

function updateStats() {
  if (!currentDoc) return;
  const decisions = loadDecisions();
  const links = currentDoc.links || [];
  const docId = currentDoc.doc_id;

  let total = 0, reviewed = 0, accepted = 0, rejected = 0, flagged = 0;
  let notAPerson = 0, wrongEra = 0;

  for (const link of links) {
    for (const c of link.candidates || []) {
      total++;
      const d = decisions[decisionKey(docId, link.person, c.outremer_id)];
      if (d) {
        reviewed++;
        if (d.decision === "accept")  accepted++;
        else if (d.decision === "reject") rejected++;
        else if (d.decision === "flag") flagged++;
      }
    }

    // Count Wikidata candidates for no_match persons
    if (!link.candidates?.length) {
      const wdCands = wikidataCandidatesFor(link.person);
      if (wdCands.length) {
        for (const c of wdCands) {
          total++;
          const d = decisions[decisionKey(docId, link.person, `wikidata:${c.qid}`)];
          if (d) {
            reviewed++;
            if (d.decision === "accept")  accepted++;
            else if (d.decision === "reject") rejected++;
          }
        }
      } else {
        total++;  // unresolvable no_match still counts as a slot
      }
    }

    // Count entity-level flags
    if (decisions[decisionKey(docId, link.person, "_not_a_person")]?.decision === "not_a_person") notAPerson++;
    if (decisions[decisionKey(docId, link.person, "_wrong_era")]?.decision  === "wrong_era")  wrongEra++;
  }

  document.getElementById("statReviewed").textContent  = `${reviewed} / ${total} reviewed`;
  document.getElementById("statAcceptedN").textContent  = accepted;
  document.getElementById("statRejectedN").textContent  = rejected;
  document.getElementById("statFlaggedN").textContent   = flagged;
  const efEl = document.getElementById("statEntityFlagsN");
  if (efEl) efEl.textContent = notAPerson + wrongEra;
  document.getElementById("statsBar").classList.remove("hidden");
  document.getElementById("filterBar").classList.remove("hidden");
}

// ── Filter ─────────────────────────────────────────────────────────────────

function setFilter(f) {
  currentFilter = f;
  document.querySelectorAll(".filter-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.filter === f));
  renderLinks(currentDoc);
}

function linkMatchesFilter(link, decisions, docId) {
  if (currentFilter === "all")      return true;
  if (currentFilter === "no_match") return link.status === "no_match";
  if (currentFilter === "conflict") return hasConflictInLink(link, docId);
  const candidates = link.candidates || [];
  for (const c of candidates) {
    const d = decisions[decisionKey(docId, link.person, c.outremer_id)];
    if (currentFilter === "unreviewed" && !d) return true;
    if (currentFilter === "accepted"  && d?.decision === "accept") return true;
    if (currentFilter === "rejected"  && d?.decision === "reject") return true;
    if (currentFilter === "flagged"   && d?.decision === "flag")   return true;
  }
  if (currentFilter === "unreviewed" && !candidates.length) return true;
  return false;
}

// ── Persons section ────────────────────────────────────────────────────────

function renderPersons(doc) {
  const container = document.getElementById("persons");
  container.innerHTML = "";
  const persons = doc.persons || [];
  document.getElementById("personCount").textContent = persons.length;

  if (!persons.length) { container.textContent = "No persons extracted."; return; }

  for (const p of persons) {
    const card = el("div", "card");
    const confPct = Math.round((p.confidence ?? 0) * 100);
    const confCls = confPct >= 70 ? "conf-high" : confPct >= 40 ? "conf-med" : "conf-low";

    let pills = "";
    if (p.group)   pills += badge("group",   "pill-group");
    if (p.title)   pills += badge(p.title,   "pill-neutral");
    if (p.toponym) pills += badge("📍 " + p.toponym, "pill-neutral");
    if (p.role)    pills += badge(p.role,    "pill-neutral");
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

// ── Community votes display ────────────────────────────────────────────────

function communityBadgeHtml(key) {
  const v = communityVotes[key];
  if (!v) return '<span class="community-votes muted">no votes yet</span>';
  const parts = [];
  const names = v.names || {};
  if (v.accept) {
    const tip = names.accept?.join(", ") || "";
    parts.push(`<span class="cv-accept" title="${tip}">✅ ${v.accept}</span>`);
  }
  if (v.reject) {
    const tip = names.reject?.join(", ") || "";
    parts.push(`<span class="cv-reject" title="${tip}">❌ ${v.reject}</span>`);
  }
  if (v.flag) {
    const tip = names.flag?.join(", ") || "";
    parts.push(`<span class="cv-flag" title="${tip}">🚩 ${v.flag}</span>`);
  }
  if (!parts.length) return '<span class="community-votes muted">no votes yet</span>';
  const conflict = v.accept > 0 && v.reject > 0
    ? `<span class="cv-conflict" title="Conflict: reviewers disagree">⚠️</span>` : "";
  return `<span class="community-votes">${conflict}${parts.join(" ")}</span>`;
}

// ── Candidate rows ─────────────────────────────────────────────────────────

function renderCandidateRow(link, candidate, docId, decisions) {
  const k       = decisionKey(docId, link.person, candidate.outremer_id);
  const stored  = decisions[k];
  const decision = stored?.decision || null;
  const comment  = stored?.comment  || "";

  const scorePct  = Math.round((candidate.score ?? 0) * 100);
  const statusCls = candidate.score >= 0.9  ? "status-high"
                  : candidate.score >= 0.75 ? "status-med"
                  :                           "status-low";

  // Load authority file data for this candidate
  const authData = loadAuthorityData(candidate.outremer_id);
  
  // Build context comparison HTML
  const contextHtml = buildContextComparison(link, candidate, authData);

  const row = el("div", "candidate-row");
  row.dataset.key = k;
  if (decision) row.dataset.decision = decision;
  if (isConflict(k)) row.dataset.conflict = "true";

  row.innerHTML = `
    <div class="candidate-info">
      <span class="candidate-name">${esc(candidate.outremer_name)}</span>
      <span class="score-badge ${statusCls}">${scorePct}%</span>
      <span class="match-type">${esc(candidate.match_type)}</span>
      <span class="candidate-type muted">${esc(candidate.type)}</span>
      <span class="outremer-id muted">${esc(candidate.outremer_id)}</span>
      ${contextHtml}
      ${communityBadgeHtml(k)}
    </div>
    <div class="adjudication">
      <button class="adj-btn accept ${decision==="accept"?"active":""}"
              data-action="accept" data-key="${esc(k)}" title="Accept">✅</button>
      <button class="adj-btn reject ${decision==="reject"?"active":""}"
              data-action="reject" data-key="${esc(k)}" title="Reject">❌</button>
      <button class="adj-btn flag   ${decision==="flag"  ?"active":""}"
              data-action="flag"   data-key="${esc(k)}" title="Flag">🚩</button>
      <span class="sync-indicator" title="Sync status"></span>
      <input class="comment-input" type="text"
             placeholder="Comment…" data-key="${esc(k)}" value="${esc(comment)}" />
    </div>
  `;

  // ── Adjudication button handler ──────────────────────────────────────────
  const syncEl = row.querySelector(".sync-indicator");

  async function handleDecision(action, key) {
    const d = loadDecisions();
    const prev = d[key]?.decision;

    // Parse doc/person/outremer_id from key
    const [dId, person, oId] = key.split("::");

    if (prev === action) {
      // Toggle off
      delete d[key];
      row.querySelectorAll(".adj-btn").forEach(b => b.classList.remove("active"));
      row.removeAttribute("data-decision");
      saveDecisions(d);
      updateStats();
      setSyncPending(syncEl);
      try {
        await deleteDecisionFromServer(dId, person, oId);
        setSyncOk(syncEl);
      } catch { setSyncErr(syncEl); }
    } else {
      d[key] = { decision: action, comment: d[key]?.comment || "", ts: new Date().toISOString() };
      row.querySelectorAll(".adj-btn").forEach(b => b.classList.remove("active"));
      row.querySelector(`[data-action="${action}"]`).classList.add("active");
      row.dataset.decision = action;
      saveDecisions(d);
      updateStats();
      setSyncPending(syncEl);
      try {
        await syncDecisionToServer(dId, person, oId, action, d[key].comment);
        setSyncOk(syncEl);
        // Update community vote display locally (optimistic)
        if (!communityVotes[key]) communityVotes[key] = { accept: 0, reject: 0, flag: 0 };
        if (prev) communityVotes[key][prev] = Math.max(0, (communityVotes[key][prev] || 0) - 1);
        communityVotes[key][action] = (communityVotes[key][action] || 0) + 1;
        row.querySelector(".community-votes, .community-votes.muted")?.remove?.();
        row.querySelector(".candidate-info").insertAdjacentHTML("beforeend", communityBadgeHtml(key));
      } catch { setSyncErr(syncEl); }
    }
  }

  row.querySelectorAll(".adj-btn").forEach(btn => {
    btn.addEventListener("click", () => handleDecision(btn.dataset.action, btn.dataset.key));
  });

  // ── Comment handler ──────────────────────────────────────────────────────
  const commentInput = row.querySelector(".comment-input");
  commentInput.addEventListener("change", async () => {
    const key = commentInput.dataset.key;
    const d   = loadDecisions();
    if (!d[key]) return;   // only save comment if a decision was made
    d[key].comment = commentInput.value.trim();
    d[key].ts = new Date().toISOString();
    saveDecisions(d);

    const [dId, person, oId] = key.split("::");
    setSyncPending(syncEl);
    try {
      await syncDecisionToServer(dId, person, oId, d[key].decision, d[key].comment);
      setSyncOk(syncEl);
    } catch { setSyncErr(syncEl); }
  });

  return row;
}

function setSyncPending(el) { el.textContent = "⟳"; el.className = "sync-indicator sync-pending"; el.title = "Syncing…"; }
function setSyncOk(el)      { el.textContent = "✓"; el.className = "sync-indicator sync-ok";      el.title = "Synced to server"; }
function setSyncErr(el)     { el.textContent = "✗"; el.className = "sync-indicator sync-err";     el.title = "Sync failed — decision saved locally"; }

// ── Wikidata candidate row (with adjudication buttons) ─────────────────────

function renderWikidataCandidateRow(link, c, docId, decisions) {
  const oId      = `wikidata:${c.qid}`;   // e.g. "wikidata:Q8581"
  const k        = decisionKey(docId, link.person, oId);
  const stored   = decisions[k];
  const decision = stored?.decision || null;
  const scorePct = Math.round((c.score || 0) * 100);
  const relevantCls = c.score >= 0.4 ? "wd-relevant" : "wd-weak";

  // Build Wikidata context HTML
  const wdContextHtml = buildWikidataContext(link, c);

  const row = el("div", `wd-row ${relevantCls} wd-adj-row`);
  row.dataset.key = k;
  if (decision) row.dataset.decision = decision;

  row.innerHTML = `
    <div class="wd-info">
      <a class="wd-name" href="${esc(c.url)}" target="_blank" rel="noopener">
        ${esc(c.label)} <span class="wd-qid">${esc(c.qid)}</span>
      </a>
      <span class="score-badge status-none">${scorePct}%</span>
      <span class="wd-desc muted">${esc(c.description)}</span>
      ${wdContextHtml}
      ${communityBadgeHtml(k)}
    </div>
    <div class="adjudication">
      <button class="adj-btn accept ${decision==="accept"?"active":""}"
              data-action="accept" title="Accept: this Wikidata entry matches the person">✅</button>
      <button class="adj-btn reject ${decision==="reject"?"active":""}"
              data-action="reject" title="Reject: wrong match">❌</button>
      <span class="sync-indicator" title="Sync status"></span>
    </div>
  `;

  const syncEl = row.querySelector(".sync-indicator");

  row.querySelectorAll(".adj-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.action;
      const d      = loadDecisions();
      const prev   = d[k]?.decision;

      if (prev === action) {
        // Toggle off
        delete d[k];
        row.querySelectorAll(".adj-btn").forEach(b => b.classList.remove("active"));
        row.removeAttribute("data-decision");
        saveDecisions(d);
        updateStats();
        setSyncPending(syncEl);
        try {
          await deleteDecisionFromServer(docId, link.person, oId);
          setSyncOk(syncEl);
        } catch { setSyncErr(syncEl); }
      } else {
        d[k] = { decision: action, ts: new Date().toISOString() };
        row.querySelectorAll(".adj-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        row.dataset.decision = action;
        saveDecisions(d);
        updateStats();
        setSyncPending(syncEl);
        try {
          await syncDecisionToServer(docId, link.person, oId, action);
          setSyncOk(syncEl);
          // Optimistic community update
          if (!communityVotes[k]) communityVotes[k] = { accept: 0, reject: 0, flag: 0 };
          if (prev) communityVotes[k][prev] = Math.max(0, (communityVotes[k][prev] || 0) - 1);
          communityVotes[k][action] = (communityVotes[k][action] || 0) + 1;
          const cvEl = row.querySelector(".community-votes, .community-votes.muted");
          if (cvEl) cvEl.outerHTML = communityBadgeHtml(k);
          else row.querySelector(".wd-info").insertAdjacentHTML("beforeend", communityBadgeHtml(k));
        } catch { setSyncErr(syncEl); }
      }
    });
  });

  return row;
}

// ── Links rendering ────────────────────────────────────────────────────────

function renderLinks(doc) {
  if (!doc) return;
  const container = document.getElementById("links");
  container.innerHTML = "";
  const links = doc.links || [];
  const docId = doc.doc_id;
  const decisions = loadDecisions();
  const visible = links.filter(l => linkMatchesFilter(l, decisions, docId));

  if (!visible.length) {
    container.textContent = currentFilter === "all" ? "No links found."
                          : `No ${currentFilter} links.`;
    return;
  }

  // Conflict alert banner
  const conflictCount = links.filter(l => hasConflictInLink(l, docId)).length;
  if (conflictCount > 0 && currentFilter !== "conflict") {
    const banner = el("div", "conflict-banner");
    banner.innerHTML = `⚠️ <strong>${conflictCount} link${conflictCount!==1?"s":""}</strong>
      with reviewer disagreement.
      <button class="btn-small" id="showConflictsBtn">Show conflicts</button>`;
    container.appendChild(banner);
    document.getElementById("showConflictsBtn")
      ?.addEventListener("click", () => setFilter("conflict"));
  }

  for (const link of visible) {
    const card = el("div", "card link-card");
    card.dataset.status = link.status;

    const statusLabel = {
      high:     badge("high confidence", "status-high"),
      medium:   badge("medium confidence", "status-med"),
      low:      badge("low confidence", "status-low"),
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

    // ── Entity-level feedback (per person, not per candidate) ──────────────
    const notPersonKey = decisionKey(docId, link.person, "_not_a_person");
    const wrongEraKey  = decisionKey(docId, link.person, "_wrong_era");
    const isNotPerson  = decisions[notPersonKey]?.decision === "not_a_person";
    const isWrongEra   = decisions[wrongEraKey]?.decision  === "wrong_era";

    const flagsEl = el("div", "entity-flags");
    flagsEl.innerHTML = `
      <span>Flag as:</span>
      <button class="flag-entity-btn ${isNotPerson ? "active-not-person" : ""}"
              data-eflag="not_a_person">⊘ Not a person</button>
      <button class="flag-entity-btn ${isWrongEra ? "active-wrong-era" : ""}"
              data-eflag="wrong_era">🕰 Wrong era (modern)</button>
    `;
    flagsEl.querySelectorAll(".flag-entity-btn").forEach(btn => {
      btn.addEventListener("click", () => toggleEntityFlag(btn.dataset.eflag, link.person, docId));
    });
    card.appendChild(flagsEl);

    if (!link.candidates?.length) {
      // Try Wikidata candidates
      const wdCands = wikidataCandidatesFor(link.person);
      if (wdCands.length) {
        const wdEl = el("div", "wikidata-section");
        wdEl.innerHTML = `<div class="wd-label">Not in authority file — Wikidata candidates (humans only):</div>`;
        for (const c of wdCands) {
          wdEl.appendChild(renderWikidataCandidateRow(link, c, docId, decisions));
        }
        card.appendChild(wdEl);
      } else {
        card.innerHTML += `<div class="no-match-note muted">No authority match · no Wikidata candidates.</div>`;
      }
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

  const meta = doc.metadata || {};
  const metaParts = [
    meta.author ? `<strong>${esc(meta.author)}</strong>` : null,
    meta.year   ? `${esc(meta.year)}` : null,
    meta.title  ? `<em>${esc(meta.title)}</em>` : null,
    meta.doc_type ? `[${esc(meta.doc_type)}]` : null,
    `<span class="muted">· extraction: ${esc(doc.extraction_mode || "unknown")} · ${(doc.links||[]).length} persons</span>`,
  ].filter(Boolean);
  document.getElementById("docMeta").innerHTML = metaParts.join(" · ");

  // Fetch community votes + Wikidata matches + authority file before rendering links
  await Promise.all([
    fetchCommunityVotes(doc.doc_id),
    fetchWikidataMatches(doc.doc_id),
    fetchAuthorityFile(),
  ]);

  renderPersons(doc);
  renderLinks(doc);
  updateStats();

  document.getElementById("raw").textContent = JSON.stringify(doc, null, 2);
}

async function loadIndex() {
  const idx = await fetchJson("./index.json");
  const sel = document.getElementById("docSelect");
  sel.innerHTML = "";

  // Filter out non-document files
  const docs = (idx.documents || []).filter(n =>
    !n.includes("wikidata") && !n.includes("authority")
  );

  // Fetch metadata for each doc to build readable labels
  const metas = await Promise.all(docs.map(async name => {
    try {
      const d = await fetchJson(`./data/${name}`);
      return { name, meta: d.metadata || {} };
    } catch {
      return { name, meta: {} };
    }
  }));

  for (const { name, meta } of metas) {
    const opt = document.createElement("option");
    opt.value = name;
    // Format: "Author (Year) — Title" or fall back to slug
    const parts = [];
    if (meta.author) parts.push(meta.author);
    if (meta.year)   parts.push(`(${meta.year})`);
    const label = parts.length
      ? `${parts.join(" ")}${meta.title ? " — " + meta.title : ""}`
      : name.replace(".json", "").replace(/-/g, " ");
    opt.textContent = label;
    sel.appendChild(opt);
  }

  if (docs.length) {
    await loadDoc(docs[0]);
  } else {
    document.getElementById("docMeta").textContent =
      "No documents found. Add .txt/.pdf files to data/raw and run the pipeline.";
  }
}

// ── TEI-XML export ─────────────────────────────────────────────────────────

function exportTei() {
  if (!currentDoc) return;
  const doc     = currentDoc;
  const docId   = doc.doc_id;
  const meta    = doc.metadata || {};
  const persons = doc.persons  || [];
  const links   = doc.links    || [];
  const decisions = loadDecisions();

  // Build accepted person refs
  const acceptedLinks = links.filter(l => {
    if (!l.top_candidate) return false;
    const k = decisionKey(docId, l.person, l.top_candidate.outremer_id);
    return decisions[k]?.decision === "accept"
        || (communityVotes[k]?.accept || 0) >= 2;
  });

  const persNameMap = {};
  for (const l of acceptedLinks) {
    persNameMap[l.person] = l.top_candidate.outremer_id;
  }

  const persListItems = [...new Set(acceptedLinks.map(l =>
    `    <person xml:id="${l.top_candidate.outremer_id.replace(/:/g,"-")}">` +
    `\n      <persName>${escXml(l.top_candidate.outremer_name)}</persName>` +
    `\n      <note type="outremer_id">${escXml(l.top_candidate.outremer_id)}</note>` +
    (wikidataCandidatesFor(l.person)[0]?.qid
      ? `\n      <idno type="wikidata">https://www.wikidata.org/wiki/${escXml(wikidataCandidatesFor(l.person)[0].qid)}</idno>`
      : "") +
    `\n    </person>`
  ))].join("\n");

  // Tag person mentions in a simplified body
  let bodyText = persons.map(p => {
    const ref = persNameMap[p.name];
    const ctx = escXml(p.context || p.name);
    if (ref) {
      const cert = (links.find(l=>l.person===p.name)?.status) === "high" ? "high" : "medium";
      return `<persName ref="#${ref.replace(/:/g,"-")}" cert="${cert}">${escXml(p.raw_mention || p.name)}</persName>`;
    }
    return `<persName>${escXml(p.raw_mention || p.name)}</persName>`;
  }).join("\n    ");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>${escXml(meta.title || docId)}</title>
        ${meta.author ? `<author>${escXml(meta.author)}</author>` : ""}
      </titleStmt>
      <publicationStmt>
        <p>Generated by the Outremer PoC pipeline · ${new Date().toISOString()}</p>
        <p>Source: ${escXml(doc.source_file || "")}</p>
      </publicationStmt>
    </fileDesc>
  </teiHeader>
  <text>
    <body>
      <listPerson>
${persListItems}
      </listPerson>
      <div type="extracted_persons">
    ${bodyText}
      </div>
    </body>
  </text>
</TEI>`;

  downloadText(xml, `${docId}.tei.xml`, "application/xml");
}

function escXml(s) {
  return String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;")
    .replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&apos;");
}

// ── JSON-LD export ─────────────────────────────────────────────────────────

function exportJsonLd() {
  if (!currentDoc) return;
  const doc   = currentDoc;
  const docId = doc.doc_id;
  const meta  = doc.metadata || {};
  const links = doc.links    || [];
  const decisions = loadDecisions();

  const entities = [];
  for (const link of links) {
    if (!link.top_candidate) continue;
    const k = decisionKey(docId, link.person, link.top_candidate.outremer_id);
    const d = decisions[k];
    const communityAccepts = (communityVotes[k]?.accept || 0);
    if (!d && communityAccepts < 2) continue;   // only export reviewed/agreed

    const wdCands = wikidataCandidatesFor(link.person);
    const entity = {
      "@type":        "schema:Person",
      "@id":          `outremer:${link.top_candidate.outremer_id}`,
      "schema:name":  link.top_candidate.outremer_name,
      "rdfs:label":   link.person,
      "outremer:confidence":   link.confidence,
      "outremer:matchStatus":  link.status,
      "outremer:authorityId":  link.top_candidate.outremer_id,
    };
    if (wdCands.length && wdCands[0].score >= 0.4) {
      entity["owl:sameAs"] = `http://www.wikidata.org/entity/${wdCands[0].qid}`;
    }
    if (d?.decision) {
      entity["outremer:humanDecision"] = d.decision;
      entity["outremer:reviewer"] = d.scholar_name || "anonymous";
    }
    entities.push(entity);
  }

  const jsonld = {
    "@context": {
      "schema":    "https://schema.org/",
      "owl":       "http://www.w3.org/2002/07/owl#",
      "rdfs":      "http://www.w3.org/2000/01/rdf-schema#",
      "outremer":  "https://thodel.github.io/outremer/vocab#",
      "crm":       "http://www.cidoc-crm.org/cidoc-crm/",
    },
    "@id":         `outremer:doc/${docId}`,
    "@type":       "schema:Dataset",
    "schema:name": meta.title || docId,
    "schema:author": meta.author || null,
    "schema:dateCreated": meta.year || null,
    "schema:description": `Outremer PoC extraction — ${new Date().toISOString()}`,
    "schema:hasPart": entities,
  };

  downloadText(JSON.stringify(jsonld, null, 2), `${docId}.jsonld`, "application/ld+json");
}

// ── Download helper ─────────────────────────────────────────────────────────

function downloadText(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ── Export decisions ────────────────────────────────────────────────────────

function exportDecisions() {
  const d = loadDecisions();
  const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `outremer-decisions-${new Date().toISOString().slice(0,10)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ── Init ───────────────────────────────────────────────────────────────────

document.getElementById("loadBtn").addEventListener("click", () =>
  loadDoc(document.getElementById("docSelect").value));

document.getElementById("exportBtn")?.addEventListener("click", exportDecisions);
document.getElementById("exportTeiBtn")?.addEventListener("click", exportTei);
document.getElementById("exportJsonLdBtn")?.addEventListener("click", exportJsonLd);

initScholarName();

document.getElementById("toggleRaw").addEventListener("click", function () {
  const raw = document.getElementById("raw");
  const hidden = raw.classList.toggle("hidden");
  this.textContent = hidden ? "show" : "hide";
});

document.querySelectorAll(".filter-btn").forEach(btn =>
  btn.addEventListener("click", () => setFilter(btn.dataset.filter)));

loadIndex().catch(err => {
  document.getElementById("docMeta").textContent = String(err);
});
