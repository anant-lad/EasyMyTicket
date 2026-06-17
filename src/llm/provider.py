"""
LLM provider factory — Groq primary, OpenRouter fallback.

Observability is pluggable via OBSERVABILITY_PROVIDER env var:
  custom   (default) — stores traces in local PostgreSQL llm_traces table
  langfuse           — sends to cloud.langfuse.com (free: 50K obs/month)
  none               — no tracing

Usage:
    from src.llm.provider import get_llm, get_small_llm, get_callbacks

    callbacks = get_callbacks()
    result = get_llm(callbacks).invoke(...)
"""
import logging
from functools import lru_cache
from typing import List, Optional

from langchain_core.language_models import BaseChatModel

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Observability — pick provider at startup
# ─────────────────────────────────────────────────────────────────────────────

def get_callbacks() -> list:
    """
    Return the active list of LangChain callbacks for the configured provider.
    Call once per request/node invocation.
    """
    from src.config import Config

    provider = Config.OBSERVABILITY_PROVIDER.lower()

    if provider == "langfuse":
        return _langfuse_callbacks()
    elif provider == "custom":
        return _custom_callbacks()
    return []


def _langfuse_callbacks() -> list:
    """LangFuse cloud tracing (free tier: 50K obs/month)."""
    try:
        from src.config import Config
        if not (Config.LANGFUSE_PUBLIC_KEY and Config.LANGFUSE_SECRET_KEY):
            log.debug("LANGFUSE_PUBLIC_KEY/SECRET_KEY not set — LangFuse disabled")
            return []
        from langfuse.callback import CallbackHandler
        handler = CallbackHandler(
            public_key=Config.LANGFUSE_PUBLIC_KEY,
            secret_key=Config.LANGFUSE_SECRET_KEY,
            host=Config.LANGFUSE_HOST,
        )
        return [handler]
    except Exception as e:
        log.warning("LangFuse init failed (%s) — falling back to no tracing", e)
        return []


def _custom_callbacks() -> list:
    """Custom PostgreSQL tracer — no external service, unlimited, free."""
    try:
        from src.observability.tracer import get_tracer
        return [get_tracer()]
    except Exception as e:
        log.warning("Custom tracer init failed (%s) — no tracing", e)
        return []


# ─────────────────────────────────────────────────────────────────────────────
#  LLM chain builder (Groq → OpenRouter fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _build_chain(groq_model: str, openrouter_model: str) -> BaseChatModel:
    from src.config import Config
    from langchain_groq import ChatGroq
    from langchain_openai import ChatOpenAI

    groq_llm = ChatGroq(
        api_key=Config.GROQ_API_KEY,
        model=groq_model,
        temperature=Config.LLM_TEMPERATURE,
        max_tokens=Config.LLM_MAX_TOKENS,
    )

    fallbacks: List[BaseChatModel] = []
    if Config.OPENROUTER_API_KEY:
        openrouter_llm = ChatOpenAI(
            api_key=Config.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            model=openrouter_model,
            temperature=Config.LLM_TEMPERATURE,
            max_tokens=Config.LLM_MAX_TOKENS,
            default_headers={
                "HTTP-Referer": "https://easymyticket.app",
                "X-Title": "EasyMyTicket",
            },
        )
        fallbacks.append(openrouter_llm)
        log.debug("OpenRouter fallback configured (%s)", openrouter_model)
    else:
        log.debug("OPENROUTER_API_KEY not set — no fallback provider")

    if fallbacks:
        return groq_llm.with_fallbacks(fallbacks, exceptions_to_handle=(Exception,))
    return groq_llm


@lru_cache(maxsize=2)
def _get_llm_cached(size: str) -> BaseChatModel:
    from src.config import Config
    if size == "large":
        return _build_chain(
            groq_model=Config.CLASSIFICATION_MODEL,
            openrouter_model="meta-llama/llama-3.3-70b-instruct",
        )
    return _build_chain(
        groq_model=Config.METADATA_EXTRACTION_MODEL,
        openrouter_model="meta-llama/llama-3.1-8b-instruct:free",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_llm(callbacks: Optional[list] = None) -> BaseChatModel:
    """Large model (llama-3.3-70b) — classification, resolution."""
    llm = _get_llm_cached("large")
    if callbacks:
        return llm.with_config({"callbacks": callbacks})
    return llm


def get_small_llm(callbacks: Optional[list] = None) -> BaseChatModel:
    """Small model (llama-3.1-8b) — fast metadata extraction."""
    llm = _get_llm_cached("small")
    if callbacks:
        return llm.with_config({"callbacks": callbacks})
    return llm
