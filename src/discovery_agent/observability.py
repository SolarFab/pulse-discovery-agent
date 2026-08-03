"""Langfuse tracing (task 3.4) — strictly optional.

Absent keys, an uninstalled SDK, or a broken collector must never affect a scout
run: this module degrades to no-ops. Observability that can take down the thing it
observes is a liability, and a nightly job has nobody watching it fail.

What gets traced:
  * one span per publisher — inputs, outcome, recipe, budgets actually consumed
  * one generation per LLM call — model, messages, usage, cost
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import shape depends on the environment
    from langfuse import Langfuse
    _AVAILABLE = True
except ImportError:  # pragma: no cover
    Langfuse = None  # type: ignore[assignment]
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
        # Credentials are passed EXPLICITLY. `get_client()` reads os.environ, which
        # pydantic-settings never populates — it loads .env into a Settings object —
        # so the SDK silently constructed a disabled client and every span was
        # dropped while this module still reported tracing as enabled.
        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception:  # noqa: BLE001 - never let telemetry break a run
        _client = None
    return _client


class _NullSpan:
    """Stands in for a span so call sites need no `if tracing:` branches."""

    def update(self, **_kw) -> None:
        pass

    def score(self, **_kw) -> None:
        pass


_warned: set[str] = set()


def _warn_once(where: str, exc: Exception) -> None:
    """Telemetry failures are guarded, but never silent.

    Swallowing them wordlessly is how this module reported tracing as "enabled"
    for an entire pilot while emitting nothing.
    """
    if where not in _warned:
        _warned.add(where)
        logger.warning("tracing disabled at %s: %s: %s", where, type(exc).__name__, exc)


@contextmanager
def _observation(kind: str, **kwargs):
    """Shared guard. Yields exactly once on every path — a @contextmanager that
    yields inside `try` and again in `except` raises RuntimeError the moment the
    caller's body throws.
    """
    client = _lf()
    cm = None
    if client is not None:
        try:
            cm = client.start_as_current_observation(**kwargs)
        except Exception as exc:  # noqa: BLE001
            _warn_once(kind, exc)
    if cm is None:
        yield _NullSpan(), None
        return
    with cm as observation:
        yield observation, client


@contextmanager
def scout_span(publisher: dict[str, Any]):
    # The trace inherits its name from this root observation, so no separate
    # trace-update call is needed — and this SDK has none anyway (no update_trace
    # on the span, no update_current_trace on the client). Category and kind ride
    # along as metadata, which IS supported, instead of as trace tags.
    with _observation(
        "scout_span",
        name="scout-publisher",
        # The v4 client has no start_as_current_span; observations carry a type.
        as_type="agent",
        input={"name": publisher.get("name"), "website": publisher.get("website")},
        metadata={"category": publisher.get("category") or "uncategorised",
                  "kind": publisher.get("kind"), "component": "scout"},
    ) as (span, _client):
        yield span


@contextmanager
def llm_generation(model: str, messages: list[dict]):
    with _observation(
        "llm_generation",
        as_type="generation", name="scout-investigate", model=model,
        input=messages[-2:],   # system prompt is static; last exchange is the signal
    ) as (gen, _client):
        yield gen


def flush() -> None:
    client = _lf()
    if client is not None:
        try:
            client.flush()
        except Exception:  # noqa: BLE001
            pass


def enabled() -> bool:
    return _lf() is not None
