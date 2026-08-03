"""Langfuse tracing (task 3.4) — strictly optional.

Absent keys, an uninstalled SDK, or a broken collector must never affect a scout
run: this module degrades to no-ops. Observability that can take down the thing it
observes is a liability, and a nightly job has nobody watching it fail.

What gets traced:
  * one span per publisher — inputs, outcome, recipe, budgets actually consumed
  * one generation per LLM call — model, messages, usage, cost
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from .config import settings

try:  # pragma: no cover - import shape depends on the environment
    from langfuse import get_client
    _AVAILABLE = True
except ImportError:  # pragma: no cover
    get_client = None  # type: ignore[assignment]
    _AVAILABLE = False

_client: Any = None
_checked = False


def _lf() -> Any:
    """The Langfuse client, or None when tracing is off/unavailable/broken."""
    global _client, _checked
    if _checked:
        return _client
    _checked = True
    if not (_AVAILABLE and settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    try:
        _client = get_client()
    except Exception:  # noqa: BLE001 - never let telemetry break a run
        _client = None
    return _client


class _NullSpan:
    """Stands in for a span so call sites need no `if tracing:` branches."""

    def update(self, **_kw) -> None:
        pass

    def score(self, **_kw) -> None:
        pass


@contextmanager
def scout_span(publisher: dict[str, Any]):
    client = _lf()
    if client is None:
        yield _NullSpan()
        return
    try:
        with client.start_as_current_span(
            name="scout-publisher",
            input={"name": publisher.get("name"), "website": publisher.get("website"),
                   "category": publisher.get("category"), "kind": publisher.get("kind")},
        ) as span:
            span.update_trace(name="scout-publisher",
                              tags=["scout", publisher.get("category") or "uncategorised"])
            yield span
    except Exception:  # noqa: BLE001
        yield _NullSpan()


@contextmanager
def llm_generation(model: str, messages: list[dict]):
    client = _lf()
    if client is None:
        yield _NullSpan()
        return
    try:
        with client.start_as_current_observation(
            as_type="generation", name="scout-investigate", model=model,
            input=messages[-2:],   # system prompt is static; last exchange is the signal
        ) as gen:
            yield gen
    except Exception:  # noqa: BLE001
        yield _NullSpan()


def flush() -> None:
    client = _lf()
    if client is not None:
        try:
            client.flush()
        except Exception:  # noqa: BLE001
            pass


def enabled() -> bool:
    return _lf() is not None
