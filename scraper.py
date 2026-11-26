import json, re, time
from datetime import datetime
from playwright.sync_api import sync_playwright

URLS = [
    ("Os. Tysiąclecia", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/osiedle-tysiaclecia?priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Os. Witosa", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/osiedle-witosa?priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Wełnowiec", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/welnowiec-jozefowiec?priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Os. Paderewskiego", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/osiedle-paderewskiego--muchowiec?priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Klimzowiec", "Chorzów", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/chorzow/chorzow/chorzow/centrum/klimzowiec?priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
]

results = []
seen = set()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        locale="pl-PL",
        viewport={"width": 1366, "height": 768}
    )
    page = context.new_page()

    for district, city, url in URLS:
        print(f"Fetching {district}...", flush=True)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2500)
            html = page.content()
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            if not m:
                print(f"  No __NEXT_DATA__ found for {district} (likely blocked or changed layout)", flush=True)
                continue
            data = json.loads(m.group(1))
            items = data.get("props", {}).get("pageProps", {}).get("data", {}).get("searchAds", {}).get("items", [])
            print(f"  Found {len(items)} items in {district}", flush=True)
            for it in items:
                slug = it.get("slug")
                if not slug or slug in seen:
                    continue
                price = (it.get("totalPrice") or {}).get("value")
                area = it.get("areaInSquareMeters")
                if not price or not area or price > 500000 or area < 40:
                    continue
                seen.add(slug)
                imgs = it.get("images") or []
                thumb = imgs[0].get("medium") or imgs[0].get("large") if imgs else ""
                street = ((it.get("location") or {}).get("address") or {}).get("street") or {}
                results.append({
                    "id": str(it.get("id", slug)),
                    "district": district,
                    "city": city,
                    "street": street.get("name", ""),
                    "price": int(price),
                    "area": float(area),
                    "rooms": int(it.get("roomsNumber") or 2),
                    "adminFee": int(((it.get("rent") or {}).get("value")) or 0),
                    "condition": "Do zamieszkania",
                    "firstListed": (it.get("dateCreatedFirst") or it.get("dateCreated") or datetime.utcnow().strftime("%Y-%m-%d"))[:10],
                    "title": it.get("title", "Mieszkanie"),
                    "otodomUrl": f"https://www.otodom.pl/pl/oferta/{slug}",
                    "olxUrl": "",
                    "thumbnail": thumb
                })
        except Exception as e:
            print(f"  Error on {district}: {e}", flush=True)
        time.sleep(1)

    browser.close()

print(f"Total saved: {len(results)}", flush=True)
with open("listings.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
