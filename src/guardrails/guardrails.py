"""
EasyMyTicket — NeMo Guardrails wrapper (E6).

Wraps LLM calls in classification and chat nodes with:
  - Input rails: block off-topic questions, credential sharing
  - Output rails: prevent hallucinated procedures
  - Topic adherence: IT support only

Usage:
    from src.guardrails.guardrails import get_rails, guarded_generate

    # Simple one-shot call
    reply = await guarded_generate(user_message="My printer is broken")

    # With full message history (for chat)
    reply = await guarded_generate_chat(messages=[...])
"""
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config.yml"
_rails_instance = None


def _build_rails_config():
    """Build NeMo RailsConfig pointing at our guardrails directory."""
    try:
        from nemoguardrails import RailsConfig
        return RailsConfig.from_path(str(_CONFIG_PATH.parent))
    except Exception as e:
        log.warning("NeMo Guardrails config load failed: %s — guardrails disabled", e)
        return None


def get_rails():
    """Lazy singleton — only initialised once per process."""
    global _rails_instance
    if _rails_instance is None:
        cfg = _build_rails_config()
        if cfg is None:
            return None
        try:
            from nemoguardrails import LLMRails
            # Patch: use our existing Groq LLM rather than a new model instance
            from src.llm.provider import get_llm, get_callbacks
            llm = get_llm(get_callbacks())
            _rails_instance = LLMRails(cfg, llm=llm)
            log.info("NeMo Guardrails initialised")
        except Exception as e:
            log.warning("NeMo LLMRails init failed: %s — guardrails disabled", e)
            _rails_instance = None
    return _rails_instance


async def guarded_generate(
    user_message: str,
    context: Optional[str] = None,
) -> Optional[str]:
    """
    Run user_message through NeMo rails and return the guarded LLM response.
    Returns None if guardrails are unavailable (caller falls back to raw LLM).
    """
    rails = get_rails()
    if rails is None:
        return None

    messages = []
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": user_message})

    try:
        result = await rails.generate_async(messages=messages)
        return result
    except Exception as e:
        log.warning("Guardrails generate failed: %s — falling back to unguarded LLM", e)
        return None


async def guarded_generate_chat(messages: List[Dict]) -> Optional[str]:
    """
    Run a full conversation through NeMo rails.
    messages: list of {"role": "user"|"assistant"|"system", "content": "..."}
    """
    rails = get_rails()
    if rails is None:
        return None
    try:
        return await rails.generate_async(messages=messages)
    except Exception as e:
        log.warning("Guardrails chat generate failed: %s", e)
        return None


def check_output_safety(text: str) -> bool:
    """
    Lightweight synchronous check — returns False if the output text
    looks like it might contain unsafe content (credential leaks etc.).
    NeMo output rails handle the LLM-side; this is a regex backstop.
    """
    import re
    danger_patterns = [
        r"password\s*[:=]\s*\S+",
        r"api[_-]?key\s*[:=]\s*\S+",
        r"secret\s*[:=]\s*\S+",
        r"token\s*[:=]\s*[A-Za-z0-9+/=]{20,}",
    ]
    for pattern in danger_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            log.warning("Output safety check blocked a potentially sensitive response")
            return False
    return True
