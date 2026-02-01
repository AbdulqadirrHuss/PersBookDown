#!/usr/bin/env python3
"""
Ebook Download via Proxy/Tor Routing
Strategy: Direct LibGen Search (Tor)
Dependencies: curl_cffi (TLS Impersonation) + Tor (IP Masking)
"""

import os
import re
import sys
import time
import logging
from pathlib import Path
from urllib.parse import urljoin
from curl_cffi import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DOWNLOADS_DIR = Path("downloads")
SEARCH_TERMS_FILE = Path("search_terms.txt")

# LibGen Mirrors
LIBGEN_MIRRORS = [
    "https://libgen.rs",
    "https://libgen.li",
    "https://libgen.st",
    "https://libgen.is",
]

def get_proxies():
    """Get proxy configuration from environment"""
    # Debug: Print all PROXY_ env vars
    for k, v in os.environ.items():
        if k.startswith("PROXY_"):
            logger.info(f"DEBUG ENV: {k}={v}")
            
    proxy_url = os.environ.get("PROXY_URL")
    if proxy_url:
        logger.info(f"Confirmed Proxy in Script: {proxy_url}")
        return {"http": proxy_url, "https": proxy_url}
    return None

def check_tor_connection():
    """Verify that we are routed through Tor"""
    logger.info("Verifying Tor connection...")
    proxies = get_proxies()
    if not proxies:
        logger.warning("No PROXY_URL set. Verification skipped (Direct Connection).")
        return

    try:
        # Check IP
        response = requests.get(
            "https://checkip.amazonaws.com",
            proxies=proxies,
            impersonate="chrome110",
            timeout=90,
            verify=False
        )
        if response.status_code == 200:
            ip = response.text.strip()
            logger.info(f"Tor Connection Confirmed. Masked IP: {ip}")
            return True
        else:
            logger.error(f"Tor verification failed with status: {response.status_code}")
    except Exception as e:
        logger.error(f"Tor verification failed: {e}")
        logger.error("Is the Tor service running? Check port 9050.")
        if os.environ.get("PROXY_URL"):
             sys.exit(1) # Strict Fail only if proxy was expected

def get_page(url: str, referer: str = None, retries: int = 3) -> str:
    """Get page content using curl_cffi with Proxy and Retries"""
    proxies = get_proxies()
    
    for attempt in range(retries):
        try:
            headers = {
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
            }
            if referer:
                headers["Referer"] = referer
            
            logger.info(f"Fetching: {url} (Attempt {attempt+1}/{retries})")
            response = requests.get(
                url,
                headers=headers,
                proxies=proxies,
                impersonate="chrome110",
                timeout=90,
                verify=False,
                allow_redirects=True
            )
            
            if response.status_code == 200:
                return response.text
            elif response.status_code in [404]:
                logger.warning(f"Page not found: {url}")
                return None 
            
            logger.warning(f"Request failed: {url} [{response.status_code}]")
            
        except Exception as e:
            logger.warning(f"Network error on {url}: {e}")
            
        time.sleep(2 * (attempt + 1)) # Backoff
        
    logger.error(f"Failed to get {url} after {retries} attempts")
    return None

def clean_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name)[:50].strip().replace(' ', '_')

