"""A small tool-using agent: the model decides which data to look up, we run the lookup, it answers with sources."""
import json
import logging
from collections.abc import AsyncIterator
from datetime import date

import httpx

import asyncio
import re
import time

from .config import MAX_TOOL_ROUNDS, PROVIDERS
from .store import get_store

log = logging.getLogger("agent")

SYSTEM = f"""You are the DarGlobal Property Concierge, an assistant for people exploring luxury real estate.
Today is {date.today():%d %B %Y}.

You know two things, and only through your tools:
1. DarGlobal (darglobal.co.uk): the London-listed luxury developer. Its projects (AIDA in Oman, Trump Tower Jeddah, Trump International Hotel & Tower Dubai, DaVinci Tower by Pagani, Les Vagues, Marea, Tierra Viva, Urban Oasis by Missoni, W Residences and more), brand partners, press releases, investor information and contact details.
2. Wasalt (wasalt.sa): the Saudi property portal. Individual listings with prices, rooms, size and district, plus market-wide counts.

Rules:
- Always call a tool before answering a factual question. One well-chosen call is usually enough; never run more than two searches for one question. Use search_knowledge for DarGlobal and general questions, search_listings to find specific Wasalt properties, market_overview for "how many / typical / market" questions about Wasalt. Call several tools if the question spans both.
- Answer only from tool results. Never add features, views, furnishing, amenities, locations or prices that are not written in the results. If a field is missing, leave it out rather than guess.
- Report counts exactly as the tool gives them ("matches": N). Don't say "only" or "all" unless the numbers show it.
- Market prices come from a small sample: always say how many priced listings a price figure is based on, and if it's fewer than 5, say the sample is too small to call it a market price.
- For Wasalt listings, direct enquiries to the listing on Wasalt, not to DarGlobal. Only give DarGlobal's contact details for DarGlobal projects. If the data does not cover something, say so plainly and suggest who to contact (DarGlobal: +971 4562 9616 or darglobal.co.uk/get-in-touch). Never invent prices, dates or project facts.
- Prices are in SAR unless the source says otherwise. Format money like "SAR 1,250,000".
- Be concise and warm, like a senior property advisor. Use short paragraphs or bullets. Use markdown links [title](url) to cite the pages you used.
- When you show Wasalt listings, mention 2-4 standout options in a sentence each; the interface shows the full cards.
- Reply in the user's language (English or Arabic). In Arabic, DarGlobal is "دار جلوبال" and Wasalt is "وصلت".
- Tool arguments (city, district, property type) must always be in English, e.g. city "Riyadh" even when the user writes "الرياض".
"""

