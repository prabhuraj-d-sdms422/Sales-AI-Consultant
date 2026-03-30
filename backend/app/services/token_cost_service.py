from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.config.settings import settings

Provider = Literal["anthropic", "openai", "gemini"]


@dataclass(frozen=True)
class ModelPricing:
    input_usd_per_1k_tokens: float
    output_usd_per_1k_tokens: float


PRICING_USD_PER_1K: dict[Provider, dict[str, ModelPricing]] = {
    "anthropic": {
        # https://www.anthropic.com/pricing (verify if you change models)
        "claude-3-5-sonnet-20241022": ModelPricing(0.003, 0.015),
    },
    "openai": {
        # https://openai.com/pricing (verify if you change models)
        "gpt-4o": ModelPricing(0.0025, 0.010),
    },
    "gemini": {
        # https://ai.google.dev/gemini-api/docs/pricing (verify if you change models)
        # gemini-2.5-flash (Standard): $0.30 / 1M input, $2.50 / 1M output
        # => per 1K tokens: $0.0003 input, $0.0025 output
        "gemini-2.5-flash": ModelPricing(0.0003, 0.0025),
        # Legacy / fallback
        "gemini-1.5-pro": ModelPricing(0.00125, 0.005),
    },
}


def get_active_provider_and_model() -> tuple[Provider, str]:
    provider: Provider = settings.llm_provider
    if provider == "anthropic":
        return provider, settings.anthropic_model
    if provider == "openai":
        return provider, settings.openai_model
    return provider, settings.gemini_model


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip():
            return int(float(value.strip()))
    except Exception:
        return None
    return None


def extract_token_usage_from_message(msg: Any) -> dict[str, int]:
    """
    Extract token usage from a LangChain AIMessage (or similar) in a provider-agnostic way.

    We prefer provider-reported usage metadata. This is the only "real" token count available.
    """

    usage: Any = getattr(msg, "usage_metadata", None)
    if not isinstance(usage, dict):
        # Some providers/models place usage under response_metadata.
        rm: Any = getattr(msg, "response_metadata", None)
        if isinstance(rm, dict):
            usage = rm.get("usage") or rm.get("token_usage") or rm.get("usage_metadata")

    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    # Common LangChain keys: input_tokens/output_tokens/total_tokens
    input_tokens = _to_int(usage.get("input_tokens")) or 0
    output_tokens = _to_int(usage.get("output_tokens")) or 0
    total_tokens = _to_int(usage.get("total_tokens"))

    # Provider-specific fallbacks
    if input_tokens == 0:
        input_tokens = _to_int(usage.get("prompt_tokens")) or 0
    if output_tokens == 0:
        output_tokens = _to_int(usage.get("completion_tokens")) or 0

    if total_tokens is None:
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": max(0, int(input_tokens)),
        "output_tokens": max(0, int(output_tokens)),
        "total_tokens": max(0, int(total_tokens)),
    }


def estimate_cost_usd_inr(
    *,
    provider: Provider,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, float]:
    pricing = PRICING_USD_PER_1K.get(provider, {}).get(model)
    if pricing is None:
        return {
            "estimated_cost_usd": 0.0,
            "estimated_cost_inr": 0.0,
            "usd_to_inr_rate": float(settings.usd_to_inr_rate),
        }

    usd = (input_tokens / 1000.0) * pricing.input_usd_per_1k_tokens + (
        output_tokens / 1000.0
    ) * pricing.output_usd_per_1k_tokens
    inr = usd * float(settings.usd_to_inr_rate)
    return {
        "estimated_cost_usd": float(usd),
        "estimated_cost_inr": float(inr),
        "usd_to_inr_rate": float(settings.usd_to_inr_rate),
    }


def add_usage_totals(
    *,
    current: dict[str, Any] | None,
    add_input_tokens: int,
    add_output_tokens: int,
    provider: Provider,
    model: str,
) -> dict[str, Any]:
    base = dict(current or {})
    base["provider"] = provider
    base["model"] = model

    total_input = int(base.get("total_input_tokens") or 0) + int(add_input_tokens or 0)
    total_output = int(base.get("total_output_tokens") or 0) + int(add_output_tokens or 0)
    base["total_input_tokens"] = total_input
    base["total_output_tokens"] = total_output
    base["total_tokens"] = total_input + total_output

    base.update(
        estimate_cost_usd_inr(
            provider=provider,
            model=model,
            input_tokens=total_input,
            output_tokens=total_output,
        )
    )
    return base

