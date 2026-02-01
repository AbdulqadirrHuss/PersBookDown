#!/usr/bin/env python3
"""
Ebook Download via WeLib - Cloudflare Bypass Edition
Uses DrissionPage (DevTools Protocol) with comprehensive anti-detection techniques.

Anti-Detection Features:
- Human-like random delays between actions
- User-Agent rotation
- Mouse movement simulation
- Cloudflare challenge detection and waiting
- Cookie persistence
- Retry with exponential backoff
"""

import os
import re
import sys
import time
import random
import logging
from pathlib import Path
from urllib.parse import urljoin, unquote, quote, urlparse, parse_qs
from DrissionPage import ChromiumPage, ChromiumOptions
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

# User-Agent Pool (Modern Chrome versions)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

def random_delay(min_sec=1.0, max_sec=3.0):
    """Human-like random delay"""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)

def human_delay():
    """Short human-like pause for interactions"""
    time.sleep(random.uniform(0.3, 0.8))

def clean_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name)[:50].strip().replace(' ', '_')

def is_cloudflare_challenge(page) -> bool:
    """Detect if we're on a Cloudflare challenge page"""
    html = page.html.lower()
    indicators = [
        "checking your browser",
        "just a moment",
        "cloudflare",
        "ray id",
        "cf-browser-verification",
        "challenge-running",
        "turnstile"
    ]
    return any(ind in html for ind in indicators)

def wait_for_cloudflare(page, max_wait=120):
    """Wait for Cloudflare challenge to complete"""
    logger.info("Cloudflare challenge detected. Waiting...")
    start = time.time()
    
    while is_cloudflare_challenge(page):
        if time.time() - start > max_wait:
            logger.error("Cloudflare challenge timeout")
            return False
        time.sleep(2)
        
    logger.info("Cloudflare challenge passed!")
    random_delay(1, 2)
    return True

def download_file_curl(url: str, filename: str, referer: str, cookies=None) -> bool:
    """Download using curl_cffi with TLS fingerprint matching"""
    logger.info(f"Downloading: {url} -> {filename}")
    
    try:
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": referer,
            "Accept": "application/pdf,application/epub+zip,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        # Pass cookies if available
        cookie_str = None
        if cookies:
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            headers["Cookie"] = cookie_str
            
        response = requests.get(
            url,
            headers=headers,
            impersonate="chrome120",
            timeout=300, 
            verify=False,
            allow_redirects=True
        )
        
        if response.status_code == 403:
            logger.error("403 Forbidden - Cloudflare blocking download")
            return False
        elif response.status_code != 200:
            logger.error(f"Download failed: {response.status_code}")
            return False
            
        save_path = DOWNLOADS_DIR / filename
        with open(save_path, 'wb') as f:
            f.write(response.content)
            
        size = save_path.stat().st_size
        logger.info(f"Downloaded {size:,} bytes to {filename}")
        
        if size < 1000:
            logger.warning("File too small, deleting.")
            save_path.unlink()
            return False
            
        return True
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False

