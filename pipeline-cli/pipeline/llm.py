import os
import json

try:
    import anthropic
except ImportError:
    anthropic = None

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

_QUALITY_PROMPT = (
    "You are a requirements quality evaluator. Given the following EARS requirements:\n\n"
    "{texts}\n\n"
    "Score each of the following dimensions from 0 to 10 (10 = excellent, 0 = absent/critical):\n"
    "{dimensions}\n\n"
    "Return a JSON object with a single key 'dimensions' containing a list of objects, "
    "each with 'dimension', 'score' (integer 0-10), and 'justification' (one sentence)."
)


def evaluateQuality(texts, dimensions):
    apiKey = os.environ.get("ANTHROPIC_API_KEY")
    try:
        client = anthropic.Anthropic(api_key=apiKey)
        prompt = _QUALITY_PROMPT.format(
            texts="\n".join(texts),
            dimensions="\n".join("- {d}".format(d=d) for d in dimensions),
        )
        message = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text
        data = json.loads(raw)
        return data["dimensions"]
    except Exception:
        return []

_EXPAND_PROMPT = (
    "Translate the following search query to English technical terms suitable for "
    "searching source code. Return only the expanded query, no explanation.\n\nQuery: {query}"
)


def expandQuery(query):
    apiKey = os.environ.get("ANTHROPIC_API_KEY")
    if not apiKey:
        return query
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=apiKey)
        message = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=64,
            messages=[{"role": "user", "content": _EXPAND_PROMPT.format(query=query)}],
        )
        return message.content[0].text.strip()
    except Exception:
        return query
