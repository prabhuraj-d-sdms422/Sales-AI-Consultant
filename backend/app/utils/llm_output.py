"""Normalize LLM outputs across providers (OpenAI/Anthropic/Gemini)."""

from __future__ import annotations

from typing import Any


def extract_text(content: Any) -> str:
    """
    LangChain message content is usually a string, but some providers/tooling can return
    structured payloads (e.g. Gemini returning {"type":"text","text":...}).
    This helper ensures we always get plain user-facing text.
    """
    if content is None:
        return ""

    # Common case: already a string.
    if isinstance(content, str):
        return content

    # Gemini/structured: {"type":"text","text":"..."} or {"text":"..."}
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        # Sometimes nested under "content"
        inner = content.get("content")
        if isinstance(inner, str):
            return inner
        return str(content)

    # Multi-part: ["...", {"type":"text","text":"..."}]
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if item is None:
                continue
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, str):
                    parts.append(t)
                    continue
                # Some toolchains nest as {"type":"text","text":...}
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(str(item["text"]))
                    continue
            # fallback: stringify unknown parts
            parts.append(str(item))
        return "".join(parts)

    # Fallback for unexpected objects.
    return str(content)

