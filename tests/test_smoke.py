"""Smoke tests — no DB or network required. They check the wiring, not behaviour."""

from __future__ import annotations

from discovery_agent import tools
from discovery_agent.config import settings
from discovery_agent.graph import TOOLS, build_graph


def test_settings_have_demo_defaults():
    assert settings.database_url.startswith("postgresql://")
    assert settings.scout_max_venues > 0


def test_graph_compiles():
    # Building the graph must not require a DB or an LLM key.
    assert build_graph() is not None


def test_tools_are_registered():
    assert set(TOOLS) == {"fetch_url", "find_events_page", "check_resident_advisor"}
    assert all(callable(fn) for fn in TOOLS.values())


def test_fetch_url_handles_bad_host_gracefully():
    # Untrusted-input path must degrade to an error string, not raise.
    out = tools.fetch_url("http://nonexistent.invalid")
    assert out.startswith("[fetch_error]")
