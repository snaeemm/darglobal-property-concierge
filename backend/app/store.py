"""Loads the scraped data and answers the agent's tool calls."""
import json
import re
import statistics
from collections import Counter

from rank_bm25 import BM25Okapi

from .config import DATA_DIR

TOKEN = re.compile(r"[a-z0-9؀-ۿ]+")
STOP = set("the a an and or of to in for on with is are was what which who how do does i me my you your it its at by from be this that as can about any".split())


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


AR = {  # Arabic names the model may pass as filter values -> the English names stored in the data
    "الرياض": "riyadh", "جدة": "jeddah", "جده": "jeddah", "الدمام": "dammam", "الخبر": "khobar", "مكة": "makkah", "مكه": "makkah",
    "المدينة": "madinah", "المدينة المنورة": "madinah", "الطائف": "taif", "أبها": "abha", "ابها": "abha", "جازان": "jazan",
    "الأحساء": "ahsa", "الاحساء": "ahsa", "الخرج": "kharj", "خميس مشيط": "khamis", "بريدة": "buraidah", "تبوك": "tabuk",
    "شقة": "apartment", "شقق": "apartment", "فيلا": "villa", "فلل": "villa", "أرض": "land", "ارض": "land", "أراضي": "land",
    "دور": "floor", "عمارة": "building", "استراحة": "rest house", "بيع": "sale", "للبيع": "sale", "إيجار": "rent", "ايجار": "rent", "للإيجار": "rent",
}


def _norm(s) -> str:
    s = str(s or "").strip()
    for ar, en in sorted(AR.items(), key=lambda kv: -len(kv[0])):
        s = s.replace(ar, en)
    return re.sub(r"[^a-z]", "", s.lower().replace("al-", "al"))


def _match(want, have) -> bool:
    w = _norm(want)
    return not w or w in _norm(have) or (w.startswith("al") and w[2:] in _norm(have))


def _tidy(text: str) -> str:
    """Page text was flattened without separators; restore readable breaks for the preview."""
    text = re.sub(r"English\s*\|\s*العربية", "", text)
    text = re.sub(r"([a-z0-9.?!:%”’)])([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([?!.])([A-Z])", r"\1 \2", text)
    return text.strip()


