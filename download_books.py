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
from typing import Optional, List, Tuple
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
BOOKS_FILE = Path("books.txt")
REQUEST_TIMEOUT = 30
RETRY_ATTEMPTS = 3
RETRY_DELAY = 2

# LibGen mirrors to try (ordered by typical reliability)
LIBGEN_MIRRORS = [
    "https://libgen.li",
    "https://libgen.is",
    "https://libgen.rs", 
    "https://libgen.st",
    "https://libgen.lc",
    "https://libgen.gs",
]

# Anna's Archive mirrors
ANNAS_MIRRORS = [
    "https://annas-archive.org",
    "https://annas-archive.gs",
    "https://annas-archive.se",
    "https://annas-archive.li",
]


# Preferred formats in order of priority
PREFERRED_FORMATS = ['.epub', '.pdf', '.mobi', '.azw3']

# User agent for requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def sanitize_filename(filename: str) -> str:
    """Remove invalid characters from filename."""
    # Remove invalid characters for Windows/Unix filenames
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Limit length
    return sanitized[:200]


def parse_books_file(filepath: Path) -> List[Tuple[str, str]]:
    """
    Parse books.txt file and return list of (title, author) tuples.
    Expected format: "Title - Author" per line
    """
    books = []
    
    if not filepath.exists():
        logger.error(f"Books file not found: {filepath}")
        return books
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            # Parse "Title - Author" format
            if ' - ' in line:
                parts = line.split(' - ', 1)
                title = parts[0].strip()
                author = parts[1].strip() if len(parts) > 1 else ""
                books.append((title, author))
                logger.info(f"Parsed: '{title}' by '{author}'")
            else:
                logger.warning(f"Line {line_num}: Invalid format (expected 'Title - Author'): {line}")
    
    return books


