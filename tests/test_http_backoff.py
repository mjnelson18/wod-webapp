"""Transport-level failure handling: back off and stop, don't hammer or crash.

FPL publishes no rate limits, so the contract we hold ourselves to is: strictly
sequential requests, a descriptive User-Agent, and on 429/503 stop the run rather
than retry hard. The next cron fires within minutes.

The other half is responses that are not failures and are not data either: between
seasons the draft API serves an HTML holding page under HTTP 200, which no status
code check catches.
"""

import email.message
import urllib.error

import pytest

from pipeline.fetchers import http

# Trimmed from the real response served by draft.premierleague.com/api/game while
# the game is being rolled over to a new season.
HOLDING_PAGE = (b"<!DOCTYPE html> <title>Game Updating</title> <article>"
                b"<p>Fantasy Draft is currently being updated for the 2026/27 season,"
                b" check back soon</p></article>")


class FakeResponse:
    def __init__(self, payload, content_type="application/json", status=200):
        self.payload = payload
        self.status = status
        self.headers = email.message.Message()
        if content_type:
            self.headers["Content-Type"] = content_type

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


def test_holding_page_raises_maintenance(monkeypatch):
    """
    The between-seasons failure mode: HTTP 200, text/html, "Game Updating". No
    status code flags it, so before this it reached json.loads and raised
    FetchError straight out of the schedule gate, reddening the whole workflow.
    """
    calls = []

    def urlopen(*a, **k):
        calls.append(1)
        return FakeResponse(HOLDING_PAGE, content_type="text/html")

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    with pytest.raises(http.Maintenance) as raised:
        http.get_json("http://x")
    # the title is the useful bit in an Actions log
    assert "Game Updating" in str(raised.value)
    assert len(calls) == 1, "a maintenance window outlasts any retry budget"


def test_maintenance_is_a_fetch_error():
    """Callers that catch FetchError broadly must keep catching this."""
    assert issubclass(http.Maintenance, http.FetchError)


def test_html_without_a_content_type_is_still_detected(monkeypatch):
    monkeypatch.setattr(http.urllib.request, "urlopen",
                        lambda *a, **k: FakeResponse(b"  <html><body>nope</body></html>",
                                                     content_type=None))
    with pytest.raises(http.Maintenance):
        http.get_json("http://x")


def test_truncated_json_is_retried_not_called_maintenance(monkeypatch):
    """
    A short read is transient and worth retrying; a holding page is not. Only the
    latter may short-circuit, or a network blip would look like a season rollover
    and skip a build that should have happened.
    """
    state = {"n": 0}

    def urlopen(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            return FakeResponse(b'{"a": 1')        # truncated, still application/json
        return FakeResponse(b'{"a": 1}')

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    assert http.get_json("http://x") == {"a": 1}
    assert state["n"] == 2


def test_json_under_an_odd_content_type_still_parses(monkeypatch):
    """Detection must not depend on FPL labelling its own JSON correctly."""
    monkeypatch.setattr(http.urllib.request, "urlopen",
                        lambda *a, **k: FakeResponse(b'{"a":1}', content_type="text/plain"))
    assert http.get_json("http://x") == {"a": 1}


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
