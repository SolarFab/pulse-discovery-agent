"""Budget-separation tests.

The pilot's paid path scored 0/9 because the sniffer and the investigator shared one
fetch counter: deterministic probing burned the whole allowance, so the LLM aborted
before its first fetch. These tests pin the fix.
"""

from unittest.mock import patch

from discovery_agent import investigator as I
from discovery_agent.config import settings


class FakeSession:
    def __init__(self, already_spent=0):
        self.fetches = already_spent


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _Call:
    def __init__(self, name, arguments, cid="c1"):
        self.id = cid
        self.function = _Fn(name, arguments)

    def model_dump(self, **_kw):
        return {"role": "assistant"}


class _Msg:
    def __init__(self, calls):
        self.tool_calls = calls
        self.content = None

    def model_dump(self, **_kw):
        return {"role": "assistant", "tool_calls": []}


def _resp(calls):
    class R:
        choices = [type("C", (), {"message": _Msg(calls)})()]
        usage = None
    return R()


def test_llm_gets_its_own_fetch_allowance():
    """A session that already spent the sniffer's fetches must not starve the LLM."""
    session = FakeSession(already_spent=settings.scout_max_sniff_fetches)
    trace, fetched = [], []

    def fake_fetch(sess, url):
        fetched.append(url)
        sess.fetches += 1
        return "PAGE"

    calls = iter([_resp([_Call("fetch_page", '{"url": "https://venue.example/a"}')]),
                  _resp([_Call("fetch_page", '{"url": "https://venue.example/b"}')]),
                  _resp([_Call("propose_recipe",
                               '{"recipe_type": "none", "confidence": 0.8}')])])

    with patch.object(I, "fetch_page", fake_fetch), \
         patch.object(I, "_client") as client, \
         patch.object(settings, "openrouter_api_key", "test-key"):
        client.return_value.chat.completions.create.side_effect = lambda **_kw: next(calls)
        recipe, _tokens, _usd = I.investigate(
            {"name": "V", "website": "https://venue.example"}, session, trace)

    assert fetched == ["https://venue.example/a", "https://venue.example/b"]
    assert recipe is not None and recipe.recipe_type == "none"
    assert not any(s.get("reason") == "fetch budget" for s in trace)


def test_llm_fetch_budget_still_binds():
    """The allowance is separate, not unlimited."""
    session = FakeSession(already_spent=3)
    trace = []

    def fake_fetch(sess, url):
        sess.fetches += 1
        return "PAGE"

    with patch.object(I, "fetch_page", fake_fetch), \
         patch.object(I, "_client") as client, \
         patch.object(settings, "openrouter_api_key", "test-key"):
        client.return_value.chat.completions.create.side_effect = lambda **_kw: _resp(
            [_Call("fetch_page", '{"url": "https://venue.example/x"}')])
        I.investigate({"name": "V", "website": "https://venue.example"}, session, trace)

    used = session.fetches - 3
    assert used == settings.scout_max_fetches
    assert any(s.get("reason") == "fetch budget" for s in trace)


def test_missing_api_key_degrades_instead_of_raising():
    trace = []
    with patch.object(settings, "openrouter_api_key", ""):
        recipe, tokens, usd = I.investigate({"name": "V"}, FakeSession(), trace)
    assert (recipe, tokens, usd) == (None, 0, 0.0)
    assert trace[-1]["step"] == "llm_error"
