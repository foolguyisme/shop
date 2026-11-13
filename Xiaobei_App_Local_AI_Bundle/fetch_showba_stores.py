"""Refresh the store directory from SHOWBA's public store finder."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path

import requests

BASE = "https://www.showba.com.tw/store_page"
ROOT = Path(__file__).resolve().parent
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SHOWBA-Prototype/1.0)"}
SPECIAL_IDS = {"崑大店": "kunda", "科工店": "kegong", "麻豆店": "madou"}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


class StoreParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stores = []
        self.current = None
        self.depth = 0
        self.field = None
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "div" and "store_detail" in classes and self.current is None:
            self.current = {"name": "", "address": "", "phone": "", "hours": "", "services": "", "mapsUrl": ""}
            self.depth = 1
            self.field = None
            self.stack = [("div", None)]
            return
        if self.current is None:
            return

        previous = self.field
        self.stack.append((tag, previous))
        if tag == "div":
            self.depth += 1
            if "add" in classes:
                self.field = "address"
            elif "phone" in classes:
                self.field = "phone"
            elif "time" in classes:
                self.field = "hours"
            elif "service" in classes:
                self.field = "services"
            elif "navigation" in classes:
                self.field = "navigation"
        elif tag == "h3":
            self.field = "name"
        elif tag == "a" and self.field == "navigation":
            self.current["mapsUrl"] = attrs.get("href", "")

    def handle_data(self, data):
        if self.current is not None and self.field in self.current:
            self.current[self.field] += data

    def handle_endtag(self, tag):
        if self.current is None:
            return
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if index is None:
            return
        _, previous = self.stack[index]
        self.stack = self.stack[:index]
        if tag == "div":
            self.depth -= 1
            if self.depth <= 0:
                store = {key: clean(value) for key, value in self.current.items()}
                if store["name"] and store["address"]:
                    self.stores.append(store)
                self.current = None
                self.depth = 0
                self.field = None
                self.stack = []
                return
        self.field = previous


def district_from_address(city_name, address):
    tail = address[len(city_name):] if address.startswith(city_name) else address
    match = re.match(r"(.{1,8}?(?:區|鄉|鎮|市))", tail)
    return match.group(1) if match else ""


def fetch_city(city, districts):
    response = requests.get(BASE, params={"menuid": "9", "city": city["id"]}, headers=HEADERS, timeout=35)
    response.raise_for_status()
    parser = StoreParser()
    parser.feed(response.text)
    results = []
    for index, store in enumerate(parser.stores, 1):
        district = district_from_address(city["name"], store["address"])
        district_id = next((d["id"] for d in districts if d["name"] == district), "")
        store_id = SPECIAL_IDS.get(store["name"], f"tw-{city['id']}-{index:03d}")
        results.append({
            "id": store_id,
            "name": store["name"],
            "city": city["name"],
            "cityId": city["id"],
            "district": district,
            "districtId": district_id,
            "area": district,
            "address": store["address"],
            "phone": store["phone"],
            "hours": store["hours"],
            "services": store["services"],
            "mapsUrl": store["mapsUrl"],
            "source": "小北百貨官方門市查詢"
        })
    return results


def main():
    response = requests.get(BASE, params={"menuid": "9"}, headers=HEADERS, timeout=35)
    response.raise_for_status()
    city_match = re.search(r"var\s+cityList\s*=\s*(\[.*?\]);", response.text, re.S)
    canton_match = re.search(r"var\s+cantonObj\s*=\s*(\{.*?\});", response.text, re.S)
    if not city_match or not canton_match:
        raise RuntimeError("Could not read city/district filters from SHOWBA's store finder")
    cities = json.loads(city_match.group(1))
    canton_obj = json.loads(canton_match.group(1))

    stores = []
    errors = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(fetch_city, city, canton_obj.get(city["id"], [])): city for city in cities}
        for job in as_completed(jobs):
            city = jobs[job]
            try:
                stores.extend(job.result())
            except Exception as error:  # retain other cities if one query fails
                errors.append({"city": city["name"], "error": str(error)})
            time.sleep(.04)

    # Keep source order stable and remove any duplicated store IDs.
    unique = {}
    for store in stores:
        unique[store["id"]] = store
    stores = sorted(unique.values(), key=lambda s: (s["city"], s["district"], s["name"]))
    payload = {
        "source": BASE + "?menuid=9",
        "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "officialCityCount": len(cities),
        "storeCount": len(stores),
        "errors": errors,
        "stores": stores,
    }
    (ROOT / "stores-tw.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    js = "window.SHOWBA_STORE_DATA=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\nwindow.SHOWBA_STORES=window.SHOWBA_STORE_DATA.stores;\n"
    (ROOT / "stores-tw.js").write_text(js, encoding="utf-8")
    print(json.dumps({"cityCount": len(cities), "storeCount": len(stores), "errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
