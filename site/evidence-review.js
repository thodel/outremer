"use strict";

const reviews = [];

async function digest(text) {
  const bytes = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map(x => x.toString(16).padStart(2, "0")).join("");
}

async function addReview(target, action, supersedes = null) {
  const reviewerSeed = document.querySelector("#reviewer").value || "anonymous";
  const reviewer = `reviewer-${(await digest(reviewerSeed)).slice(0, 12)}`;
  const comment = prompt("Review comment") || "";
  const timestamp = new Date().toISOString();
  const id = `outremer:review:${(await digest(
    [target.id, action, reviewer, timestamp, supersedes || ""].join("\u001f")
  )).slice(0, 24)}`;
  reviews.push({
    id, target_id: target.id, target_type: target.type, action,
    reviewer, timestamp, comment, supersedes
  });
  renderHistory(target.id);
}

function activeReviews(targetId) {
  const history = reviews.filter(item => item.target_id === targetId);
  const superseded = new Set(history.map(item => item.supersedes).filter(Boolean));
  return history.filter(item => !superseded.has(item.id));
}

function renderHistory(targetId) {
  const output = document.querySelector(`[data-history="${CSS.escape(targetId)}"]`);
  const active = activeReviews(targetId);
  const actions = new Set(active.map(item => item.action));
  const conflict = actions.has("accept") && (actions.has("reject") || actions.has("flag"));
  output.textContent = JSON.stringify({conflict, active, history:
    reviews.filter(item => item.target_id === targetId)}, null, 2);
}

function renderItem(target) {
  const article = document.createElement("article");
  article.innerHTML = `<h2>${target.type}: ${target.id}</h2>
    <pre>${JSON.stringify(target, null, 2)}</pre>
    <div class="actions"></div><pre data-history="${target.id}"></pre>`;
  for (const action of ["accept", "reject", "flag"]) {
    const button = document.createElement("button");
    button.textContent = action;
    button.onclick = () => addReview(target, action);
    article.querySelector(".actions").append(button);
  }
  const supersede = document.createElement("button");
  supersede.textContent = "supersede selected prior review";
  supersede.onclick = () => {
    const prior = prompt("Prior review ID to supersede");
    if (prior) addReview(target, "supersede", prior);
  };
  article.querySelector(".actions").append(supersede);
  return article;
}

document.querySelector("#dataset").addEventListener("change", async event => {
  const dataset = JSON.parse(await event.target.files[0].text());
  const items = dataset.objects.filter(item =>
    ["assertion", "identity_hypothesis"].includes(item.type));
  const container = document.querySelector("#items");
  container.replaceChildren(...items.map(renderItem));
});

document.querySelector("#export").onclick = () => {
  const blob = new Blob(
    [reviews.map(item => JSON.stringify(item)).join("\n") + "\n"],
    {type: "application/x-ndjson"}
  );
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "evidence-reviews.jsonl";
  link.click();
  URL.revokeObjectURL(link.href);
};
