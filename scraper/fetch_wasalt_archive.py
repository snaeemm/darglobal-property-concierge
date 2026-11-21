"""Fetch archived Wasalt pages from the Internet Archive (Wayback Machine) and keep only property facts (no personal data)."""
import json, random, re, time, html as H
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import urllib.request

HERE = Path(__file__).parent
random.seed(11)
rows = [l.split(" ", 1) for l in (HERE / "cache/wayback_property.txt").read_text().split("\n") if " " in l]
latest = {}
for ts, url in rows:
    key = re.sub(r"^https?://(www\.)?", "", url.strip()).split("?")[0]
    if key not in latest or ts > latest[key][0]: latest[key] = (ts, url.strip())
items = list(latest.values())
props = [i for i in items if "/property/" in i[1] and re.search(r"/(sale|rent)/", i[1])]
other = [i for i in items if i not in props]
recent = [i for i in props if i[0] >= "2026"]
older = [i for i in props if i[0] < "2026"]
todo = other + recent + random.sample(older, min(450, len(older)))
out = HERE / "wasalt_archive.jsonl"
done = {json.loads(l)["src"] for l in out.open()} if out.exists() else set()
todo = [t for t in todo if t[1] not in done]
print("todo", len(todo), flush=True)

def strip(s): return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()

def parse(ts, url, page):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m: return None
    pp = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
    p = pp.get("propertyDetailsV3")
    base = {"src": url, "snapshot": ts[:8]}
    if p and p.get("propertyInfo"):
        i = p["propertyInfo"]; attrs = {a["key"]: a.get("value") for a in p.get("attributes", [])}
        extra = {a["label"]: a.get("value") for a in p.get("additionalAttributes", [])}
        val = p.get("priceValuation") or {}
        return {**base, "kind": "listing", "id": p.get("id"), "title": i.get("title"), "purpose": i.get("propertyFor"),
                "type": i.get("propertySubType"), "usage": i.get("propertyMainType"), "city": i.get("city"), "district": i.get("district"),
                "price_sar": i.get("salePrice") or i.get("expectedRent") or None, "rent_frequency": i.get("rentFreq") or None,
                "bedrooms": attrs.get("noOfBedrooms"), "bathrooms": attrs.get("noOfBathrooms"), "living_rooms": attrs.get("noOfLivingrooms"),
                "area_sqm": attrs.get("builtUpArea") or attrs.get("landArea") or attrs.get("plotArea"), "furnishing": i.get("furnishingType"),
                "possession": i.get("possessionType"), "street_width_m": (p.get("streetInfo") or {}).get("streetWidth"),
                "valuation_low": round(val.get("lower_bound", {}).get("amount") or 0) or None, "valuation_high": round(val.get("upper_bound", {}).get("amount") or 0) or None,
                "extra": extra, "published": (p.get("publishedAt") or "")[:10], "description": strip(i.get("description"))[:1500],
                "lat": (p.get("location") or {}).get("lat"), "lon": (p.get("location") or {}).get("lon"),
                "url": url.replace("http://", "https://")}
    # project / static pages: keep readable text only
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.S)
    title = strip((re.search(r"<title>(.*?)</title>", page, re.S) or [None, ""])[1])
    return {**base, "kind": "page", "title": title, "url": url.replace("http://", "https://"), "text": strip(body)[:8000]}

def get(t):
    ts, url = t
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"https://web.archive.org/web/{ts}id_/{url}", headers={"User-Agent": "research-fetch/1.0"})
            page = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
            time.sleep(1.0)
            return parse(ts, url, page)
        except Exception as e:
            time.sleep(5 * (attempt + 1))
    return None

ok = 0
with out.open("a") as fh, ThreadPoolExecutor(3) as ex:
    for n, r in enumerate(ex.map(get, todo), 1):
        if r: fh.write(json.dumps(r, ensure_ascii=False) + "\n"); fh.flush(); ok += 1
        if n % 50 == 0: print(n, "fetched,", ok, "kept", flush=True)
print("final", ok, flush=True)
