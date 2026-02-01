#!/usr/bin/env python3
"""
Ebook Download via WeLib - Cloudflare Solver Edition
Uses DrissionPage with active Cloudflare Turnstile solving via human-like interaction.

Cloudflare Solving Features:
- Detects Turnstile iframe
- Locates checkbox within iframe
- Human-like mouse movement (Bezier curves)
- Natural click timing and jitter
- Multiple retry strategies
"""

import os
import re
import sys
import time
import random
import math
import logging
from pathlib import Path
from urllib.parse import urljoin, unquote, quote, urlparse, parse_qs
from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.errors import ElementNotFoundError
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

# User-Agent Pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# =============================================================================
# HUMAN-LIKE MOUSE MOVEMENT (Bezier Curves)
# =============================================================================

def bezier_curve(t, points):
    """Calculate point on a Bezier curve at parameter t (0 to 1)"""
    n = len(points) - 1
    x = 0
    y = 0
    for i, (px, py) in enumerate(points):
        # Binomial coefficient
        coef = math.comb(n, i) * (1 - t) ** (n - i) * t ** i
        x += coef * px
        y += coef * py
    return (x, y)

def generate_human_path(start, end, steps=25):
    """Generate human-like mouse path using Bezier curves with control points"""
    x1, y1 = start
    x2, y2 = end
    
    # Add 2-3 random control points for natural curve
    num_control = random.randint(2, 3)
    control_points = [(x1, y1)]
    
    for i in range(num_control):
        # Control points with random offset from straight line
        t = (i + 1) / (num_control + 1)
        base_x = x1 + (x2 - x1) * t
        base_y = y1 + (y2 - y1) * t
        
        # Random deviation (more at middle, less at ends)
        deviation = 50 * math.sin(t * math.pi)
        offset_x = random.uniform(-deviation, deviation)
        offset_y = random.uniform(-deviation, deviation)
        
        control_points.append((base_x + offset_x, base_y + offset_y))
    
    control_points.append((x2, y2))
    
    # Generate path points
    path = []
    for i in range(steps + 1):
        t = i / steps
        # Ease in/out for natural acceleration
        t = t * t * (3 - 2 * t)  # Smoothstep
        point = bezier_curve(t, control_points)
        
        # Add micro-jitter
        jitter_x = random.uniform(-2, 2)
        jitter_y = random.uniform(-2, 2)
        path.append((int(point[0] + jitter_x), int(point[1] + jitter_y)))
    
    return path

def human_click_delay():
    """Human-like delay before/after click"""
    time.sleep(random.uniform(0.05, 0.15))

# =============================================================================
# CLOUDFLARE TURNSTILE SOLVER
# =============================================================================

def is_cloudflare_page(page) -> bool:
    """Detect Cloudflare challenge page"""
    html = page.html.lower()
    indicators = [
        "checking your browser",
        "just a moment",
        "cf-browser-verification",
        "challenge-running",
        "turnstile",
        "cf-turnstile",
        "_cf_chl"
    ]
    return any(ind in html for ind in indicators)

def find_turnstile_iframe(page):
    """Find the Cloudflare Turnstile iframe"""
    logger.info("Searching for Turnstile iframe...")
    
    # Common Turnstile iframe selectors
    iframe_selectors = [
        "iframe[src*='challenges.cloudflare.com']",
        "iframe[src*='turnstile']",
        "iframe[title*='Cloudflare']",
        "iframe[title*='turnstile']",
        "iframe.cf-turnstile",
        "[id*='cf-turnstile'] iframe",
        "div.cf-turnstile iframe",
    ]
    
    for selector in iframe_selectors:
        try:
            iframe = page.ele(f"css:{selector}", timeout=2)
            if iframe:
                logger.info(f"Found Turnstile iframe: {selector}")
                return iframe
        except:
            continue
    
    return None

