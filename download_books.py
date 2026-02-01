#!/usr/bin/env python3
"""
Ebook Download via Anna's Archive
Uses FlareSolverr for Cloudflare bypass and curl_cffi for TLS fingerprint impersonation
Targets "Slow Partner Server" links which have minimal protection
"""

import os
import re
import sys
import time
import json
import logging
from pathlib import Path

import requests
from curl_cffi import requests as curl_requests

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

# Anna's Archive domains (may change)
ANNAS_ARCHIVE_DOMAINS = [
    "annas-archive.org",
    "annas-archive.li", 
    "annas-archive.se",
]

# Session ID for reusing Cloudflare clearance
SESSION_ID = None


def flaresolverr_request(url: str, max_timeout: int = 60000) -> dict:
    """
    Send request through FlareSolverr to bypass Cloudflare
    Returns dict with 'html' and 'cookies' keys
    """
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
            logger.error(f"FlareSolverr error: {response.status_code}")
            return None
        
        result = response.json()
        
        if result.get("status") != "ok":
            logger.error(f"FlareSolverr failed: {result.get('message')}")
            return None
        
        solution = result.get("solution", {})
        
        if not SESSION_ID and "session" in result:
            SESSION_ID = result["session"]
            logger.info(f"Created FlareSolverr session: {SESSION_ID}")
        
        return {
            "html": solution.get("response", ""),
            "cookies": solution.get("cookies", []),
            "status": solution.get("status", 0),
            "url": solution.get("url", url)
        }
        
    except requests.exceptions.Timeout:
        logger.error("FlareSolverr request timed out")
        return None
    except Exception as e:
        logger.error(f"FlareSolverr error: {e}")
        return None


def create_session():
    """Create a FlareSolverr session for cookie persistence"""
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
                logger.info(f"Created session: {SESSION_ID}")
                return True
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
    
    return False


def destroy_session():
    """Clean up FlareSolverr session"""
    global SESSION_ID
    
    if not SESSION_ID:
        return
    
    try:
        requests.post(
            FLARESOLVERR_URL,
            json={"cmd": "sessions.destroy", "session": SESSION_ID},
            timeout=10
        )
        logger.info(f"Destroyed session: {SESSION_ID}")
    except:
        pass
    
    SESSION_ID = None


def download_with_curl_cffi(url: str, filename: str) -> bool:
    """
    Download file using curl_cffi with Chrome TLS fingerprint impersonation.
    This bypasses TLS fingerprint blocking that catches regular Python requests.
    """
    save_path = DOWNLOADS_DIR / filename
    
    logger.info(f"Downloading with Chrome impersonation: {url[:80]}...")
    
    try:
        # Use curl_cffi with Chrome 110 impersonation
        # This makes the TLS handshake look exactly like Chrome
        response = curl_requests.get(
            url,
            impersonate="chrome110",
            timeout=120,
            allow_redirects=True
        )
        
        logger.info(f"Response status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Download failed with status {response.status_code}")
            return False
        
        # Check content type
        content_type = response.headers.get('content-type', '')
        logger.info(f"Content-Type: {content_type}")
        
        # Reject HTML responses (error pages)
        if 'text/html' in content_type.lower():
            logger.warning("Got HTML response instead of file")
            # Save for debugging
            with open('/tmp/download_error.html', 'w', encoding='utf-8') as f:
                f.write(response.text[:5000])
            return False
        
        # Determine file extension
        if 'epub' in content_type or '.epub' in url.lower():
            save_path = DOWNLOADS_DIR / filename.replace('.pdf', '.epub')
        elif '.mobi' in url.lower():
            save_path = DOWNLOADS_DIR / filename.replace('.pdf', '.mobi')
        elif '.azw3' in url.lower():
            save_path = DOWNLOADS_DIR / filename.replace('.pdf', '.azw3')
        
        # Write file
        with open(save_path, 'wb') as f:
            f.write(response.content)
        
        size = save_path.stat().st_size
        logger.info(f"Downloaded {size:,} bytes to {save_path.name}")
        
        # Check minimum file size
        if size < 10000:
            logger.warning(f"File too small ({size} bytes), likely error page")
            save_path.unlink()
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"curl_cffi download error: {e}")
        import traceback
        traceback.print_exc()
        return False


def search_annas_archive(query: str) -> dict:
    """
    Search Anna's Archive and return first result with download links.
    Anna's Archive is a meta-search that indexes LibGen, Z-Library, etc.
    """
    # Try different Anna's Archive domains
    for domain in ANNAS_ARCHIVE_DOMAINS:
        encoded_query = query.replace(' ', '+')
        url = f"https://{domain}/search?q={encoded_query}"
        
        logger.info(f"Searching: {url}")
        
        result = flaresolverr_request(url)
        
        if result and result.get("html"):
            html = result["html"]
            
            # Save for debugging
            with open('/tmp/annas_search.html', 'w', encoding='utf-8') as f:
                f.write(html[:50000])
            
            logger.info(f"Search response: {len(html)} chars")
            
            # Look for book result links - Anna's uses /md5/ pattern
            md5_matches = re.findall(r'href="(/md5/[a-fA-F0-9]{32})"', html)
            
            if md5_matches:
                book_url = f"https://{domain}{md5_matches[0]}"
                logger.info(f"Found book link: {book_url}")
                return {
                    "url": book_url,
                    "domain": domain,
                    "cookies": result.get("cookies", [])
                }
            
            # Alternative pattern - some pages use different URL structure
            alt_matches = re.findall(r'href="([^"]+/md5/[a-fA-F0-9]{32}[^"]*)"', html)
            if alt_matches:
                book_url = alt_matches[0]
                if not book_url.startswith('http'):
                    book_url = f"https://{domain}{book_url}"
                logger.info(f"Found book link (alt): {book_url}")
                return {
                    "url": book_url,
                    "domain": domain,
                    "cookies": result.get("cookies", [])
                }
            
            logger.warning(f"No book links found on {domain}")
        else:
            logger.warning(f"Failed to search {domain}")
    
    return None


