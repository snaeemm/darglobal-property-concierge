import os
import re


def _key(*names: str) -> str:
    """Read an API key, forgiving copy-paste accidents: spaces, newlines, quotes, or a pasted 'name=' prefix."""
    for n in names:
        v = os.getenv(n)
        if v:
            v = v.strip().strip("'\"").strip()
            v = re.sub(r"^[A-Za-z_]+\s*=\s*", "", v).strip().strip("'\"")
            return re.sub(r"\s+", "", v)
    return ""

from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
STATIC_DIR = Path(os.getenv("STATIC_DIR", Path(__file__).resolve().parents[2] / "frontend" / "dist"))

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_API_KEY = _key("OPENROUTER_API_KEY", "api_key")
# Free OpenRouter models, tried in order; the next one is used if one is rate-limited or down.
LLM_MODELS = [m.strip() for m in os.getenv(
    "LLM_MODELS",
    "nvidia/nemotron-3.5-super-vl:free,nvidia/nemotron-3.5-lightning:free,inclusionai/ling-3.2-flash:free,google/gemma-4-31b-it:free",
).split(",") if m.strip()]

GROQ_API_KEY = _key("GROQ_API_KEY", "groq_key")
GROQ_MODELS = [m.strip() for m in os.getenv("GROQ_MODELS", "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b").split(",") if m.strip()]

GEMINI_API_KEY = _key("GEMINI_API_KEY", "gemini_key")
# Keys are recognisable by prefix (Groq: gsk_, OpenRouter: sk-or-); put each with the right provider even if the
# environment variables were filled in the wrong boxes.
if GEMINI_API_KEY.startswith("gsk_") and not GROQ_API_KEY.startswith("gsk_"):
    GEMINI_API_KEY, GROQ_API_KEY = GROQ_API_KEY, GEMINI_API_KEY

GEMINI_MODELS = [m.strip() for m in os.getenv("GEMINI_MODELS", "gemini-3.5-flash-lite,gemini-flash-lite-latest").split(",") if m.strip()]

# Ordered chain of (label, base_url, key, model). OpenRouter free models first; Gemini's free tier, then Groq's,
# take over when OpenRouter's daily free quota or a model's capacity runs out.
PROVIDERS = [("openrouter", LLM_BASE_URL, LLM_API_KEY, m) for m in LLM_MODELS if LLM_API_KEY] + \
            [("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", GEMINI_API_KEY, m) for m in GEMINI_MODELS if GEMINI_API_KEY] + \
            [("groq", "https://api.groq.com/openai/v1", GROQ_API_KEY, m) for m in GROQ_MODELS if GROQ_API_KEY]

# Non-secret fingerprints so a misconfigured key can be spotted on /api/health without revealing it.
KEY_FINGERPRINTS = {name: (f"{k[:4]}… ({len(k)} chars)" if k else "missing")
                    for name, k in (("openrouter", LLM_API_KEY), ("gemini", GEMINI_API_KEY), ("groq", GROQ_API_KEY))}

MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "3"))
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "12"))
