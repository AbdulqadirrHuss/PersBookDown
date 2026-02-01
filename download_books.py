#!/usr/bin/env python3
"""
Ebook Download via WeLib Strict Workflow (DrissionPage Version)
Strategy: Search -> Click Book -> Click 'Read' -> Find Iframe -> Decode URL -> Download
Uses DrissionPage (DevTools Protocol) to bypass Cloudflare detection.
"""

import os
import re
import sys
import time
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

def clean_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name)[:50].strip().replace(' ', '_')

def download_file_curl(url: str, filename: str, referer: str) -> bool:
    """Perform the direct download using curl_cffi for robust TLS"""
    logger.info(f"Downloading: {url} -> {filename}")
    
    try:
        headers = {
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
             "Referer": referer
        }
            
        response = requests.get(
            url,
            headers=headers,
            impersonate="chrome120",
            timeout=300, 
            verify=False,
            allow_redirects=True
        )
        
        if response.status_code != 200:
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

def process_workflow(page, query: str) -> bool:
    """
    Strict Workflow with DrissionPage:
    1. Search & Wait
    2. Click Book
    3. Click Read
    4. Find Iframe -> Extract Src
    5. Decode -> Download
    """
    logger.info(f"Processing: {query}")
    
    # 1. Search
    encoded_query = quote(query)
    search_url = f"https://welib.org/search?q={encoded_query}"
    
    logger.info(f"Navigating to: {search_url}")
    try:
        page.get(search_url)
        
        # Wait for search results (up to 60s)
        logger.info("Waiting for search results...")
        book_selector = "div.cursor-pointer, a[href*='/text/'], a[href*='/book/']"
        
        book_element = page.ele(book_selector, timeout=60)
        if not book_element:
            logger.error("No search results found.")
            page.get_screenshot(path="debug_error.png")
            with open("debug_error.html", "w", encoding="utf-8") as f:
                f.write(page.html)
            return False
            
        # 2. Click Book
        logger.info("Clicking first book result...")
        book_element.click()
        page.wait.load_start()
        
        logger.info(f"On Book Page: {page.url}")
        
    except Exception as e:
        logger.error(f"Search/Navigation error: {e}")
        try:
            page.get_screenshot(path="debug_error.png")
        except:
            pass
        return False

    # 3. Click 'Read'
    try:
        logger.info("Looking for 'Read' button...")
        
        # Wait and find Read button
        read_element = page.ele("text:Read", timeout=30) or page.ele("a[href*='/read/']", timeout=10)
        
        if not read_element:
            logger.warning("Could not find Read button.")
            page.get_screenshot(path="debug_no_read.png")
            return False
            
        logger.info("Clicking Read...")
        read_element.click()
        page.wait.load_start()
        
        logger.info(f"On Viewer Page: {page.url}")
        
    except Exception as e:
        logger.error(f"Error clicking Read: {e}")
        return False
        
    # 4. Wait for Iframe
    logger.info("Waiting for viewer iframe...")
    try:
        # Look for iframe with viewer_frame id or fast_view/web-premium in src
        iframe_element = page.ele("iframe#viewer_frame", timeout=60) or \
                        page.ele("iframe[src*='fast_view']", timeout=10) or \
                        page.ele("iframe[src*='web-premium']", timeout=10)
        
        if not iframe_element:
            logger.error("Could not find viewer iframe.")
            page.get_screenshot(path="debug_no_iframe.png")
            with open("debug_iframe.html", "w", encoding="utf-8") as f:
                f.write(page.html)
            return False
        
        src = iframe_element.attr("src")
        if not src:
            logger.error("Iframe has no src attribute.")
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
            
        # 6. Download
        safe_title = clean_filename(query)
        ext = ".pdf"
        if ".epub" in real_url: ext = ".epub"
        elif ".mobi" in real_url: ext = ".mobi"
        
        filename = f"{safe_title}{ext}"
        
        return download_file_curl(real_url, filename, referer=page.url)

    except Exception as e:
        logger.error(f"Iframe error: {e}")
        try:
            page.get_screenshot(path="debug_iframe_error.png")
        except:
            pass
        return False

def main():
    logger.info("Starting WeLib DrissionPage Workflow...")
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    if not SEARCH_TERMS_FILE.exists():
        logger.error("search_terms.txt not found!")
        sys.exit(1)
        
    search_terms = [l.strip() for l in SEARCH_TERMS_FILE.read_text(encoding='utf-8-sig').split('\n') if l.strip()]
    logger.info(f"Loaded {len(search_terms)} terms.")
    
    # Setup ChromiumPage with headless options for CI
    options = ChromiumOptions()
    options.headless()
    options.set_argument('--no-sandbox')
    options.set_argument('--disable-gpu')
    options.set_argument('--disable-dev-shm-usage')
    
    logger.info("Launching Browser (DrissionPage/DevTools)...")
    page = ChromiumPage(options)
    
    for term in search_terms:
        try:
            if process_workflow(page, term):
                logger.info(f"SUCCESS: {term}")
            else:
                logger.error(f"FAILED: {term}")
        except Exception as e:
            logger.error(f"Workflow Exception: {e}")
            
        time.sleep(5)
        
    page.quit()

if __name__ == "__main__":
    main()