def make_request(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[requests.Response]:
    """Make HTTP request with retry logic."""
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request failed (attempt {attempt + 1}/{RETRY_ATTEMPTS}): {e}")
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    return None


def get_best_format(formats_available: List[dict]) -> Optional[dict]:
    """Select the best format from available options based on priority."""
    for preferred in PREFERRED_FORMATS:
        for item in formats_available:
            extension = item.get('extension', '').lower()
            if f'.{extension}' == preferred or extension == preferred.lstrip('.'):
                return item
    # Return first available if no preferred format found
    return formats_available[0] if formats_available else None


# ============================================================================
# Library Genesis Functions
# ============================================================================

def search_libgen(title: str, author: str) -> Optional[dict]:
    """Search Library Genesis for a book."""
    search_query = f"{title} {author}".strip()
    
    for mirror in LIBGEN_MIRRORS:
        try:
            # Search URL
            search_url = f"{mirror}/search.php?req={quote_plus(search_query)}&lg_topic=libgen&open=0&view=simple&res=25&phrase=1&column=def"
            logger.info(f"Searching LibGen: {search_url}")
            
            response = make_request(search_url)
            if not response:
                continue
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Find results table
            tables = soup.find_all('table', class_='c')
            if not tables:
                logger.debug("No results table found")
                continue
            
            results_table = tables[0] if tables else None
            if not results_table:
                continue
            
            rows = results_table.find_all('tr')[1:]  # Skip header row
            
            results = []
            for row in rows[:10]:  # Check first 10 results
                cols = row.find_all('td')
                if len(cols) < 9:
                    continue
                
                try:
                    result = {
                        'title': cols[2].get_text(strip=True),
                        'author': cols[1].get_text(strip=True),
                        'extension': cols[8].get_text(strip=True).lower(),
                        'size': cols[7].get_text(strip=True),
                        'mirror': mirror,
                    }
                    
                    # Get download link from mirrors column
                    mirrors_col = cols[9] if len(cols) > 9 else cols[8]
                    links = mirrors_col.find_all('a')
                    if links:
                        result['download_page'] = links[0].get('href', '')
                    
                    results.append(result)
                except (IndexError, AttributeError) as e:
                    logger.debug(f"Error parsing row: {e}")
                    continue
            
            if results:
                best = get_best_format(results)
                if best:
                    logger.info(f"Found on LibGen: {best['title']} ({best['extension']})")
                    return best
                    
        except Exception as e:
            logger.error(f"LibGen search error on {mirror}: {e}")
            continue
    
    return None


def download_from_libgen(book_info: dict, save_path: Path) -> bool:
    """Download a book from Library Genesis."""
    download_page = book_info.get('download_page', '')
    
    if not download_page:
        logger.error("No download page URL available")
        return False
    
    try:
        # Make the download page URL absolute if needed
        if not download_page.startswith('http'):
            download_page = urljoin(book_info['mirror'], download_page)
        
        logger.info(f"Accessing download page: {download_page}")
        response = make_request(download_page)
        
        if not response:
            return False
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find the GET download link (usually on library.lol or similar)
        download_link = None
        
        # Try to find direct download link
        for link in soup.find_all('a'):
            href = link.get('href', '')
            text = link.get_text(strip=True).lower()
            if 'get' in text or 'download' in text:
                download_link = href
                break
        
        if not download_link:
            # Try finding by href pattern
            for link in soup.find_all('a', href=True):
                href = link['href']
                if any(ext in href.lower() for ext in ['.epub', '.pdf', '.mobi']):
                    download_link = href
                    break
        
        if not download_link:
            logger.error("Could not find download link on page")
            return False
        
        # Download the file
        logger.info(f"Downloading from: {download_link}")
        file_response = make_request(download_link, timeout=120)
        
        if not file_response:
            return False
        
        # Save the file
        with open(save_path, 'wb') as f:
            f.write(file_response.content)
        
        logger.info(f"Successfully downloaded: {save_path}")
        return True
        
    except Exception as e:
        logger.error(f"LibGen download error: {e}")
        return False


# ============================================================================
# Anna's Archive Functions  
# ============================================================================

def search_annas_archive(title: str, author: str) -> Optional[dict]:
    """Search Anna's Archive for a book."""
    search_query = f"{title} {author}".strip()
    
    for mirror in ANNAS_MIRRORS:
        try:
            search_url = f"{mirror}/search?q={quote_plus(search_query)}"
            logger.info(f"Searching Anna's Archive: {search_url}")
            
            response = make_request(search_url)
            if not response:
                continue
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Find book results
            results = []
            
            # Anna's Archive uses various layouts, try multiple selectors
            book_items = soup.select('a[href*="/md5/"]') or soup.select('.search-result')
            
            for item in book_items[:10]:
                try:
                    href = item.get('href', '')
                    if '/md5/' not in href:
                        continue
                    
                    text = item.get_text(' ', strip=True)
                    
                    # Try to extract format from text
                    extension = 'pdf'  # default
                    for fmt in PREFERRED_FORMATS:
                        if fmt.lstrip('.').upper() in text.upper():
                            extension = fmt.lstrip('.')
                            break
                    
                    result = {
                        'title': text[:100],
                        'author': author,
                        'extension': extension,
                        'detail_url': urljoin(mirror, href),
                        'mirror': mirror,
                    }
                    results.append(result)
                    
                except Exception as e:
                    logger.debug(f"Error parsing Anna's item: {e}")
                    continue
            
            if results:
                best = get_best_format(results)
                if best:
                    logger.info(f"Found on Anna's Archive: {best['title'][:50]}... ({best['extension']})")
                    return best
                    
        except Exception as e:
            logger.error(f"Anna's Archive search error on {mirror}: {e}")
            continue
    
    return None


def download_from_annas(book_info: dict, save_path: Path) -> bool:
    """Download a book from Anna's Archive."""
    detail_url = book_info.get('detail_url', '')
    
    if not detail_url:
        logger.error("No detail URL available")
        return False
    
    try:
        logger.info(f"Accessing detail page: {detail_url}")
        response = make_request(detail_url)
        
        if not response:
            return False
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find download links (usually through slow download or external mirrors)
        download_link = None
        
        # Look for download buttons/links
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text(strip=True).lower()
            
            # Look for LibGen mirrors or slow download
            if any(x in href.lower() or x in text for x in ['libgen', 'download', 'slow']):
                download_link = href if href.startswith('http') else urljoin(book_info['mirror'], href)
                break
        
        if not download_link:
            logger.error("Could not find download link on Anna's Archive")
            return False
        
        # For LibGen links, redirect to LibGen download
        if 'libgen' in download_link.lower() or 'library.lol' in download_link.lower():
            logger.info(f"Redirecting to LibGen mirror: {download_link}")
            
            mirror_response = make_request(download_link)
            if not mirror_response:
                return False
            
            mirror_soup = BeautifulSoup(mirror_response.text, 'lxml')
            
            # Find actual download link
            for link in mirror_soup.find_all('a'):
                text = link.get_text(strip=True).lower()
                if 'get' in text or 'download' in text:
                    download_link = link.get('href', '')
                    break
        
        if not download_link:
            return False
        
        # Download the file
        logger.info(f"Downloading from: {download_link}")
        file_response = make_request(download_link, timeout=120)
        
        if not file_response:
            return False
        
        with open(save_path, 'wb') as f:
            f.write(file_response.content)
        
        logger.info(f"Successfully downloaded: {save_path}")
        return True
        
    except Exception as e:
        logger.error(f"Anna's Archive download error: {e}")
        return False


# ============================================================================
# Main Download Logic
# ============================================================================

def download_book(title: str, author: str) -> bool:
    """
    Attempt to download a book, trying LibGen first, then Anna's Archive.
    Returns True if successful, False otherwise.
    """
    # Create downloads directory if needed
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    # Generate base filename
    base_filename = sanitize_filename(f"{title} - {author}")
    
    # Try LibGen first
    logger.info(f"Searching LibGen for: {title} by {author}")
    libgen_result = search_libgen(title, author)
    
    if libgen_result:
        extension = libgen_result.get('extension', 'pdf')
        save_path = DOWNLOADS_DIR / f"{base_filename}.{extension}"
        
        if download_from_libgen(libgen_result, save_path):
            return True
        logger.warning("LibGen download failed, trying Anna's Archive...")
    
    # Try Anna's Archive
    logger.info(f"Searching Anna's Archive for: {title} by {author}")
    annas_result = search_annas_archive(title, author)
    
    if annas_result:
        extension = annas_result.get('extension', 'pdf')
        save_path = DOWNLOADS_DIR / f"{base_filename}.{extension}"
        
        if download_from_annas(annas_result, save_path):
            return True
    
    logger.error(f"Could not download: {title} by {author}")
    return False


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Ebook Download Automation Script")
    logger.info("=" * 60)
    
    # Parse books file
    books = parse_books_file(BOOKS_FILE)
    
    if not books:
        logger.error("No books to download. Check books.txt file.")
        sys.exit(1)
    
    logger.info(f"Found {len(books)} book(s) to download")
    
    # Track results
    successful = []
    failed = []
    
    # Process each book
    for i, (title, author) in enumerate(books, 1):
        logger.info(f"\n[{i}/{len(books)}] Processing: {title} by {author}")
        
        try:
            if download_book(title, author):
                successful.append(f"{title} - {author}")
            else:
                failed.append(f"{title} - {author}")
        except Exception as e:
            logger.error(f"Unexpected error processing '{title}': {e}")
            failed.append(f"{title} - {author}")
        
        # Rate limiting between downloads
        if i < len(books):
            time.sleep(2)
    
    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    
    logger.info(f"\nSuccessful downloads ({len(successful)}):")
    for book in successful:
        logger.info(f"  ✓ {book}")
    
    if failed:
        logger.info(f"\nFailed downloads ({len(failed)}):")
        for book in failed:
            logger.info(f"  ✗ {book}")
    
    # List downloaded files
    if DOWNLOADS_DIR.exists():
        files = list(DOWNLOADS_DIR.iterdir())
        if files:
            logger.info(f"\nFiles in downloads folder ({len(files)}):")
            for f in files:
                logger.info(f"  - {f.name} ({f.stat().st_size / 1024 / 1024:.2f} MB)")
    
    # Exit with error if any downloads failed
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
