#!/usr/bin/env python3
"""
Ebook Downloader — LibGen API Edition
--------------------------------------
No browser automation. No Cloudflare. No Selenium.
Pipeline:
  1. Search libgen.rs → get result IDs (HTML parse, one table)
    2. libgen.is/json.php → get MD5 + metadata (pure JSON, no scraping)
      3. library.lol/main/{md5} → parse direct download link
        4. Stream download to disk
        """
import sys
import time
import random
import logging
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DOWNLOADS_DIR = Path("downloads")
SEARCH_TERMS_FILE = Path("search_terms.txt")
LIBGEN_SEARCH_URL = "https://libgen.rs/search.php"
LIBGEN_JSON_URL = "https://libgen.is/json.php"
LIBRARY_LOL_URL = "https://library.lol/main/{md5}"
# Fallback mirrors if library.lol download link is absent
LIBGEN_LI_DL = "https://libgen.li/ads.php?md5={md5}"

HEADERS = {
        "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------
session = requests.Session()
session.headers.update(HEADERS)

# ---------------------------------------------------------------------------
# Step 1 — Search
# ---------------------------------------------------------------------------
def search_libgen(query: str, max_results: int = 10) -> list[str]:
    """
        Search libgen.rs and return a list of numeric book IDs.
            """
        log.info(f"Searching LibGen: {query!r}")
    try:
                r = session.get(
                                LIBGEN_SEARCH_URL,
                                params={
                                                    "req": query,
                                                    "res": 25,
                                                    "view": "simple",
                                                    "phrase": 1,
                                                    "column": "def",
                                },
                                timeout=30,
                )
                r.raise_for_status()
except requests.RequestException as e:
        log.error(f"Search request failed: {e}")
        return []

    soup = BeautifulSoup(r.text, "lxml")
    # Results live in <table id="res"> on libgen.rs
    table = soup.find("table", id="res") or soup.find("table", class_="c")
    if not table:
                log.warning("Results table not found — no matches or site changed layout")
                return []

    ids: list[str] = []
    for row in table.find_all("tr")[1:]:  # skip header row
                cells = row.find_all("td")
                if not cells:
                                continue
                            cell_text = cells[0].get_text(strip=True)
        if cell_text.isdigit():
                        ids.append(cell_text)
                    if len(ids) >= max_results:
                                    break

    log.info(f"Found {len(ids)} result IDs")
    return ids


# ---------------------------------------------------------------------------
# Step 2 — Metadata via JSON API
# ---------------------------------------------------------------------------
def get_metadata(ids: list[str]) -> list[dict]:
        """
            Fetch rich metadata for a list of LibGen IDs via the JSON API.
                Returns a list of dicts with keys: id, title, author, extension, md5, filesize, year, language.
                    """
    if not ids:
                return []

    log.info(f"Fetching metadata for {len(ids)} IDs via JSON API")
    try:
                r = session.get(
                    LIBGEN_JSON_URL,
                    params={
                        "ids": ",".join(ids),
                                        "fields": "id,title,author,extension,md5,filesize,year,language",
                    },
                    timeout=30,
    )
        r.raise_for_status()
        data = r.json()
        log.info(f"Metadata received for {len(data)} books")
        return data
except requests.RequestException as e:
        log.error(f"JSON API request failed: {e}")
except ValueError as e:
        log.error(f"JSON parse error: {e}")
    return []


# ---------------------------------------------------------------------------
# Step 3 — Pick best result
# ---------------------------------------------------------------------------
FORMAT_PRIORITY = {"epub": 100, "pdf": 80, "mobi": 60, "azw3": 50, "djvu": 30}


def pick_best(books: list[dict]) -> dict | None:
        """
            Score books and return the best candidate.
                Prefer EPUB > PDF > others, English language, and larger files.
                    """
    if not books:
                return None

    def score(b: dict) -> int:
                s = FORMAT_PRIORITY.get(b.get("extension", "").lower(), 0)
        lang = b.get("language", "").lower()
        if lang in ("english", "en", "eng"):
                        s += 50
elif not lang:
            s += 10  # unknown is OK
        try:
                        s += min(int(b.get("filesize", 0)), 200_000) // 10_000
except (ValueError, TypeError):
            pass
        return s

    best = max(books, key=score)
    log.info(
                f"Selected: [{best.get('extension','?')}] "
                f"{best.get('title','?')} — {best.get('author','?')} "
                f"({best.get('year','?')}) MD5={best.get('md5','?')}"
    )
    return best


# ---------------------------------------------------------------------------
# Step 4 — Resolve download URL from library.lol
# ---------------------------------------------------------------------------
def get_download_url(md5: str) -> str | None:
        """
            Fetch the library.lol page for an MD5 and extract the direct GET link.
                """
    page_url = LIBRARY_LOL_URL.format(md5=md5.lower())
    log.info(f"Fetching download page: {page_url}")

    try:
                r = session.get(page_url, timeout=30)
        r.raise_for_status()
except requests.RequestException as e:
        log.error(f"library.lol request failed: {e}")
        return _fallback_libgen_li(md5)

    soup = BeautifulSoup(r.text, "lxml")

    # Primary: <div id="download"><ul><li><a href="...">GET</a>
    dl_div = soup.find("div", id="download")
    if dl_div:
                a = dl_div.find("a", href=True)
        if a:
            href = a["href"]
            log.info(f"Download URL (div#download): {href}")
            return href

    # Fallback A: any link with 'GET' text
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).upper()
                            if text in ("GET", "GET\n"):
            href = a["href"]
            log.info(f"Download URL (GET text): {href}")
            return href

                                    # Fallback B: direct link to known file hosts
                                    import re
    for a in soup.find_all("a", href=True):
                href = a["href"]
                if re.search(r"libgen\.(li|lc|gs)|library\.lol/get", href):
                                log.info(f"Download URL (mirror link): {href}")
                                return href

            log.warning("No download link found on library.lol — trying libgen.li fallback")
    return _fallback_libgen_li(md5)


