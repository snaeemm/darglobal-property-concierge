"""Clean the raw scrapes and write the files the backend loads.

Inputs (scraper/):
  darglobal_raw.json      pages crawled from darglobal.co.uk
  wasalt_archive.jsonl    archived Wasalt listings + project/company pages
Outputs (backend/data/):
  knowledge.json          text chunks for keyword search (Dar Global + Wasalt pages)
  listings.json           detailed Wasalt listings (price, rooms, area, location...)
  wasalt_listings.json    lightweight index of every listing in Wasalt's sitemaps (written by parse_wasalt_sitemaps.py)
  stats.json              counts shown in the UI
"""
import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE.parent / "backend" / "data"
OUT.mkdir(parents=True, exist_ok=True)

SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT.split(text) if len(s.strip()) > 2]


def chunk(sents: list[str], size: int = 900, overlap: int = 1) -> list[str]:
    chunks, cur = [], []
    for s in sents:
        cur.append(s)
        if sum(len(x) for x in cur) >= size:
            chunks.append(" ".join(cur))
            cur = cur[-overlap:]
    if cur and (not chunks or len(" ".join(cur)) > 120):
        chunks.append(" ".join(cur))
    return chunks


def section_of(url: str) -> str:
    path = url.split("darglobal.co.uk", 1)[-1].strip("/")
    if not path:
        return "Home"
    head = path.split("/")[0]
    return {"press": "Press release", "partners": "Brand partner", "projects": "Projects", "one-of-one": "One of One collection",
            "investor": "Investor relations", "about": "About", "why-invest": "Why invest", "blog": "Blog", "insights": "Insights",
            "faq": "FAQ"}.get(head, "Project")


def build_darglobal() -> list[dict]:
    pages = json.load(open(HERE / "darglobal_raw.json"))
    seen, uniq = set(), []
    for p in pages:
        u = p["url"].rstrip("/") or p["url"]
        if u in seen or len(p["text"]) < 200:
            continue
        seen.add(u)
        uniq.append(p)
    # sentences repeated on many pages are navigation / footer boilerplate
    freq = Counter(s for p in uniq for s in set(sentences(p["text"])))
    limit = max(4, len(uniq) * 0.08)
    docs = []
    for p in uniq:
        body = [s for s in sentences(p["text"]) if freq[s] <= limit]
        if sum(len(s) for s in body) < 150:
            continue
        title = re.sub(r"\s*\|\s*Dar ?Global.*$", "", p["title"] or "", flags=re.I).strip() or section_of(p["url"])
        for i, c in enumerate(chunk(body)):
            docs.append({"id": f"dg-{len(docs)}", "source": "darglobal", "section": section_of(p["url"]), "title": title,
                         "url": p["url"], "text": c})
    return docs


def build_wasalt():
    pages, listings = [], []
    path = HERE / "wasalt_archive.jsonl"
    if not path.exists():
        return pages, listings
    best = {}
    for line in path.open():
        r = json.loads(line)
        key = r.get("id") or r["url"]
        if key not in best or r["snapshot"] > best[key]["snapshot"]:
            best[key] = r
    for r in best.values():
        if r["kind"] == "listing":
            if not r.get("price_sar") or not r.get("city"):
                continue
            try:
                r["price_sar"] = float(r["price_sar"])
                r["area_sqm"] = float(r["area_sqm"]) if r.get("area_sqm") not in (None, "") else None
            except (TypeError, ValueError):
                continue
            listings.append(r)
        elif len(r.get("text", "")) > 300:
            title = re.sub(r"\s*[|-]\s*(wasalt|Wasalt).*$", "", r["title"]).strip()
            for c in chunk(sentences(r["text"]))[:6]:
                pages.append({"id": f"ws-{len(pages)}", "source": "wasalt", "section": "Wasalt project" if "/project/" in r["url"] else "Wasalt",
                              "title": title, "url": r["url"], "text": c})
    return pages, listings


def main():
    dg = build_darglobal()
    ws_pages, listings = build_wasalt()
    knowledge = dg + ws_pages
    for l in listings:  # listing descriptions are also searchable as text
        knowledge.append({"id": f"wl-{l['id']}", "source": "wasalt", "section": "Wasalt listing", "title": f"{l['title']} - {l['district']}, {l['city']}",
                          "url": l["url"], "text": l["description"], "listing_id": l["id"]})
    json.dump(knowledge, open(OUT / "knowledge.json", "w"), ensure_ascii=False)
    json.dump(listings, open(OUT / "listings.json", "w"), ensure_ascii=False)
    sitemap = json.load(open(OUT / "wasalt_listings.json")) if (OUT / "wasalt_listings.json").exists() else []
    stats = {
        "darglobal_pages": len({d["url"] for d in dg}),
        "darglobal_chunks": len(dg),
        "wasalt_pages": len({d["url"] for d in ws_pages}),
        "wasalt_detailed_listings": len(listings),
        "wasalt_index_listings": len(sitemap),
        "cities": sorted(Counter(l["city"] for l in listings).keys()),
    }
    json.dump(stats, open(OUT / "stats.json", "w"), indent=1)
    print(json.dumps(stats, indent=1)[:600])


if __name__ == "__main__":
    main()
