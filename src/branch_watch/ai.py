"""AI release-risk analysis using an OpenAI-compatible chat API."""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict


class AIError(RuntimeError):
    pass


def analyze_release_risk(health: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.environ.get("AI_API_KEY")
    if not api_key:
        raise AIError("AI is not configured. Set AI_API_KEY before using Analyze with AI.")

    base_url = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("AI_MODEL", "gpt-4o-mini")
    prompt = {
        "repository": health["repo"],
        "production_branch": health["production"],
        "release_branch": health["release"],
        "behind_commits": health["behind"],
        "ahead_commits": health["ahead"],
        "commits": health.get("commits", [])[:20],
        "changed_files": health.get("changed_files", [])[:50],
    }
    request_body = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a senior release-risk analyst. Analyze branch drift and return JSON only "
                    "with exactly these keys: risk, summary, impact, recommendation, tests. "
                    "risk must be low, medium, or high; tests must be an array of short strings. "
                    "Do not invent details that are not present in the input."
                ),
            },
            {"role": "user", "content": json.dumps(prompt)},
        ],
    }
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(request_body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "branch-watch",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise AIError("AI provider returned {}: {}".format(error.code, detail)) from error
    except urllib.error.URLError as error:
        raise AIError("Could not reach AI provider: {}".format(error.reason)) from error

    try:
        content = payload["choices"][0]["message"]["content"]
        result = json.loads(content)
        required = {"risk", "summary", "impact", "recommendation", "tests"}
        if not required.issubset(result) or result["risk"] not in {"low", "medium", "high"}:
            raise ValueError("AI response did not match the expected schema")
        return result
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AIError("AI provider returned an invalid analysis response") from error