def find_turnstile_checkbox(page, iframe):
    """Find the checkbox element inside Turnstile"""
    logger.info("Looking for Turnstile checkbox...")
    
    # Try to get iframe location for coordinate-based clicking
    try:
        # Get iframe bounding box
        rect = iframe.rect
        if rect:
            iframe_x = rect.get('x', 0)
            iframe_y = rect.get('y', 0)
            iframe_w = rect.get('width', 300)
            iframe_h = rect.get('height', 65)
            
            # Checkbox is typically in the left portion of the iframe
            # Approximately 20-30px from left, centered vertically
            checkbox_x = iframe_x + 28 + random.randint(-3, 3)
            checkbox_y = iframe_y + (iframe_h / 2) + random.randint(-3, 3)
            
            logger.info(f"Calculated checkbox position: ({checkbox_x}, {checkbox_y})")
            return (checkbox_x, checkbox_y)
    except Exception as e:
        logger.warning(f"Could not get iframe rect: {e}")
    
    return None

def move_mouse_human(page, target_x, target_y):
    """Move mouse to target using human-like Bezier path"""
    try:
        # Get current mouse position (or start from random corner)
        start_x = random.randint(100, 400)
        start_y = random.randint(100, 300)
        
        path = generate_human_path((start_x, start_y), (target_x, target_y))
        
        logger.info(f"Moving mouse from ({start_x},{start_y}) to ({target_x},{target_y})")
        
        for x, y in path:
            page.actions.move_to(x, y)
            time.sleep(random.uniform(0.01, 0.03))
            
        return True
    except Exception as e:
        logger.warning(f"Mouse move error: {e}")
        return False

def click_turnstile_checkbox(page, coords):
    """Click the Turnstile checkbox with human-like behavior"""
    x, y = coords
    
    try:
        # Move mouse to target
        move_mouse_human(page, x, y)
        
        # Small pause before click
        human_click_delay()
        
        # Click
        logger.info(f"Clicking at ({x}, {y})...")
        page.actions.click()
        
        # Small pause after click
        human_click_delay()
        
        return True
    except Exception as e:
        logger.error(f"Click error: {e}")
        return False

def solve_cloudflare_turnstile(page, max_attempts=3) -> bool:
    """Attempt to solve Cloudflare Turnstile challenge"""
    logger.info("=" * 40)
    logger.info("CLOUDFLARE TURNSTILE SOLVER")
    logger.info("=" * 40)
    
    for attempt in range(max_attempts):
        logger.info(f"Solve attempt {attempt + 1}/{max_attempts}")
        
        # Wait a bit for page to stabilize
        time.sleep(random.uniform(2, 4))
        
        # Find Turnstile iframe
        iframe = find_turnstile_iframe(page)
        
        if not iframe:
            logger.warning("No Turnstile iframe found, waiting...")
            time.sleep(3)
            continue
        
        # Find checkbox coordinates
        coords = find_turnstile_checkbox(page, iframe)
        
        if not coords:
            logger.warning("Could not locate checkbox")
            continue
        
        # Click the checkbox
        if click_turnstile_checkbox(page, coords):
            logger.info("Click performed, waiting for verification...")
            
            # Wait for challenge to process
            time.sleep(random.uniform(3, 6))
            
            # Check if challenge is solved
            if not is_cloudflare_page(page):
                logger.info("SUCCESS: Cloudflare challenge solved!")
                return True
            else:
                logger.warning("Challenge still present after click")
        
        # Exponential backoff between attempts
        time.sleep(2 ** attempt)
    
    logger.error("Failed to solve Turnstile after all attempts")
    page.get_screenshot(path="debug_turnstile_fail.png")
    return False

def wait_and_solve_cloudflare(page, max_wait=120) -> bool:
    """Wait for and solve Cloudflare challenge"""
    if not is_cloudflare_page(page):
        return True
    
    logger.info("Cloudflare challenge detected!")
    page.get_screenshot(path="debug_cloudflare_detected.png")
    
    start = time.time()
    
    # Try to solve actively
    if solve_cloudflare_turnstile(page):
        return True
    
    # Fallback: Just wait (some challenges auto-resolve)
    logger.info("Active solve failed, waiting for auto-resolution...")
    while is_cloudflare_page(page):
        if time.time() - start > max_wait:
            logger.error("Cloudflare timeout")
            return False
        time.sleep(3)
    
    return True

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def random_delay(min_sec=1.0, max_sec=3.0):
    time.sleep(random.uniform(min_sec, max_sec))

