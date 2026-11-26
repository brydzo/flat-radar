import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8765
DATA_FILE = Path(__file__).with_name("listings_cache.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

OTODOM_DISTRICTS = {
    "Os. Witosa": ("Katowice", "slaskie/katowice/katowice/katowice/osiedle-witosa"),
    "Os. Tysiąclecia": ("Katowice", "slaskie/katowice/katowice/katowice/osiedle-tysiaclecia"),
    "Os. Paderewskiego": ("Katowice", "slaskie/katowice/katowice/katowice/osiedle-paderewskiego--muchowiec"),
    "Wełnowiec-Józefowiec": ("Katowice", "slaskie/katowice/katowice/katowice/welnowiec--jozefowiec"),
    "Dąb": ("Katowice", "slaskie/katowice/katowice/katowice/dab"),
    "Koszutka": ("Katowice", "slaskie/katowice/katowice/katowice/koszutka"),
    "Zawodzie": ("Katowice", "slaskie/katowice/katowice/katowice/zawodzie"),
    "Klimzowiec": ("Chorzów", "slaskie/chorzow/chorzow/chorzow/centrum/klimzowiec"),
}

OLX_DISTRICT_MAP = {
    "osiedle witosa": "Os. Witosa",
    "witosa": "Os. Witosa",
    "osiedle tysiąclecia": "Os. Tysiąclecia",
    "tysiąclecia": "Os. Tysiąclecia",
    "osiedle paderewskiego": "Os. Paderewskiego",
    "paderewskiego": "Os. Paderewskiego",
    "wełnowiec": "Wełnowiec-Józefowiec",
    "józefowiec": "Wełnowiec-Józefowiec",
    "dąb": "Dąb",
    "koszutka": "Koszutka",
    "zawodzie": "Zawodzie",
    "klimzowiec": "Klimzowiec",
}


def fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=18) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def days_since(iso_str: str) -> int:
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return max(0, (now - dt).days)
    except Exception:
        return 0


def parse_rooms(val) -> int:
    if isinstance(val, int):
        return val
    m = re.search(r"(\d+)", str(val or ""))
    return int(m.group(1)) if m else 2


def fetch_otodom_district(district: str, city: str, loc_slug: str) -> list[dict]:
    url = (
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{loc_slug}"
        f"?limit=36&ownerTypeSingleSelect=ALL&priceMax=550000&areaMin=40&areaMax=75&by=LATEST&direction=DESC"
    )
    html = fetch_url(url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    payload = json.loads(m.group(1))
    items = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("data", {})
        .get("searchAds", {})
        .get("items", [])
    )
    results = []
    for it in items:
        price_obj = it.get("totalPrice") or {}
        price = price_obj.get("value")
        area = it.get("areaInSquareMeters")
        if not price or not area or price > 550000 or not (40 <= float(area) <= 75):
            continue

        slug = it.get("slug", "")
        ad_id = f"OT-{it.get('id', slug[-6:])}"
        images = it.get("images") or []
        thumb = ""
        if images and isinstance(images[0], dict):
            thumb = images[0].get("medium") or images[0].get("large") or ""

        rent_obj = it.get("rentPrice") or {}
        admin_fee = rent_obj.get("value") or 0

        loc = it.get("location") or {}
        street_obj = (loc.get("address") or {}).get("street") or {}
        street = street_obj.get("name") or district

        floor_raw = str(it.get("floorNumber") or "").replace("FLOOR_", "")
        floor_map = {"GROUND": "0", "GARRET": "Poddasze", "CELLAR": "Parter"}
        floor = floor_map.get(floor_raw, floor_raw or "-")

        results.append({
            "id": ad_id,
            "portal": "Otodom",
            "city": city,
            "district": district,
            "street": street,
            "title": it.get("title") or f"Mieszkanie {district}",
            "price": int(round(float(price))),
            "prevPrice": None,
            "adminFee": int(round(float(admin_fee))) if admin_fee else 720,
            "condition": "Rynek wtórny / Oferta",
            "conditionType": "good",
            "area": round(float(area), 2),
            "rooms": parse_rooms(it.get("roomsNumber")),
            "floor": floor,
            "daysOld": days_since(it.get("dateCreatedFirst") or it.get("dateCreated")),
            "duplicateGroup": None,
            "url": f"https://www.otodom.pl/pl/oferta/{slug}" if slug else url,
            "thumb": thumb,
        })
    return results


