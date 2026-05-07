import cloudscraper
from bs4 import BeautifulSoup

def analyze_page():
    url = "https://vortexscans.org/series/rebirth-of-the-divine-demon/chapter-41"
    scraper = cloudscraper.create_scraper()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    response = scraper.get(url, headers=headers, timeout=15)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        with open("page_analysis.html", "w", encoding="utf-8") as f:
            f.write(soup.prettify())
        print("Page content saved to page_analysis.html")
    else:
        print(f"Failed to fetch page. Status code: {response.status_code}")

if __name__ == "__main__":
    analyze_page()