TOOLS = [
    {"type": "function", "function": {
        "name": "search_knowledge",
        "description": "Keyword search over pages scraped from darglobal.co.uk and wasalt.sa (projects, partners, press, investor info, FAQs, Wasalt projects and listing descriptions).",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Search keywords, e.g. 'AIDA Oman golf' or 'Trump Tower Jeddah handover'"},
            "source": {"type": "string", "enum": ["any", "darglobal", "wasalt"], "description": "Restrict to one site"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "search_listings",
        "description": "Filter real Wasalt property listings (Saudi Arabia). Returns matching listings with price, rooms, area and link, plus a price summary.",
        "parameters": {"type": "object", "properties": {
            "purpose": {"type": "string", "enum": ["sale", "rent"]},
            "city": {"type": "string", "description": "In English, e.g. Riyadh, Jeddah, Dammam, Madinah, Makkah"},
            "district": {"type": "string"},
            "property_type": {"type": "string", "description": "apartment, villa, land, floor, building, duplex, townhouse, office, shop..."},
            "min_price": {"type": "number"}, "max_price": {"type": "number"},
            "min_bedrooms": {"type": "integer"}, "max_bedrooms": {"type": "integer"},
            "min_area": {"type": "number", "description": "square metres"},
            "furnished": {"type": "boolean"},
            "sort": {"type": "string", "enum": ["relevance", "price_low", "price_high", "largest"]},
            "limit": {"type": "integer", "description": "1-10, default 6"}}}}},
    {"type": "function", "function": {
        "name": "market_overview",
        "description": "Market-level numbers for Wasalt: listing counts by type, bedroom mix, typical sizes, and price ranges from the detailed sample.",
        "parameters": {"type": "object", "properties": {
            "purpose": {"type": "string", "enum": ["sale", "rent"]},
            "property_type": {"type": "string"},
            "city": {"type": "string"}}}}},
]

STATUS = {"search_knowledge": "Searching DarGlobal & Wasalt pages", "search_listings": "Filtering Wasalt listings",
          "market_overview": "Crunching market numbers"}


def run_tool(name: str, args: dict):
    s = get_store()
    try:
        if name == "search_knowledge":
            return s.search_knowledge(args.get("query", ""), args.get("source") or "any")
        if name == "search_listings":
            allowed = {"purpose", "city", "district", "property_type", "min_price", "max_price", "min_bedrooms", "max_bedrooms", "min_area", "furnished", "sort", "limit"}
            return s.search_listings(**{k: v for k, v in args.items() if k in allowed and v not in (None, "")})
        if name == "market_overview":
            return s.market_overview(**{k: v for k, v in args.items() if k in {"purpose", "property_type", "city"} and v})
    except Exception as e:  # bad arguments from the model should not kill the chat
        log.warning("tool %s failed: %s", name, e)
        return {"error": str(e)}
    return {"error": f"unknown tool {name}"}


async def _stream_completion(client: httpx.AsyncClient, prov: tuple, messages: list, use_tools: bool, force_tool: bool = False):
    label, base, key, model = prov
    if label == "gemini":  # tool calls made by another provider carry no signature; Gemini accepts this placeholder
        messages = [{**m, "tool_calls": [tc if tc.get("extra_content") else {**tc, "extra_content": {"google": {"thought_signature": "skip_thought_signature_validator"}}}
                                         for tc in m["tool_calls"]]} if m.get("tool_calls") else m for m in messages]
    elif any(m.get("tool_calls") for m in messages):  # other providers don't know Gemini's extra field
        messages = [{**m, "tool_calls": [{k: v for k, v in tc.items() if k != "extra_content"} for tc in m["tool_calls"]]} if m.get("tool_calls") else m for m in messages]
    body = {"model": model, "messages": messages, "stream": True, "temperature": 0.3, "max_tokens": 1200}
    if use_tools:
        body["tools"] = TOOLS
        if force_tool:  # the first step must be a lookup, never an answer from memory
            body["tool_choice"] = "required"
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "darglobal-concierge/1.0", "HTTP-Referer": "https://darglobal-concierge.onrender.com",
               "X-Title": "DarGlobal Property Concierge"}
    async with client.stream("POST", f"{base}/chat/completions", json=body, headers=headers) as r:
        if r.status_code != 200:
            raise RuntimeError(f"{model}: HTTP {r.status_code} {(await r.aread())[:200]!r}")
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            if chunk.get("error"):
                raise RuntimeError(f"{model}: {chunk['error']}")
            if chunk.get("choices"):
                yield chunk["choices"][0].get("delta") or {}


_cooldown: dict[str, float] = {}  # provider/model -> time it may be tried again
last_error: dict[str, str] = {}  # provider/model -> last failure, shown on /api/health (no secrets)


def available(prefer: str | None = None) -> list[tuple]:
    now = time.time()
    chain = [p for p in PROVIDERS if _cooldown.get(p[0] + p[3], 0) <= now]
    if prefer:
        chain = [p for p in chain if p[0] == prefer] + [p for p in chain if p[0] != prefer]
    return chain


def cool(provider: tuple, err: str):
    """Skip a failing provider: as long as it asked (per-minute limit), longer for daily quota or hard errors."""
    last_error[f"{provider[0]}:{provider[3]}"] = f"{time.strftime('%H:%M:%S')} {err[:160]}"
    if "429" not in err and "rate" not in err.lower():
        # bad key, unknown model, provider outage: don't hammer it on every request
        if any(code in err for code in ("401", "403", "404")):
            _cooldown[provider[0] + provider[3]] = time.time() + 600
        else:
            _cooldown[provider[0] + provider[3]] = time.time() + 20
        return
    if "per-day" in err or "per day" in err or "(RPD)" in err:
        wait = 900
    else:
        m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", err)
        wait = (int(m.group(1) or 0) * 60 + float(m.group(2)) + 1) if m else 20
    _cooldown[provider[0] + provider[3]] = time.time() + wait


async def wait_for_capacity(max_wait: float = 30) -> list[tuple]:
    """If every model is briefly rate-limited, wait for the first one to free up rather than failing."""
    chain = available()
    if chain or not PROVIDERS:
        return chain
    soonest = min(_cooldown.get(p[0] + p[3], 0) for p in PROVIDERS) - time.time()
    if soonest <= max_wait:
        await asyncio.sleep(max(0, soonest))
        return available()
    return []


