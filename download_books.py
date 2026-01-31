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
            return None
        
        # Check if blocked by Cloudflare
        if 'Cloudflare' in response.text and 'blocked' in response.text.lower():
            logger.error("Blocked by Cloudflare")
            return None
        
        html = response.text
        
        # WeLib book result patterns - analyze all links
        all_links = re.findall(r'href="([^"]+)"', html)
        
        logger.info(f"Total links found: {len(all_links)}")
        
        # Filter to unique links and log them
        unique_links = list(set(all_links))
        
        # Separate links by type for debugging
        book_links = []
        for link in unique_links:
            # Skip static/navigation links
            if any(skip in link for skip in ['.css', '.js', '.png', '.jpg', '/donate', '/login', '/account', '/search?', 'javascript:', '#', '/manifest', 'favicon']):
                continue
            book_links.append(link)
        
        logger.info(f"Potential content links: {len(book_links)}")
        for link in book_links[:30]:  # Log first 30
            logger.info(f"  Link: {link}")
        
        # Pattern 1: /md5/HASH - this is the standard pattern
        md5_matches = re.findall(r'href="(/md5/[a-fA-F0-9]{32})"', html)
        if md5_matches:
            link = md5_matches[0]
            logger.info(f"Found MD5 link: {link}")
            return {'link': f"https://welib.org{link}", 'type': 'md5'}
        
        # Pattern 2: Check for /book/ID pattern
        book_id_matches = re.findall(r'href="(/book/[^"]+)"', html)
        if book_id_matches:
            link = book_id_matches[0]
            logger.info(f"Found book ID link: {link}")
            return {'link': f"https://welib.org{link}", 'type': 'book'}
        
        # Pattern 3: Check for result cards - common patterns in book libraries
        # Look for links that contain identifiers like ISBNs, fileIDs, etc
        for link in book_links:
            # Links with long alphanumeric IDs
            if re.search(r'/[a-zA-Z]+/[a-zA-Z0-9]{8,}', link):
                if not link.startswith('http'):
                    link = f"https://welib.org{link}"
                logger.info(f"Found ID-based link: {link}")
                return {'link': link, 'type': 'id'}
        
        # Pattern 4: Links containing 'file', 'download', 'get'
        for link in book_links:
            if any(kw in link.lower() for kw in ['file', 'download', 'get', 'epub', 'pdf']):
                if not link.startswith('http'):
                    link = f"https://welib.org{link}"
                logger.info(f"Found download-type link: {link}")
                return {'link': link, 'type': 'download'}
        
        # Pattern 5: Look at links starting with specific paths
        for link in book_links:
            # Skip obvious site pages
            if link in ['/', '/about', '/help', '/faq', '/contact']:
                continue
            # Any other path that might be a book
            if link.startswith('/') and len(link) > 5:
                # Has some ID-like component
                if re.search(r'[0-9]', link) or len(link) > 20:
                    full_link = f"https://welib.org{link}"
                    logger.info(f"Found potential book path: {full_link}")
                    return {'link': full_link, 'type': 'path'}
        
        logger.warning("Could not identify book links in search results")
        logger.info("First 5000 chars of body for debugging:")
        # Find body content
        body_start = html.find('<main')
        if body_start > 0:
            logger.info(html[body_start:body_start+5000])
        else:
            logger.info(html[:5000])
        
        return None
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_download_link(result: dict) -> str:
    """Get download link from result"""
    
    if result['type'] == 'md5':
        # Extract MD5 from link URL like /md5/abc123... or https://welib.org/md5/abc123...
        link = result['link']
        md5_match = re.search(r'/md5/([a-fA-F0-9]{32})', link)
        if md5_match:
            return get_download_from_md5(md5_match.group(1))
        else:
            logger.error(f"Could not extract MD5 from link: {link}")
            return None
    elif result['type'] == 'direct':
        return result['link']
    else:
        return get_download_from_page(result['link'])


