import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin
from curl_cffi import requests

OTODOM_URLS = [
    ("Os. Tysiąclecia", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/osiedle-tysiaclecia?limit=72&priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Os. Witosa", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/osiedle-witosa?limit=72&priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Wełnowiec", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/welnowiec--jozefowiec?limit=72&priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Os. Paderewskiego", "Katowice", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice/osiedle-paderewskiego--muchowiec?limit=72&priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
    ("Klimzowiec", "Chorzów", "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/chorzow/chorzow/chorzow/centrum/klimzowiec?limit=72&priceMax=500000&areaMin=40&by=LATEST&direction=DESC"),
]

OLX_URLS = [
    ("Katowice", "https://www.olx.pl/nieruchomosci/mieszkania/sprzedaz/katowice/?search%5Bfilter_float_price%3Ato%5D=500000&search%5Bfilter_float_m%3Afrom%5D=40&search%5Border%5D=created_at%3Adesc"),
    ("Chorzów", "https://www.olx.pl/nieruchomosci/mieszkania/sprzedaz/chorzow/?search%5Bfilter_float_price%3Ato%5D=500000&search%5Bfilter_float_m%3Afrom%5D=40&search%5Border%5D=created_at%3Adesc"),
]

DISTRICT_ALIASES = {
    "Os. Tysiąclecia": ["tysiąclecia", "tysiaclecia", "chrobrego", "ułańska", "ulanska", "mieszka i"],
    "Os. Witosa": ["witosa", "sławka", "slawka", "rataja", "obroki"],
    "Wełnowiec": ["wełnowiec", "welnowiec", "józek", "jozefowiec", "korfantego", "bytkowska"],
    "Os. Paderewskiego": ["paderewskiego", "muchowiec", "sowińskiego", "sowinskiego", "graniczna", "trzech stawów", "3 stawów"],
    "Klimzowiec": ["klimzowiec", "gałeczki", "galeczki", "wiosenna", "różana", "rozana", "park róż", "park roz"],
}

ROOMS_MAP = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6,
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
}

old_thumbs = {}
if os.path.exists("listings.json"):
    try:
        with open("listings.json", "r", encoding="utf-8") as f:
            for row in json.load(f):
                oid = str(row.get("id") or "")
                thumb = row.get("thumbnail") or row.get("photo") or ""
                if oid and thumb:
                    old_thumbs[oid] = thumb
    except Exception:
        pass


def detect_district(city, text):
    hay = (text or "").lower()
    if city == "Chorzów":
        for kw in DISTRICT_ALIASES["Klimzowiec"]:
            if kw in hay:
                return "Klimzowiec"
        return None
    for district in ["Os. Tysiąclecia", "Os. Witosa", "Wełnowiec", "Os. Paderewskiego"]:
        for kw in DISTRICT_ALIASES[district]:
            if kw in hay:
                return district
    return None


def fetch_og_image(offer_url):
    try:
        resp = requests.get(offer_url, impersonate="chrome", timeout=10)
        if resp.status_code != 200:
            return ""
        html = resp.text
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
    except Exception:
        pass
    return ""


