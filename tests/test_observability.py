"""Tracing must never be able to break a scout run."""

from unittest.mock import patch

from discovery_agent import observability as O
from discovery_agent.config import settings


def _reset():
    O._client, O._checked = None, False


def test_no_keys_means_no_tracing():
    _reset()
    with patch.object(settings, "langfuse_public_key", ""), \
         patch.object(settings, "langfuse_secret_key", ""):
        assert not O.enabled()
        with O.scout_span({"name": "V"}) as span:
            span.update(output={"outcome": "none"})   # must not raise
        with O.llm_generation("m", [{"role": "user", "content": "x"}]) as gen:
            gen.update(output={})
        O.flush()
    _reset()


def test_broken_client_degrades_to_noop():
    """A collector that is down, misconfigured, or throwing must not surface."""
    _reset()
    with patch.object(settings, "langfuse_public_key", "pk"), \
         patch.object(settings, "langfuse_secret_key", "sk"), \
         patch.object(O, "_AVAILABLE", True), \
         patch.object(O, "get_client", side_effect=RuntimeError("collector down")):
        assert not O.enabled()
        with O.scout_span({"name": "V"}) as span:
            span.update(output={})
    _reset()


def test_span_failure_mid_run_does_not_propagate():
    _reset()

    class ExplodingClient:
        def start_as_current_span(self, **_kw):
            raise RuntimeError("boom")

        def start_as_current_observation(self, **_kw):
            raise RuntimeError("boom")

        def flush(self):
            raise RuntimeError("boom")

    with patch.object(settings, "langfuse_public_key", "pk"), \
         patch.object(settings, "langfuse_secret_key", "sk"), \
         patch.object(O, "_AVAILABLE", True), \
         patch.object(O, "get_client", return_value=ExplodingClient()):
        with O.scout_span({"name": "V"}) as span:
            span.update(output={})           # no raise
        with O.llm_generation("m", [{}, {}]) as gen:
            gen.update(output={})            # no raise
        O.flush()                            # no raise
    _reset()
