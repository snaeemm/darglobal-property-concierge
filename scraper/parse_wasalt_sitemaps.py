"""Turn Wasalt's public sitemaps into structured listing + market-coverage data."""
import json, re
from collections import Counter
from pathlib import Path
C = Path(__file__).parent / "cache"
def entries(f):
    x = (C / f).read_text()
    return re.findall(r"<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?", x)

listings = []
for f in ["product_sitemap_en_sa.xml", "rental_pdp_sitemap_en_sa.xml"]:
    for url, mod in entries(f):
        m = re.search(r"/property/(sale|rent)/(.+)-(\d+)$", url)
        if not m: continue
        purpose, slug, pid = m.groups()
        typ = re.match(r"([a-z]+(?:-[a-z]+)*?)(?:-\d|-with|-facing|-for|$)", slug)
        rec = {"id": int(pid), "purpose": purpose, "type": (typ.group(1) if typ else slug.split("-")[0]).replace("-", " "),
               "size_sqm": None, "bedrooms": None, "facing": None, "street_width_m": None, "updated": mod, "url": url}
        if s := re.search(r"(\d+)-sqm", slug): rec["size_sqm"] = int(s.group(1)) / (100 if int(s.group(1)) > 5000 and rec["type"] == "apartment" else 1)
        if b := re.search(r"(\d+)-bedroom", slug): rec["bedrooms"] = int(b.group(1))
        if fc := re.search(r"facing-([a-z-]+?)-on", slug): rec["facing"] = fc.group(1).replace("-", " ")
        if w := re.search(r"on-(\d+)m-width", slug): rec["street_width_m"] = int(w.group(1))
        listings.append(rec)

markets = []
for f in ["category_sitemap_en_sa.xml", "rental_srp_sitemap_en_sa.xml"]:
    for url, _ in entries(f):
        m = re.search(r"/en/(?:(\d+)-bedroom-)?([a-z-]+?)-for-(sale|rent)-in-([a-z0-9-]+)$", url)
        if m:
            beds, typ, purpose, place = m.groups()
            markets.append({"type": typ.replace("-", " "), "purpose": purpose, "place": place.replace("-", " "), "bedrooms": int(beds) if beds else None, "url": url})

out = Path(__file__).parents[1] / "backend" / "data"; out.mkdir(parents=True, exist_ok=True)
json.dump(listings, open(out / "wasalt_listings.json", "w"))
json.dump(markets, open(out / "wasalt_markets.json", "w"))
print(len(listings), "listings;", len(markets), "market pages")
print(Counter((l["purpose"], l["type"]) for l in listings).most_common(15))
print(Counter(m["place"].split()[0] for m in markets).most_common(12))
