"""Thin HTTP client. No logic beyond retry/backoff.

FPL endpoints are public reads — no auth, no credentials, no secrets anywhere in
the pipeline or the Action.
"""

import json
import time
import urllib.error
import urllib.request

# Identifies the job so FPL can see who is calling and where to complain.
USER_AGENT = "wod-datapacks/1.0 (+https://github.com/mN3l50n-nms/wod-webapp)"
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


class FetchError(RuntimeError):
    pass


class RateLimited(FetchError):
    """
    The API asked us to back off.

    Raised instead of retrying indefinitely. The caller should abandon the run —
    the next cron fires within minutes, so there is nothing to gain from pushing.
    """


def _retry_after(error) -> float | None:
    value = error.headers.get("Retry-After") if error.headers else None
    if not value:
        return None
    try:
        return min(float(value), MAX_RETRY_AFTER)
    except ValueError:
        return None


def get_json(url: str, *, retries: int = MAX_RETRIES, throttle: float = THROTTLE):
    """
    GET and parse JSON. Returns None on 404 (a real answer for some entry/GW pairs).

    Raises RateLimited on a persistent 429/503 so the build can stop cleanly rather
    than hammering an endpoint that has told us to wait.
    """
    last = None
    backoffs = 0
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read())
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
