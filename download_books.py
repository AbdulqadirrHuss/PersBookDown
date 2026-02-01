#!/usr/bin/env python3
"""
Ebook Download via Anna's Archive -> External Mirror (LibGen)
Uses curl_cffi for TLS fingerprint impersonation to bypass blocks on ALL steps.
Strategy: Anna's Archive (Search) -> LibGen Mirror (Page) -> File (Download)
"""

import os
import re
import sys
import time
import logging
from pathlib import Path
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


def download_file(url: str, filename: str, referer: str = None) -> bool:
    """Download file using curl_cffi (Chrome impersonation)"""
    save_path = DOWNLOADS_DIR / filename
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
        if 'text/html' in content_type:
            logger.error("Got HTML instead of file (likely timer page or error)")
            return False
            
        # Determine extension
        if 'epub' in content_type or '.epub' in url.lower():
            save_path = DOWNLOADS_DIR / filename.replace('.pdf', '.epub')
        elif '.mobi' in url.lower():
            save_path = DOWNLOADS_DIR / filename.replace('.pdf', '.mobi')
            
        with open(save_path, 'wb') as f:
            f.write(response.content)
            
        size = save_path.stat().st_size
        logger.info(f"Downloaded {size:,} bytes")
        
        if size < 10000:
            logger.warning("File too small, deleting")
            save_path.unlink()
            return False
            
        return True
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False


def resolve_libgen_mirror(mirror_url: str) -> str:
    """
    Visit LibGen/Library.lol mirror page and extract the real 'GET' link
    Using curl_cffi logic to bypass TLS blocks on the mirror page itself
    """
    logger.info(f"Resolving mirror: {mirror_url}")
    html = get_page_with_curl(mirror_url)
    if not html:
        return None
        
    # Pattern matching for "GET", "Cloudflare", or "IPFS.io" links
    # These are usually the direct download buttons
    patterns = [
        r'href="(https?://[^"]+/get\.php\?[^"]+)"',
        r'href="(https?://[^"]+\.(?:pdf|epub|mobi|azw3))"',
        r'<a[^>]+href="([^"]+)"[^>]*>\s*GET\s*</a>',
        r'<a[^>]+href="([^"]+)"[^>]*>.*?GET.*?</a>',
        r'<a[^>]+href="([^"]+)"[^>]*>\s*Cloudflare\s*</a>',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for link in matches:
            if not link.startswith('http'):
                # Handle relative URLs often found on mirrors
                from urllib.parse import urljoin
                link = urljoin(mirror_url, link)
            
            logger.info(f"Found true download link: {link}")
            return link
            
    logger.warning("No download link found on mirror page")
    return None


def get_external_mirrors(book_url: str) -> list:
    """Extract external mirror links (LibGen, etc) from Anna's book page"""
    logger.info(f"Checking {book_url} for external mirrors...")
    
    # We can use FlareSolverr OR curl_cffi here. Using curl_cffi for consistency
    html = get_page_with_curl(book_url)
    if not html:
        return []
        
    mirrors = []
    
    # Targeting "External Downloads" section
    # library.lol, libgen.li, libgen.rs
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
            if link not in mirrors:
                mirrors.append(link)
                logger.info(f"Found external mirror: {link}")
                
    return mirrors


def search_annas_archive(query: str) -> dict:
    """Search Anna's Archive"""
    for domain in ANNAS_ARCHIVE_DOMAINS:
        encoded_query = query.replace(' ', '+')
        url = f"https://{domain}/search?q={encoded_query}"
        logger.info(f"Searching: {url}")
        
        result = flaresolverr_request(url)
        if result and result.get("html"):
            html = result["html"]
            # Look for MD5 link
            md5_matches = re.findall(r'href="(/md5/[a-fA-F0-9]{32})"', html)
            if md5_matches:
                book_url = f"https://{domain}{md5_matches[0]}"
                logger.info(f"Found book page: {book_url}")
                return {"url": book_url}
    return None


def process_search(query: str) -> bool:
    """Main processing logic"""
    logging.info(f"Processing: {query}")
    
    # 1. Search
    result = search_annas_archive(query)
    if not result:
        logger.error("No results found")
        return False
        
    book_url = result["url"]
    safe_name = re.sub(r'[^\w\s-]', '', query)[:50].strip().replace(' ', '_')
    filename = f"{safe_name}.pdf"
    
    # 2. Get External Mirrors (Prioritize these over slow partners)
    mirrors = get_external_mirrors(book_url)
    if not mirrors:
        logger.error("No external mirrors found")
        return False
        
    # 3. Resolve and Download from Mirrors
    for i, mirror in enumerate(mirrors):
        logger.info(f"Trying mirror {i+1}/{len(mirrors)}: {mirror}")
        
        # Resolve the actual download link from the mirror page
        download_link = resolve_libgen_mirror(mirror)
        if not download_link:
            continue
            
        # Download the file
        if download_file(download_link, filename, referer=mirror):
            logger.info(f"Successfully downloaded: {filename}")
            return True
            
        time.sleep(2)
        
    logger.error("All mirrors failed")
    return False


def main():
    logger.info("Ebook Download - External Mirrors + curl_cffi")
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
