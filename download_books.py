#!/usr/bin/env python3
"""
Ebook Download via WeLib Strict Workflow
Strategy: Search -> Click Book -> Click 'Read' -> Find Iframe -> Decode URL -> Download
Constaint: NO LibGen, NO 'Download' buttons.
"""

import os
import re
import sys
import time
import logging
from pathlib import Path
from urllib.parse import urljoin, unquote, quote
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
        return {"http": proxy_url, "https": proxy_url}
    return None

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
            
            # Simple sleep to be polite
            time.sleep(1)
            
            logger.info(f"Fetching: {url}")
            response = requests.get(
                url,
                headers=headers,
                proxies=proxies,
                impersonate="chrome110",
                timeout=60,
                verify=False,
                allow_redirects=True
            )
            
            if response.status_code == 200:
                return response.text
                
            logger.warning(f"Request failed: {url} [{response.status_code}]")
            
        except Exception as e:
            logger.warning(f"Network error on {url}: {e}")
            
        time.sleep(2 * (attempt + 1))
        
    logger.error(f"Failed to get {url}")
    return None

def clean_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name)[:50].strip().replace(' ', '_')

def download_from_url(url: str, filename: str, referer: str) -> bool:
    """Perform the direct download from the decoded URL"""
    proxies = get_proxies()
    logger.info(f"Starting Download: {url} -> {filename}")
    
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
            
        # Verify content type if possible, or just save
        save_path = DOWNLOADS_DIR / filename
            
        with open(save_path, 'wb') as f:
            f.write(response.content)
            
        size = save_path.stat().st_size
        logger.info(f"Downloaded {size:,} bytes to {filename}")
        
        if size < 1000:
            logger.warning("File too small, likely an error page.")
            return False
            
        return True
    except Exception as e:
        logger.error(f"Download fatal error: {e}")
        return False

def process_workflow(query: str) -> bool:
    """
    Strict Workflow:
    1. Search
    2. Click Book
    3. Click Read
    4. Find Iframe -> Extract Src
    5. Decode -> Download
    """
    logger.info(f"Processing Search: {query}")
    
    # 1. Search
    encoded_query = quote(query)
    search_url = f"https://welib.org/search?q={encoded_query}"
    html = get_page(search_url)
    if not html:
        return False
        
    # 2. Click Book
    # Regex to find the first book link. usually /text/ID or /book/ID
    # We prefer /text/ as it usually leads to the main book page
    book_match = re.search(r'href="(/text/[^"]+)"', html) or re.search(r'href="(/book/[^"]+)"', html)
    if not book_match:
        logger.warning("No book found in search results.")
        return False
        
    book_path = book_match.group(1)
    book_url = f"https://welib.org{book_path}"
    logger.info(f"Found Book Page: {book_url}")
    
    # 3. Click 'Read'
    book_html = get_page(book_url, referer=search_url)
    if not book_html:
        return False
        
    # Find the "Read" button.
    # Look for href containing "read" or text matching "Read"
    # Example: <a href="/read/..." class="btn ...">Read</a>
    # We look for the link that contains '/read/'
    read_match = re.search(r'href="(/read/[^"]+)"', book_html)
    
    # Fallback: link with text "Read"
    if not read_match:
        read_match = re.search(r'href="([^"]+)"[^>]*>\s*Read\s*</a>', book_html, re.IGNORECASE)
        
    if not read_match:
        logger.warning("Could not find 'Read' button on book page.")
        return False
        
    read_path = read_match.group(1)
    read_url = f"https://welib.org{read_path}"
    logger.info(f"Triggering Viewer (Clicking Read): {read_url}")
    
    # 4. Wait for Iframe (Fetch Read Page)
    # The user says "Wait for DOM to load <iframe id='viewer_frame'>".
    # In requests, we get the static HTML. We hope the iframe is there.
    viewer_html = get_page(read_url, referer=book_url)
    if not viewer_html:
        return False
        
    # Look for iframe src
    # Pattern: <iframe id="viewer_frame" src="...">
    # Or just any iframe with 'web-premium' or 'fast_view' as per prompt
    iframe_match = re.search(r'<iframe[^>]+src="([^"]+)"', viewer_html)
    iframe_src = None
    
    if iframe_match:
        # Check if it looks right
        src_candidate = iframe_match.group(1)
        if "viewer_frame" in viewer_html or "fast_view" in src_candidate or "web-premium" in src_candidate:
             iframe_src = src_candidate
             
    # Fallback regex specific to prompt example
    if not iframe_src:
        # Look for the specific src pattern
        fallback_match = re.search(r'src="(/fast_view\?url=[^"]+)"', viewer_html)
        if fallback_match:
            iframe_src = fallback_match.group(1)
            
    if not iframe_src:
        logger.warning("Could not locate viewer iframe (id='viewer_frame' or src='/fast_view...').")
        logger.debug(f"Viewer HTML snippet: {viewer_html[:500]}")
        return False
        
    logger.info(f"Found Iframe Src: {iframe_src}")
    
    # 5. Extract & Decode URL
    # format: /fast_view?url=https%3A%2F%2F...
    # We need to parse valid URL from this.
    
    # Handle relative path
    full_iframe_url = urljoin("https://welib.org", iframe_src)
    
    # Parse querystring
    parsed_url = urllib.parse.urlparse(full_iframe_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    
    real_file_url_encoded = query_params.get('url', [None])[0]
    
    if not real_file_url_encoded:
        logger.warning(f"Could not extract 'url' parameter from iframe src: {iframe_src}")
        return False
        
    # 6. Decode
    # The prompt says: "Decode it (convert %3A -> :) to get the real file link."
    # requests/urllib might have done some, but we ensure it's fully decoded
    # Actually param extraction does *some* decoding, but unquote is safer.
    real_file_url = unquote(real_file_url_encoded)
    
    # Double check if it needs more decoding? usually standard parse_qs does it.
    # But prompt explicitly asked for it. 
    # Example: https%3A%2F%2F -> https://
    # If parse_qs already did it, great.
    
    logger.info(f"Decoded Real File URL: {real_file_url}")
    
    if not real_file_url.startswith("http"):
        logger.warning("Decoded URL does not look like a valid link.")
        return False
        
    # Determine Filename
    # We use search query as base, plus extension from url or default pdf
    safe_title = clean_filename(query)
    ext = ".pdf"
    if ".epub" in real_file_url: ext = ".epub"
    elif ".mobi" in real_file_url: ext = ".mobi"
    
    filename = f"{safe_title}{ext}"
    
    # 7. Download
    return download_from_url(real_file_url, filename, referer=read_url)

def main():
    logger.info("Starting WeLib Strict Workflow...")
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    # Check proxy
    proxies = get_proxies()
    if proxies:
        logger.info(f"Using Proxy: {proxies['http']}")
    else:
        logger.info("No Proxy Configured (Direct Connection)")
        
    if not SEARCH_TERMS_FILE.exists():
        logger.error("search_terms.txt not found!")
        sys.exit(1)
        
    search_terms = [l.strip() for l in SEARCH_TERMS_FILE.read_text(encoding='utf-8-sig').split('\n') if l.strip()]
    logger.info(f"Loaded {len(search_terms)} terms.")
    
    for term in search_terms:
        success = process_workflow(term)
        if success:
            logger.info(f"SUCCESS: {term}")
        else:
            logger.error(f"FAILED: {term}")
            
        time.sleep(10) # Wait between books
        
if __name__ == "__main__":
    main()
