#!/usr/bin/env python3
"""
Paged exporter (robust under WDQS timeouts):

- Count qualifying people
- Page through qualifying QIDs with LIMIT/OFFSET
- For each QID page, download all truthy (wdt:) statements in long form
- Write per-page CSVs + ZIP bundle

Fixes:
- Uses POST (avoids GET URL-length 400)
- Avoids Python .format() conflicts with SPARQL braces by using string.Template
- Resume support (skips existing files)
"""

import csv
import os
import sys
import time
import zipfile
from string import Template
from typing import List

import requests

ENDPOINT = "https://query.wikidata.org/sparql"

HEADERS = {
    "Accept": "text/csv",
    # Replace with your contact email or a repo URL (WDQS etiquette)
    "User-Agent": "peerage-pre1500-export/1.3 (contact: you@example.org)",
    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
}

FILTER_BLOCK = """
  ?item wdt:P4638 ?peerageID .
  ?item wdt:P31 wd:Q5 .  # human

  OPTIONAL { ?item wdt:P569 ?birth . }    # date of birth
  OPTIONAL { ?item wdt:P570 ?death . }    # date of death
  OPTIONAL { ?item wdt:P1317 ?floruit . } # floruit

  FILTER(
    (BOUND(?birth)   && YEAR(?birth)   < 1500) ||
    (BOUND(?death)   && YEAR(?death)   < 1500) ||
    (BOUND(?floruit) && YEAR(?floruit) < 1500)
  )
"""

COUNT_QUERY = f"""
SELECT (COUNT(DISTINCT ?item) AS ?count) WHERE {{
{FILTER_BLOCK}
}}
"""

QID_PAGE_QUERY_TPL = Template(f"""
SELECT ?item WHERE {{
{FILTER_BLOCK}
}}
ORDER BY ?item
LIMIT $limit
OFFSET $offset
""")

DATA_PAGE_QUERY_TPL = Template(f"""
SELECT
  ?item ?itemLabel ?peerageID ?birth ?death ?floruit
  ?prop ?propLabel
  ?value ?valueLabel
WHERE {{
  VALUES ?item {{
$values_block
  }}

{FILTER_BLOCK}

  ?item ?prop ?value .
  FILTER(STRSTARTS(STR(?prop), "http://www.wikidata.org/prop/direct/"))

  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }}
}}
ORDER BY ?item ?prop ?value
""")

def sparql_csv_post(query: str, timeout_s: int = 180) -> str:
    r = requests.post(ENDPOINT, data={"query": query}, headers=HEADERS, timeout=timeout_s)
    if r.status_code >= 400:
        msg = r.text[:800].replace("\n", " ")
        raise requests.HTTPError(f"{r.status_code} {r.reason}: {msg}", response=r)
    return r.text

def parse_single_value(csv_text: str, field: str) -> str:
    rows = list(csv.DictReader(csv_text.splitlines()))
    if not rows:
        raise ValueError("No rows returned")
    return rows[0][field]

def extract_qids_from_item_csv(csv_text: str) -> List[str]:
    rows = list(csv.DictReader(csv_text.splitlines()))
    qids = []
    for row in rows:
        uri = (row.get("item") or "").strip()
        qid = uri.rsplit("/", 1)[-1]
        if qid.startswith("Q"):
            qids.append(qid)
    # de-dup preserving order
    seen = set()
    out = []
    for q in qids:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out

def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)

def zip_csvs(base_dir: str, zip_name: str) -> str:
    zip_path = os.path.join(base_dir, zip_name)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(base_dir):
            for fn in sorted(files):
                if fn.lower().endswith(".csv"):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, base_dir)
                    z.write(full, arcname=rel)
    return zip_path