def get_slow_partner_links(book_url: str, domain: str) -> list:
    """
    Get "Slow Partner Server" download links from Anna's Archive book page.
    These are direct HTTP downloads with minimal protection.
    """
    logger.info(f"Getting download links from: {book_url}")
    
    result = flaresolverr_request(book_url)
    
    if not result:
        return []
    
    html = result.get("html", "")
    
    # Save for debugging
    with open('/tmp/annas_book.html', 'w', encoding='utf-8') as f:
        f.write(html[:50000])
    
    logger.info(f"Book page: {len(html)} chars")
    
    links = []
    
    # Pattern 1: Slow Partner Server links (PRIMARY TARGET)
    # These are the easiest to download - minimal protection
    slow_patterns = [
        r'href="(https?://[^"]*slow[^"]*)"',  # URLs containing 'slow'
        r'Slow Partner.*?href="([^"]+)"',      # Text followed by link
        r'href="([^"]+)"[^>]*>.*?Slow',        # Link followed by text
        r'partner.*?href="(https?://[^"]+)"',  # Partner server links
    ]
    
    for pattern in slow_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
        for match in matches:
            if match.startswith('http') and 'slow' in match.lower():
                if match not in [l["url"] for l in links]:
                    links.append({"url": match, "type": "slow_partner"})
                    logger.info(f"Found Slow Partner link: {match[:80]}")
    
    # Pattern 2: Direct download links (any format)
    direct_patterns = [
        r'href="(https?://[^"]+\.(?:pdf|epub|mobi|azw3|djvu))"',
        r'href="(https?://[^"]+/file/[^"]+)"',
        r'href="(https?://[^"]+download[^"]*)"',
    ]
    
    for pattern in direct_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for match in matches:
            # Skip junk URLs
            if any(skip in match.lower() for skip in ['javascript:', '#', 'ipfs.tech']):
                continue
            if match not in [l["url"] for l in links]:
                links.append({"url": match, "type": "direct"})
                logger.info(f"Found direct link: {match[:80]}")
    
    # Pattern 3: External mirrors (library.lol, libgen)
    mirror_patterns = [
        r'href="(https?://library\.lol/[^"]+)"',
        r'href="(https?://libgen\.[^"]+)"',
        r'href="(https?://[^"]*z-library[^"]+)"',
    ]
    
    for pattern in mirror_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for match in matches:
            if match not in [l["url"] for l in links]:
                links.append({"url": match, "type": "mirror"})
                logger.info(f"Found mirror link: {match[:80]}")
    
    logger.info(f"Total download links found: {len(links)}")
    return links


def process_search(query: str) -> bool:
    """Process a single search query"""
    
    logger.info(f"Processing: {query}")
    
    # Search Anna's Archive
    search_result = search_annas_archive(query)
    
    if not search_result:
        logger.error(f"No results found for: {query}")
        return False
    
    # Get download links from book page
    download_links = get_slow_partner_links(
        search_result["url"], 
        search_result["domain"]
    )
    
    if not download_links:
        logger.error("No download links found")
        return False
    
    # Create safe filename
    safe_name = re.sub(r'[^\w\s-]', '', query)[:50].strip().replace(' ', '_')
    filename = f"{safe_name}.pdf"
    
    # Try each download source - prioritize slow partner links
    # Sort to try slow_partner first, then direct, then mirror
    download_links.sort(key=lambda x: {"slow_partner": 0, "direct": 1, "mirror": 2}.get(x["type"], 3))
    
    for i, link_info in enumerate(download_links):
        url = link_info["url"]
        link_type = link_info["type"]
        
        logger.info(f"Trying [{link_type}] source {i+1}/{len(download_links)}: {url[:60]}...")
        
        # Use curl_cffi for Chrome impersonation (bypasses TLS blocking)
        if download_with_curl_cffi(url, filename):
            logger.info(f"Successfully downloaded: {filename}")
            return True
        
        logger.warning(f"Source {i+1} failed, trying next...")
        time.sleep(2)
    
    logger.error("All download sources failed")
    return False


def main():
    """Main entry point"""
    
    logger.info("=" * 60)
    logger.info("Ebook Download - Anna's Archive + curl_cffi")
    logger.info("=" * 60)
    
    # Create downloads directory
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    # Read search terms
    if not SEARCH_TERMS_FILE.exists():
        logger.error(f"Search terms file not found: {SEARCH_TERMS_FILE}")
        sys.exit(1)
    
    search_terms = [
        line.strip() 
        for line in SEARCH_TERMS_FILE.read_text().strip().split('\n')
        if line.strip()
    ]
    
    if not search_terms:
        logger.error("No search terms provided")
        sys.exit(1)
    
    logger.info(f"Search terms: {search_terms}")
    
    # Create FlareSolverr session
    create_session()
    
    # Track results
    successful = []
    failed = []
    
    try:
        for query in search_terms:
            logger.info("=" * 60)
            
            if process_search(query):
                successful.append(query)
            else:
                failed.append(query)
            
            # Wait between searches
            if query != search_terms[-1]:
                logger.info("Waiting 10 seconds before next search...")
                time.sleep(10)
    
    finally:
        destroy_session()
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    
    if successful:
        logger.info(f"Successful ({len(successful)}):")
        for q in successful:
            logger.info(f"  ✓ {q}")
    
    if failed:
        logger.info(f"Failed ({len(failed)}):")
        for q in failed:
            logger.info(f"  ✗ {q}")
    
    # Exit with error if all failed
    if not successful and failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
