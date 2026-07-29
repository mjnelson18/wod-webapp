"""Thin HTTP client. No logic beyond retry/backoff.

FPL endpoints are public reads — no auth, no credentials, no secrets anywhere in
the pipeline or the Action.
"""

import json
import time
import urllib.error
import urllib.request

USER_AGENT = "wod-datapacks/1.0 (+https://github.com/mN3l50n-nms/wod-webapp)"
MAX_RETRIES = 4
TIMEOUT = 60
THROTTLE = 0.2


class FetchError(RuntimeError):
    pass


def get_json(url: str, *, retries: int = MAX_RETRIES, throttle: float = THROTTLE):
    """GET and parse JSON. Returns None on 404 (a real answer for some entry/GW pairs)."""
    last = None
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
            last = error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last = error
        time.sleep(2 ** attempt)
    raise FetchError(f"{url}: {last}")