async def follow_ups(client: httpx.AsyncClient, question: str, answer: str) -> list[str]:
    """Ask a fast model for three short next questions the user might tap."""
    lang = "Arabic" if re.search(r"[\u0600-\u06ff]", question) else "English"
    prompt = ("A user asked a property assistant (DarGlobal developments + Wasalt Saudi listings):\n"
              f"Q: {question[:500]}\nA: {answer[:1800]}\n\n"
              "Suggest 3 natural follow-up questions the user could ask next. Each must build on specific things named in the answer "
              "(a project, district, listing, price, partner or figure it mentioned), under 9 words, "
              f"answerable from DarGlobal or Wasalt data, written in {lang}. "
              "Return only a JSON array of 3 strings.")
    chain = available(prefer="gemini")
    for prov in chain[:3]:
        label, base, key, model = prov
        try:
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.5, "max_tokens": 700}
            if label == "openrouter":
                body["reasoning"] = {"enabled": False}
            elif label == "gemini":
                body["reasoning_effort"] = "none"
            else:
                body["reasoning_effort"] = "low" if "gpt-oss" in model else None
                body = {k: v for k, v in body.items() if v is not None}
            r = await client.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}", "User-Agent": "darglobal-concierge/1.0"},
                                  json=body, timeout=20)
            if r.status_code != 200:
                cool(prov, f"{r.status_code} {r.text[:200]}")
                continue
            msg = r.json()["choices"][0]["message"]
            text = msg.get("content") or msg.get("reasoning") or ""
            items = json.loads(text[text.index("["): text.rindex("]") + 1])
            return [str(x).strip() for x in items if str(x).strip()][:3]
        except Exception as e:
            log.info("follow-ups failed on %s: %s", model, e)
    return []


async def chat(history: list[dict]) -> AsyncIterator[dict]:
    """Yields UI events: status, token, listings, sources, done, error."""
    messages = [{"role": "system", "content": SYSTEM}] + history[-12:]
    sources, seen, answer = [], set(), ""
    models = await wait_for_capacity()
    used = None
    deadline = time.time() + 60  # never keep a user waiting longer than this
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=15)) as client:
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            use_tools = round_no < MAX_TOOL_ROUNDS
            text, calls, sent_any, remap = "", {}, False, {}
            while True:
                if not models and time.time() < deadline:
                    yield {"type": "status", "text": "High demand on the free models, retrying", "tool": "retry", "args": {}}
                    models = await wait_for_capacity(max_wait=min(30, max(0, deadline - time.time())))
                if not models:
                    yield {"type": "error", "text": "All free models are busy right now. Please try again in a few seconds."}
                    return
                model = models[0]
                try:
                    async for delta in _stream_completion(client, model, messages, use_tools, force_tool=(round_no == 0)):
                        if delta.get("content"):
                            text += delta["content"]
                            sent_any = True
                            yield {"type": "token", "text": delta["content"]}
                        for tc in delta.get("tool_calls") or []:
                            pidx = tc.get("index", 0)
                            idx = remap.get(pidx, pidx)
                            # some providers send parallel calls all with index 0; a new id means a new call
                            if tc.get("id") and idx in calls and calls[idx]["id"] and calls[idx]["id"] != tc["id"]:
                                idx = max(calls) + 1
                                remap[pidx] = idx
                            c = calls.setdefault(idx, {"id": "", "name": "", "args": "", "extra": None})
                            c["id"] = tc.get("id") or c["id"]
                            c["extra"] = tc.get("extra_content") or c["extra"]  # Gemini thought signature, must be echoed back
                            fn = tc.get("function") or {}
                            c["name"] += fn.get("name") or ""
                            c["args"] += fn.get("arguments") or ""
                    used = model
                    break
                except Exception as e:
                    log.warning("model failed: %s", e)
                    cool(model, str(e))
                    if sent_any:  # already streaming text; can't switch mid-answer
                        break
                    models.remove(model)
                    text, calls, remap = "", {}, {}

            if not calls:
                answer = text
                break
            messages.append({"role": "assistant", "content": text or None, "tool_calls": [
                {"id": c["id"] or f"call_{i}", "type": "function", "function": {"name": c["name"], "arguments": c["args"] or "{}"},
                 **({"extra_content": c["extra"]} if c["extra"] else {})}
                for i, c in calls.items()]})
            for i, c in calls.items():
                try:
                    args = json.loads(c["args"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield {"type": "status", "text": STATUS.get(c["name"], "Looking that up"), "tool": c["name"], "args": args}
                result = run_tool(c["name"], args)
                if c["name"] == "search_listings" and result.get("listings"):
                    yield {"type": "listings", "items": result["listings"], "summary": result["summary"]}
                if c["name"] == "search_knowledge":
                    for r in result:
                        if r["url"] not in seen:
                            seen.add(r["url"])
                            sources.append({"title": r["title"], "url": r["url"], "source": r["source"]})
                messages.append({"role": "tool", "tool_call_id": c["id"] or f"call_{i}", "content": json.dumps(result, ensure_ascii=False, separators=(",", ":"))[:6000]})
        if sources:
            yield {"type": "sources", "items": sources[:6]}
        if answer:
            q = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
            fu = await follow_ups(client, q, answer)
            if fu:
                yield {"type": "followups", "items": fu}
    yield {"type": "done", "model": f"{used[0]}:{used[3]}" if used else None}
