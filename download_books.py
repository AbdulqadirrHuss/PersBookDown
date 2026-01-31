#!/usr/bin/env python3
"""
Ebook Download Automation Script

Searches for books from Library Genesis (LibGen) and Anna's Archive,
prioritizing .epub and .pdf formats, and downloads them to the downloads/ folder.
"""

import os
import re
import sys
import time
import logging
from pathlib import Path
from typing import Optional, List
from urllib.parse import urljoin, quote_plus

import requests
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
BOOKS_FILE = Path("books.txt")  # Fallback
REQUEST_TIMEOUT = 30
RETRY_ATTEMPTS = 3
RETRY_DELAY = 2

# LibGen mirrors to try (ordered by typical reliability)
LIBGEN_MIRRORS = [
    "https://libgen.li",
    "https://libgen.is",
    "https://libgen.rs", 
    "https://libgen.st",
]

# Anna's Archive mirrors
ANNAS_MIRRORS = [
    "https://annas-archive.org",
    "https://annas-archive.gs",
    "https://annas-archive.se",
]

# Preferred formats in order of priority
PREFERRED_FORMATS = ['epub', 'pdf', 'mobi', 'azw3']

# User agent for requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def sanitize_filename(filename: str) -> str:
    """Remove invalid characters from filename."""
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    return sanitized[:150]


