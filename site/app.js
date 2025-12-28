const docSelect = document.getElementById("docSelect");
const loadBtn = document.getElementById("loadBtn");
const docMeta = document.getElementById("docMeta");
const personsEl = document.getElementById("persons");
const linksEl = document.getElementById("links");
const rawEl = document.getElementById("raw");

function card(title, bodyObj) {
  const div = document.createElement("div");
  div.className = "card";
  div.innerHTML = `<div><strong>${title}</strong></div><pre class="mono">${escapeHtml(JSON.stringify(bodyObj, null, 2))}</pre>`;
  return div;
}

function escapeHtml(s) {
  return s.replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
}

async function loadIndex() {
  const res = await fetch("./index.json", { cache: "no-store" });
  if (!res.ok) throw new Error("Missing site/index.json. Did the pipeline run?");
  const idx = await res.json();

  docSelect.innerHTML = "";
  for (const name of idx.documents) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    docSelect.appendChild(opt);
  }
  if (idx.documents.length) {
    await loadDoc(idx.documents[0]);
  }
}

async function loadDoc(filename) {
  const res = await fetch(`../output/${filename}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Cannot fetch output/${filename}`);
  const doc = await res.json();

  docMeta.textContent = JSON.stringify({
    doc_id: doc.doc_id,
    source_file: doc.source_file,
    metadata: doc.metadata
  }, null, 2);

  personsEl.innerHTML = "";
  for (const p of (doc.persons || [])) {
    personsEl.appendChild(card(p.name || "Unnamed person", p));
  }
  if (!(doc.persons || []).length) {
    personsEl.textContent = "No persons found.";
  }

  linksEl.innerHTML = "";
  for (const l of (doc.links || [])) {
    linksEl.appendChild(card(`${l.person} → ${l.outremer_name}`, l));
  }
  if (!(doc.links || []).length) {
    linksEl.textContent = "No links found.";
  }

  rawEl.textContent = JSON.stringify(doc, null, 2);
}

loadBtn.addEventListener("click", () => loadDoc(docSelect.value));

loadIndex().catch(err => {
  docMeta.textContent = String(err);
});
