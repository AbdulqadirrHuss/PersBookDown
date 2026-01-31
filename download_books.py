#!/usr/bin/env python3
"""
Ebook Download Automation Script

Uses curl_cffi for browser TLS impersonation and Tor for IP masking.
Searches LibGen and Anna's Archive for books.
"""

import os
import re
import sys
import time
import logging
from pathlib import Path
from typing import Optional, List
from urllib.parse import urljoin, quote_plus

from curl_cffi import requests
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DOWNLOADS_DIR = Path("downloads")
SEARCH_TERMS_FILE = Path("search_terms.txt")
BOOKS_FILE = Path("books.txt")
REQUEST_TIMEOUT = 45
RETRY_ATTEMPTS = 3
RETRY_DELAY = 3

# Tor SOCKS5 proxy (localhost:9050 when Tor is running)
TOR_PROXY = "socks5://127.0.0.1:9050"

# LibGen mirrors
LIBGEN_MIRRORS = [
    "https://libgen.is",
    "https://libgen.rs",
    "https://libgen.st",
    "https://libgen.li",
]

# Anna's Archive mirrors
ANNAS_MIRRORS = [
    "https://annas-archive.org",
    "https://annas-archive.gs",
    "https://annas-archive.se",
]

# Preferred formats
PREFERRED_FORMATS = ['epub', 'pdf', 'mobi', 'azw3']

# Check if Tor proxy is available
def check_tor_proxy():
    """Check if Tor SOCKS proxy is running."""
    try:
        response = requests.get(
            "https://check.torproject.org/api/ip",
            impersonate="chrome110",
            proxies={"https": TOR_PROXY, "http": TOR_PROXY},
            timeout=15
        )
        data = response.json()
        if data.get("IsTor"):
            logger.info(f"✓ Tor is working! Exit IP: {data.get('IP', 'unknown')}")
            return True
    except Exception as e:
        logger.debug(f"Tor check failed: {e}")
    return False

USE_TOR = check_tor_proxy()

def get_proxies():
    """Return proxy config if Tor is available."""
    if USE_TOR:
        return {"https": TOR_PROXY, "http": TOR_PROXY}
    return None


def sanitize_filename(filename: str) -> str:
    """Remove invalid characters from filename."""
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    return sanitized[:150]


