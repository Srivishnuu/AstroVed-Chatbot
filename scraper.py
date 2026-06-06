import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time

# ← Unoda website URL pottu
BASE_URL = "https://qa.astroved.com/"

visited = set()
all_text = []

def scrape_page(url):
    if url in visited:
        return
    if not url.startswith(BASE_URL):
        return
        
    visited.add(url)
    print(f"Scraping: {url}")
    
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        
        # Remove unwanted tags
        for tag in soup(["script", "style", "nav", 
                         "footer", "header", "aside"]):
            tag.decompose()
        
        # Extract clean text
        text = soup.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 40]
        
        if lines:
            all_text.append(f"\n--- PAGE: {url} ---\n")
            all_text.extend(lines)
        
        # Find all links on this page
        for a in soup.find_all("a", href=True):
            link = urljoin(BASE_URL, a["href"])
            # Only scrape same domain
            if urlparse(link).netloc == urlparse(BASE_URL).netloc:
                scrape_page(link)
                
        time.sleep(0.5)  # Be polite — don't overload server
        
    except Exception as e:
        print(f"Error scraping {url}: {e}")

# Run the scraper
print("Starting website scrape...")
scrape_page(BASE_URL)

# Save to knowledge_base.txt
with open("knowledge_base.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(all_text))

print(f"✅ Done! Scraped {len(visited)} pages")
print(f"✅ Saved to knowledge_base.txt")

