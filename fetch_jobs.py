"""
Fetch data/AI job postings in Bavaria from the Bundesagentur fuer Arbeit job board
and save the raw API responses, one JSON file per day.

Run:  python fetch_jobs.py
Output: data/raw/YYYY-MM-DD/<search_term>__<city>.json
"""

import json
import time
from datetime import date
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
# Public client key used by the job board's own website (not an official API -> may change).
HEADERS = {"X-API-Key": "jobboerse-jobsuche", "User-Agent": "bavaria-data-jobs-tracker (portfolio project)"}

SEARCH_TERMS = ["Data Engineer", "Data Scientist", "AI Engineer", "Data Analyst", "Machine Learning Engineer"]

# Bavaria has no single "state" filter we can rely on, so we search around its main hubs.
# Overlapping radii create duplicates on purpose; we dedupe later in dbt by `referenznummer`.
CITIES = ["München", "Nürnberg", "Augsburg", "Regensburg", "Würzburg", "Ingolstadt"]
RADIUS_KM = 50
PAGE_SIZE = 100          # max the API returns per page
MAX_PAGES = 10           # safety limit so a bug can't loop forever
PAUSE_SECONDS = 1.0      # be polite: one request per second

# Retry transient failures (timeouts, 429, 5xx) with exponential backoff: 2s, 4s, 8s, ...
# 4xx errors like 403 are NOT retried, so a real API change still fails loudly.
SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
    total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"],
)))


def fetch_all_pages(term: str, city: str) -> list[dict]:
    """Return every posting for one (search term, city) pair, across all pages."""
    postings = []
    for page in range(1, MAX_PAGES + 1):
        params = {
            "was": term,
            "wo": city,
            "umkreis": RADIUS_KM,
            "angebotsart": 1,   # 1 = regular employment (not training/internship)
            "page": page,
            "size": PAGE_SIZE,
        }
        response = SESSION.get(API_URL, headers=HEADERS, params=params, timeout=30)
        response.raise_for_status()   # fail loudly: a silent empty file is worse than a crash
        batch = response.json().get("ergebnisliste", [])
        postings.extend(batch)
        time.sleep(PAUSE_SECONDS)
        if len(batch) < PAGE_SIZE:   # last page reached
            break
    return postings


def main() -> None:
    today = date.today().isoformat()
    out_dir = Path("data/raw") / today
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for term in SEARCH_TERMS:
        for city in CITIES:
            postings = fetch_all_pages(term, city)
            filename = f"{term.replace(' ', '_')}__{city}.json"
            payload = {
                "fetched_at": today,
                "search_term": term,
                "city": city,
                "radius_km": RADIUS_KM,
                "count": len(postings),
                "postings": postings,   # keep the raw records untouched
            }
            (out_dir / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{term:28s} {city:12s} {len(postings):4d} postings")
            total += len(postings)

    print(f"\nSaved {total} postings (with duplicates) to {out_dir}")


if __name__ == "__main__":
    main()