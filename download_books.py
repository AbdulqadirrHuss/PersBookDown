#!/usr/bin/env python3
"""
Ebook Download via Anna's Archive -> External Mirror (LibGen)
Uses curl_cffi for TLS fingerprint impersonation to bypass blocks on ALL steps.
Strategy: Anna's Archive (Search) -> Constructed Mirror Link (MD5) -> File (Download)
Now with MD5 Link Construction, IPFS Handling, and Strict Validation.
"""

import os
import re
import sys
import time
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urljoin
from curl_cffi import requests as curl_requests
import requests # retained for FlareSolverr communication only

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DOWNLOADS_DIR = Path("downloads")
SEARCH_TERMS_FILE = Path("search_terms.txt")
FLARESOLVERR_URL = "http://localhost:8191/v1"

# Anna's Archive domains
ANNAS_ARCHIVE_DOMAINS = [
    "annas-archive.org",
    "annas-archive.li", 
    "annas-archive.se",
]

# Session ID for reusing Cloudflare clearance (for search only)
SESSION_ID = None


def flaresolverr_request(url: str, max_timeout: int = 60000) -> dict:
    """Send request through FlareSolverr (for initial search only)"""
    global SESSION_ID
    
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": max_timeout
    }
    
    if SESSION_ID:
        payload["session"] = SESSION_ID
    
    logger.info(f"FlareSolverr request: {url[:80]}...")
    
    try:
        response = requests.post(
            FLARESOLVERR_URL,
            json=payload,
            timeout=120
        )
        
        if response.status_code != 200:
            return None
        
        result = response.json()
        if result.get("status") != "ok":
            return None
        
        solution = result.get("solution", {})
        if not SESSION_ID and "session" in result:
            SESSION_ID = result["session"]
            logger.info(f"Created FlareSolverr session: {SESSION_ID}")
        
        return {
            "html": solution.get("response", ""),
            "status": solution.get("status", 0),
            "url": solution.get("url", url)
        }
    except Exception:
        return None


def create_session():
    """Create a FlareSolverr session"""
    global SESSION_ID
    try:
        response = requests.post(
            FLARESOLVERR_URL,
            json={"cmd": "sessions.create"},
            timeout=30
        )
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "ok":
                SESSION_ID = result.get("session")
                return True
    except:
        pass
    return False


def get_page_with_curl(url: str, referer: str = None) -> str:
    """Get page content using curl_cffi (Chrome impersonation)"""
    try:
        headers = {
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        }
        if referer:
            headers["Referer"] = referer
            
        response = curl_requests.get(
            url,
            headers=headers,
            impersonate="chrome110",
            timeout=60,
            allow_redirects=True
        )
        if response.status_code == 200:
            return response.text
        logger.warning(f"Failed to get page {url}: {response.status_code}")
    except Exception as e:
        logger.warning(f"Error getting page {url}: {e}")
    return ""


def clean_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name)[:50].strip().replace(' ', '_')


