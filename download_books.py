#!/usr/bin/env python3
"""
Ebook Download using FlareSolverr to bypass Cloudflare
FlareSolverr uses a real Chrome browser to solve challenges
"""

import os
import re
import sys
import time
import json
import logging
from pathlib import Path

import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DOWNLOADS_DIR = Path("downloads")
SEARCH_TERMS_FILE = Path("search_terms.txt")
FLARESOLVERR_URL = "http://localhost:8191/v1"

# Session ID for reusing Cloudflare clearance
SESSION_ID = None

# Junk domains that should NEVER be treated as download links
JUNK_DOMAINS = [
    'ipfs.tech',           # IPFS project homepage
    'cloudflare.com',      # CDN provider homepage
    'welib.org/',          # WeLib root (not a download)
    'welib.st/',           # WeLib alternate root
    'annas-archive.li/',   # Just the homepage, not a download
    'github.com',          # Not a download source
    'software.annas-archive', # Software page, not book
]

# Public IPFS gateways - try many for better success rate
IPFS_GATEWAYS = [
    'https://dweb.link/ipfs/',
    'https://ipfs.io/ipfs/',
    'https://w3s.link/ipfs/',
    'https://cf-ipfs.com/ipfs/',
    'https://4everland.io/ipfs/',
    'https://gateway.pinata.cloud/ipfs/',
    'https://cloudflare-ipfs.com/ipfs/',
    'https://ipfs.runfission.com/ipfs/',
    'https://gateway.ipfs.io/ipfs/',
    'https://hardbin.com/ipfs/',
    'https://ipfs.eth.aragon.network/ipfs/',
    'https://ipfs.fleek.co/ipfs/',
    'https://nftstorage.link/ipfs/',
    'https://ipfs.best-practice.se/ipfs/',
    'https://gw3.io/ipfs/',
]

# IPFS downloads need longer timeouts (network propagation delay)
IPFS_TIMEOUT = 90  # seconds


def is_valid_download_url(url: str, md5: str = None) -> bool:
    """
    Check if URL is a valid download link, not a junk/homepage link.
    Returns True only for actual download URLs.
    """
    if not url:
        return False
    
    # Reject ipfs:// protocol (can't be downloaded directly)
    if url.startswith('ipfs://'):
        logger.warning(f"Rejecting ipfs:// protocol URL (not HTTP): {url[:60]}")
        return False
    
    # Must be HTTP/HTTPS
    if not url.startswith('http://') and not url.startswith('https://'):
        return False
    
    # Reject known junk domains
    for junk in JUNK_DOMAINS:
        if junk in url:
            logger.warning(f"Rejecting junk URL (matches '{junk}'): {url[:60]}")
            return False
    
    # If we have MD5, prefer links that contain it (more likely to be correct file)
    # But don't reject links that don't have MD5 (IPFS gateways, etc)
    
    return True


def convert_ipfs_to_gateway(ipfs_url: str) -> str:
    """
    Convert ipfs:// URL to HTTP gateway URL.
    Example: ipfs://QmHash... -> https://dweb.link/ipfs/QmHash...
    """
    if ipfs_url.startswith('ipfs://'):
        cid = ipfs_url[7:]  # Remove 'ipfs://'
        # Use dweb.link as primary gateway (reliable)
        return f"https://dweb.link/ipfs/{cid}"
    return ipfs_url


def flaresolverr_request(url: str, max_timeout: int = 60000) -> dict:
    """
    Send request through FlareSolverr to bypass Cloudflare
    Returns dict with 'html' and 'cookies' keys
    """
    global SESSION_ID
    
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": max_timeout
    }
    
    # Reuse session if available (faster, uses same clearance cookies)
    if SESSION_ID:
        payload["session"] = SESSION_ID
    
    logger.info(f"FlareSolverr request: {url}")
    
    try:
        response = requests.post(
            FLARESOLVERR_URL,
            json=payload,
            timeout=120  # Allow time for Cloudflare solving
        )
        
        if response.status_code != 200:
            logger.error(f"FlareSolverr error: {response.status_code}")
            return None
        
        result = response.json()
        
        if result.get("status") != "ok":
            logger.error(f"FlareSolverr failed: {result.get('message')}")
            return None
        
        solution = result.get("solution", {})
        
        # Save session ID for reuse
        if not SESSION_ID and "session" in result:
            SESSION_ID = result["session"]
            logger.info(f"Created FlareSolverr session: {SESSION_ID}")
        
        return {
            "html": solution.get("response", ""),
            "cookies": solution.get("cookies", []),
            "status": solution.get("status", 0),
            "url": solution.get("url", url)
        }
        
    except requests.exceptions.Timeout:
        logger.error("FlareSolverr request timed out")
        return None
    except Exception as e:
        logger.error(f"FlareSolverr error: {e}")
        return None