def download_file(url: str, base_filename: str, referer: str = None) -> bool:
    """Download file via Proxy"""
    proxies = get_proxies()
    logger.info(f"Downloading: {url[:80]}...")
    
    try:
        headers = {
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        }
        if referer:
            headers["Referer"] = referer
            
        response = requests.get(
            url,
            headers=headers,
            proxies=proxies,
            impersonate="chrome110",
            timeout=300, 
            verify=False,
            allow_redirects=True
        )
        
        if response.status_code != 200:
            logger.error(f"Download blocked/failed: {response.status_code}")
            return False
            
        content_type = response.headers.get('content-type', '').lower()
        content_disposition = response.headers.get('content-disposition', '')
        
        if 'text/html' in content_type:
            logger.error("Got HTML instead of file (likely landing page or error)")
            return False
            
        # Dynamic Extension Detection
        extension = ""
        filename_match = re.search(r'filename="?([^"]+)"?', content_disposition)
        if filename_match:
            original_name = filename_match.group(1)
            ext = os.path.splitext(original_name)[1].lower()
            if ext in ['.pdf', '.epub', '.mobi', '.azw3', '.djvu', '.zip', '.rar']:
                extension = ext
        
        if not extension:
            if 'pdf' in content_type: extension = '.pdf'
            elif 'epub' in content_type: extension = '.epub'
            elif 'mobi' in content_type: extension = '.mobi'
            elif 'zip' in content_type: extension = '.zip'
            
        if not extension:
            ext = os.path.splitext(url.split('?')[0])[1].lower()
            if ext in ['.pdf', '.epub', '.mobi']:
                extension = ext
        
        if not extension:
            extension = '.pdf'
            
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

def search_libgen_direct(query: str) -> dict:
    """Search LibGen directly - bypasses Anna's Archive"""
    for base_url in LIBGEN_MIRRORS:
        search_url = f"{base_url}/search.php?req={query.replace(' ', '+')}"
        logger.info(f"Searching: {search_url}")
        
        html = get_page(search_url)
        if not html:
            continue
        
        # Parse LibGen table for first result
        # Pattern: mirror links contain MD5
        md5_match = re.search(r'[?&]md5=([a-fA-F0-9]{32})', html)
        title_match = re.search(r'<a[^>]+title="([^"]+)"', html)
        
        if md5_match:
            title = title_match.group(1) if title_match else query
            
            # Simple header cleaning
            title = re.sub(r'<[^>]+>', '', title).strip()
            
            logger.info(f"Match found: '{title}'")
            return {"md5": md5_match.group(1), "title": title}
            
    logger.warning("No results found on LibGen")
    return None

def process_search(query: str) -> bool:
    """Main processing logic"""
    logging.info(f"Processing: {query}")
    
    # 1. Search LibGen Direct
    result = search_libgen_direct(query)
    if not result:
        logger.error(f"No valid results found for: {query}")
        return False
        
    md5 = result["md5"]
    base_filename = clean_filename(result["title"])
    
    # 2. Construct LibGen Mirrors
    libgen_mirrors = [
        f"http://library.lol/main/{md5}",
        f"https://libgen.li/ads.php?md5={md5}",
        f"https://libgen.rs/book/index.php?md5={md5}",
        f"https://libgen.is/book/index.php?md5={md5}",
        f"https://libgen.st/book/index.php?md5={md5}",
    ]
    
    # 3. Try Mirrors
    for mirror in libgen_mirrors:
        logger.info(f"Trying mirror: {mirror}")
        
        # Get Landing Page
        html = get_page(mirror)
        if not html:
            continue
            
        # Parse for GET link
        patterns = [
            r'href="(https?://[^"]+/get\.php\?[^"]+)"',
            r'<a[^>]+href="([^"]+)"[^>]*>\s*GET\s*</a>',
            r'<a[^>]+href="([^"]+)"[^>]*>.*?GET.*?</a>',
             r'href="(https?://[^"]+\.(?:pdf|epub|mobi))"',
             r'href="(https?://[^"]*cloudflare[^"]+)"', 
        ]
        
        download_link = None
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                download_link = match.group(1)
                if not download_link.startswith('http'):
                    download_link = urljoin(mirror, download_link)
                break
        
        if download_link:
            if download_file(download_link, base_filename, referer=mirror):
                return True
                
    logger.error("All mirrors failed")
    return False

def main():
    logger.info("Ebook Download - LibGen Direct + Tor")
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    # Verify Tor Connection
    check_tor_connection()
    
    if not SEARCH_TERMS_FILE.exists():
        sys.exit(1)
        
    search_terms = [l.strip() for l in SEARCH_TERMS_FILE.read_text().split('\n') if l.strip()]
    
    for query in search_terms:
        process_search(query)
        time.sleep(15) 

if __name__ == "__main__":
    main()