def safe_click(page, element):
    """Click element with fallbacks for elements without location/size"""
    try:
        # Try normal click first
        element.click()
        return True
    except Exception as e:
        if "no location or size" in str(e):
            logger.info("Element has no location, trying JS click...")
            try:
                # JavaScript click fallback
                page.run_js("arguments[0].click()", element)
                return True
            except Exception as e2:
                logger.warning(f"JS click failed: {e2}")
                # Try clicking via href if it's a link
                try:
                    href = element.attr("href")
                    if href:
                        logger.info(f"Navigating directly to: {href}")
                        if href.startswith("/"):
                            href = f"https://welib.org{href}"
                        page.get(href)
                        return True
                except:
                    pass
        logger.error(f"Click failed: {e}")
        return False

def clean_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name)[:50].strip().replace(' ', '_')

def download_file_curl(url: str, filename: str, referer: str, cookies=None) -> bool:
    """Download using curl_cffi"""
    logger.info(f"Downloading: {url}")
    
    try:
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": referer,
            "Accept": "application/pdf,application/epub+zip,*/*",
        }
        
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
        
        if response.status_code not in [200, 206]:
            logger.error(f"Download failed: {response.status_code}")
            return False
            
        save_path = DOWNLOADS_DIR / filename
        with open(save_path, 'wb') as f:
            f.write(response.content)
            
        size = save_path.stat().st_size
        logger.info(f"Downloaded {size:,} bytes")
        
        if size < 1000:
            save_path.unlink()
            return False
            
        return True
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False

# =============================================================================
# MAIN WORKFLOW
# =============================================================================

