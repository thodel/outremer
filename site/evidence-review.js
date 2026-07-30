import {loadReviews, renderEvidenceReview} from "./evidence-review-core.mjs";

const datasetInput = document.querySelector("#dataset");
const items = document.querySelector("#items");

datasetInput.addEventListener("change", async event => {
  const dataset = JSON.parse(await event.target.files[0].text());
  renderEvidenceReview(items, dataset, {
    reviewer: () => document.querySelector("#reviewer").value || "anonymous",
  });
});

document.querySelector("#export").addEventListener("click", () => {
  const reviews = loadReviews();
  const blob = new Blob(
    [reviews.map(item => JSON.stringify(item)).join("\n") + "\n"],
    {type: "application/x-ndjson"}
  );
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "evidence-reviews.jsonl";
  link.click();
  URL.revokeObjectURL(link.href);
});