def get_download_from_md5(md5: str) -> list:
    """Get all download links from MD5 - including LibGen mirrors"""
    
    links = []
    
    # Add LibGen mirror links FIRST - they often work without auth
    # These use the MD5 hash directly to download
    libgen_mirrors = [
        f"https://libgen.li/ads.php?md5={md5}",
        f"https://libgen.rocks/ads.php?md5={md5}",
        f"http://library.lol/main/{md5}",
        f"https://libgen.is/book/index.php?md5={md5}",
        f"https://libgen.rs/book/index.php?md5={md5}",
    ]
    
    for mirror in libgen_mirrors:
        links.append(mirror)
        logger.info(f"Added LibGen mirror: {mirror}")
    
    # Also try welib page for additional links
    url = f"https://welib.org/md5/{md5}"
    
    logger.info(f"Getting MD5 page: {url}")
    logger.info("Waiting 5 seconds...")
    time.sleep(5)
    
    try:
        response = scraper.get(url, timeout=60)
        logger.info(f"Response status: {response.status_code}")
        
        # Save for debugging
        with open('/tmp/welib_md5.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        if response.status_code == 200:
            welib_links = extract_download_links(response.text)
            for link in welib_links:
                if link not in links:
                    links.append(link)
        
    except Exception as e:
        logger.error(f"Error getting MD5 page: {e}")
    
    return links


def get_download_from_page(url: str) -> list:
    """Get all download links from a book page"""
    
    logger.info(f"Getting book page: {url}")
    logger.info("Waiting 5 seconds...")
    time.sleep(5)
    
    try:
        response = scraper.get(url, timeout=60)
        logger.info(f"Response status: {response.status_code}")
        
        # Save for debugging
        with open('/tmp/welib_book.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        if response.status_code != 200:
            return []
        
        return extract_download_links(response.text)
        
    except Exception as e:
        logger.error(f"Error getting book page: {e}")
        return []


def get_download_links(result: dict) -> list:
    """Get all download links from result"""
    
    if result['type'] == 'md5':
        # Extract MD5 from link URL
        link = result['link']
        md5_match = re.search(r'/md5/([a-fA-F0-9]{32})', link)
        if md5_match:
            return get_download_from_md5(md5_match.group(1))
        else:
            logger.error(f"Could not extract MD5 from link: {link}")
            return []
    elif result['type'] == 'direct':
        return [result['link']]
    else:
        return get_download_from_page(result['link'])


def extract_download_links(html: str) -> list:
    """Extract ALL download links from page HTML for fallback support"""
    
    links = []
    
    # Pattern 1: Slow download link (preferred but may 403)
    slow_matches = re.findall(r'href="([^"]*(?:slow_download|slow|free)[^"]*)"', html, re.IGNORECASE)
    for link in slow_matches:
        if not link.startswith('http'):
            link = f"https://welib.org{link}"
        if link not in links:
            links.append(link)
            logger.info(f"Found slow download link: {link}")
    
    # Pattern 2: IPFS CID links - convert to HTTP gateways
    # Look for ipfs:// protocol links with CID
    ipfs_cid_matches = re.findall(r'ipfs://([a-zA-Z0-9]{46,})', html)
    for cid in ipfs_cid_matches:
        # Use multiple IPFS gateways for reliability
        gateway_urls = [
            f"https://ipfs.io/ipfs/{cid}",
            f"https://dweb.link/ipfs/{cid}",
            f"https://w3s.link/ipfs/{cid}",
        ]
        for gateway_url in gateway_urls:
            if gateway_url not in links:
                links.append(gateway_url)
                logger.info(f"Found IPFS CID, using gateway: {gateway_url}")
    
    # Also try to find direct gateway links in page
    gateway_matches = re.findall(r'href="(https?://[^"]*(?:ipfs\.io|dweb\.link|w3s\.link|gateway\.pinata\.cloud)/ipfs/[^"]+)"', html, re.IGNORECASE)
    for link in gateway_matches:
        if link not in links:
            links.append(link)
            logger.info(f"Found IPFS gateway link: {link}")
    
    # Pattern 3: Direct CDN/file links
    cdn_matches = re.findall(r'href="(https?://[^"]*(?:cdn|download|get)[^"]*\.(pdf|epub|mobi|azw3))"', html, re.IGNORECASE)
    for match in cdn_matches:
        link = match[0]
        if link not in links:
            links.append(link)
            logger.info(f"Found CDN link: {link}")
    
    # Pattern 4: Fast download links
    fast_matches = re.findall(r'href="([^"]*(?:fast_download|fast)[^"]*)"', html, re.IGNORECASE)
    for link in fast_matches:
        if not link.startswith('http'):
            link = f"https://welib.org{link}"
        if link not in links:
            links.append(link)
            logger.info(f"Found fast download link: {link}")
    
    
    # Pattern 5: General download links (but exclude account pages)
    download_matches = re.findall(r'href="([^"]*download[^"]*)"', html, re.IGNORECASE)
    for link in download_matches:
        # Skip account pages, slow/fast (already captured)
        if 'slow' in link or 'fast' in link or 'account' in link:
            continue
        if not link.startswith('http'):
            link = f"https://welib.org{link}"
        if link not in links:
            links.append(link)
            logger.info(f"Found download link: {link}")
    
    # Pattern 6: LibGen mirrors
    libgen_matches = re.findall(r'href="(https?://[^"]*(?:libgen|library\.lol|gen\.lib)[^"]*)"', html, re.IGNORECASE)
    for link in libgen_matches:
        if link not in links:
            links.append(link)
            logger.info(f"Found LibGen mirror: {link}")
    
    if not links:
        logger.warning("No download links found in page")
    else:
        logger.info(f"Total download links found: {len(links)}")
    
    return links


def extract_download_link(html: str) -> str:
    """Extract first download link (legacy compatibility)"""
    links = extract_download_links(html)
    return links[0] if links else None


def download_file(url: str, filename: str) -> bool:
    """Download file from URL - handles LibGen pages that require parsing"""
    
    save_path = DOWNLOADS_DIR / filename
    
    logger.info(f"Downloading: {url}")
    logger.info(f"Saving as: {filename}")
    
    # Check if this is a LibGen page URL that needs parsing
    if any(domain in url for domain in ['libgen.li', 'libgen.rocks', 'libgen.is', 'libgen.rs', 'library.lol']):
        logger.info("Detected LibGen URL, parsing page for download link...")
        time.sleep(3)
        try:
            page_response = scraper.get(url, timeout=60)
            if page_response.status_code == 200:
                # LibGen pages have download links with GET pattern or direct file links
                download_patterns = [
                    r'href="(https?://[^"]+/get\.php\?[^"]+)"',
                    r'href="(https?://download[^"]+)"',
                    r'href="(https?://[^"]+\.pdf)"',
                    r'href="(https?://[^"]+\.epub)"',
                    r'<a href="([^"]+)"[^>]*>GET</a>',
                    r'<a href="([^"]+)"[^>]*>Cloudflare</a>',
                    r'<a href="([^"]+)"[^>]*>IPFS\.io</a>',
                ]
                for pattern in download_patterns:
                    matches = re.findall(pattern, page_response.text, re.IGNORECASE)
                    if matches:
                        url = matches[0]
                        if not url.startswith('http'):
                            # Handle relative URLs
                            from urllib.parse import urljoin
                            url = urljoin(page_response.url, url)
                        logger.info(f"Found LibGen download link: {url}")
                        break
                else:
                    logger.warning("Could not find download link in LibGen page")
                    # Save for debugging
                    with open('/tmp/libgen_page.html', 'w', encoding='utf-8') as f:
                        f.write(page_response.text[:5000])
                    return False
            else:
                logger.error(f"LibGen page returned status {page_response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error parsing LibGen page: {e}")
            return False
    
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
        
        # Reject HTML responses - they're error pages, not books
        if 'text/html' in content_type:
            logger.warning("Got HTML response instead of file, skipping")
            return False
        
        # Determine file extension from content type or URL
        if 'epub' in content_type or '.epub' in url:
            save_path = DOWNLOADS_DIR / filename.replace('.pdf', '.epub')
        elif 'mobi' in url:
            save_path = DOWNLOADS_DIR / filename.replace('.pdf', '.mobi')
        
        # Write file
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        size = save_path.stat().st_size
        logger.info(f"Downloaded: {size} bytes")
        
        if size < 10000:
            logger.warning("File too small, probably error page")
            with open(save_path, 'r', errors='ignore') as f:
                content = f.read()[:500]
                logger.info(f"Content preview: {content}")
            save_path.unlink()
            return False
        
        logger.info(f"SUCCESS: {save_path.name} ({size / 1024 / 1024:.2f} MB)")
        return True
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        import traceback
        traceback.print_exc()
        return False


def process_search(query: str) -> bool:
    """Process a single search query"""
    
    logger.info("=" * 60)
    logger.info(f"Processing: {query}")
    logger.info("=" * 60)
    
    # Search
    result = search_welib(query)
    if not result:
        logger.error("No search results")
        return False
    
    # Get ALL download links
    download_urls = get_download_links(result)
    if not download_urls:
        logger.error("No download links found")
        return False
    
    # Try each download link until one works
    safe_name = re.sub(r'[^a-zA-Z0-9 ]', '', query)[:50].replace(' ', '_')
    filename = f"{safe_name}.pdf"
    
    for i, url in enumerate(download_urls):
        logger.info(f"Trying download source {i+1}/{len(download_urls)}: {url[:80]}...")
        if download_file(url, filename):
            return True
        logger.warning(f"Download source {i+1} failed, trying next...")
        time.sleep(5)  # Brief pause between attempts
    
    logger.error("All download sources failed")
    return False


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
