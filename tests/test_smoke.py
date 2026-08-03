"""Smoke tests — no DB or network required. They check the wiring, not behaviour."""

from __future__ import annotations

from discovery_agent.config import settings
from discovery_agent.graph import build_graph
from discovery_agent.guards import FetchSession
from discovery_agent.investigator import TOOL_SCHEMAS
from discovery_agent.tools import fetch_page


def test_settings_have_demo_defaults():
    assert settings.database_url.startswith("postgresql://")
    assert settings.run_max_publishers > 0
    assert settings.scout_max_usd > 0


def test_graph_compiles():
    # Building the graph must not require a DB or an LLM key.
    assert build_graph() is not None


def test_investigator_exposes_exactly_two_tools():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"fetch_page", "propose_recipe"}


def test_fetch_page_handles_bad_host_gracefully():
    # Untrusted-input path must degrade to an error string, not raise.
    out = fetch_page(FetchSession(), "https://nonexistent.invalid")
    assert out.startswith(("[fetch_error]", "[fetch_refused]"))