def parse_search_terms() -> List[str]:
    """
    Parse search terms from search_terms.txt (comma-separated workflow input)
    or fall back to books.txt.
    """
    search_terms = []
    
    # Try search_terms.txt first (from workflow input)
    if SEARCH_TERMS_FILE.exists():
        logger.info(f"Reading search terms from {SEARCH_TERMS_FILE}")
        with open(SEARCH_TERMS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                term = line.strip()
                if term and not term.startswith('#'):
                    search_terms.append(term)
                    logger.info(f"  Search term: '{term}'")
        if search_terms:
            return search_terms
    
    # Fall back to books.txt
    if BOOKS_FILE.exists():
        logger.info(f"Reading from {BOOKS_FILE}")
        with open(BOOKS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Handle old "Title - Author" format by just using as search term
                search_terms.append(line.replace(' - ', ' '))
                logger.info(f"  Search term: '{line}'")
    
    return search_terms


def make_request(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[requests.Response]:
    """Make HTTP request with retry logic."""
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request failed (attempt {attempt + 1}/{RETRY_ATTEMPTS}): {e}")
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    return None


def get_best_format(results: List[dict]) -> Optional[dict]:
    """Select the best format from available options based on priority."""
    for preferred in PREFERRED_FORMATS:
        for item in results:
            ext = item.get('extension', '').lower().strip('.')
            if ext == preferred:
                return item
    return results[0] if results else None


# ============================================================================
# Library Genesis Functions
# ============================================================================

def search_libgen(search_term: str) -> Optional[dict]:
    """Search Library Genesis for a book."""
    for mirror in LIBGEN_MIRRORS:
        try:
            search_url = f"{mirror}/search.php?req={quote_plus(search_term)}&lg_topic=libgen&open=0&view=simple&res=25&phrase=1&column=def"
            logger.info(f"Searching LibGen: {mirror}")
            
            response = make_request(search_url)
            if not response:
                continue
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Find results table
            tables = soup.find_all('table', class_='c')
            if not tables:
                # Try alternative table structure
                tables = soup.find_all('table')
                tables = [t for t in tables if t.find('tr') and len(t.find_all('tr')) > 1]
            
            if not tables:
                logger.debug(f"No results table found on {mirror}")
                continue
            
            results_table = tables[0]
            rows = results_table.find_all('tr')[1:]  # Skip header
            
            results = []
            for row in rows[:10]:
                cols = row.find_all('td')
                if len(cols) < 8:
                    continue
                
                try:
                    # Extract info from columns
                    title_col = cols[2] if len(cols) > 2 else cols[1]
                    author_col = cols[1] if len(cols) > 1 else None
                    
                    result = {
                        'title': title_col.get_text(strip=True)[:100],
                        'author': author_col.get_text(strip=True)[:50] if author_col else '',
                        'extension': cols[8].get_text(strip=True).lower() if len(cols) > 8 else 'pdf',
                        'size': cols[7].get_text(strip=True) if len(cols) > 7 else '',
                        'mirror': mirror,
                    }
                    
                    # Get download link
                    mirrors_col = cols[9] if len(cols) > 9 else cols[-1]
                    links = mirrors_col.find_all('a', href=True)
                    if links:
                        result['download_page'] = links[0]['href']
                    
                    if result.get('download_page'):
                        results.append(result)
                except Exception as e:
                    logger.debug(f"Error parsing row: {e}")
                    continue
            
            if results:
                best = get_best_format(results)
                if best:
                    logger.info(f"Found: {best['title'][:50]}... ({best['extension']})")
                    return best
                    
        except Exception as e:
            logger.error(f"LibGen search error on {mirror}: {e}")
            continue
    
    return None


def download_from_libgen(book_info: dict, save_path: Path) -> bool:
    """Download a book from Library Genesis."""
    download_page = book_info.get('download_page', '')
    
    if not download_page:
        return False
    
    try:
        if not download_page.startswith('http'):
            download_page = urljoin(book_info['mirror'], download_page)
        
        logger.info(f"Accessing download page...")
        response = make_request(download_page)
        
        if not response:
            return False
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find download link
        download_link = None
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text(strip=True).lower()
            if 'get' in text or 'download' in text or 'cloudflare' in href.lower():
                download_link = href
                break
        
        if not download_link:
            for link in soup.find_all('a', href=True):
                href = link['href']
                if any(ext in href.lower() for ext in ['.epub', '.pdf', '.mobi']):
                    download_link = href
                    break
        
        if not download_link:
            # Try finding h2 with download link
            h2 = soup.find('h2')
            if h2:
                link = h2.find('a', href=True)
                if link:
                    download_link = link['href']
        
        if not download_link:
            logger.error("Could not find download link")
            return False
        
        logger.info(f"Downloading file...")
        file_response = make_request(download_link, timeout=120)
        
        if not file_response:
            return False
        
        # Check if we got actual file content
        content_type = file_response.headers.get('content-type', '')
        if 'text/html' in content_type and len(file_response.content) < 10000:
            logger.warning("Got HTML instead of file, trying to extract link")
            return False
        
        with open(save_path, 'wb') as f:
            f.write(file_response.content)
        
        file_size = save_path.stat().st_size
        if file_size < 1000:  # Less than 1KB is probably an error
            logger.warning(f"Downloaded file too small ({file_size} bytes)")
            save_path.unlink()
            return False
        
        logger.info(f"Downloaded: {save_path.name} ({file_size/1024/1024:.2f} MB)")
        return True
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False


# ============================================================================
# Anna's Archive Functions  
# ============================================================================

def search_annas_archive(search_term: str) -> Optional[dict]:
    """Search Anna's Archive for a book."""
    for mirror in ANNAS_MIRRORS:
        try:
            search_url = f"{mirror}/search?q={quote_plus(search_term)}"
            logger.info(f"Searching Anna's Archive: {mirror}")
            
            response = make_request(search_url)
            if not response:
                continue
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Find book results
            results = []
            book_links = soup.select('a[href*="/md5/"]')
            
            for link in book_links[:10]:
                try:
                    href = link.get('href', '')
                    if '/md5/' not in href:
                        continue
                    
                    text = link.get_text(' ', strip=True)
                    
                    # Extract format from text
                    extension = 'pdf'
                    for fmt in PREFERRED_FORMATS:
                        if fmt.upper() in text.upper():
                            extension = fmt
                            break
                    
                    result = {
                        'title': text[:100],
                        'extension': extension,
                        'detail_url': urljoin(mirror, href),
                        'mirror': mirror,
                    }
                    results.append(result)
                    
                except Exception as e:
                    continue
            
            if results:
                best = get_best_format(results)
                if best:
                    logger.info(f"Found: {best['title'][:50]}... ({best['extension']})")
                    return best
                    
        except Exception as e:
            logger.error(f"Anna's Archive error on {mirror}: {e}")
            continue
    
    return None


def download_from_annas(book_info: dict, save_path: Path) -> bool:
    """Download a book from Anna's Archive."""
    detail_url = book_info.get('detail_url', '')
    
    if not detail_url:
        return False
    
    try:
        logger.info(f"Accessing book page...")
        response = make_request(detail_url)
        
        if not response:
            return False
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find download link
        download_link = None
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text(strip=True).lower()
            
            if any(x in text for x in ['slow download', 'download']):
                download_link = href if href.startswith('http') else urljoin(book_info['mirror'], href)
                break
        
        if not download_link:
            return False
        
        # Follow through to get actual file
        if 'libgen' in download_link.lower() or 'library.lol' in download_link.lower():
            # Redirect to LibGen download
            response = make_request(download_link)
            if not response:
                return False
            
            soup = BeautifulSoup(response.text, 'lxml')
            for link in soup.find_all('a', href=True):
                text = link.get_text(strip=True).lower()
                if 'get' in text:
                    download_link = link['href']
                    break
        
        if not download_link:
            return False
        
        logger.info(f"Downloading file...")
        file_response = make_request(download_link, timeout=120)
        
        if not file_response:
            return False
        
        with open(save_path, 'wb') as f:
            f.write(file_response.content)
        
        file_size = save_path.stat().st_size
        if file_size < 1000:
            save_path.unlink()
            return False
        
        logger.info(f"Downloaded: {save_path.name} ({file_size/1024/1024:.2f} MB)")
        return True
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False


# ============================================================================
# Main Download Logic
# ============================================================================

def download_book(search_term: str) -> bool:
    """Attempt to download a book using the search term."""
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    base_filename = sanitize_filename(search_term)
    
    # Try LibGen first
    logger.info(f"Searching LibGen...")
    result = search_libgen(search_term)
    
    if result:
        ext = result.get('extension', 'pdf').strip('.')
        save_path = DOWNLOADS_DIR / f"{base_filename}.{ext}"
        
        if download_from_libgen(result, save_path):
            return True
        logger.warning("LibGen download failed, trying Anna's Archive...")
    
    # Try Anna's Archive
    logger.info(f"Searching Anna's Archive...")
    result = search_annas_archive(search_term)
    
    if result:
        ext = result.get('extension', 'pdf').strip('.')
        save_path = DOWNLOADS_DIR / f"{base_filename}.{ext}"
        
        if download_from_annas(result, save_path):
            return True
    
    logger.error(f"Could not download: {search_term}")
    return False


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Ebook Download Automation Script")
    logger.info("=" * 60)
    
    search_terms = parse_search_terms()
    
    if not search_terms:
        logger.error("No search terms found. Create search_terms.txt or books.txt")
        sys.exit(1)
    
    logger.info(f"Processing {len(search_terms)} search term(s)")
    
    successful = []
    failed = []
    
    for i, term in enumerate(search_terms, 1):
        logger.info(f"\n[{i}/{len(search_terms)}] Searching: {term}")
        
        try:
            if download_book(term):
                successful.append(term)
            else:
                failed.append(term)
        except Exception as e:
            logger.error(f"Error: {e}")
            failed.append(term)
        
        if i < len(search_terms):
            time.sleep(2)
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    
    logger.info(f"\nSuccessful ({len(successful)}):")
    for term in successful:
        logger.info(f"  ✓ {term}")
    
    if failed:
        logger.info(f"\nFailed ({len(failed)}):")
        for term in failed:
            logger.info(f"  ✗ {term}")
    
    if DOWNLOADS_DIR.exists():
        files = list(DOWNLOADS_DIR.iterdir())
        if files:
            logger.info(f"\nDownloaded files:")
            for f in files:
                logger.info(f"  - {f.name} ({f.stat().st_size/1024/1024:.2f} MB)")
    
    if failed and not successful:
        sys.exit(1)


if __name__ == "__main__":
    main()
