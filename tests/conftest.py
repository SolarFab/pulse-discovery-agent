"""Test-wide guarantees.

Tests must not touch the network, and they must not emit telemetry. The second
one bit for real: `pytest` sent 15 `scout-investigate` generations to the
production Langfuse project, because observability reads live keys from .env and
the budget tests exercise the investigator loop with a mocked LLM. Mock traffic
in a real observability project is worse than no traffic — it corrupts exactly
the numbers you would use to judge the agent.
"""

import pytest

from discovery_agent import observability
from discovery_agent.config import settings


@pytest.fixture(autouse=True)
def _no_telemetry(monkeypatch):
    """Disable Langfuse for every test unless the test opts in by patching."""
    monkeypatch.setattr(settings, "langfuse_public_key", "", raising=False)
    monkeypatch.setattr(settings, "langfuse_secret_key", "", raising=False)
    monkeypatch.setattr(observability, "_client", None, raising=False)
    monkeypatch.setattr(observability, "_checked", False, raising=False)
    yield
    observability._client = None
    observability._checked = False
