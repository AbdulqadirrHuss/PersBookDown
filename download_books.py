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
        
        book = page.ele("css:div.cursor-pointer, a[href*='/text/'], a[href*='/book/']", timeout=60)
        if not book:
            logger.error("No results found")
            page.get_screenshot(path="debug_no_results.png")
            return False
        
        # Click book
        logger.info("Clicking book...")
        if not safe_click(page, book):
            return False
        random_delay(2, 3)
        
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
            
        if not read:
            logger.warning("No Read button")
            page.get_screenshot(path="debug_no_read.png")
            return False
        
        logger.info("Clicking Read...")
        if not safe_click(page, read):
            return False
        random_delay(3, 5)
        
        if not wait_and_solve_cloudflare(page):
            return False
        
        # Find iframe - Deep Search for ANY iframe with correct src
        logger.info("Waiting for viewer iframe...")
        page.get_screenshot(path="debug_before_iframe.png")
        
        iframe = None
        
        # Try finding ANY iframe by iterating through all of them
        for attempt in range(3):
            logger.info(f"Iframe search attempt {attempt + 1}/3")
            
            # Scroll page to trigger lazy loading
            page.run_js("window.scrollTo(0, document.body.scrollHeight / 2)")
            random_delay(2, 3)
            
            # Get ALL iframes on the page
            all_iframes = page.eles("css:iframe")
            logger.info(f"Found {len(all_iframes)} total iframes on page")
            
            for fr in all_iframes:
                try:
                    src = fr.attr("src")
                    if not src:
                        continue
                        
                    logger.info(f"Checking iframe src: {src[:50]}...")
                    
                    if 'fast_view' in src or 'web-premium' in src or 'url=' in src:
                        logger.info(f"MATCH FOUND! Iframe src: {src}")
                        iframe = fr
                        break
                except Exception as e:
                    logger.warning(f"Error checking iframe: {e}")
            
            if iframe:
                break
                
            random_delay(3, 5)

        if not iframe:
            logger.error("No viewer iframe found after deep search")
            page.get_screenshot(path="debug_no_iframe.png")
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(page.html)
            return False
            
        src = iframe.attr("src")
        if not src:
            logger.error("Iframe has no src attribute")
            return False
        
        # Extract URL
        full_src = urljoin("https://welib.org", src)
        parsed = urlparse(full_src)
        qs = parse_qs(parsed.query)
        
        real_url = qs.get('url', [None])[0]
        if not real_url:
            return False
        
        real_url = unquote(real_url)
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
