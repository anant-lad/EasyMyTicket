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

def _groq_rate_limit_exceptions() -> tuple:
    """Return exception types that indicate Groq quota/rate-limit exhaustion."""
    types: list = []
    try:
        from groq import RateLimitError as _GroqRateLimit
        types.append(_GroqRateLimit)
    except ImportError:
        pass
    try:
        # langchain_groq wraps the raw error in this on some versions
        from langchain_groq.chat_models import ChatGroqError as _ChatGroqError
        types.append(_ChatGroqError)
    except ImportError:
        pass
    # Always fall back on generic HTTP 429 pattern caught by openai-compat clients
    try:
        from openai import RateLimitError as _OAIRateLimit
        types.append(_OAIRateLimit)
    except ImportError:
        pass
    # Broad safety net: any exception whose message contains rate-limit signals
    types.append(Exception)
    return tuple(types)


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
        log.info("OpenRouter fallback configured: %s → %s", groq_model, openrouter_model)
    else:
        log.warning("OPENROUTER_API_KEY not set — Groq rate-limit has no fallback")

    if fallbacks:
        exc_types = _groq_rate_limit_exceptions()
        # Retry Groq up to 3x with backoff before falling over to OpenRouter
        groq_with_retry = groq_llm.with_retry(
            retry_if_exception_type=exc_types,
            wait_exponential_jitter=True,
            stop_after_attempt=3,
        )
        return groq_with_retry.with_fallbacks(
            fallbacks,
            exceptions_to_handle=exc_types,
        )
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


def get_llm_for_tools(callbacks: Optional[list] = None, tools: Optional[list] = None) -> BaseChatModel:
    """Return an LLM chain suitable for tool-calling with Groq → OpenRouter fallback.

    .bind_tools() is applied to each model individually before wrapping in the
    fallback chain, because RunnableWithFallbacks does not expose bind_tools itself.
    Pass tools here instead of calling .bind_tools() on the returned chain.
    If tools is None, returns bare ChatGroq (backward-compatible)."""
    from src.config import Config
    from langchain_groq import ChatGroq

    groq_llm = ChatGroq(
        api_key=Config.GROQ_API_KEY,
        model=Config.CLASSIFICATION_MODEL,
        temperature=Config.LLM_TEMPERATURE,
        max_tokens=Config.LLM_MAX_TOKENS,
    )

    if tools is None:
        # Backward-compatible: caller will call .bind_tools() themselves
        llm: BaseChatModel = groq_llm
        if callbacks:
            return llm.with_config({"callbacks": callbacks})
        return llm

    # Bind tools to each model before wrapping — this is required because
    # RunnableWithFallbacks/RunnableRetry don't expose bind_tools().
    groq_bound = groq_llm.bind_tools(tools)

    exc_types = _groq_rate_limit_exceptions()
    groq_with_retry = groq_bound.with_retry(
        retry_if_exception_type=exc_types,
        wait_exponential_jitter=True,
        stop_after_attempt=3,
    )

    fallbacks: List[BaseChatModel] = []
    if Config.OPENROUTER_API_KEY:
        from langchain_openai import ChatOpenAI
        openrouter_llm = ChatOpenAI(
            api_key=Config.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            model="meta-llama/llama-3.3-70b-instruct",
            temperature=Config.LLM_TEMPERATURE,
            max_tokens=Config.LLM_MAX_TOKENS,
            default_headers={
                "HTTP-Referer": "https://easymyticket.app",
                "X-Title": "EasyMyTicket",
            },
        )
        fallbacks.append(openrouter_llm.bind_tools(tools))
        log.info("Remediation agent: Groq → OpenRouter fallback configured for tool-calling")
    else:
        log.warning("OPENROUTER_API_KEY not set — remediation agent has no fallback on Groq 429")

    chain = groq_with_retry.with_fallbacks(fallbacks, exceptions_to_handle=exc_types) if fallbacks else groq_with_retry
    if callbacks:
        return chain.with_config({"callbacks": callbacks})
    return chain