def download_file(url: str, base_filename: str, referer: str = None) -> bool:
    """Download file and dynamically determine extension from headers"""
    logger.info(f"Downloading: {url[:80]}...")
    
    try:
        headers = {
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        }
        if referer:
            headers["Referer"] = referer
            
        response = curl_requests.get(
            url,
            headers=headers,
            impersonate="chrome110",
            timeout=300,
            allow_redirects=True
        )
        
        if response.status_code != 200:
            logger.error(f"Download blocked/failed: {response.status_code}")
            return False
            
        content_type = response.headers.get('content-type', '').lower()
        content_disposition = response.headers.get('content-disposition', '')
        
        if 'text/html' in content_type:
            logger.error("Got HTML instead of file (likely timer page or error)")
            return False
            
        # Dynamic Extension Detection
        # 1. Try filename from Content-Disposition
        extension = ""
        filename_match = re.search(r'filename="?([^"]+)"?', content_disposition)
        if filename_match:
            original_name = filename_match.group(1)
            ext = os.path.splitext(original_name)[1].lower()
            if ext in ['.pdf', '.epub', '.mobi', '.azw3', '.djvu', '.zip', '.rar']:
                extension = ext
                logger.info(f"Detected extension from header: {extension}")
        
        # 2. Try extension from Content-Type
        if not extension:
            if 'pdf' in content_type: extension = '.pdf'
            elif 'epub' in content_type: extension = '.epub'
            elif 'mobi' in content_type: extension = '.mobi'
            elif 'zip' in content_type: extension = '.zip'
            elif 'djvu' in content_type: extension = '.djvu'
            
        # 3. Fallback to URL extension
        if not extension:
            ext = os.path.splitext(url.split('?')[0])[1].lower()
            if ext in ['.pdf', '.epub', '.mobi', '.azw3']:
                extension = ext
        
        # Default if completely unknown
        if not extension:
            extension = '.pdf'
            logger.warning("Could not detect extension, defaulting to .pdf")
            
        final_filename = f"{base_filename}{extension}"
        save_path = DOWNLOADS_DIR / final_filename
            
        with open(save_path, 'wb') as f:
            f.write(response.content)
            
        size = save_path.stat().st_size
        logger.info(f"Downloaded {size:,} bytes to {final_filename}")
        
        if size < 10000:
            logger.warning("File too small, deleting")
            save_path.unlink()
            return False
            
        return True
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False