def main():
    # Tunables (override via env vars)
    out_dir = os.environ.get("OUT_DIR", "peerage_pre1500_export")
    qid_page_size = int(os.environ.get("QID_PAGE_SIZE", "500"))   # QIDs per QID page query
    values_chunk_size = int(os.environ.get("VALUES_SIZE", "200")) # QIDs per VALUES in data query
    sleep_s = float(os.environ.get("SLEEP_S", "1.0"))
    retries = int(os.environ.get("RETRIES", "6"))
    timeout_qids = int(os.environ.get("TIMEOUT_QIDS", "180"))
    timeout_data = int(os.environ.get("TIMEOUT_DATA", "300"))

    if "you@example.org" in HEADERS["User-Agent"]:
        print(
            "\n⚠️  Edit HEADERS['User-Agent'] in export_peerage_pre1500.py "
            "and replace you@example.org with your email or project URL.\n",
            file=sys.stderr,
        )

    os.makedirs(out_dir, exist_ok=True)
    qid_dir = os.path.join(out_dir, "qid_pages")
    data_dir = os.path.join(out_dir, "data_pages")
    os.makedirs(qid_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)

    print("0/5 Verifying count…")
    count_csv = sparql_csv_post(COUNT_QUERY, timeout_s=timeout_qids)
    total = int(parse_single_value(count_csv, "count"))
    print(f"   WDQS count (distinct items): {total}")

    num_qid_pages = (total + qid_page_size - 1) // qid_page_size
    print(f"1/5 Paging QIDs: {num_qid_pages} pages (page_size={qid_page_size})")

    page_index = 0
    offset = 0

    while offset < total:
        page_index += 1
        qid_page_path = os.path.join(qid_dir, f"qids_{page_index:04d}.csv")

        # Fetch QID page (or reuse existing)
        if os.path.exists(qid_page_path) and os.path.getsize(qid_page_path) > 0:
            with open(qid_page_path, "r", encoding="utf-8") as f:
                qid_page_csv = f.read()
            qids = extract_qids_from_item_csv(qid_page_csv)
            print(f"   QID page {page_index:04d}: exists ({len(qids)} qids), skipping fetch")
        else:
            q = QID_PAGE_QUERY_TPL.substitute(limit=qid_page_size, offset=offset)
            qid_page_csv = None
            for attempt in range(1, retries + 1):
                try:
                    qid_page_csv = sparql_csv_post(q, timeout_s=timeout_qids)
                    write_text(qid_page_path, qid_page_csv)
                    break
                except Exception as e:
                    print(f"   QID page {page_index:04d} attempt {attempt} failed: {e}", file=sys.stderr)
                    if attempt == retries:
                        raise
                    time.sleep(6 * attempt)

            qids = extract_qids_from_item_csv(qid_page_csv)
            print(f"   QID page {page_index:04d}: fetched {len(qids)} qids")

        if not qids:
            print("   No more QIDs returned; stopping.")
            break

        # Download data in VALUES chunks
        print(f"2/5 Downloading data for QID page {page_index:04d} in chunks of {values_chunk_size}…")
        subpage = 0
        for start in range(0, len(qids), values_chunk_size):
            subpage += 1
            chunk = qids[start:start + values_chunk_size]
            data_path = os.path.join(data_dir, f"page_{page_index:04d}_{subpage:03d}.csv")

            if os.path.exists(data_path) and os.path.getsize(data_path) > 0:
                print(f"   Data {page_index:04d}_{subpage:03d}: exists, skipping")
                continue

            values_block = "\n".join(f"    wd:{qid}" for qid in chunk)
            dq = DATA_PAGE_QUERY_TPL.substitute(values_block=values_block)

            for attempt in range(1, retries + 1):
                try:
                    csv_text = sparql_csv_post(dq, timeout_s=timeout_data)
                    write_text(data_path, csv_text)
                    print(f"   Data {page_index:04d}_{subpage:03d}: saved ({len(chunk)} qids)")
                    break
                except Exception as e:
                    print(f"   Data {page_index:04d}_{subpage:03d} attempt {attempt} failed: {e}", file=sys.stderr)
                    if attempt == retries:
                        raise
                    time.sleep(6 * attempt)

            time.sleep(sleep_s)

        offset += qid_page_size
        time.sleep(sleep_s)

    print("3/5 Creating ZIP of all CSVs…")
    zip_path = zip_csvs(out_dir, "peerage_pre1500_pages.zip")
    print(f"   ZIP written: {zip_path}")

    print("4/5 Done.")
    print(f"Output folder: {os.path.abspath(out_dir)}")

if __name__ == "__main__":
    main()