def fetch_olx_offers() -> list[dict]:
    results = []
    cities = [("Katowice", 7691), ("Chorzów", 7631)]
    for city, city_id in cities:
        api_url = (
            f"https://www.olx.pl/api/v1/offers/?offset=0&limit=50&category_id=1307"
            f"&city_id={city_id}&filter_float_price:to=550000"
            f"&filter_float_m:from=40&filter_float_m:to=75&sort_by=created_at:desc"
        )
        try:
            raw = json.loads(fetch_url(api_url))
        except Exception:
            continue

        for it in raw.get("data", []):
            loc = it.get("location") or {}
            dist_name = ((loc.get("district") or {}).get("name") or "").lower()
            title_lower = (it.get("title") or "").lower()
            matched_dist = None
            for key, canonical in OLX_DISTRICT_MAP.items():
                if key in dist_name or key in title_lower:
                    matched_dist = canonical
                    break
            if not matched_dist:
                continue

            price = 0
            area = 0.0
            rooms = 2
            floor = "-"
            admin_fee = 700
            for p in it.get("params", []):
                k = p.get("key")
                v = p.get("value") or {}
                if k == "price":
                    price = int(round(float(v.get("value") or 0)))
                elif k == "m":
                    area = float(v.get("key") or 0)
                elif k == "rooms":
                    rooms = parse_rooms(v.get("key"))
                elif k == "floor_select":
                    floor = str(v.get("label") or "-")
                elif k == "rent":
                    try:
                        admin_fee = int(round(float(v.get("key") or 700)))
                    except Exception:
                        pass

            if not price or price > 550000 or not (40 <= area <= 75):
                continue

            photos = it.get("photos") or []
            thumb = ""
            if photos and isinstance(photos[0], dict):
                link = photos[0].get("link") or ""
                thumb = link.replace("{width}", "314").replace("{height}", "236")

            results.append({
                "id": f"OLX-{it.get('id')}",
                "portal": "OLX",
                "city": "Chorzów" if matched_dist == "Klimzowiec" else "Katowice",
                "district": matched_dist,
                "street": (loc.get("district") or {}).get("name") or matched_dist,
                "title": it.get("title") or f"Mieszkanie {matched_dist}",
                "price": price,
                "prevPrice": None,
                "adminFee": admin_fee,
                "condition": "Oferta OLX",
                "conditionType": "good",
                "area": round(area, 2),
                "rooms": rooms,
                "floor": floor,
                "daysOld": days_since(it.get("created_time")),
                "duplicateGroup": None,
                "url": it.get("url") or "https://www.olx.pl",
                "thumb": thumb,
            })
    return results


def scrape_all() -> dict:
    prev_prices = {}
    if DATA_FILE.exists():
        try:
            old = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for row in old.get("listings", []):
                prev_prices[row["id"]] = row["price"]
        except Exception:
            pass

    all_items = []
    errors = []
    for dist, (city, slug) in OTODOM_DISTRICTS.items():
        try:
            all_items.extend(fetch_otodom_district(dist, city, slug))
        except Exception as e:
            errors.append(f"Otodom {dist}: {e}")

    try:
        all_items.extend(fetch_olx_offers())
    except Exception as e:
        errors.append(f"OLX: {e}")

    # Tag price changes & cross-portal duplicates (same district + rounded area + price)
    seen_sig = {}
    for item in all_items:
        old_p = prev_prices.get(item["id"])
        if old_p and old_p != item["price"]:
            item["prevPrice"] = old_p
        sig = f"{item['district']}-{round(item['area'])}-{round(item['price'], -3)}"
        if sig in seen_sig:
            grp = f"DUP-{abs(hash(sig)) % 9000 + 1000}"
            item["duplicateGroup"] = grp
            seen_sig[sig]["duplicateGroup"] = grp
        else:
            seen_sig[sig] = item

    payload = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(all_items),
        "errors": errors,
        "listings": all_items,
    }
    DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/listings":
            if DATA_FILE.exists():
                body = DATA_FILE.read_bytes()
            else:
                body = json.dumps(scrape_all(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/refresh":
            payload = scrape_all()
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        return super().do_GET()


if __name__ == "__main__":
    print(f"Apartment Monitor running at http://127.0.0.1:{PORT}/dashboard.html")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
