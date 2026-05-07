#!/usr/bin/env python3
import os
import sys
import json

try:
    import anthropic
except ImportError:
    sys.exit(1)

_MODEL = "claude-haiku-4-5-20251001"

_PROMPT = (
    "You are a semantic search classifier for a software development assistant. "
    "Given the following user message, decide whether a semantic context search "
    "of the codebase is needed.\n\n"
    "Return ONLY valid JSON:\n"
    '{"search": true/false, "query": "3-8 word query if search=true, empty string if false"}\n\n'
    "Set search=true for: implementing features, fixing bugs, refactoring, resolving incidents. "
    "Extract: main domain entity + operation type + affected component for the query.\n"
    "Set search=false for: questions, admin operations, status checks, general conversation.\n\n"
    "User message: {message}"
)


def classify(message):
    apiKey = os.environ.get("ANTHROPIC_API_KEY")
    if not apiKey:
        sys.exit(1)
    client = anthropic.Anthropic(api_key=apiKey)
    response = client.messages.create(
        model=_MODEL,
        max_tokens=64,
        messages=[{"role": "user", "content": _PROMPT.format(message=message)}],
    )
    result = json.loads(response.content[0].text.strip())
    print(json.dumps(result))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    message = " ".join(sys.argv[1:])
    classify(message)
