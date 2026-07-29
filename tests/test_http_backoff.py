"""Rate-limit handling: back off and stop, don't hammer.

FPL publishes no rate limits, so the contract we hold ourselves to is: strictly
sequential requests, a descriptive User-Agent, and on 429/503 stop the run rather
than retry hard. The next cron fires within minutes.
"""

import urllib.error

import pytest

from pipeline.fetchers import http


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("http://x", code, "err", headers, None)


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """Keep the tests instant while still exercising the retry paths."""
    monkeypatch.setattr(http.time, "sleep", lambda *_: None)


def test_returns_parsed_json(monkeypatch):
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda *a, **k: FakeResponse(b'{"a":1}'))
    assert http.get_json("http://x") == {"a": 1}


def test_404_is_an_answer_not_an_error(monkeypatch):
    """Some entry/gameweek pairs legitimately 404; that must not burn retries."""
    calls = []

    def urlopen(*a, **k):
        calls.append(1)
        raise _http_error(404)

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    assert http.get_json("http://x") is None
    assert len(calls) == 1


@pytest.mark.parametrize("code", [429, 503])
def test_persistent_backoff_code_raises_rate_limited(monkeypatch, code):
    calls = []

    def urlopen(*a, **k):
        calls.append(1)
        raise _http_error(code)

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    with pytest.raises(http.RateLimited):
        http.get_json("http://x")
    # gives up quickly instead of exhausting every retry
    assert len(calls) <= http.BACKOFF_ATTEMPTS + 1


def test_transient_429_then_success(monkeypatch):
    """A single 429 is retried once, honouring Retry-After."""
    state = {"n": 0}
    slept = []
    monkeypatch.setattr(http.time, "sleep", lambda s: slept.append(s))

    def urlopen(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise _http_error(429, retry_after="7")
        return FakeResponse(b'{"ok":true}')

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    assert http.get_json("http://x") == {"ok": True}
    assert 7 in slept, f"expected Retry-After honoured, slept {slept}"


def test_retry_after_is_capped(monkeypatch):
    """A hostile Retry-After must not stall the job for hours."""
    slept = []
    monkeypatch.setattr(http.time, "sleep", lambda s: slept.append(s))

    def urlopen(*a, **k):
        raise _http_error(503, retry_after="99999")

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    with pytest.raises(http.RateLimited):
        http.get_json("http://x")
    assert max(slept) <= http.MAX_RETRY_AFTER


def test_other_errors_still_retry_then_fail(monkeypatch):
    calls = []

    def urlopen(*a, **k):
        calls.append(1)
        raise _http_error(500)

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    with pytest.raises(http.FetchError):
        http.get_json("http://x", retries=3)
    assert len(calls) == 3


def test_user_agent_identifies_the_project(monkeypatch):
    """FPL should be able to see who is calling and where to complain."""
    seen = {}

    def urlopen(request, *a, **k):
        seen["ua"] = request.get_header("User-agent")
        return FakeResponse(b"{}")

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    http.get_json("http://x")
    assert "wod-datapacks" in seen["ua"]
    assert "github.com" in seen["ua"]


def test_requests_are_spaced(monkeypatch):
    """A steady trickle is far less likely to be throttled than a burst."""
    slept = []
    monkeypatch.setattr(http.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda *a, **k: FakeResponse(b"{}"))
    http.get_json("http://x")
    assert slept == [http.THROTTLE]
