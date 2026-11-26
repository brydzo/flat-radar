import json, re, time
from datetime import datetime
from curl_cffi import requests

URLS = [
    ("Os. Tysiąclecia", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/osiedle-tysiaclecia?limit=72&priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Os. Witosa", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/osiedle-witosa?limit=72&priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Wełnowiec", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/welnowiec--jozefowiec?limit=72&priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Os. Paderewskiego", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/osiedle-paderewskiego--muchowiec?limit=72&priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Klimzowiec", "Chorzów", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/chorzow/chorzow/chorzow/centrum/klimzowiec?limit=72&priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
]

ROOMS_MAP = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6,
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6
}

results = []
seen = set()

for district, city, url in URLS:
    print(f"Fetching {district}...")
    try:
        r = requests.get(url, impersonate="chrome", timeout=15)
        print(f"  HTTP {r.status_code}")
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if not m:
            print(f"  No __NEXT_DATA__ found for {district}")
            continue
        data = json.loads(m.group(1))
        items = data.get("props", {}).get("pageProps", {}).get("data", {}).get("searchAds", {}).get("items", [])
        print(f"  Found {len(items)} items in {district}")
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
            thumb = (imgs[0].get("medium") or imgs[0].get("large")) if imgs else ""
            street = ((it.get("location") or {}).get("address") or {}).get("street") or {}
            raw_rooms = str(it.get("roomsNumber") or "2").upper()
            rooms = ROOMS_MAP.get(raw_rooms, 2)
            results.append({
                "id": str(it.get("id", slug)),
                "district": district,
                "city": city,
                "street": street.get("name", ""),
                "price": int(price),
                "area": float(area),
                "rooms": rooms,
                "adminFee": int(((it.get("rent") or {}).get("value")) or 0),
                "condition": "Do zamieszkania",
                "firstListed": (it.get("dateCreatedFirst") or it.get("dateCreated") or datetime.utcnow().strftime("%Y-%m-%d"))[:10],
                "title": it.get("title", "Mieszkanie"),
                "otodomUrl": f"https://www.otodom.pl/pl/oferta/{slug}",
                "olxUrl": "",
                "thumbnail": thumb
            })
    except Exception as e:
        print(f"  Error on {district}: {e}")
    time.sleep(1)

print(f"Total saved: {len(results)}")
with open("listings.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
