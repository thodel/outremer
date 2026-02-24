import csv
import math
import os
import time
import zipfile
from typing import List
import requests

ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {
    "Accept": "text/csv",
    # Set this to something meaningful for WDQS etiquette:
    "User-Agent": "peerage-pre1500-export/1.0 (you@example.org)"
}

QID_LIST_QUERY = """
SELECT ?item WHERE {
  ?item wdt:P4638 ?peerageID .
  ?item wdt:P31 wd:Q5 .
  OPTIONAL { ?item wdt:P569 ?birth . }
  OPTIONAL { ?item wdt:P570 ?death . }
  OPTIONAL { ?item wdt:P1317 ?floruit . }
  FILTER(
    (BOUND(?birth)   && YEAR(?birth)   < 1500) ||
    (BOUND(?death)   && YEAR(?death)   < 1500) ||
    (BOUND(?floruit) && YEAR(?floruit) < 1500)
  )
}
ORDER BY ?item
"""

PAGE_QUERY_TEMPLATE = """
SELECT
  ?item ?itemLabel ?peerageID ?birth ?death ?floruit
  ?prop ?propLabel
  ?value ?valueLabel
WHERE {{
  VALUES ?item {{
{values_block}
  }}

  ?item wdt:P4638 ?peerageID .
  ?item wdt:P31 wd:Q5 .

  OPTIONAL {{ ?item wdt:P569 ?birth . }}
  OPTIONAL {{ ?item wdt:P570 ?death . }}
  OPTIONAL {{ ?item wdt:P1317 ?floruit . }}

  FILTER(
    (BOUND(?birth)   && YEAR(?birth)   < 1500) ||
    (BOUND(?death)   && YEAR(?death)   < 1500) ||
    (BOUND(?floruit) && YEAR(?floruit) < 1500)
  )

  ?item ?prop ?value .
  FILTER(STRSTARTS(STR(?prop), "http://www.wikidata.org/prop/direct/"))

  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }}
}}
ORDER BY ?item ?prop ?value
"""

def sparql_csv(query: str, timeout_s: int = 180) -> str:
    r = requests.get(ENDPOINT, params={"query": query}, headers=HEADERS, timeout=timeout_s)
    r.raise_for_status()
    return r.text

def extract_qids(qid_csv_text: str) -> List[str]:
    # CSV has header "item"
    rows = list(csv.DictReader(qid_csv_text.splitlines()))
    qids = []
    for row in rows:
        uri = row["item"].strip()
        # uri like: http://www.wikidata.org/entity/Q123
        qid = uri.rsplit("/", 1)[-1]
        if qid.startswith("Q"):
            qids.append(qid)
    return qids

def chunk(lst: List[str], n: int) -> List[List[str]]:
    return [lst[i:i+n] for i in range(0, len(lst), n)]

def main(out_dir="peerage_pre1500_export", chunk_size=1000, sleep_s=1.0):
    os.makedirs(out_dir, exist_ok=True)

    # 1) Get QIDs once
    print("Fetching QID list…")
    qid_csv = sparql_csv(QID_LIST_QUERY, timeout_s=300)
    qids = extract_qids(qid_csv)
    print(f"Found {len(qids)} QIDs")

    with open(os.path.join(out_dir, "qids.csv"), "w", encoding="utf-8", newline="") as f:
        f.write(qid_csv)

    # 2) Fetch pages
    pages = chunk(qids, chunk_size)
    print(f"Downloading {len(pages)} CSV pages (chunk_size={chunk_size})…")

    for i, page in enumerate(pages, start=1):
        values_block = "\n".join(f"    wd:{qid}" for qid in page)
        q = PAGE_QUERY_TEMPLATE.format(values_block=values_block)

        # simple retry loop
        for attempt in range(1, 4):
            try:
                csv_text = sparql_csv(q, timeout_s=300)
                out_path = os.path.join(out_dir, f"page_{i:03d}.csv")
                with open(out_path, "w", encoding="utf-8", newline="") as f:
                    f.write(csv_text)
                print(f"Saved {out_path} ({len(page)} items)")
                break
            except Exception as e:
                print(f"Page {i} attempt {attempt} failed: {e}")
                if attempt == 3:
                    raise
                time.sleep(5 * attempt)

        time.sleep(sleep_s)

    # 3) Zip all CSVs
    zip_path = os.path.join(out_dir, "peerage_pre1500_pages.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(out_dir)):
            if fn.endswith(".csv"):
                z.write(os.path.join(out_dir, fn), arcname=fn)

    print(f"Done. ZIP: {zip_path}")

if __name__ == "__main__":
    main()
