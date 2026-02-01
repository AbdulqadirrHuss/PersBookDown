#!/usr/bin/env python3
"""
Ebook Download via WeLib Strict Workflow (Playwright Version)
Strategy: Search -> Click Book -> Click 'Read' -> Find Iframe -> Decode URL -> Download
Constaint: NO LibGen, NO 'Download' buttons.
Uses Playwright to handle JS rendering and specific element waits.
"""

import os
import re
import sys
import time
import logging
from pathlib import Path
from urllib.parse import urljoin, unquote, quote
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_sync
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

def get_proxies():
    """Get proxy configuration from environment"""
    proxy_url = os.environ.get("PROXY_URL")
    if proxy_url:
        # Chromium (Playwright) doesn't support socks5h://, replace with socks5://
        if proxy_url.startswith("socks5h://"):
            proxy_url = proxy_url.replace("socks5h://", "socks5://")
        return {"server": proxy_url}
    return None

def clean_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name)[:50].strip().replace(' ', '_')

def download_file_curl(url: str, filename: str, referer: str) -> bool:
    """Perform the direct download using curl_cffi for robust TLS impersonation"""
    logger.info(f"Starting Download (curl_cffi): {url} -> {filename}")
    
    proxies = None
    env_proxy = os.environ.get("PROXY_URL")
    if env_proxy:
        proxies = {"http": env_proxy, "https": env_proxy}

    try:
        headers = {
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
             "Referer": referer
        }
            
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
            logger.error(f"Download request failed: {response.status_code}")
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
        logger.error(f"Download fatal error: {e}")
        return False

