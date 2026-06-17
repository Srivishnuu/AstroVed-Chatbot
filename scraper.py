"""
AstroVed.AI — Sitemap-based Website Scraper
Uses sitemap.xml to get ALL page URLs (parent + child pages) safely.
NO recursion crawling. NO infinite date-loop. NO crash.
"""

import requests
from bs4 import BeautifulSoup
import time
import re

BASE_URL = "https://www.astroved.com"
SITEMAP_URL = "https://www.astroved.com/sitemaps/astroved-sitemap.xml"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

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


def main():
    print("=" * 60)
    print("Step 1: Reading sitemap.xml ...")
    print("=" * 60)

    all_urls = get_all_sitemap_urls(SITEMAP_URL)
    all_urls = sorted(set(all_urls))  # dedupe

    print(f"\nTotal unique URLs found (after skipping date-horoscope pages): {len(all_urls)}\n")

    if not all_urls:
        print("No URLs found! Check if sitemap.xml exists at:", SITEMAP_URL)
        return

    # Save URL list for review before scraping content
    with open("all_urls.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(all_urls))
    print("Saved full URL list to all_urls.txt — review it before running content scrape!\n")

    print("=" * 60)
    print("Step 2: Scraping content from each page...")
    print("=" * 60)

    all_text = []
    success_count = 0

    for i, url in enumerate(all_urls, 1):
        print(f"[{i}/{len(all_urls)}] Scraping: {url}")
        title, lines = scrape_page_content(url)
        if lines:
            all_text.append(f"\n--- PAGE: {title} ({url}) ---\n")
            all_text.extend(lines)
            success_count += 1
        time.sleep(0.4)  # polite delay so we don't hammer the server

    with open("knowledge_base.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(all_text))

    print("\n" + "=" * 60)
    print(f"DONE! Scraped {success_count}/{len(all_urls)} pages successfully")
    print(f"Saved to knowledge_base.txt")
    print("=" * 60)


if __name__ == "__main__":
    main()