def process_workflow(page, query: str) -> bool:
    """Main download workflow with Cloudflare solving"""
    logger.info(f"Processing: {query}")
    
    encoded_query = quote(query)
    search_url = f"https://welib.org/search?q={encoded_query}"
    
    try:
        # Navigate
        random_delay(1, 2)
        page.get(search_url)
        
        # Handle Cloudflare
        if not wait_and_solve_cloudflare(page):
            return False
        
        # Wait for results
        random_delay(2, 4)
        
        # Click book - Refined selector to avoid sidebar (div.mb-4 is used in filters too!)
        logger.info("Looking for book...")
        # Use 'main' to scope strictly to search results, avoiding sidebar/header
        book = page.ele("css:main div.mb-4 a", timeout=60)
        
        if book:
            # excessive safety check: ensure it's not a random link
            href = book.attr("href")
            if not href or href == "#":
                logger.warning(f"Found book element but href is suspicious: {href}. Trying fallbacks...")
                book = None
        
        if not book:
             # Fallback
             book = page.ele("css:div.cursor-pointer, a[href*='/text/'], a[href*='/book/']", timeout=10)
        
        if not book:
            logger.error("No results found")
            page.get_screenshot(path="debug_no_results.png")
            return False

        logger.info("Clicking book...")
        if not safe_click(page, book):
            return False
        random_delay(3, 5)
        
        if not wait_and_solve_cloudflare(page):
            return False
        
        # Find Read button
        logger.info("Looking for 'Read' button...")
        # Selector strategy based on user feedback:
        # <a href="/slow_download... ... Read ... </a>
        read = page.ele("css:a[href*='/slow_download']", timeout=10) or \
               page.ele("css:a[href*='/read/']", timeout=10) or \
               page.ele("text:Read", timeout=5)
        
        if not read:
            logger.warning("No Read button found. Trying backup search...")
            # Backup: search for any link containing 'Read' text
            read = page.ele("xpath://a[contains(text(), 'Read')]", timeout=5)
            
        # Click Read and handle subsequent Cloudflare challenge
        logger.info("Clicking Read...")
        
        # Click and immediately check for new page load / challenge
        if not safe_click(page, read):
            return False
            
        logger.info("Clicked Read. Waiting for potential Cloudflare challenge...")
        time.sleep(5) # Wait for challenge to trigger
        
        if is_cloudflare_page(page):
            logger.info("New Cloudflare challenge detected! Solving...")
            if not wait_and_solve_cloudflare(page):
                return False
        
        # INCREASED WAIT: Allow time for iframe to load after challenge
        logger.info("Waiting for iframe to load...")
        time.sleep(10)  # Fixed wait for slow load
        random_delay(3, 5)
        
        # Find iframe - Deep Search for ANY iframe with correct src
        logger.info("Waiting for viewer iframe...")
        page.get_screenshot(path="debug_before_iframe.png")
        
        iframe = None
        
        # Try finding ANY iframe by iterating through all of them
        # RECURSIVE SEARCH: Check iframes inside iframes too
        def find_iframe_recursive(ele_list, depth=0):
            if depth > 2: return None
            for fr in ele_list:
                try:
                    src = fr.attr("src")
                    if src:
                        logger.info(f"Checking iframe (depth {depth}) src: {src[:50]}...")
                        if 'fast_view' in src or 'web-premium' in src or 'url=' in src:
                            return fr
                    
                    # Check inside this iframe
                    inner_frames = fr.eles("css:iframe")
                    if inner_frames:
                        res = find_iframe_recursive(inner_frames, depth + 1)
                        if res: return res
                except:
                    continue
            return None

        # --- SEARCH STRATEGY START ---
        real_url = None
        
        # 1. BROAD SEARCH (User request): Look for ANY element with fast_view?url
        logger.info("STRATEGY 1: Broad Search for 'fast_view?url'...")
        
        def check_element_for_download(ele):
            candidates = [ele.attr("href"), ele.attr("src"), ele.attr("data-src")]
            for val in candidates:
                if val and "fast_view?url" in val:
                    # Decode
                    if val.startswith("/"): val = "https://welib.org" + val
                    try:
                        parsed = urlparse(val)
                        qs = parse_qs(parsed.query)
                        if 'url' in qs:
                            decoded = unquote(qs['url'][0])
                            if any(x in decoded.lower() for x in ['.pdf', '.epub', '.mobi']):
                                return decoded
                    except:
                        pass
            return None

        potential_urls = []
        for tag in ["a", "iframe", "embed", "object"]:
             eles = page.eles(f"css:{tag}[href*='fast_view?url'], {tag}[src*='fast_view?url']")
             for e in eles:
                 res = check_element_for_download(e)
                 if res: potential_urls.append(res)

        if not potential_urls:
            # Brute force scan
            any_eles = page.eles("css:*[src*='fast_view?url'], *[href*='fast_view?url']")
            for e in any_eles:
                 res = check_element_for_download(e)
                 if res: potential_urls.append(res)

        if potential_urls:
            real_url = potential_urls[0]
            logger.info(f"MATCH (Broad Search): {real_url}")

        # 2. STRICT #bookIframe SEARCH (Fallback)
        if not real_url:
            logger.info("STRATEGY 2: Strict #bookIframe Search...")
            iframe = page.ele("#bookIframe", timeout=5)
            if iframe:
                # Check src
                src = iframe.attr("src")
                if src and "url=" in src:
                     try:
                         if src.startswith("/"): src = "https://welib.org" + src
                         qs = parse_qs(urlparse(src).query)
                         if 'url' in qs:
                             decoded = unquote(qs['url'][0])
                             if ".pdf" in decoded:
                                 real_url = decoded
                                 logger.info(f"MATCH (#bookIframe src): {real_url}")
                     except: pass
                
                # Check inner content if src failed
                if not real_url:
                    try:
                        pdf_link = iframe.ele("css:a[href$='.pdf']", timeout=2)
                        if pdf_link:
                            real_url = pdf_link.attr("href")
                            logger.info(f"MATCH (#bookIframe inner link): {real_url}")
                    except: pass

        # 3. RECURSIVE IFRAME SEARCH (Deep Fallback)
        if not real_url:
            logger.info("STRATEGY 3: Recursive Iframe Search...")
            iframe = find_iframe_recursive(page.eles("css:iframe"))
            if iframe:
                 # Check src
                 src = iframe.attr("src")
                 if src and "url=" in src:
                     try:
                         qs = parse_qs(urlparse(src).query)
                         if 'url' in qs:
                             real_url = unquote(qs['url'][0])
                             logger.info(f"MATCH (Recursive src): {real_url}")
                     except: pass
        
        # 4. LAST RESORT: PAGE TEXT SCAN
        if not real_url:
            logger.info("STRATEGY 4: Page Text Regex Scan...")
            import re
            match = re.search(r'https?://[^"\s<>]+\.pdf', page.html)
            if match:
                real_url = match.group(0)
                logger.info(f"MATCH (Regex Scan): {real_url}")

        # --- FINAL DOWNLOAD ---
        if not real_url:
            logger.error("ALL STRATEGIES FAILED. Could not find download URL.")
            return False
            
        logger.info(f"FINAL URL: {real_url}")
        
        if not real_url.startswith("http"):
            logger.error(f"Invalid URL format: {real_url}")
            return False
        
        safe_title = clean_filename(query)
        ext = ".pdf"
        if ".epub" in real_url: ext = ".epub"
        elif ".mobi" in real_url: ext = ".mobi"
        
        return download_file_curl(real_url, f"{safe_title}{ext}", page.url, page.cookies())
        
        # Fallback: Recursive search if bookIframe not found or revealed nothing
        if not real_url and not iframe:
            logger.info("bookIframe not found/empty. Starting recursive deep search...")
            iframe = find_iframe_recursive(page.eles("css:iframe"))
            
        if not real_url and iframe:
             # Try one last time with the found iframe (recurisve result)
             # ... (logic to check recursively found iframe)
             pass

        if not real_url:
             # Try scanning ANY visible text on page for a .pdf link
             # sometimes it's an embed
             logger.info("Last resort: Scanning entire page text for PDF url...")
             match = re.search(r'https?://[^"\s<>]+\.pdf', page.html)
             if match:
                 real_url = match.group(0)
                 logger.info(f"FOUND PDF URL in Page HTML: {real_url}")
        
        if not real_url:
            logger.error("Could not find download URL in iframe or page content")
            return False
            
        logger.info(f"Download URL: {real_url}")
        
        if not real_url.startswith("http"):
            return False
        
        # Download
        safe_title = clean_filename(query)
        ext = ".pdf"
        if ".epub" in real_url: ext = ".epub"
        elif ".mobi" in real_url: ext = ".mobi"
        
        return download_file_curl(real_url, f"{safe_title}{ext}", page.url, page.cookies())

    except Exception as e:
        logger.error(f"Workflow error: {e}")
        page.get_screenshot(path="debug_error.png")
        return False

