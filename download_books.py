#!/usr/bin/env python3
"""
Ebook Download via IPFS Gateway

Strategy:
1. Search LibGen to get MD5 hash (lightweight, less blocking)
2. Download via IPFS gateways (Cloudflare, ipfs.io - rarely blocked)

Uses curl_cffi for browser impersonation + Tor proxy.
"""

import os
import re
import sys
import time
import logging
import hashlib
from pathlib import Path
from typing import Optional, List, Tuple
from urllib.parse import quote_plus

from curl_cffi import requests
from bs4 import BeautifulSoup

# ============================================================================
# LOGGING SETUP
# ============================================================================
logging.basicConfig(
    level=logging.DEBUG,  # Verbose logging
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================
DOWNLOADS_DIR = Path("downloads")
SEARCH_TERMS_FILE = Path("search_terms.txt")
BOOKS_FILE = Path("books.txt")
REQUEST_TIMEOUT = 30
RETRY_ATTEMPTS = 2

# Tor proxy
TOR_PROXY = "socks5://127.0.0.1:9050"

# LibGen search mirrors (for getting MD5 only)
LIBGEN_SEARCH_MIRRORS = [
    "https://libgen.is",
    "https://libgen.rs", 
    "https://libgen.st",
]

# IPFS Gateways for downloading (these are CDN-backed, rarely blocked)
IPFS_GATEWAYS = [
    "https://cloudflare-ipfs.com/ipfs",
    "https://ipfs.io/ipfs",
    "https://gateway.pinata.cloud/ipfs",
    "https://dweb.link/ipfs",
]

# LibGen's library.lol for getting IPFS CID from MD5
LIBRARY_LOL_URL = "https://library.lol/main"

PREFERRED_FORMATS = ['epub', 'pdf', 'mobi']

# ============================================================================
# NETWORK HELPERS
# ============================================================================

def check_tor():
    """Check if Tor is available and working."""
    logger.info("=" * 50)
    logger.info("STEP 1: Checking Tor connection...")
    logger.info("=" * 50)
    
    try:
        response = requests.get(
            "https://check.torproject.org/api/ip",
            impersonate="chrome110",
            proxies={"https": TOR_PROXY, "http": TOR_PROXY},
            timeout=15
        )
        data = response.json()
        if data.get("IsTor"):
            logger.info(f"✅ Tor is WORKING!")
            logger.info(f"   Exit node IP: {data.get('IP', 'unknown')}")
            return True
        else:
            logger.warning(f"⚠️ Connected but NOT using Tor. IP: {data.get('IP')}")
            return False
    except Exception as e:
        logger.error(f"❌ Tor connection FAILED: {type(e).__name__}: {e}")
        return False

USE_TOR = False  # Will be set in main()

def get_proxies():
    """Get proxy config."""
    if USE_TOR:
        return {"https": TOR_PROXY, "http": TOR_PROXY}
    return None

def make_request(url: str, timeout: int = REQUEST_TIMEOUT, description: str = "") -> Optional[requests.Response]:
    """Make HTTP request with detailed logging."""
    proxies = get_proxies()
    proxy_str = "via Tor" if proxies else "direct"
    
    for attempt in range(RETRY_ATTEMPTS):
        try:
            logger.debug(f"   Attempt {attempt+1}/{RETRY_ATTEMPTS} ({proxy_str}): {url[:80]}...")
            
            response = requests.get(
                url,
                impersonate="chrome110",
                proxies=proxies,
                timeout=timeout,
                allow_redirects=True
            )
            
            logger.debug(f"   Response: HTTP {response.status_code}, {len(response.content)} bytes")
            
            if response.status_code == 200:
                return response
            elif response.status_code == 403:
                logger.warning(f"   ⚠️ 403 Forbidden - IP/TLS blocked")
            elif response.status_code == 404:
                logger.warning(f"   ⚠️ 404 Not Found")
            else:
                logger.warning(f"   ⚠️ HTTP {response.status_code}")
                
        except Exception as e:
            error_type = type(e).__name__
            logger.warning(f"   ❌ {error_type}: {str(e)[:100]}")
            
        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(2)
    
    return None

# ============================================================================
# SEARCH TERM PARSING
# ============================================================================

def parse_search_terms() -> List[str]:
    """Parse search terms from files."""
    logger.info("=" * 50)
    logger.info("STEP 2: Loading search terms...")
    logger.info("=" * 50)
    
    terms = []
    
    if SEARCH_TERMS_FILE.exists():
        logger.info(f"Reading: {SEARCH_TERMS_FILE}")
        with open(SEARCH_TERMS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                term = line.strip()
                if term and not term.startswith('#'):
                    terms.append(term)
                    logger.info(f"   ✓ '{term}'")
    
    if not terms and BOOKS_FILE.exists():
        logger.info(f"Reading: {BOOKS_FILE}")
        with open(BOOKS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    terms.append(line.replace(' - ', ' '))
    
    logger.info(f"Total: {len(terms)} search term(s)")
    return terms

# ============================================================================
# LIBGEN SEARCH (Get MD5 only - no download)
# ============================================================================

def search_libgen_for_md5(search_term: str) -> List[dict]:
    """
    Search LibGen and extract MD5 hashes.
    Returns list of {md5, title, author, extension, size}
    """
    logger.info("-" * 40)
    logger.info(f"Searching LibGen for MD5: '{search_term}'")
    logger.info("-" * 40)
    
    results = []
    
    for mirror in LIBGEN_SEARCH_MIRRORS:
        url = f"{mirror}/search.php?req={quote_plus(search_term)}&lg_topic=libgen&open=0&view=simple&res=25&phrase=1&column=def"
        logger.info(f"Trying mirror: {mirror}")
        
        response = make_request(url, description="LibGen search")
        
        if not response:
            logger.warning(f"   Failed to reach {mirror}")
            continue
        
        # Check if we got real content
        if len(response.text) < 1000:
            logger.warning(f"   Response too short ({len(response.text)} chars) - likely blocked")
            continue
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find table with results
        table = soup.find('table', class_='c')
        if not table:
            # Try finding any table with enough rows
            tables = soup.find_all('table')
            for t in tables:
                rows = t.find_all('tr')
                if len(rows) > 2:
                    table = t
                    break
        
        if not table:
            logger.warning(f"   No results table found on {mirror}")
            logger.debug(f"   Page title: {soup.title.string if soup.title else 'N/A'}")
            continue
        
        rows = table.find_all('tr')[1:]  # Skip header
        logger.info(f"   Found {len(rows)} result rows")
        
        for i, row in enumerate(rows[:5]):  # Process top 5
            cols = row.find_all('td')
            if len(cols) < 8:
                continue
            
            try:
                # Extract MD5 from download link
                # LibGen links contain MD5: /book/index.php?md5=XXXX or /main/XXXX
                md5 = None
                for link in row.find_all('a', href=True):
                    href = link['href']
                    
                    # Pattern 1: md5=XXXXX
                    md5_match = re.search(r'md5=([a-fA-F0-9]{32})', href)
                    if md5_match:
                        md5 = md5_match.group(1).upper()
                        break
                    
                    # Pattern 2: /main/XXXXX or /fiction/XXXXX
                    md5_match = re.search(r'/(main|fiction)/([a-fA-F0-9]{32})', href)
                    if md5_match:
                        md5 = md5_match.group(2).upper()
                        break
                
                if not md5:
                    logger.debug(f"   Row {i+1}: No MD5 found in links")
                    continue
                
                # Extract metadata
                title = cols[2].get_text(strip=True)[:80] if len(cols) > 2 else "Unknown"
                author = cols[1].get_text(strip=True)[:50] if len(cols) > 1 else ""
                extension = cols[8].get_text(strip=True).lower() if len(cols) > 8 else "pdf"
                size = cols[7].get_text(strip=True) if len(cols) > 7 else ""
                
                result = {
                    'md5': md5,
                    'title': title,
                    'author': author,
                    'extension': extension,
                    'size': size,
                }
                results.append(result)
                logger.info(f"   ✅ Found: {title[:40]}... [{extension}] MD5: {md5[:8]}...")
                
            except Exception as e:
                logger.debug(f"   Row {i+1} parse error: {e}")
                continue
        
        if results:
            logger.info(f"   Got {len(results)} results from {mirror}")
            return results  # Success, don't try other mirrors
    
    logger.warning(f"No results found for: {search_term}")
    return []

# ============================================================================
# MD5 TO IPFS CID CONVERSION
# ============================================================================

def get_ipfs_cid_from_library_lol(md5: str) -> Optional[str]:
    """
    Get IPFS CID from library.lol using MD5.
    library.lol provides IPFS links for LibGen content.
    """
    logger.info(f"Getting IPFS CID for MD5: {md5[:8]}...")
    
    url = f"{LIBRARY_LOL_URL}/{md5}"
    response = make_request(url, description="library.lol")
    
    if not response:
        logger.warning("   Failed to reach library.lol")
        return None
    
    soup = BeautifulSoup(response.text, 'lxml')
    
    # Look for IPFS link
    for link in soup.find_all('a', href=True):
        href = link['href']
        
        # Pattern: ipfs.io/ipfs/CID or cloudflare-ipfs.com/ipfs/CID
        if '/ipfs/' in href:
            cid_match = re.search(r'/ipfs/([a-zA-Z0-9]+)', href)
            if cid_match:
                cid = cid_match.group(1)
                logger.info(f"   ✅ Found IPFS CID: {cid[:20]}...")
                return cid
    
    # Sometimes the CID is the same as MD5 (older books)
    # Try using MD5 as CID directly (base58 encoded)
    logger.warning("   No IPFS link found on library.lol, will try MD5 as path")
    return None

# ============================================================================
# IPFS GATEWAY DOWNLOAD
# ============================================================================

def download_from_ipfs(cid: str, filename: str) -> bool:
    """
    Download file from IPFS gateways.
    These are standard HTTPS endpoints - rarely blocked!
    """
    logger.info(f"Downloading from IPFS gateways...")
    logger.info(f"   CID: {cid[:30]}...")
    
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    save_path = DOWNLOADS_DIR / filename
    
    for gateway in IPFS_GATEWAYS:
        url = f"{gateway}/{cid}"
        logger.info(f"   Trying: {gateway}")
        
        try:
            # Use longer timeout for file download
            response = make_request(url, timeout=120, description="IPFS download")
            
            if not response:
                continue
            
            # Verify we got actual content
            content_type = response.headers.get('content-type', '')
            content_length = len(response.content)
            
            logger.debug(f"   Content-Type: {content_type}, Size: {content_length}")
            
            if content_length < 1000:
                logger.warning(f"   File too small ({content_length} bytes) - probably error page")
                continue
            
            if 'text/html' in content_type and content_length < 50000:
                logger.warning(f"   Got HTML instead of file - gateway error")
                continue
            
            # Save file
            with open(save_path, 'wb') as f:
                f.write(response.content)
            
            size_mb = save_path.stat().st_size / 1024 / 1024
            logger.info(f"   ✅ SUCCESS! Saved: {filename} ({size_mb:.2f} MB)")
            return True
            
        except Exception as e:
            logger.warning(f"   ❌ {type(e).__name__}: {e}")
            continue
    
    logger.error(f"   Failed all IPFS gateways for CID: {cid[:20]}...")
    return False

# ============================================================================
# ALTERNATIVE: Direct download link from library.lol
# ============================================================================

def download_from_library_lol(md5: str, filename: str) -> bool:
    """
    Alternative: Get direct download link from library.lol
    """
    logger.info(f"Trying library.lol direct download...")
    
    url = f"{LIBRARY_LOL_URL}/{md5}"
    response = make_request(url, description="library.lol page")
    
    if not response:
        return False
    
    soup = BeautifulSoup(response.text, 'lxml')
    
    # Find download links (GET button, Cloudflare link, etc.)
    download_url = None
    for link in soup.find_all('a', href=True):
        text = link.get_text(strip=True).lower()
        href = link['href']
        
        if 'get' in text or 'download' in text:
            download_url = href
            logger.info(f"   Found download link: {href[:50]}...")
            break
    
    if not download_url:
        # Look for h2 with link
        h2 = soup.find('h2')
        if h2:
            link = h2.find('a', href=True)
            if link:
                download_url = link['href']
    
    if not download_url:
        logger.warning("   No download link found")
        return False
    
    # Download the file
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    save_path = DOWNLOADS_DIR / filename
    
    logger.info(f"   Downloading file...")
    response = make_request(download_url, timeout=120, description="file download")
    
    if not response or len(response.content) < 1000:
        logger.warning("   Download failed or file too small")
        return False
    
    with open(save_path, 'wb') as f:
        f.write(response.content)
    
    size_mb = save_path.stat().st_size / 1024 / 1024
    logger.info(f"   ✅ SUCCESS! Saved: {filename} ({size_mb:.2f} MB)")
    return True

# ============================================================================
# MAIN DOWNLOAD LOGIC
# ============================================================================

def select_best_result(results: List[dict]) -> Optional[dict]:
    """Select best format from results."""
    for fmt in PREFERRED_FORMATS:
        for r in results:
            if r.get('extension', '').lower() == fmt:
                return r
    return results[0] if results else None

def download_book(search_term: str) -> bool:
    """
    Main download flow:
    1. Search LibGen → Get MD5
    2. Get IPFS CID from library.lol
    3. Download via IPFS gateway
    4. Fallback: Direct download from library.lol
    """
    logger.info("=" * 50)
    logger.info(f"DOWNLOADING: {search_term}")
    logger.info("=" * 50)
    
    # Step 1: Search LibGen for MD5
    results = search_libgen_for_md5(search_term)
    
    if not results:
        logger.error(f"❌ No results found for: {search_term}")
        return False
    
    # Select best format
    best = select_best_result(results)
    if not best:
        logger.error("❌ No suitable format found")
        return False
    
    md5 = best['md5']
    ext = best.get('extension', 'pdf')
    filename = f"{re.sub(r'[^a-zA-Z0-9 ]', '', search_term)[:50]}.{ext}"
    
    logger.info(f"Selected: {best['title'][:40]}... [{ext}]")
    logger.info(f"MD5: {md5}")
    
    # Step 2: Get IPFS CID
    cid = get_ipfs_cid_from_library_lol(md5)
    
    if cid:
        # Step 3: Download via IPFS gateway
        if download_from_ipfs(cid, filename):
            return True
        logger.warning("IPFS download failed, trying fallback...")
    
    # Step 4: Fallback - direct download from library.lol
    if download_from_library_lol(md5, filename):
        return True
    
    logger.error(f"❌ All download methods failed for: {search_term}")
    return False

# ============================================================================
# MAIN
# ============================================================================

def main():
    global USE_TOR
    
    logger.info("=" * 60)
    logger.info("📚 EBOOK DOWNLOAD AUTOMATION (IPFS Strategy)")
    logger.info("=" * 60)
    logger.info("")
    
    # Check Tor
    USE_TOR = check_tor()
    
    if not USE_TOR:
        logger.warning("⚠️ Continuing without Tor (may get blocked)")
    
    logger.info("")
    
    # Load search terms
    search_terms = parse_search_terms()
    
    if not search_terms:
        logger.error("❌ No search terms found!")
        logger.error("   Create search_terms.txt or books.txt")
        sys.exit(1)
    
    logger.info("")
    
    # Process each term
    successful = []
    failed = []
    
    for i, term in enumerate(search_terms, 1):
        logger.info("")
        logger.info(f"[{i}/{len(search_terms)}] Processing: {term}")
        
        try:
            if download_book(term):
                successful.append(term)
            else:
                failed.append(term)
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            failed.append(term)
        
        if i < len(search_terms):
            logger.info("Waiting 3 seconds...")
            time.sleep(3)
    
    # Final summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 FINAL RESULTS")
    logger.info("=" * 60)
    
    if successful:
        logger.info(f"\n✅ Successfully downloaded ({len(successful)}):")
        for t in successful:
            logger.info(f"   • {t}")
    
    if failed:
        logger.info(f"\n❌ Failed ({len(failed)}):")
        for t in failed:
            logger.info(f"   • {t}")
    
    # List downloaded files
    if DOWNLOADS_DIR.exists():
        files = list(DOWNLOADS_DIR.iterdir())
        if files:
            logger.info(f"\n📁 Files in downloads/:")
            for f in files:
                size = f.stat().st_size / 1024 / 1024
                logger.info(f"   • {f.name} ({size:.2f} MB)")
    
    logger.info("")
    logger.info("=" * 60)
    
    if failed and not successful:
        sys.exit(1)

if __name__ == "__main__":
    main()