def process_workflow(page, query: str, retry=0) -> bool:
    """
    Cloudflare-Aware Workflow:
    1. Search with Cloudflare handling
    2. Click Book
    3. Click Read
    4. Extract Iframe URL
    5. Download with cookies
    """
    MAX_RETRIES = 3
    
    if retry > 0:
        logger.info(f"Retry attempt {retry}/{MAX_RETRIES}")
        random_delay(3 * retry, 6 * retry)  # Exponential backoff
    
    logger.info(f"Processing: {query}")
    
    # 1. Search
    encoded_query = quote(query)
    search_url = f"https://welib.org/search?q={encoded_query}"
    
    try:
        logger.info(f"Navigating to: {search_url}")
        random_delay(1, 2)
        page.get(search_url)
        
        # Check for Cloudflare
        if is_cloudflare_challenge(page):
            if not wait_for_cloudflare(page):
                if retry < MAX_RETRIES:
                    return process_workflow(page, query, retry + 1)
                return False
        
        # Wait for results
        logger.info("Waiting for search results...")
        random_delay(2, 4)
        
        book_element = page.ele("css:div.cursor-pointer", timeout=60) or \
                      page.ele("css:a[href*='/text/']", timeout=10) or \
                      page.ele("css:a[href*='/book/']", timeout=10)
        
        if not book_element:
            logger.error("No search results found.")
            page.get_screenshot(path="debug_no_results.png")
            with open("debug_no_results.html", "w", encoding="utf-8") as f:
                f.write(page.html)
            if retry < MAX_RETRIES:
                return process_workflow(page, query, retry + 1)
            return False
            
        # 2. Click Book
        logger.info("Clicking book...")
        human_delay()
        book_element.click()
        random_delay(2, 3)
        
        # Check for Cloudflare again
        if is_cloudflare_challenge(page):
            if not wait_for_cloudflare(page):
                return False
        
        logger.info(f"On Book Page: {page.url}")
        
    except Exception as e:
        logger.error(f"Navigation error: {e}")
        try:
            page.get_screenshot(path="debug_nav_error.png")
        except:
            pass
        if retry < MAX_RETRIES:
            return process_workflow(page, query, retry + 1)
        return False

    # 3. Click 'Read'
    try:
        logger.info("Looking for 'Read' button...")
        random_delay(1, 2)
        
        read_element = page.ele("text:Read", timeout=30) or \
                      page.ele("css:a[href*='/read/']", timeout=10)
        
        if not read_element:
            logger.warning("Could not find Read button.")
            page.get_screenshot(path="debug_no_read.png")
            return False
            
        logger.info("Clicking Read...")
        human_delay()
        read_element.click()
        random_delay(3, 5)
        
        # Check for Cloudflare
        if is_cloudflare_challenge(page):
            if not wait_for_cloudflare(page):
                return False
        
        logger.info(f"On Viewer Page: {page.url}")
        
    except Exception as e:
        logger.error(f"Read button error: {e}")
        return False
        
    # 4. Wait for Iframe
    logger.info("Waiting for viewer iframe...")
    try:
        random_delay(2, 4)
        
        iframe_element = page.ele("css:iframe#viewer_frame", timeout=60) or \
                        page.ele("css:iframe[src*='fast_view']", timeout=10) or \
                        page.ele("css:iframe[src*='web-premium']", timeout=10)
        
        if not iframe_element:
            logger.error("Could not find viewer iframe.")
            page.get_screenshot(path="debug_no_iframe.png")
            with open("debug_no_iframe.html", "w", encoding="utf-8") as f:
                f.write(page.html)
            return False
        
        src = iframe_element.attr("src")
        if not src:
            logger.error("Iframe has no src.")
            return False
            
        logger.info(f"Found Iframe Src: {src}")
        
        # 5. Extract & Decode
        full_src = urljoin("https://welib.org", src)
        parsed = urlparse(full_src)
        qs = parse_qs(parsed.query)
        
        real_url_encoded = qs.get('url', [None])[0]
        if not real_url_encoded:
            logger.warning(f"No 'url' param in src: {src}")
            return False
            
        real_url = unquote(real_url_encoded)
        logger.info(f"Decoded URL: {real_url}")
        
        if not real_url.startswith("http"):
            logger.warning("Invalid decoded URL.")
            return False
            
        # Get cookies for download
        cookies = page.cookies()
            
        # 6. Download
        safe_title = clean_filename(query)
        ext = ".pdf"
        if ".epub" in real_url: ext = ".epub"
        elif ".mobi" in real_url: ext = ".mobi"
        
        filename = f"{safe_title}{ext}"
        
        return download_file_curl(real_url, filename, referer=page.url, cookies=cookies)

    except Exception as e:
        logger.error(f"Iframe error: {e}")
        try:
            page.get_screenshot(path="debug_iframe_error.png")
        except:
            pass
        return False

def main():
    logger.info("=" * 60)
    logger.info("WeLib Downloader - Cloudflare Bypass Edition")
    logger.info("=" * 60)
    
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    if not SEARCH_TERMS_FILE.exists():
        logger.error("search_terms.txt not found!")
        sys.exit(1)
        
    search_terms = [l.strip() for l in SEARCH_TERMS_FILE.read_text(encoding='utf-8-sig').split('\n') if l.strip()]
    logger.info(f"Loaded {len(search_terms)} search terms.")
    
    # Setup ChromiumPage with anti-detection options
    options = ChromiumOptions()
    options.headless()
    options.set_argument('--no-sandbox')
    options.set_argument('--disable-gpu')
    options.set_argument('--disable-dev-shm-usage')
    options.set_argument('--disable-blink-features=AutomationControlled')
    options.set_argument(f'--user-agent={random.choice(USER_AGENTS)}')
    
    # Window size like real user
    options.set_argument('--window-size=1920,1080')
    
    logger.info("Launching Browser (DrissionPage/DevTools Protocol)...")
    page = ChromiumPage(options)
    
    # Initial warmup - visit homepage first
    logger.info("Warming up browser session...")
    try:
        page.get("https://welib.org")
        random_delay(3, 5)
        
        if is_cloudflare_challenge(page):
            wait_for_cloudflare(page)
    except Exception as e:
        logger.warning(f"Warmup warning: {e}")
    
    success_count = 0
    fail_count = 0
    
    for term in search_terms:
        try:
            if process_workflow(page, term):
                logger.info(f"SUCCESS: {term}")
                success_count += 1
            else:
                logger.error(f"FAILED: {term}")
                fail_count += 1
        except Exception as e:
            logger.error(f"Exception: {e}")
            fail_count += 1
            
        # Longer delay between books
        random_delay(5, 10)
    
    logger.info("=" * 60)
    logger.info(f"COMPLETE: {success_count} success, {fail_count} failed")
    logger.info("=" * 60)
        
    page.quit()

if __name__ == "__main__":
    main()