def main():
    logger.info("=" * 60)
    logger.info("WeLib Downloader - Cloudflare SOLVER Edition")
    logger.info("=" * 60)
    
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    
    if not SEARCH_TERMS_FILE.exists():
        logger.error("search_terms.txt not found!")
        sys.exit(1)
    
    search_terms = [l.strip() for l in SEARCH_TERMS_FILE.read_text(encoding='utf-8-sig').split('\n') if l.strip()]
    logger.info(f"Loaded {len(search_terms)} terms")
    
    # Browser options - NOT headless (Cloudflare detects it)
    options = ChromiumOptions()
    options.set_argument('--no-sandbox')
    options.set_argument('--disable-gpu')
    options.set_argument('--disable-dev-shm-usage')
    options.set_argument('--disable-blink-features=AutomationControlled')
    options.set_argument(f'--user-agent={random.choice(USER_AGENTS)}')
    options.set_argument('--start-maximized')
    
    logger.info("Launching browser...")
    page = ChromiumPage(options)
    
    # Warmup
    logger.info("Warming up...")
    try:
        page.get("https://welib.org")
        random_delay(3, 5)
        wait_and_solve_cloudflare(page)
    except Exception as e:
        logger.warning(f"Warmup issue: {e}")
    
    success = 0
    fail = 0
    
    for term in search_terms:
        if process_workflow(page, term):
            logger.info(f"SUCCESS: {term}")
            success += 1
        else:
            logger.error(f"FAILED: {term}")
            fail += 1
        random_delay(5, 10)
    
    logger.info("=" * 60)
    logger.info(f"DONE: {success} success, {fail} failed")
    logger.info("=" * 60)
    
    page.quit()

if __name__ == "__main__":
    main()
