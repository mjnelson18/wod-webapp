"""Thin HTTP client. No logic beyond retry/backoff.

FPL endpoints are public reads — no auth, no credentials, no secrets anywhere in
the pipeline or the Action.
"""

import json
import re
import time
import urllib.error
import urllib.request

# Identifies the job so FPL can see who is calling and where to complain.
USER_AGENT = "wod-datapacks/1.0 (+https://github.com/mjnelson18/wod-webapp)"
MAX_RETRIES = 4
TIMEOUT = 60
# Requests are strictly sequential and spaced. Never parallelise these endpoints:
# a burst is far more likely to be throttled than a steady trickle.
THROTTLE = 0.2

# Codes that mean "you are asking too often" or "we are struggling". Treated as a
# stop signal rather than something to retry hard against.
BACKOFF_CODES = {429, 503}
BACKOFF_ATTEMPTS = 2
MAX_RETRY_AFTER = 120

# A holding page announces itself as markup, not as a failure code. Only these
# content types are trusted to be data; anything else that fails to parse is
# checked against the markup test below.
JSON_CONTENT_TYPES = {"application/json", "text/json"}
HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
TITLE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class FetchError(RuntimeError):
    pass


class RateLimited(FetchError):
    """
    The API asked us to back off.

    Raised instead of retrying indefinitely. The caller should abandon the run —
    the next cron fires within minutes, so there is nothing to gain from pushing.
    """


class Maintenance(FetchError):
    """
    The endpoint answered, but with a holding page instead of data.

    Between seasons the draft API serves an HTML "Game Updating" page under
    HTTP 200 — not a 503, so none of the back-off handling sees it, and json.loads
    would raise straight out of the caller. Raised immediately rather than
    retried: a maintenance window lasts days, not the few seconds of retry budget.
    Treated like RateLimited by callers — an expected state, not a fault.
    """


def _retry_after(error) -> float | None:
    value = error.headers.get("Retry-After") if error.headers else None
    if not value:
        return None
    try:
        return min(float(value), MAX_RETRY_AFTER)
    except ValueError:
        return None


def _holding_page(response, body: bytes) -> str | None:
    """
    Describe `body` if it is a holding page rather than data, else None.

    Only consulted once JSON parsing has already failed, and only says yes on
    positive evidence of markup. That way valid JSON served under an odd content
    type still goes through, and a truncated read stays on the retry path — a
    network blip must not be mistaken for a season rollover.
    """
    content_type = response.headers.get_content_type() if response.headers else ""
    if content_type in JSON_CONTENT_TYPES:
        return None
    if content_type not in HTML_CONTENT_TYPES and body.lstrip()[:1] != b"<":
        return None
    title = TITLE.search(body)
    if title:
        return f"{content_type}, titled {title.group(1).decode(errors='replace').strip()[:80]!r}"
    return content_type or "no content type"


def get_json(url: str, *, retries: int = MAX_RETRIES, throttle: float = THROTTLE):
    """
    GET and parse JSON. Returns None on 404 (a real answer for some entry/GW pairs).

    Raises RateLimited on a persistent 429/503, and Maintenance when a 200 carries
    a holding page instead of data, so the build can stop cleanly rather than
    hammering — or crashing on — an endpoint with nothing to give.
    """
    last = None
    backoffs = 0
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                body = response.read()
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    holding = _holding_page(response, body)
                    if holding is None:
                        raise                      # transient: retried below
                    raise Maintenance(
                        f"{url}: HTTP {response.status} carried a holding page, not "
                        f"JSON ({holding}) — the endpoint is between seasons or down "
                        f"for maintenance; the next scheduled run will retry"
                    ) from None
            if throttle:
                time.sleep(throttle)
            return payload
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code in BACKOFF_CODES:
                backoffs += 1
                if backoffs > BACKOFF_ATTEMPTS:
                    raise RateLimited(
                        f"{url}: HTTP {error.code} after {backoffs} attempts — "
                        f"backing off, the next scheduled run will retry"
                    ) from error
                time.sleep(_retry_after(error) or (5 * backoffs))
                continue
            last = error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last = error
        time.sleep(2 ** attempt)
    raise FetchError(f"{url}: {last}")