class Store:
    def __init__(self):
        self.docs = json.load(open(DATA_DIR / "knowledge.json"))
        self.bm25 = BM25Okapi([tokens(f"{d['title']} {d['title']} {d['section']} {d['text']}") for d in self.docs])
        self.listings = json.load(open(DATA_DIR / "listings.json"))
        self.index = json.load(open(DATA_DIR / "wasalt_listings.json"))
        self.stats = json.load(open(DATA_DIR / "stats.json"))

    # ---- tool: search_knowledge -------------------------------------------------
    def search_knowledge(self, query: str, source: str = "any", k: int = 5) -> list[dict]:
        scores = self.bm25.get_scores(tokens(query))
        ranked = sorted(range(len(self.docs)), key=lambda i: -scores[i])
        out, per_url = [], Counter()
        for i in ranked:
            d = self.docs[i]
            if scores[i] <= 0 or len(out) >= k:
                break
            if source != "any" and d["source"] != source:
                continue
            if per_url[d["url"]] >= 2:  # keep results diverse
                continue
            per_url[d["url"]] += 1
            out.append({"title": d["title"], "section": d["section"], "source": d["source"], "url": d["url"], "text": d["text"][:750]})
        return out

    # ---- tool: search_listings ----------------------------------------------------
    def search_listings(self, purpose=None, city=None, district=None, property_type=None, min_price=None, max_price=None,
                        min_bedrooms=None, max_bedrooms=None, min_area=None, furnished=None, sort="relevance", limit=6) -> dict:
        res = self.listings
        if purpose:
            res = [l for l in res if l["purpose"] == (_norm(purpose) or purpose.lower())]
        if city:
            res = [l for l in res if _norm(city) and _match(city, l["city"])]
        if district:
            res = [l for l in res if _norm(district) and _match(district, l["district"])]
        if property_type:
            t = _norm(property_type).rstrip("s")
            res = [l for l in res if t in _norm(l["type"])]
        if min_price:
            res = [l for l in res if l["price_sar"] >= float(min_price)]
        if max_price:
            res = [l for l in res if l["price_sar"] <= float(max_price)]
        if min_bedrooms:
            res = [l for l in res if (l.get("bedrooms") or 0) >= int(min_bedrooms)]
        if max_bedrooms:
            res = [l for l in res if l.get("bedrooms") is not None and l["bedrooms"] <= int(max_bedrooms)]
        if min_area:
            res = [l for l in res if (l.get("area_sqm") or 0) >= float(min_area)]
        if furnished is not None:
            res = [l for l in res if ("un" not in (l.get("furnishing") or "un").lower()) == bool(furnished)]
        if sort == "price_low":
            res = sorted(res, key=lambda l: l["price_sar"])
        elif sort == "price_high":
            res = sorted(res, key=lambda l: -l["price_sar"])
        elif sort == "largest":
            res = sorted(res, key=lambda l: -(l.get("area_sqm") or 0))
        else:
            res = sorted(res, key=lambda l: l.get("published") or "", reverse=True)
        prices = [l["price_sar"] for l in res]
        summary = {"matches": len(res), "shown": min(len(res), max(1, min(int(limit or 6), 10)))}
        if prices:
            summary.update(min_price=min(prices), median_price=statistics.median(prices), max_price=max(prices))
        return {"summary": summary, "listings": [self.card(l) for l in res[: max(1, min(int(limit or 6), 10))]]}

    @staticmethod
    def card(l: dict) -> dict:
        keep = ["id", "title", "purpose", "type", "city", "district", "price_sar", "rent_frequency", "bedrooms", "bathrooms", "area_sqm",
                "furnishing", "valuation_low", "valuation_high", "published", "url"]
        c = {k: l.get(k) for k in keep if l.get(k) not in (None, "")}
        c["highlights"] = l.get("description", "")[:160]
        return c

    # ---- page preview for the UI -------------------------------------------------
    def page(self, url: str) -> dict | None:
        key = url.split("#")[0].rstrip("/").replace("http://", "https://")
        for l in self.listings:
            if l["url"].rstrip("/") == key or str(l["id"]) == key.rsplit("-", 1)[-1]:
                c = self.card(l)
                c.update(kind="listing", description=l.get("description", ""), extra=l.get("extra", {}), lat=l.get("lat"), lon=l.get("lon"))
                return c
        parts = [d for d in self.docs if d["url"].rstrip("/") == key and "listing_id" not in d]
        if not parts:
            return None
        return {"kind": "page", "url": parts[0]["url"], "title": parts[0]["title"], "section": parts[0]["section"],
                "source": parts[0]["source"], "text": _tidy("\n\n".join(p["text"] for p in parts))[:6000]}

    # ---- tool: market_overview ----------------------------------------------------
    def market_overview(self, purpose=None, property_type=None, city=None) -> dict:
        idx = self.index
        if purpose:
            idx = [l for l in idx if l["purpose"] == purpose.lower()]
        if property_type:
            t = _norm(property_type).rstrip("s")
            idx = [l for l in idx if t in _norm(l["type"])]
        by_type = Counter(f"{l['type']} for {l['purpose']}" for l in idx).most_common(10)
        beds = Counter(l["bedrooms"] for l in idx if l.get("bedrooms")).most_common(6)
        sizes = sorted(l["size_sqm"] for l in idx if l.get("size_sqm"))
        out = {
            "note": "Counts come from Wasalt's public listing index (whole of Saudi Arabia, no city or price data). "
                    "Prices come from the detailed listing sample.",
            "listings_in_index": len(idx),
            "top_types": by_type,
            "bedroom_mix": beds,
            "median_size_sqm": sizes[len(sizes) // 2] if sizes else None,
        }
        detailed = self.search_listings(purpose=purpose, property_type=property_type, city=city, limit=1)["summary"]
        out["price_sample"] = {"priced_listings_in_sample": detailed.pop("matches"), **detailed}
        if not city:
            out["detailed_sample_by_city"] = Counter(l["city"] for l in self.listings).most_common(10)
        return out


store: Store | None = None


def get_store() -> Store:
    global store
    if store is None:
        store = Store()
    return store