def parse_olx_card(card_html, city):
    link_m = re.search(r'href=["\'](https?://www\.olx\.pl/d/oferta/[^"\'?#]+|/d/oferta/[^"\'?#]+)["\']', card_html, re.I)
    if not link_m:
        return None
    offer_url = urljoin("https://www.olx.pl", link_m.group(1))

    title_m = re.search(r'<h[2-6][^>]*>(.*?)</h[2-6]>', card_html, re.S | re.I)
    title = re.sub(r"<[^>]+>", " ", title_m.group(1)).strip() if title_m else ""
    title = re.sub(r"\s+", " ", title)
    if not title:
        slug_part = offer_url.rstrip("/").split("/")[-1].replace(".html", "").replace("-", " ")
        title = slug_part.capitalize()

    plain_text = re.sub(r"<[^>]+>", " ", card_html)
    plain_text = re.sub(r"\s+", " ", plain_text)

    price_m = re.search(r"(\d[\d\s]{2,9})\s*zł", plain_text, re.I)
    if not price_m:
        return None
    try:
        price = int(re.sub(r"\s+", "", price_m.group(1)))
    except ValueError:
        return None

    area_m = re.search(r"(\d{2,3}(?:[.,]\d{1,2})?)\s*m²", plain_text, re.I)
    if not area_m:
        return None
    try:
        area = float(area_m.group(1).replace(",", "."))
    except ValueError:
        return None

    if price <= 0 or price > 500000 or area < 40:
        return None

    district = detect_district(city, f"{title} {plain_text} {offer_url}")
    if not district:
        return None

    rooms = 2
    rooms_m = re.search(r"\b([1-6])\s*(?:pok|pokoj)", f"{title} {plain_text}", re.I)
    if rooms_m:
        rooms = int(rooms_m.group(1))

    img_m = re.search(
        r'https://ireland\.apollo\.olxcdn\.com(?::443)?/v1/files/[^"\'\\<\s&]+',
        card_html,
        re.I,
    )
    thumb = img_m.group(0).replace("&amp;", "&").strip() if img_m else ""

    id_m = re.search(r"-ID([A-Za-z0-9]+)\.html", offer_url)
    offer_id = f"olx-ID{id_m.group(1)}" if id_m else f"olx-{abs(hash(offer_url)) % 10**8}"

    return {
        "id": offer_id,
        "district": district,
        "city": city,
        "street": "",
        "price": price,
        "area": area,
        "rooms": rooms,
        "adminFee": 0,
        "condition": "Do zamieszkania",
        "firstListed": datetime.utcnow().strftime("%Y-%m-%d"),
        "title": title,
        "otodomUrl": "",
        "olxUrl": offer_url,
        "thumbnail": thumb,
    }


results = []
seen_slugs = set()
seen_olx_urls = set()
og_fetches = 0
MAX_OG_FETCHES = 40

for district, city, url in OTODOM_URLS:
    print(f"[Otodom] Fetching {district}...", flush=True)
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
            if not slug or slug in seen_slugs:
                continue
            price = (it.get("totalPrice") or {}).get("value")
            area = it.get("areaInSquareMeters")
            if not price or not area or price > 500000 or area < 40:
                continue
            seen_slugs.add(slug)

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

for city, url in OLX_URLS:
    print(f"[OLX] Fetching {city}...", flush=True)
    try:
        r = requests.get(url, impersonate="chrome", timeout=15)
        print(f"  HTTP {r.status_code}", flush=True)
        cards = re.findall(r'<div[^>]+data-cy=["\']l-card["\'][^>]*>.*?(?=<div[^>]+data-cy=["\']l-card["\']|</main>|$)', r.text, re.S | re.I)
        if not cards:
            cards = re.findall(r'<article[^>]*>.*?</article>', r.text, re.S | re.I)
        print(f"  Found {len(cards)} raw cards in {city}", flush=True)

        added_olx = 0
        for card in cards:
            parsed = parse_olx_card(card, city)
            if not parsed or parsed["olxUrl"] in seen_olx_urls:
                continue
            seen_olx_urls.add(parsed["olxUrl"])

            if not parsed["thumbnail"] and parsed["id"] in old_thumbs:
                parsed["thumbnail"] = old_thumbs[parsed["id"]]
            if not parsed["thumbnail"] and og_fetches < MAX_OG_FETCHES:
                og_fetches += 1
                parsed["thumbnail"] = fetch_og_image(parsed["olxUrl"])
                time.sleep(0.25)

            results.append(parsed)
            added_olx += 1
        print(f"  Added {added_olx} matching OLX offers in {city}", flush=True)
    except Exception as e:
        print(f"  Error on OLX {city}: {e}", flush=True)
    time.sleep(1)

print(f"Total saved: {len(results)} (og:image fetched: {og_fetches})", flush=True)
with open("listings.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