def _fallback_libgen_li(md5: str) -> str | None:
        """
            Fallback: resolve via libgen.li ads page → extract direct link.
                """
    url = LIBGEN_LI_DL.format(md5=md5.lower())
    log.info(f"Trying libgen.li fallback: {url}")
    try:
                r = session.get(url, timeout=30)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "lxml")
                a = soup.find("a", href=re.compile(r"get\.php|/get/"))
                if a:
                                href = a["href"]
                                if not href.startswith("http"):
                                                    href = "https://libgen.li/" + href.lstrip("/")
                                                log.info(f"Fallback download URL: {href}")
                                return href
    except requests.RequestException as e:
        log.error(f"libgen.li fallback failed: {e}")
    return None


# ---------------------------------------------------------------------------
# Step 5 — Download file
# ---------------------------------------------------------------------------
def download_file(url: str, save_path: Path) -> bool:
        log.info(f"Downloading → {save_path.name}")
    try:
                with session.get(url, stream=True, timeout=300) as r:
                                r.raise_for_status()
            content_type = r.headers.get("Content-Type", "")
            if "text/html" in content_type:
                                log.warning(f"Response is HTML, not a file (Content-Type: {content_type})")
                return False

            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65_536):
                                        if chunk:
                                                                    f.write(chunk)

                            size = save_path.stat().st_size
        if size < 5_000:
                        log.warning(f"File too small ({size} bytes) — likely an error page")
            save_path.unlink(missing_ok=True)
            return False

        log.info(f"Saved {size:,} bytes → {save_path}")
        return True
except requests.RequestException as e:
        log.error(f"Download error: {e}")
        save_path.unlink(missing_ok=True)
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clean_filename(name: str) -> str:
        import re
    name = re.sub(r'[^\w\s\-]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    return name


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def process_query(query: str) -> bool:
        log.info("")
    log.info("=" * 55)
    log.info(f" QUERY: {query}")
    log.info("=" * 55)

    # 1. Search
    ids = search_libgen(query)
    if not ids:
        log.error("No search results — skipping")
        return False

    # 2. Metadata
    books = get_metadata(ids)
    if not books:
        log.error("Could not fetch metadata — skipping")
        return False

    # 3. Pick best
    book = pick_best(books)
    if not book:
        log.error("No suitable book found")
        return False

    md5 = book.get("md5", "").strip()
                if not md5:
                                         log.error("Book has no MD5 hash")
        return False

    # 4. Resolve download URL
    time.sleep(random.uniform(1.0, 2.5))
    dl_url = get_download_url(md5)
    if not dl_url:
                log.error("Could not resolve download URL")
        return False

    # 5. Download
    ext = book.get("extension", "pdf").lower()
    title = clean_filename(book.get("title", query))
    save_path = DOWNLOADS_DIR / f"{title}.{ext}"

    # Avoid overwriting if already downloaded
    if save_path.exists() and save_path.stat().st_size > 5_000:
        log.info(f"Already exists: {save_path} — skipping download")
                return True

    time.sleep(random.uniform(1.0, 3.0))
    return download_file(dl_url, save_path)


def main():
    log.info("LibGen Downloader — API Edition (no browser, no Cloudflare)")

    DOWNLOADS_DIR.mkdir(exist_ok=True)

    if not SEARCH_TERMS_FILE.exists():
                log.error(f"{SEARCH_TERMS_FILE} not found!")
        sys.exit(1)

    raw_lines = SEARCH_TERMS_FILE.read_text(encoding="utf-8-sig").splitlines()
    terms = [l.strip() for l in raw_lines if l.strip() and not l.strip().startswith("#")]

    if not terms:
        log.error("No search terms found in search_terms.txt")
        sys.exit(1)

    log.info(f"Processing {len(terms)} search term(s)")

    success = fail = 0
    for i, term in enumerate(terms):
                if process_query(term):
                    success += 1
                                log.info(f"SUCCESS: {term}")
else:
            fail += 1
            log.error(f"FAILED: {term}")

        # Polite delay between searches (skip after last)
        if i < len(terms) - 1:
                        delay = random.uniform(3.0, 7.0)
            log.info(f"Waiting {delay:.1f}s ...")
            time.sleep(delay)

    # Summary
    log.info("")
    log.info("=" * 55)
    log.info(f" DONE — {success} succeeded, {fail} failed")
    log.info("=" * 55)

    downloaded = sorted(DOWNLOADS_DIR.iterdir())
        if downloaded:
        log.info("Downloaded files:")
        for f in downloaded:
                        log.info(f"  {f.name} ({f.stat().st_size:,} bytes)")
            else:
                                        log.info("No files in downloads/")

    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
                                    main()
