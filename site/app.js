const docSelect = document.getElementById("docSelect");
const loadBtn = document.getElementById("loadBtn");
const docMeta = document.getElementById("docMeta");
const personsEl = document.getElementById("persons");
const linksEl = document.getElementById("links");
const rawEl = document.getElementById("raw");

function escapeHtml(s) {
  return s.replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
}

function mkCard(title, subtitle, obj, extraHtml = "") {
  const div = document.createElement("div");
  div.className = "card";
  div.innerHTML = `
    <div class="cardTitle">${escapeHtml(title)}</div>
    ${subtitle ? `<div class="cardSub">${escapeHtml(subtitle)}</div>` : ""}
    ${extraHtml}
    <pre class="mono">${escapeHtml(JSON.stringify(obj, null, 2))}</pre>
  `;
  return div;
}

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Fetch failed: ${url} (${res.status})`);
  return await res.json();
}

async function loadIndex() {
  const idx = await fetchJson("./index.json");

  docSelect.innerHTML = "";
  for (const name of (idx.documents || [])) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    docSelect.appendChild(opt);
  }

  if ((idx.documents || []).length) {
    await loadDoc(idx.documents[0]);
  } else {
    docMeta.textContent = "No documents found. Add .txt/.pdf files to data/raw and run the pipeline.";
  }
}

async function loadDoc(filename) {
  const doc = await fetchJson(`./data/${filename}`);

  docMeta.textContent = JSON.stringify({
    doc_id: doc.doc_id,
    source_file: doc.source_file,
    input_type: doc.input_type,
    metadata: doc.metadata
  }, null, 2);

  // Persons
  personsEl.innerHTML = "";
  const persons = doc.persons || [];
  if (!persons.length) {
    personsEl.textContent = "No persons found.";
  } else {
    for (const p of persons) {
      personsEl.appendChild(mkCard(p.name || "Unnamed person", "", p));
    }
  }

  // Links
  linksEl.innerHTML = "";
  const links = doc.links || [];
  if (!links.length) {
    linksEl.textContent = "No links found.";
  } else {
    for (const l of links) {
      const bibUrl = `./bib/${doc.doc_id}.bib`;
      const extra = `
        <div class="row" style="margin: 6px 0 10px 0;">
          <a class="btnLike" href="${bibUrl}">BibTeX</a>
          <span class="hint">confidence: ${String(l.confidence ?? "")}</span>
        </div>
      `;
      linksEl.appendChild(
        mkCard(`${l.person} → ${l.outremer_name}`, l.type || "", l, extra)
      );
    }
  }

  rawEl.textContent = JSON.stringify(doc, null, 2);
}

loadBtn.addEventListener("click", () => loadDoc(docSelect.value));

loadIndex().catch(err => {
  docMeta.textContent = String(err);
});
