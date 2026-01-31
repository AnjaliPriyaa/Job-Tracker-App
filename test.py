import requests
from bs4 import BeautifulSoup
url = "https://www.linkedin.com/jobs/search/?location=Bengaluru%2C%20India&keywords=(%22software%20engineer%22%20OR%20devops%20OR%20devsecops%20OR%20infrastructure%20OR%20%22site%20reliability%22%20OR%20%22cloud%20security%22%20OR%20sre%20OR%20%22platform%20engineer%22%20OR%20%22cloud%20engineer%22)%20AND%20(devops%20OR%20kubernetes%20OR%20aws%20OR%20azure%20OR%20terraform%20OR%20ansible)&f_TPR=r54000&f_E=3%2C4"
resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
# print(resp.text)
soup = BeautifulSoup(resp.text, "html.parser")

for card in soup.find_all("div", class_="base-card"):
    # Skip promoted and popular jobs
    # text = card.get_text().lower()
    # Get job info
    title_tag = card.find("h3", class_="base-search-card__title")
    company_tag = card.find("h4", class_="base-search-card__subtitle")
    link_tag = card.find("a", class_="base-card__full-link")

    if not title_tag or not link_tag:
        continue

    title = title_tag.get_text(strip=True)
    company = company_tag.get_text(strip=True) if company_tag else ""
    print(f"Title: {title}, Company: {company}, URL: {link_tag.get('href')}")