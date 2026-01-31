#!/usr/bin/env python3
"""
Ebook Download from welib.org using cloudscraper to bypass Cloudflare
"""

import os
import re
import sys
import time
import logging
from pathlib import Path

import cloudscraper

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DOWNLOADS_DIR = Path("downloads")
SEARCH_TERMS_FILE = Path("search_terms.txt")

# Create scraper that can bypass Cloudflare
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)


def search_welib(query: str) -> dict:
    """Search welib.org and return first result"""
    
    encoded_query = query.replace(' ', '%20')
    url = f"https://welib.org/search?q={encoded_query}"
    
    logger.info(f"Searching: {url}")
    logger.info("Waiting 5 seconds before request...")
    time.sleep(5)
    
    try:
        response = scraper.get(url, timeout=60)
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response length: {len(response.text)} characters")
        
        # Save for debugging
        with open('/tmp/welib_search.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        logger.info("Saved response to /tmp/welib_search.html")
        
        if response.status_code != 200:
            logger.error(f"Bad status code: {response.status_code}")
            logger.error(f"Response: {response.text[:1000]}")
            return None
        
        # Check if still blocked
        if 'Cloudflare' in response.text and 'blocked' in response.text.lower():
            logger.error("Still blocked by Cloudflare")
            return None
        
        # Try to extract MD5 from results
        # Pattern: /md5/XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
        md5_matches = re.findall(r'/md5/([a-fA-F0-9]{32})', response.text)
        
        if md5_matches:
            md5 = md5_matches[0]
            logger.info(f"Found MD5: {md5}")
            return {'md5': md5}
        
        logger.warning("No MD5 found in search results")
        logger.info(f"First 2000 chars: {response.text[:2000]}")
        return None
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return None


def get_download_link(md5: str) -> str:
    """Get download link from MD5 page"""
    
    url = f"https://welib.org/md5/{md5}"
    
    logger.info(f"Getting download page: {url}")
    logger.info("Waiting 5 seconds...")
    time.sleep(5)
    
    try:
        response = scraper.get(url, timeout=60)
        logger.info(f"Response status: {response.status_code}")
        
        # Save for debugging
        with open('/tmp/welib_md5.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        if response.status_code != 200:
            return None
        
        # Look for slow download link
        slow_matches = re.findall(r'href="([^"]*slow[^"]*)"', response.text, re.IGNORECASE)
        if slow_matches:
            link = slow_matches[0]
            if not link.startswith('http'):
                link = f"https://welib.org{link}"
            logger.info(f"Found slow download link: {link}")
            return link
        
        # Look for any download link
        download_matches = re.findall(r'href="([^"]*download[^"]*)"', response.text, re.IGNORECASE)
        if download_matches:
            link = download_matches[0]
            if not link.startswith('http'):
                link = f"https://welib.org{link}"
            logger.info(f"Found download link: {link}")
            return link
        
        # Look for direct file links
        file_matches = re.findall(r'href="([^"]*\.(pdf|epub|mobi)[^"]*)"', response.text, re.IGNORECASE)
        if file_matches:
            link = file_matches[0][0]
            if not link.startswith('http'):
                link = f"https://welib.org{link}"
            logger.info(f"Found file link: {link}")
            return link
        
        logger.warning("No download link found")
        return None
        
    except Exception as e:
        logger.error(f"Error getting download link: {e}")
        return None


def download_file(url: str, filename: str) -> bool:
    """Download file from URL"""
    
    save_path = DOWNLOADS_DIR / filename
    
    logger.info(f"Downloading: {url}")
    logger.info(f"Saving as: {filename}")
    logger.info("Waiting 10 seconds (slow server)...")
    time.sleep(10)
    
    try:
        response = scraper.get(url, timeout=300, stream=True)
        logger.info(f"Response status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Download failed with status {response.status_code}")
            return False
        
        # Check content type
        content_type = response.headers.get('content-type', '')
        logger.info(f"Content-Type: {content_type}")
        
        # Write file
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        size = save_path.stat().st_size
        logger.info(f"Downloaded: {size} bytes")
        
        if size < 10000:
            logger.warning("File too small, probably error page")
            with open(save_path, 'r', errors='ignore') as f:
                logger.info(f"Content: {f.read()[:500]}")
            save_path.unlink()
            return False
        
        logger.info(f"SUCCESS: {filename} ({size / 1024 / 1024:.2f} MB)")
        return True
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False


def process_search(query: str) -> bool:
    """Process a single search query"""
    
    logger.info("=" * 50)
    logger.info(f"Processing: {query}")
    logger.info("=" * 50)
    
    # Search
    result = search_welib(query)
    if not result:
        logger.error("No search results")
        return False
    
    # Get download link
    md5 = result.get('md5')
    download_url = get_download_link(md5)
    if not download_url:
        logger.error("No download link found")
        return False
    
    # Download
    safe_name = re.sub(r'[^a-zA-Z0-9 ]', '', query)[:50].replace(' ', '_')
    return download_file(download_url, f"{safe_name}.pdf")


def main():
    logger.info("=" * 60)
    logger.info("Ebook Download - welib.org with Cloudflare bypass")
    logger.info("=" * 60)
    
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    if not SEARCH_TERMS_FILE.exists():
        logger.error("search_terms.txt not found")
        sys.exit(1)
    
    with open(SEARCH_TERMS_FILE, 'r') as f:
        terms = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    logger.info(f"Search terms: {terms}")
    
    successful = []
    failed = []
    
    for term in terms:
        if process_search(term):
            successful.append(term)
        else:
            failed.append(term)
        
        logger.info("Waiting 30 seconds before next search...")
        time.sleep(30)
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    
    if successful:
        logger.info(f"Successful ({len(successful)}):")
        for t in successful:
            logger.info(f"  - {t}")
    
    if failed:
        logger.info(f"Failed ({len(failed)}):")
        for t in failed:
            logger.info(f"  - {t}")
    
    # List files
    if DOWNLOADS_DIR.exists():
        files = list(DOWNLOADS_DIR.iterdir())
        if files:
            logger.info("Downloaded files:")
            for f in files:
                logger.info(f"  - {f.name} ({f.stat().st_size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
