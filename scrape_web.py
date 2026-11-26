import requests
from bs4 import BeautifulSoup

# The URLs you want the AI to know about
urls = [
    "https://anamancs.com/",
    "https://anamancs.com/about-us/",
    "https://anamancs.com/pricing/", #(add other pages here)
    #"https://anamancs.com/services"
]

all_text = ""

for url in urls:
    print(f"Scraping {url}...")
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer"]):
            script.extract()
            
        text = soup.get_text(separator=' ', strip=True)
        all_text += f"\n\n--- Content from {url} ---\n\n{text}"
    except Exception as e:
        print(f"Failed to scrape {url}: {e}")

# Save the extracted text to a file
with open("website_knowledge.txt", "w", encoding="utf-8") as f:
    f.write(all_text)

print("Done! Saved to website_knowledge.txt")