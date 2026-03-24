from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.config.settings import settings


def get_llm(streaming: bool = False, temperature: float | None = None) -> BaseChatModel:
    """Switch LLM providers by changing LLM_PROVIDER in .env — no code changes needed."""
    temp = temperature if temperature is not None else settings.llm_temperature
    if settings.llm_provider == "anthropic":
        return ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            temperature=temp,
            max_tokens=settings.llm_max_tokens,
            streaming=streaming,
        )
    if settings.llm_provider == "openai":
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=temp,
            max_tokens=settings.llm_max_tokens,
            streaming=streaming,
        )
    if settings.llm_provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=temp,
            max_output_tokens=settings.llm_max_tokens,
            streaming=streaming,
        )
    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


def get_classification_llm() -> BaseChatModel:
    """Lower temperature for intent classification — accuracy over creativity."""
    return get_llm(streaming=False, temperature=0.1)


def get_guardrail_llm() -> BaseChatModel:
    """Strictest temperature for guardrail validation."""
    return get_llm(streaming=False, temperature=0.0)
