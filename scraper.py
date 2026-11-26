import json, os, re, time
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

DEBUG_ONE = True

old_thumbs = {}
if os.path.exists("listings.json"):
    try:
        with open("listings.json", "r", encoding="utf-8") as f:
            for row in json.load(f):
                if row.get("id") and row.get("thumbnail"):
                    old_thumbs[str(row["id"])] = row["thumbnail"]
    except Exception:
        pass

def fetch_og_image(offer_url):
    global DEBUG_ONE
    try:
        resp = requests.get(offer_url, impersonate="chrome", timeout=10)
        html = resp.text
        if DEBUG_ONE:
            DEBUG_ONE = False
            print(
                f"  [DEBUG] status={resp.status_code}, len={len(html)}, "
                f"has_olxcdn={'apollo.olxcdn.com' in html}, has_og={'og:image' in html}",
                flush=True,
            )
        if resp.status_code != 200:
            return ""
        for pat in [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'https://ireland\.apollo\.olxcdn\.com/v1/files/[^"\'\\<\s&]+',
        ]:
            m = re.search(pat, html, re.I)
            if m:
                url = m.group(1) if m.lastindex else m.group(0)
                return url.replace("&amp;", "&").strip()
    except Exception as e:
        print(f"  [DEBUG] fetch_og_image err: {e}", flush=True)
    return ""

results = []
seen = set()
og_fetches = 0
MAX_OG_FETCHES = 40

for district, city, url in URLS:
    print(f"Fetching {district}...", flush=True)
    try:
        r = requests.get(url, impersonate="chrome", timeout=15)
        print(f"  HTTP {r.status_code}", flush=True)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if not m:
            print(f"  No __NEXT_DATA__ found for {district}", flush=True)
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

            offer_id = str(it.get("id", slug))
            offer_url = f"https://www.otodom.pl/pl/oferta/{slug}"

            thumb = ""
            imgs = it.get("images") or []
            if imgs:
                first = imgs[0]
                if isinstance(first, str):
                    thumb = first
                elif isinstance(first, dict):
                    thumb = (
                        first.get("medium")
                        or first.get("large")
                        or first.get("thumbnail")
                        or first.get("url")
                        or first.get("src")
                        or next((v for v in first.values() if isinstance(v, str) and v.startswith("http")), "")
                    )
            if not thumb:
                m_img = re.search(
                    r'https://[a-z0-9.-]*(?:olxcdn|otodom|static)[^"\'\\<\s]+(?:\.jpg|\.jpeg|\.webp|/image[^"\'\\<\s]*)',
                    json.dumps(it),
                    re.I,
                )
                if m_img:
                    thumb = m_img.group(0)
            if not thumb and offer_id in old_thumbs:
                thumb = old_thumbs[offer_id]
            if not thumb and og_fetches < MAX_OG_FETCHES:
                og_fetches += 1
                thumb = fetch_og_image(offer_url)
                time.sleep(0.25)

            street = ((it.get("location") or {}).get("address") or {}).get("street") or {}
            raw_rooms = str(it.get("roomsNumber") or "2").upper()
            rooms = ROOMS_MAP.get(raw_rooms, 2)
            results.append({
                "id": offer_id,
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
                "otodomUrl": offer_url,
                "olxUrl": "",
                "thumbnail": thumb,
            })
    except Exception as e:
        print(f"  Error on {district}: {e}", flush=True)
    time.sleep(1)

print(f"Total saved: {len(results)} (og:image fetched: {og_fetches})", flush=True)
with open("listings.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