def parse_search_terms() -> List[str]:
    """Parse search terms from search_terms.txt or books.txt."""
    search_terms = []
    
    if SEARCH_TERMS_FILE.exists():
        logger.info(f"Reading from {SEARCH_TERMS_FILE}")
        with open(SEARCH_TERMS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                term = line.strip()
                if term and not term.startswith('#'):
                    search_terms.append(term)
                    logger.info(f"  → {term}")
        if search_terms:
            return search_terms
    
    if BOOKS_FILE.exists():
        logger.info(f"Reading from {BOOKS_FILE}")
        with open(BOOKS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                search_terms.append(line.replace(' - ', ' '))
                logger.info(f"  → {line}")
    
    return search_terms


def make_request(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[requests.Response]:
    """Make HTTP request with browser impersonation."""
    proxies = get_proxies()
    
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = requests.get(
                url,
                impersonate="chrome110",  # Impersonate Chrome 110 TLS fingerprint
                proxies=proxies,
                timeout=timeout,
                allow_redirects=True
            )
            response.raise_for_status()
            return response
        except Exception as e:
            logger.warning(f"Request failed (attempt {attempt + 1}/{RETRY_ATTEMPTS}): {type(e).__name__}")
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    return None


def get_best_format(results: List[dict]) -> Optional[dict]:
    """Select the best format from available options."""
    for preferred in PREFERRED_FORMATS:
        for item in results:
            ext = item.get('extension', '').lower().strip('.')
            if ext == preferred:
                return item
    return results[0] if results else None


# ============================================================================
# Library Genesis
# ============================================================================

def search_libgen(search_term: str) -> Optional[dict]:
    """Search Library Genesis."""
    for mirror in LIBGEN_MIRRORS:
        try:
            url = f"{mirror}/search.php?req={quote_plus(search_term)}&lg_topic=libgen&open=0&view=simple&res=25&phrase=1&column=def"
            logger.info(f"Trying LibGen: {mirror}")
            
            response = make_request(url)
            if not response:
                continue
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Find results table
            tables = soup.find_all('table', class_='c')
            if not tables:
                tables = [t for t in soup.find_all('table') if len(t.find_all('tr')) > 2]
            
            if not tables:
                continue
            
            rows = tables[0].find_all('tr')[1:]  # Skip header
            results = []
            
            for row in rows[:5]:
                cols = row.find_all('td')
                if len(cols) < 8:
                    continue
                
                try:
                    result = {
                        'title': cols[2].get_text(strip=True)[:100],
                        'author': cols[1].get_text(strip=True)[:50],
                        'extension': cols[8].get_text(strip=True).lower() if len(cols) > 8 else 'pdf',
                        'mirror': mirror,
                    }
                    
                    # Get download link
                    links = cols[9].find_all('a', href=True) if len(cols) > 9 else cols[-1].find_all('a', href=True)
                    if links:
                        result['download_page'] = links[0]['href']
                        results.append(result)
                except:
                    continue
            
            if results:
                best = get_best_format(results)
                if best:
                    logger.info(f"✓ Found: {best['title'][:40]}... ({best['extension']})")
                    return best
                    
        except Exception as e:
            logger.debug(f"LibGen error on {mirror}: {e}")
            continue
    
    return None


def download_from_libgen(book_info: dict, save_path: Path) -> bool:
    """Download from LibGen mirror page."""
    download_page = book_info.get('download_page', '')
    if not download_page:
        return False
    
    try:
        if not download_page.startswith('http'):
            download_page = urljoin(book_info['mirror'], download_page)
        
        logger.info("Accessing download page...")
        response = make_request(download_page)
        if not response:
            return False
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find GET link
        download_link = None
        for link in soup.find_all('a', href=True):
            text = link.get_text(strip=True).lower()
            if 'get' in text or 'download' in text:
                download_link = link['href']
                break
        
        if not download_link:
            h2 = soup.find('h2')
            if h2 and h2.find('a', href=True):
                download_link = h2.find('a')['href']
        
        if not download_link:
            return False
        
        logger.info("Downloading file...")
        file_response = make_request(download_link, timeout=120)
        if not file_response:
            return False
        
        # Verify it's a real file
        if len(file_response.content) < 1000:
            return False
        
        with open(save_path, 'wb') as f:
            f.write(file_response.content)
        
        size_mb = save_path.stat().st_size / 1024 / 1024
        logger.info(f"✓ Downloaded: {save_path.name} ({size_mb:.2f} MB)")
        return True
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False


# ============================================================================
# Anna's Archive
# ============================================================================

def search_annas_archive(search_term: str) -> Optional[dict]:
    """Search Anna's Archive."""
    for mirror in ANNAS_MIRRORS:
        try:
            url = f"{mirror}/search?q={quote_plus(search_term)}"
            logger.info(f"Trying Anna's Archive: {mirror}")
            
            response = make_request(url)
            if not response:
                continue
            
            soup = BeautifulSoup(response.text, 'lxml')
            results = []
            
            for link in soup.select('a[href*="/md5/"]')[:5]:
                href = link.get('href', '')
                text = link.get_text(' ', strip=True)
                
                ext = 'pdf'
                for fmt in PREFERRED_FORMATS:
                    if fmt.upper() in text.upper():
                        ext = fmt
                        break
                
                results.append({
                    'title': text[:100],
                    'extension': ext,
                    'detail_url': urljoin(mirror, href),
                    'mirror': mirror,
                })
            
            if results:
                best = get_best_format(results)
                if best:
                    logger.info(f"✓ Found: {best['title'][:40]}... ({best['extension']})")
                    return best
                    
        except Exception as e:
            logger.debug(f"Anna's error on {mirror}: {e}")
            continue
    
    return None


def download_from_annas(book_info: dict, save_path: Path) -> bool:
    """Download from Anna's Archive."""
    detail_url = book_info.get('detail_url', '')
    if not detail_url:
        return False
    
    try:
        logger.info("Accessing book page...")
        response = make_request(detail_url)
        if not response:
            return False
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find download link
        download_link = None
        for link in soup.find_all('a', href=True):
            text = link.get_text(strip=True).lower()
            if 'slow download' in text or 'download' in text:
                href = link['href']
                download_link = href if href.startswith('http') else urljoin(book_info['mirror'], href)
                break
        
        if not download_link:
            return False
        
        # Follow through LibGen mirror if needed
        if 'libgen' in download_link.lower() or 'library.lol' in download_link.lower():
            resp = make_request(download_link)
            if resp:
                soup = BeautifulSoup(resp.text, 'lxml')
                for link in soup.find_all('a', href=True):
                    if 'get' in link.get_text(strip=True).lower():
                        download_link = link['href']
                        break
        
        logger.info("Downloading file...")
        file_response = make_request(download_link, timeout=120)
        if not file_response or len(file_response.content) < 1000:
            return False
        
        with open(save_path, 'wb') as f:
            f.write(file_response.content)
        
        size_mb = save_path.stat().st_size / 1024 / 1024
        logger.info(f"✓ Downloaded: {save_path.name} ({size_mb:.2f} MB)")
        return True
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False


# ============================================================================
# Main
# ============================================================================

def download_book(search_term: str) -> bool:
    """Download a book by search term."""
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    base_filename = sanitize_filename(search_term)
    
    # Try LibGen
    result = search_libgen(search_term)
    if result:
        ext = result.get('extension', 'pdf').strip('.')
        if download_from_libgen(result, DOWNLOADS_DIR / f"{base_filename}.{ext}"):
            return True
    
    # Try Anna's Archive
    result = search_annas_archive(search_term)
    if result:
        ext = result.get('extension', 'pdf').strip('.')
        if download_from_annas(result, DOWNLOADS_DIR / f"{base_filename}.{ext}"):
            return True
    
    logger.error(f"✗ Could not download: {search_term}")
    return False


def main():
    logger.info("=" * 50)
    logger.info("Ebook Download Automation")
    logger.info("=" * 50)
    
    if USE_TOR:
        logger.info("Using Tor proxy for anonymity")
    else:
        logger.info("Tor not available, using direct connection")
    
    logger.info("Using Chrome 110 TLS impersonation")
    
    search_terms = parse_search_terms()
    if not search_terms:
        logger.error("No search terms found!")
        sys.exit(1)
    
    logger.info(f"\nProcessing {len(search_terms)} search term(s)")
    
    successful = []
    failed = []
    
    for i, term in enumerate(search_terms, 1):
        logger.info(f"\n[{i}/{len(search_terms)}] {term}")
        
        if download_book(term):
            successful.append(term)
        else:
            failed.append(term)
        
        if i < len(search_terms):
            time.sleep(3)
    
    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("RESULTS")
    logger.info("=" * 50)
    
    if successful:
        logger.info(f"\n✓ Downloaded ({len(successful)}):")
        for t in successful:
            logger.info(f"  - {t}")
    
    if failed:
        logger.info(f"\n✗ Failed ({len(failed)}):")
        for t in failed:
            logger.info(f"  - {t}")
    
    if DOWNLOADS_DIR.exists():
        files = list(DOWNLOADS_DIR.iterdir())
        if files:
            logger.info(f"\nFiles in downloads/:")
            for f in files:
                logger.info(f"  {f.name} ({f.stat().st_size/1024/1024:.2f} MB)")
    
    if failed and not successful:
        sys.exit(1)


if __name__ == "__main__":
    main()