def resolve_mirror(mirror_url: str) -> str:
    """Visit LibGen/IPFS mirror page and extract the real 'GET' link"""
    logger.info(f"Resolving mirror: {mirror_url}")
    html = get_page_with_curl(mirror_url)
    if not html:
        return None
        
    patterns = [
        r'href="(https?://[^"]+/get\.php\?[^"]+)"',
        r'href="(https?://[^"]+\.(?:pdf|epub|mobi|azw3))"',
        r'<a[^>]+href="([^"]+)"[^>]*>\s*GET\s*</a>',
        r'<a[^>]+href="([^"]+)"[^>]*>.*?GET.*?</a>',
        r'<a[^>]+href="([^"]+)"[^>]*>\s*Cloudflare\s*</a>',
        r'<a[^>]+href="([^"]+)"[^>]*>\s*IPFS\.io\s*</a>',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for link in matches:
            if not link.startswith('http'):
                link = urljoin(mirror_url, link)
            
            logger.info(f"Found true download link: {link}")
            return link
            
    logger.warning("No download link found on mirror page")
    return None


def get_download_mirrors(book_url: str) -> list:
    """Extract and prioritize download mirrors (Constructed > IPFS > Scraped)"""
    logger.info(f"Checking {book_url} for mirrors...")
    
    mirrors = []
    
    # 1. MD5 Calculated Link (Highest Priority)
    # Extract MD5 from URL: .../md5/{md5}
    md5_match = re.search(r'/md5/([a-fA-F0-9]{32})', book_url)
    if md5_match:
        md5 = md5_match.group(1)
        constructed_link = f"http://library.lol/main/{md5}"
        mirrors.append({"url": constructed_link, "type": "constructed_libgen"})
        logger.info(f"Constructed LibGen link: {constructed_link}")
    
    html = get_page_with_curl(book_url)
    if not html:
        return mirrors # Return at least constructed link if page fails

    # Save debug HTML
    try:
        with open('/tmp/annas_book_debug.html', 'w', encoding='utf-8') as f:
            f.write(html)
    except:
        pass
        
    # 2. IPFS Links (Medium Priority)
    # Look for /ipfs_downloads/ or ipfs:// links
    ipfs_patterns = [
        r'href="([^"]*\/ipfs_downloads\/[^"]*)"',
        r'href="(ipfs://[^"]+)"',
    ]
    
    for pattern in ipfs_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for link in matches:
            if link.startswith('/'):
                # Handle relative URL: /ipfs_downloads/...
                # Need to determine base domain from book_url
                base_domain = "https://" + book_url.split('/')[2]
                link = urljoin(base_domain, link)
            
            if link not in [m["url"] for m in mirrors]:
                mirrors.append({"url": link, "type": "ipfs"})
                logger.info(f"Found IPFS mirror: {link}")

    # 3. External Mirrors (Lowest Priority)
    patterns = [
        r'href="(https?://library\.lol/[^"]+)"',
        r'href="(https?://libgen\.li/[^"]+)"',
        r'href="(https?://libgen\.rs/[^"]+)"',
        r'href="(https?://libgen\.is/[^"]+)"',
        r'href="(https?://[^"]*z-library[^"]+)"',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for link in matches:
            if link not in [m["url"] for m in mirrors]:
                mirrors.append({"url": link, "type": "scraped_external"})
                logger.info(f"Found scraped mirror: {link}")
                
    return mirrors


def search_annas_archive(query: str) -> dict:
    """Search Anna's Archive with Strict Title Validation"""
    query_terms = [t.lower() for t in query.split() if len(t) > 2] 
    
    for domain in ANNAS_ARCHIVE_DOMAINS:
        encoded_query = query.replace(' ', '+')
        url = f"https://{domain}/search?q={encoded_query}"
        logger.info(f"Searching: {url}")
        
        result = flaresolverr_request(url)
        if result and result.get("html"):
            html = result["html"]
            
            with open('/tmp/annas_search_debug.html', 'w', encoding='utf-8') as f:
                f.write(html[:50000])

            matches = re.finditer(r'<a[^>]*href="(/md5/[a-fA-F0-9]{32})"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE)
            
            found_results = []
            for match in matches:
                link = match.group(1)
                raw_text = match.group(2)
                text = re.sub(r'<[^>]+>', ' ', raw_text).strip()
                text = re.sub(r'\s+', ' ', text)
                
                found_results.append({"url": f"https://{domain}{link}", "title": text})

            logger.info(f"Found {len(found_results)} potential results")
            
            for res in found_results:
                title_lower = res["title"].lower()
                match_score = sum(1 for term in query_terms if term in title_lower)
                required_matches = max(1, len(query_terms) - 1) 
                
                if match_score >= required_matches:
                    logger.info(f"Match found: '{res['title']}'")
                    return {"url": res["url"], "title": res["title"]}
                else:
                    logger.debug(f"Skipping mismatch: '{res['title']}'")
            
            logger.warning("No results matched the search query strictly")
            
    return None


def process_search(query: str) -> bool:
    """Main processing logic"""
    logging.info(f"Processing: {query}")
    
    # 1. Search with strict validation
    result = search_annas_archive(query)
    if not result:
        logger.error(f"No valid results found for: {query}")
        return False
        
    book_url = result["url"]
    base_filename = clean_filename(result["title"])
    
    # 2. Get prioritized mirrors (Constructed > IPFS > Scraped)
    mirrors = get_download_mirrors(book_url)
    if not mirrors:
        logger.error("No mirrors found (and MD5 construction failed)")
        return False
        
    # 3. Resolve and Download
    for i, mirror_info in enumerate(mirrors):
        mirror_url = mirror_info["url"]
        mirror_type = mirror_info["type"]
        logger.info(f"Trying mirror {i+1}/{len(mirrors)} ({mirror_type}): {mirror_url}")
        
        # Determine if we need to resolve it (LibGen/IPFS usually needs resolving)
        # Or if it's a direct file link (rare)
        download_link = resolve_mirror(mirror_url)
        if not download_link:
            continue
            
        # Download (dynamic extension inside)
        if download_file(download_link, base_filename, referer=mirror_url):
            logger.info(f"Successfully downloaded book for: {query}")
            return True
            
        time.sleep(2)
        
    logger.error("All mirrors failed")
    return False


def main():
    logger.info("Ebook Download - MD5 Construction + Prioritization")
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    create_session()
    
    if not SEARCH_TERMS_FILE.exists():
        sys.exit(1)
        
    search_terms = [l.strip() for l in SEARCH_TERMS_FILE.read_text().split('\n') if l.strip()]
    
    for query in search_terms:
        process_search(query)
        time.sleep(5)


if __name__ == "__main__":
    main()