def process_workflow(page, query: str) -> bool:
    """
    Strict Workflow with Playwright:
    1. Search & Wait
    2. Click Book & Wait
    3. Click Read & Wait
    4. Find Iframe -> Extract Src
    5. Decode -> Download
    """
    logger.info(f"Processing Search: {query}")
    
    # 1. Search
    encoded_query = quote(query)
    search_url = f"https://welib.org/search?q={encoded_query}"
    
    logger.info(f"Navigating to: {search_url}")
    try:
        page.goto(search_url, timeout=60000, wait_until="domcontentloaded")
        
        # Explicit Wait for results
        # "Wait for elements with class div.cursor-pointer or the generic img[alt]"
        logger.info("Waiting for search results...")
        try:
            page.wait_for_selector("div.cursor-pointer, img[alt]", timeout=60000)
        except PlaywrightTimeoutError:
            logger.error("Timeout waiting for search results.")
            page.screenshot(path="debug_error.png")
            with open("debug_error.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            return False
            
        # 2. Click Book
        # We need to find the link that looks like a book.
        # usually inside the div.cursor-pointer or wrapping the img.
        # We prefer a link with /text/ or /book/
        
        # Strategy: Get all links and filter
        # OR: click the first div.cursor-pointer
        
        logger.info("Clicking first book result...")
        # Finding the first suitable book card
        book_locator = page.locator("div.cursor-pointer").first
        if not book_locator.count():
             # Fallback to links containing /text/ or /book/
             book_locator = page.locator("a[href*='/text/'], a[href*='/book/']").first
             
        if not book_locator.count():
            logger.warning("No book links found.")
            return False
            
        # Capture URL for logging (optional)
        # click it
        with page.expect_navigation(timeout=30000):
            book_locator.click()
            
        logger.info(f"Landed on Book Page: {page.url}")
        
    except Exception as e:
        logger.error(f"Navigation/Search error: {e}")
        return False

    # 3. Click 'Read'
    try:
        # "Locate and click the blue 'Read' button."
        # Selectors: text="Read", a[href*="/read/"], .btn-primary containing Read
        logger.info("Looking for 'Read' button...")
        
        read_locator = page.locator("text=Read").first
        if not read_locator.count():
             read_locator = page.locator("a[href*='/read/']").first
             
        if not read_locator.count():
            logger.warning("Could not find Read button.")
            page.screenshot(path="debug_no_read_button.png")
            return False
            
        # Click and wait for the viewer
        logger.info("Clicking Read...")
        
        # This might open in new tab or same tab. We assume same tab or handle popup.
        # Note: If it opens a new tab, page.on('popup') is better, but let's try strict navigation first.
        # Often these simple sites just navigate.
        with page.expect_navigation(timeout=30000):
            read_locator.click()
            
        logger.info(f"Landed on Viewer Page: {page.url}")
        
    except Exception as e:
        logger.error(f"Error clicking Read: {e}")
        return False
        
    # 4. Wait for Iframe
    logger.info("Waiting for viewer iframe...")
    try:
        # "Wait for the DOM to load the element <iframe id='viewer_frame'> (or ... containing web-premium or fast_view)"
        selector = "iframe#viewer_frame, iframe[src*='fast_view'], iframe[src*='web-premium']"
        page.wait_for_selector(selector, timeout=60000)
        
        iframe_element = page.locator(selector).first
        src = iframe_element.get_attribute("src")
        
        if not src:
            logger.error("Iframe found but no src attribute.")
            return False
            
        logger.info(f"Found Iframe Src: {src}")
        
        # 5. Extract & Decode
        # Format: /fast_view?url=ENCODED_URL
        
        full_src = urljoin("https://welib.org", src)
        import urllib.parse
        parsed = urllib.parse.urlparse(full_src)
        qs = urllib.parse.parse_qs(parsed.query)
        
        real_url_encoded = qs.get('url', [None])[0]
        if not real_url_encoded:
            logger.warning(f"No 'url' param in src: {src}")
            return False
            
        real_url = unquote(real_url_encoded)
        logger.info(f"Decoded Real URL: {real_url}")
        
        if not real_url.startswith("http"):
            logger.warning("Decoded URL invalid.")
            return False
            
        # 6. Download
        safe_title = clean_filename(query)
        ext = ".pdf"
        if ".epub" in real_url: ext = ".epub"
        elif ".mobi" in real_url: ext = ".mobi"
        
        filename = f"{safe_title}{ext}"
        
        return download_file_curl(real_url, filename, referer=page.url)

    except Exception as e:
        logger.error(f"Error waiting for iframe: {e}")
        page.screenshot(path="debug_iframe_error.png")
        return False

def main():
    logger.info("Starting WeLib Playwright Workflow...")
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    if not SEARCH_TERMS_FILE.exists():
        logger.error("search_terms.txt not found!")
        sys.exit(1)
        
    search_terms = [l.strip() for l in SEARCH_TERMS_FILE.read_text(encoding='utf-8-sig').split('\n') if l.strip()]
    logger.info(f"Loaded {len(search_terms)} terms.")
    
    # Launch Playwright
    with sync_playwright() as p:
        # Launch Browser
        # If proxy env set, use it. But usually Tor runs on localhost:9050.
        # We let requests handle the download proxy, but browser might need it too to access welib.
        # Note: WeLib might block Tor? If so, browser needs to be direct?
        # User said "Replace all others", didn't strictly say "Use Tor".
        # But previous code used Tor.
        # If running in GitHub Actions with tor service, PROXY_URL is set.
        # We apply proxy to context.
        
        proxy_config = None # Force Direct Connection (ignore env proxy for Playwright)
        browser_args = ["--no-sandbox", "--disable-setuid-sandbox"]
        
        logger.info("Launching Browser (Direct Connection)...")
        browser = p.chromium.launch(headless=True, args=browser_args)
        
        context_args = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
            "viewport": {"width": 1280, "height": 720}
        }
        # Proxy removed from context_args
            
        context = browser.new_context(**context_args)
        page = context.new_page()
        
        # CRITICAL: Apply stealth BEFORE navigating
        stealth_sync(page)
        logger.info("Stealth applied to page.")
        
        for term in search_terms:
            try:
                if process_workflow(page, term):
                    logger.info(f"SUCCESS: {term}")
                else:
                    logger.error(f"FAILED: {term}")
            except Exception as e:
                logger.error(f"Workflow Exception: {e}")
                
            time.sleep(5)
            
        browser.close()

if __name__ == "__main__":
    main()
