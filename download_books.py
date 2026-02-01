#!/usr/bin/env python3
"""
Ebook Download via Proxy/Tor Routing
Strategy: Brute Force Proxy Routing (Tor) with Retries & Verification
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

# Anna's Archive domains (Prioritize active ones)
ANNAS_ARCHIVE_DOMAINS = [
    "annas-archive.li", 
    "annas-archive.se",
    "annas-archive.org",
]

def get_proxies():
    """Get proxy configuration from environment"""
    proxy_url = os.environ.get("PROXY_URL")
    if proxy_url:
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
            timeout=30
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
        sys.exit(1) # Strict Fail

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
                timeout=60,
                allow_redirects=True
            )
            
            if response.status_code == 200:
                return response.text
            elif response.status_code in [404]:
                logger.warning(f"Page not found: {url}")
                return None # Don't retry 404
            
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
            timeout=300,  # Longer timeout for Tor
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
            
        # Fallback to URL extension
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

def search_annas_archive(query: str) -> dict:
    """Search Anna's Archive via Proxy"""
    query_terms = [t.lower() for t in query.split() if len(t) > 2] 
    
    for domain in ANNAS_ARCHIVE_DOMAINS:
        encoded_query = query.replace(' ', '+')
        url = f"https://{domain}/search?q={encoded_query}"
        
        html = get_page(url)
        if not html:
            continue

        # Extract Results
        matches = re.finditer(r'<a[^>]*href="(/md5/[a-fA-F0-9]{32})"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            link = match.group(1)
            raw_text = match.group(2)
            text = re.sub(r'<[^>]+>', ' ', raw_text).strip()
            text = re.sub(r'\s+', ' ', text)
            
            # Strict Validation
            title_lower = text.lower()
            match_score = sum(1 for term in query_terms if term in title_lower)
            required_matches = max(1, len(query_terms) - 1)
            
            if match_score >= required_matches:
                logger.info(f"Match found: '{text}'")
                return {"url": f"https://{domain}{link}", "title": text}
                
    return None

def process_search(query: str) -> bool:
    """Main processing logic"""
    logging.info(f"Processing: {query}")
    
    # 1. Search
    result = search_annas_archive(query)
    if not result:
        logger.error(f"No valid results found for: {query}")
        return False
        
    book_url = result["url"]
    base_filename = clean_filename(result["title"])
    
    # 2. Extract MD5
    md5_match = re.search(r'/md5/([a-fA-F0-9]{32})', book_url)
    if not md5_match:
        logger.error("Could not extract MD5 from URL")
        return False
        
    md5 = md5_match.group(1)
    
    # 3. Construct LibGen Mirrors
    libgen_mirrors = [
        f"http://library.lol/main/{md5}",
        f"https://libgen.li/ads.php?md5={md5}",
        f"https://libgen.rs/book/index.php?md5={md5}",
        f"https://libgen.is/book/index.php?md5={md5}",
        f"https://libgen.st/book/index.php?md5={md5}",
    ]
    
    # 4. Try Mirrors
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
             r'href="(https?://[^"]*cloudflare[^"]+)"', # often cloudflare backup links
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
    logger.info("Ebook Download - Proxy/Tor Architecture")
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    # Verify Tor Connection
    check_tor_connection()
    
    if not SEARCH_TERMS_FILE.exists():
        sys.exit(1)
        
    search_terms = [l.strip() for l in SEARCH_TERMS_FILE.read_text().split('\n') if l.strip()]
    
    for query in search_terms:
        process_search(query)
        time.sleep(10) # Wait between searches

if __name__ == "__main__":
    main()