def create_session():
    """Create a FlareSolverr session for cookie persistence"""
    global SESSION_ID
    
    try:
        response = requests.post(
            FLARESOLVERR_URL,
            json={"cmd": "sessions.create"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "ok":
                SESSION_ID = result.get("session")
                logger.info(f"Created session: {SESSION_ID}")
                return True
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
    
    return False


def destroy_session():
    """Clean up FlareSolverr session"""
    global SESSION_ID
    
    if not SESSION_ID:
        return
    
    try:
        requests.post(
            FLARESOLVERR_URL,
            json={"cmd": "sessions.destroy", "session": SESSION_ID},
            timeout=10
        )
        logger.info(f"Destroyed session: {SESSION_ID}")
    except:
        pass
    
    SESSION_ID = None


def download_direct(url: str, filename: str, cookies: list = None) -> bool:
    """Download file directly using harvested cookies"""
    
    save_path = DOWNLOADS_DIR / filename
    
    # Use longer timeout for IPFS (network propagation delay)
    is_ipfs = 'ipfs' in url.lower() or 'dweb' in url.lower()
    timeout = IPFS_TIMEOUT if is_ipfs else 60
    
    logger.info(f"Downloading: {url[:80]}...")
    logger.info(f"Timeout: {timeout}s {'(IPFS)' if is_ipfs else ''}")
    
    # Convert FlareSolverr cookies to requests format
    cookie_dict = {}
    if cookies:
        for cookie in cookies:
            cookie_dict[cookie.get("name")] = cookie.get("value")
    
    try:
        # Use harvested cookies for authenticated downloads
        response = requests.get(
            url, 
            cookies=cookie_dict,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            timeout=timeout,
            stream=True
        )
        
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
        logger.info(f"Downloaded {size:,} bytes")
        
        # Check if file is too small (probably error page)
        if size < 10000:
            logger.warning(f"File too small ({size} bytes), likely error page")
            save_path.unlink()
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        import traceback
        traceback.print_exc()
        return False


def search_welib(query: str) -> dict:
    """Search welib.org and return first result"""
    
    encoded_query = query.replace(' ', '%20')
    url = f"https://welib.org/search?q={encoded_query}"
    
    logger.info(f"Searching: {url}")
    
    result = flaresolverr_request(url)
    
    if not result:
        logger.error("Search failed")
        return None
    
    html = result.get("html", "")
    
    # Save for debugging
    with open('/tmp/welib_search.html', 'w', encoding='utf-8') as f:
        f.write(html)
    logger.info(f"Response length: {len(html)} characters")
    
    # Find MD5 links
    md5_matches = re.findall(r'href="(/md5/[a-fA-F0-9]{32})"', html)
    if md5_matches:
        link = md5_matches[0]
        logger.info(f"Found MD5 link: {link}")
        return {
            'link': f"https://welib.org{link}", 
            'type': 'md5',
            'cookies': result.get('cookies', [])
        }
    
    logger.warning("No MD5 links found")
    return None


def get_download_links(md5: str, cookies: list = None) -> list:
    """Get all download links from MD5 page"""
    
    links = []
    
    # Add LibGen mirror links FIRST - they often work without auth
    libgen_mirrors = [
        f"http://library.lol/main/{md5}",
        f"https://libgen.li/ads.php?md5={md5}",
        f"https://libgen.rocks/ads.php?md5={md5}",
    ]
    
    for mirror in libgen_mirrors:
        if is_valid_download_url(mirror, md5):
            links.append({"url": mirror, "type": "libgen"})
            logger.info(f"Added LibGen mirror: {mirror}")
    
    # Also get welib page for download links
    url = f"https://welib.org/md5/{md5}"
    
    logger.info(f"Getting MD5 page: {url}")
    
    result = flaresolverr_request(url)
    
    if result:
        html = result.get("html", "")
        
        # Save for debugging
        with open('/tmp/welib_md5.html', 'w', encoding='utf-8') as f:
            f.write(html)
        
        # Extract download links
        # Pattern 1: Slow download links (most reliable for WeLib)
        slow_matches = re.findall(r'href="([^"]*(?:slow_download)[^"]*)"', html, re.IGNORECASE)
        for link in slow_matches:
            if not link.startswith('http'):
                link = f"https://welib.org{link}"
            if is_valid_download_url(link, md5):
                links.append({"url": link, "type": "welib", "cookies": result.get("cookies", [])})
                logger.info(f"Found slow download link: {link}")
        
        # Pattern 2: IPFS protocol links - CONVERT to HTTP gateways
        # Find ipfs:// links and convert them to ALL available gateways
        ipfs_protocol_matches = re.findall(r'ipfs://([a-zA-Z0-9]{32,})', html)
        for cid in ipfs_protocol_matches:
            # Use all available gateways for maximum reliability
            for gateway in IPFS_GATEWAYS:
                gateway_url = f"{gateway}{cid}"
                if is_valid_download_url(gateway_url, md5):
                    links.append({"url": gateway_url, "type": "ipfs"})
            logger.info(f"Added {len(IPFS_GATEWAYS)} gateways for IPFS CID: {cid[:20]}...")
        
        # Pattern 3: Existing IPFS gateway links (already HTTP)
        gateway_matches = re.findall(r'href="(https?://[^"]*(?:ipfs\.io|dweb\.link|gateway\.pinata)/ipfs/[^"]+)"', html, re.IGNORECASE)
        for link in gateway_matches:
            if is_valid_download_url(link, md5):
                links.append({"url": link, "type": "ipfs"})
                logger.info(f"Found IPFS gateway link: {link}")
        
        # Pattern 4: Fast download links (may require auth)
        fast_matches = re.findall(r'href="([^"]*(?:fast_download)[^"]*)"', html, re.IGNORECASE)
        for link in fast_matches:
            if not link.startswith('http'):
                link = f"https://welib.org{link}"
            if is_valid_download_url(link, md5):
                links.append({"url": link, "type": "welib", "cookies": result.get("cookies", [])})
                logger.info(f"Found fast download link: {link}")
    
    logger.info(f"Total VALID download links found: {len(links)}")
    return links


def try_libgen_download(url: str, filename: str) -> bool:
    """Try to download from LibGen mirror page"""
    
    logger.info(f"Trying LibGen mirror: {url}")
    
    # Use FlareSolverr to get the LibGen page
    result = flaresolverr_request(url)
    
    if not result:
        return False
    
    html = result.get("html", "")
    
    # Save for debugging
    with open('/tmp/libgen_page.html', 'w', encoding='utf-8') as f:
        f.write(html[:20000])
    
    logger.info(f"LibGen page size: {len(html)} chars")
    
    # AGGRESSIVE LibGen parsing - try many patterns
    # LibGen HTML changes frequently, so we try multiple strategies
    download_patterns = [
        # Pattern 1: Direct file links ending in book extensions
        r'href="(https?://[^"]+\.(?:pdf|epub|mobi|azw3|djvu))"',
        
        # Pattern 2: get.php download links (common on libgen)
        r'href="(https?://[^"]+/get\.php\?[^"]+)"',
        
        # Pattern 3: Links with "GET" text (library.lol style)
        r'<a[^>]+href="([^"]+)"[^>]*>\s*GET\s*</a>',
        r'<a[^>]+href="([^"]+)"[^>]*>.*?GET.*?</a>',
        
        # Pattern 4: Links inside h2 tags (common LibGen layout)
        r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"',
        
        # Pattern 5: Cloudflare/IPFS buttons
        r'<a[^>]+href="([^"]+)"[^>]*>\s*Cloudflare\s*</a>',
        r'<a[^>]+href="([^"]+)"[^>]*>\s*IPFS\.io\s*</a>',
        r'<a[^>]+href="([^"]+)"[^>]*>\s*Infura\s*</a>',
        
        # Pattern 6: Download buttons with various text
        r'<a[^>]+href="([^"]+)"[^>]*>\s*Download\s*</a>',
        r'<a[^>]+href="([^"]+)"[^>]*>\s*\[1\]\s*</a>',  # [1], [2] etc buttons
        r'<a[^>]+href="([^"]+)"[^>]*>\s*\[2\]\s*</a>',
        
        # Pattern 7: Any link containing 'download' or 'get'
        r'href="(https?://[^"]*(?:download|/get/)[^"]*)"',
        
        # Pattern 8: Library.lol specific - main download div
        r'<div[^>]*id="download"[^>]*>.*?href="([^"]+)"',
    ]
    
    tried_urls = set()
    
    for pattern in download_patterns:
        try:
            matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
            for download_url in matches:
                # Skip if already tried
                if download_url in tried_urls:
                    continue
                tried_urls.add(download_url)
                
                if not download_url.startswith('http'):
                    # Handle relative URLs
                    from urllib.parse import urljoin
                    download_url = urljoin(url, download_url)
                
                # CRITICAL: Validate URL before attempting download
                if not is_valid_download_url(download_url):
                    logger.debug(f"Skipping invalid URL: {download_url[:50]}")
                    continue
                
                logger.info(f"Trying LibGen link: {download_url[:80]}")
                
                # Try direct download
                if download_direct(download_url, filename, result.get("cookies", [])):
                    return True
        except Exception as e:
            logger.debug(f"Pattern failed: {e}")
            continue
    
    logger.warning(f"Could not find valid download in LibGen page (tried {len(tried_urls)} URLs)")
    return False


def process_search(query: str) -> bool:
    """Process a single search query"""
    
    logger.info(f"Processing: {query}")
    
    # Search for books
    search_result = search_welib(query)
    
    if not search_result:
        logger.error(f"No results found for: {query}")
        return False
    
    # Extract MD5 from link
    md5_match = re.search(r'/md5/([a-fA-F0-9]{32})', search_result['link'])
    if not md5_match:
        logger.error(f"Could not extract MD5 from: {search_result['link']}")
        return False
    
    md5 = md5_match.group(1)
    logger.info(f"Found MD5: {md5}")
    
    # Get download links
    download_links = get_download_links(md5, search_result.get('cookies', []))
    
    if not download_links:
        logger.error("No download links found")
        return False
    
    # Create safe filename
    safe_name = re.sub(r'[^\w\s-]', '', query)[:50].strip().replace(' ', '_')
    filename = f"{safe_name}.pdf"
    
    # Try each download source
    for i, link_info in enumerate(download_links):
        url = link_info["url"]
        link_type = link_info["type"]
        cookies = link_info.get("cookies", [])
        
        logger.info(f"Trying download source {i+1}/{len(download_links)}: {url[:80]}...")
        
        success = False
        
        if link_type == "libgen":
            success = try_libgen_download(url, filename)
        else:
            success = download_direct(url, filename, cookies)
        
        if success:
            logger.info(f"Successfully downloaded: {filename}")
            return True
        
        logger.warning(f"Download source {i+1} failed, trying next...")
        time.sleep(3)  # Brief delay between attempts
    
    logger.error("All download sources failed")
    return False


def main():
    """Main entry point"""
    
    logger.info("=" * 60)
    logger.info("Ebook Download - FlareSolverr Mode")
    logger.info("=" * 60)
    
    # Create downloads directory
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    # Read search terms
    if not SEARCH_TERMS_FILE.exists():
        logger.error(f"Search terms file not found: {SEARCH_TERMS_FILE}")
        sys.exit(1)
    
    search_terms = [
        line.strip() 
        for line in SEARCH_TERMS_FILE.read_text().strip().split('\n')
        if line.strip()
    ]
    
    if not search_terms:
        logger.error("No search terms provided")
        sys.exit(1)
    
    logger.info(f"Search terms: {search_terms}")
    
    # Create FlareSolverr session for cookie persistence
    create_session()
    
    # Track results
    successful = []
    failed = []
    
    try:
        for query in search_terms:
            logger.info("=" * 60)
            
            if process_search(query):
                successful.append(query)
            else:
                failed.append(query)
            
            # Wait between searches
            if query != search_terms[-1]:
                logger.info("Waiting 10 seconds before next search...")
                time.sleep(10)
    
    finally:
        # Clean up session
        destroy_session()
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    
    if successful:
        logger.info(f"Successful ({len(successful)}):")
        for q in successful:
            logger.info(f"  - {q}")
    
    if failed:
        logger.info(f"Failed ({len(failed)}):")
        for q in failed:
            logger.info(f"  - {q}")
    
    # Exit with error if all failed
    if not successful and failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
