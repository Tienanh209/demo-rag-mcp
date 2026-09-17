"""One LLM entry point for every agent.

Any OpenAI-compatible endpoint. Swapping OpenAI for Gemini, vLLM or a local
Ollama is an environment change, not a code change.

A model is required. The client checks for one at startup and exits if it is
missing, rather than starting up and then refusing every question. Individual
calls still degrade — `complete_json` returns its caller's fallback when a
request fails — so one bad request costs answer quality, not the whole turn.
"""

import importlib.util
import json
from functools import lru_cache
from typing import Any

from src.common.config import settings
from src.common.trace import get_logger

log = get_logger("client.llm")

_client = None


@lru_cache(maxsize=1)
def _sdk_installed() -> bool:
    return importlib.util.find_spec("openai") is not None


def available() -> bool:
    """True when a real model is actually reachable.

    The SDK check matters: a key in .env with `openai` uninstalled used to report
    "available" here and then raise ImportError on the first call, halfway
    through a turn, instead of failing at the boundary.
    """
    if not _sdk_installed():
        return False
    if settings.llm_mode == "api":
        return bool(settings.llm_api_key)
    return bool(settings.llm_api_key and settings.llm_api_key not in {"not-set", "changeme"})


def backend() -> str:
    return "api" if available() else "unconfigured"


def router_model() -> str:
    """The model used for routing decisions — the big one unless configured."""
    return settings.router_model or settings.llm_model


def require(surface: str) -> None:
    """Exit rather than start half-working.

    Every answer path needs a model. Starting without one produced a server that
    accepted questions and refused all of them, which reads as a broken index
    rather than a missing key.
    """
    if available():
        return
    raise SystemExit(
        f"{surface}: no language model configured.\n"
        "Set LLM_API_KEY in .env (and LLM_BASE_URL for a non-OpenAI endpoint), "
        "then start again."
    )


class JsonResult(dict):
    """A dict that also remembers whether it came from the fallback path.

    Callers that only want the data keep treating it as a plain dict. The trace
    needs the difference: reporting a rule fallback as an LLM decision makes the
    trace panel lie about what actually ran.
    """

    fallback: bool = False


def _fell_back(data: dict[str, Any]) -> JsonResult:
    result = JsonResult(data)
    result.fallback = True
    return result


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    return _client


class LLMUnavailable(RuntimeError):
    """Raised when generation is requested but no backend is configured."""


async def complete(
    system: str,
    user: str,
    temperature: float | None = None,
    max_tokens: int = 900,
    model: str | None = None,
) -> str:
    if not available():
        raise LLMUnavailable("no LLM backend configured")
    resp = await _get_client().chat.completions.create(
        model=model or settings.llm_model,
        temperature=settings.llm_temperature if temperature is None else temperature,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return (resp.choices[0].message.content or "").strip()


async def complete_json(
    system: str,
    user: str,
    fallback: dict[str, Any],
    model: str | None = None,
    max_tokens: int = 400,
) -> JsonResult:
    """Ask for JSON and degrade gracefully — a malformed classifier response
    must never take down the conversation.

    The result carries `.fallback` so callers can report which path really ran.

    max_tokens defaults to 400 rather than 300 because the planner returns intent,
    tool, args, queries, topic and entities in one object. A truncated response is
    a JSONDecodeError, which lands in the fallback path — so an undersized budget
    looks exactly like "the model is ignoring the schema" while costing a full
    request every turn.
    """
    if not available():
        return _fell_back(fallback)
    try:
        raw = await complete(
            system + "\nRespond with JSON only. No prose, no code fences.",
            user,
            temperature=0.0,
            max_tokens=max_tokens,
            model=model,
        )
    except Exception as exc:  # noqa: BLE001 - deliberate fallback
        # A non-default model that fails every call is the quiet failure here:
        # the system keeps answering, every trace says "fallback", and nothing
        # points at the model name. Name it.
        if model and model != settings.llm_model:
            log.warning("LLM call on router model %r failed (%s) — using fallback", model, exc)
        else:
            log.warning("LLM call failed (%s) — using fallback", exc)
        return _fell_back(fallback)
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("classifier returned non-JSON, using fallback: %r", raw[:120])
        return _fell_back(fallback)
    return JsonResult(parsed) if isinstance(parsed, dict) else _fell_back(fallback)
