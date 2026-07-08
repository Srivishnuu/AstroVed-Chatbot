"""
AstroVed.AI — Sitemap-based Website Scraper (INCREMENTAL MODE)
Uses sitemap.xml to get ALL page URLs (parent + child pages) safely.
NO recursion crawling. NO infinite date-loop. NO crash.

INCREMENTAL BEHAVIOUR (new):
- Reads existing all_urls.txt + knowledge_base.txt (old data) first.
- Compares against the fresh sitemap to find ONLY new URLs.
- Scrapes ONLY the new URLs (fast, doesn't re-hit the whole site daily).
- APPENDS new content to knowledge_base.txt and all_urls.txt.
- Old data is never deleted or overwritten — only added to.
"""

import requests
from bs4 import BeautifulSoup
import os
import time
import re

BASE_URL = "https://www.astroved.com"
SITEMAP_URL = "https://www.astroved.com/sitemaps/astroved-sitemap.xml"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

ALL_URLS_FILE = "all_urls.txt"
KB_FILE = "knowledge_base.txt"

# ── Skip patterns — daily/weekly/monthly horoscope DATE pages (infinite combos) ──
SKIP_PATTERNS = [
    r"-daily-horoscope-\d{4}",      # e.g. aquarius-daily-horoscope-2028-09-26
    r"-weekly-horoscope-\d{4}",
    r"-monthly-horoscope-\d{4}",
    r"-yearly-horoscope-\d{4}",
    r"/horoscope/\d{4}-\d{2}-\d{2}",
    r"\?date=",
    r"\?page=",
    r"/tag/",
    r"/author/",
    r"/page/\d+",
]

def should_skip(url: str) -> bool:
    for pat in SKIP_PATTERNS:
        if re.search(pat, url):
            return True
    return False


def get_all_sitemap_urls(sitemap_url, depth=0, seen_sitemaps=None):
    """
    Reads sitemap index files (sitemaps that list other sitemaps) using a
    simple loop/recursion limited to sitemap files only (never page content),
    so depth is always small (2-3 levels) — no risk of runaway recursion.
    """
    if seen_sitemaps is None:
        seen_sitemaps = set()
    if sitemap_url in seen_sitemaps or depth > 5:
        return []
    seen_sitemaps.add(sitemap_url)

    urls = []
    try:
        res = requests.get(sitemap_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.content, "xml")

        # Case 1: sitemap index (contains <sitemap><loc>...other sitemap...</loc></sitemap>)
        sitemap_tags = soup.find_all("sitemap")
        if sitemap_tags:
            print(f"Found sitemap index with {len(sitemap_tags)} child sitemaps")
            for s in sitemap_tags:
                loc = s.find("loc")
                if loc:
                    child_url = loc.text.strip()
                    print(f"  -> Reading child sitemap: {child_url}")
                    urls.extend(get_all_sitemap_urls(child_url, depth + 1, seen_sitemaps))
                    time.sleep(0.3)
            return urls

        # Case 2: regular sitemap with <url><loc>...</loc></url>
        url_tags = soup.find_all("url")
        for u in url_tags:
            loc = u.find("loc")
            if loc:
                page_url = loc.text.strip()
                if not should_skip(page_url):
                    urls.append(page_url)

        print(f"  Collected {len(urls)} URLs from {sitemap_url}")
        return urls

    except Exception as e:
        print(f"  Error reading sitemap {sitemap_url}: {e}")
        return []


def scrape_page_content(url):
    """Scrape clean text content from a single page — NO link-following."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(res.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "form"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 40]

        title_tag = soup.find("title")
        title = title_tag.text.strip() if title_tag else url

        return title, lines

    except Exception as e:
        print(f"  Error scraping {url}: {e}")
        return None, []


def load_existing_urls():
    """Load URLs that were already scraped in previous runs (from all_urls.txt)."""
    if not os.path.exists(ALL_URLS_FILE):
        return set()
    with open(ALL_URLS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def main():
    print("=" * 60)
    print("Step 1: Reading sitemap.xml ...")
    print("=" * 60)

    sitemap_urls = get_all_sitemap_urls(SITEMAP_URL)
    sitemap_urls = sorted(set(sitemap_urls))  # dedupe
    print(f"\nTotal unique URLs found in sitemap (after skipping date-horoscope pages): {len(sitemap_urls)}\n")

    if not sitemap_urls:
        print("No URLs found! Check if sitemap.xml exists at:", SITEMAP_URL)
        return

    print("=" * 60)
    print("Step 2: Comparing against previously scraped URLs...")
    print("=" * 60)

    existing_urls = load_existing_urls()
    print(f"Previously scraped URLs on record: {len(existing_urls)}")

    new_urls = [u for u in sitemap_urls if u not in existing_urls]
    print(f"NEW URLs found this run: {len(new_urls)}\n")

    if not new_urls:
        print("No new pages found today — knowledge_base.txt stays unchanged.")
        return

    for u in new_urls:
        print(f"  + NEW: {u}")

    print("\n" + "=" * 60)
    print("Step 3: Scraping content from NEW pages only...")
    print("=" * 60)

    new_text_chunks = []
    success_count = 0
    successfully_scraped_urls = []

    for i, url in enumerate(new_urls, 1):
        print(f"[{i}/{len(new_urls)}] Scraping: {url}")
        title, lines = scrape_page_content(url)
        if lines:
            new_text_chunks.append(f"\n--- PAGE: {title} ({url}) ---\n")
            new_text_chunks.extend(lines)
            success_count += 1
            successfully_scraped_urls.append(url)
        else:
            # Page failed to scrape — don't mark it as "seen" so we retry
            # it again on the next run instead of silently skipping forever.
            print(f"  Skipped (no content) — will retry next run: {url}")
        time.sleep(0.4)  # polite delay so we don't hammer the server

    if not new_text_chunks:
        print("\nAll new URLs failed to scrape — nothing to append this run.")
        return

    # ── APPEND (never overwrite) new content to knowledge_base.txt ──
    with open(KB_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(new_text_chunks))
        f.write("\n")

    # ── APPEND newly-successful URLs to all_urls.txt so they aren't re-scraped ──
    with open(ALL_URLS_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(successfully_scraped_urls))
        f.write("\n")

    print("\n" + "=" * 60)
    print(f"DONE! Added {success_count}/{len(new_urls)} new pages")
    print(f"knowledge_base.txt and all_urls.txt updated (old data preserved)")
    print("=" * 60)


if __name__ == "__main__":
    main()