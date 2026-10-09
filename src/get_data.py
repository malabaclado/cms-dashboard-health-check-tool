# HTTP fetching + retry logic for the CMS dashboard health check API.
# get_data() is the active implementation used by perform_health_check() via
# fetch_with_retry(). load_response() below is a helper for replaying a saved
# response and is not called from the main flow.

import requests
import urllib3
import re
from pathlib import Path
import json
from write_data import save_response
from config import host
import config  # DEMO MODE (portfolio only): read MOCK_MODE / simulate_failures at call time
import random  # DEMO MODE (portfolio only): randomised delay in get_mock_data()
import time
from typing import Callable, Any, Optional


# ======================================================================
# DEMO MODE (portfolio only): not part of the original tool.
# get_mock_data() stands in for the live CMS API call: it reads the response
# from mock_input/{tag}-check.json, then saves it with the real save_response()
# so the write-to-data/responses step still runs. The input never changes,
# so every run saves identical content.
# The real fetch logic below is unchanged and runs when MOCK_MODE is off.
# ======================================================================
MOCK_INPUT_DIR = Path(__file__).resolve().parent.parent / 'mock_input'
_mock_attempts = {}  # tag -> number of fetch attempts so far (for --simulate-failure)


class _MockResponse:
    """Minimal stand-in for requests.Response: save_response() only calls .json()."""
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def get_mock_data(tag='content'):
    """Return the mock API response for `tag` ('content' or 'importer')."""
    # --simulate-failure N: fail the first N attempts of each check, so the
    # retry/backoff output from retry_with_backoff() can be demonstrated.
    _mock_attempts[tag] = _mock_attempts.get(tag, 0) + 1
    if _mock_attempts[tag] <= config.simulate_failures:
        print(f"Connection Error: simulated failure {_mock_attempts[tag]}/{config.simulate_failures} (demo mode)")
        raise ConnectionError(f"Simulated connection failure for {tag} check")

    # Short random delay so the spinner/progress output looks like a real request.
    time.sleep(random.uniform(0.5, 1.5))

    with open(MOCK_INPUT_DIR / f'{tag}-check.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    print("Status  : 200")
    print("Content : application/json")

    save_response(_MockResponse(data), tag=tag)

    print(f'{tag} check successful!'.capitalize())
    return data


def get_data(url: str, referrer: str, tag='content'):
    """Retrieves content-check data from API. Returns response data in JSON format.

    Every failure path (SSL/connection error, non-200 status, empty body,
    invalid JSON) raises rather than returning None, so that
    retry_with_backoff() (which only retries on raised exceptions) can retry
    transient failures, and the real error is what's eventually reported to
    the user instead of a downstream 'NoneType is not subscriptable' error.
    """
    # ======================================================================
    # DEMO MODE (portfolio only): not part of the original tool.
    # In demo mode, return the mock response instead of calling the live API.
    # The real fetch logic below is unchanged and runs when MOCK_MODE is off.
    # ======================================================================
    if config.MOCK_MODE:
        return get_mock_data(tag)

    # Cookies from browser session — refreshed interactively via
    # helper_functions.update_cookies() when stale (see validate_cookies()).
    # Loaded first because the X-CSRFToken header below is read from it too.
    with open('data/cookies.json', 'r') as f:
        cookies = json.load(f)

    # Replicate exact headers from browser
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9,ku;q=0.8,de-DE;q=0.7,de;q=0.6",
        "Connection": "keep-alive",
        "Host": host,
        "Referer": referrer,  # replace with actual referer
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0",
        "X-CSRFToken": cookies.get("CSRF_TOKEN"),     # from data/cookies.json
        "X-Requested-With": "XMLHttpRequest",
        "sec-ch-ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "Windows"
    }

    # Query parameters
    params = {
        "_dc": str(int(time.time() * 1000)),    # replace with actual value
        "node": "root"
    }

    # Suppress SSL warnings
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()
    session.verify = False  # ← SSL fix applied at session level

    try:
        response = session.get(
            url,
            headers=headers,
            cookies=cookies,
            params=params
        )

    except requests.exceptions.SSLError as e:
        print(f"SSL Error: {e}")
        raise  # re-raise (not return None) so retry_with_backoff() will retry
    except requests.exceptions.ConnectionError as e:
        print(f"Connection Error: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise

    # Validation
    print(f"Status  : {response.status_code}")
    print(f"Content : {response.headers.get('Content-Type')}")

    if response.status_code != 200:
        print(f"HTTP Error: {response.status_code}")
        raise requests.exceptions.HTTPError(
            f"HTTP {response.status_code} error for {tag} check ({url})"
        )

    if not response.text.strip():
        print("Empty response body")
        raise ValueError(f"Empty response body for {tag} check ({url})")

    # Persist raw response for debugging/replay (see load_response() below).
    save_response(response, tag=tag)

    try:
        print(f'{tag} check successful!'.capitalize())
        return response.json()
    except (ValueError, KeyError) as e:
        print(f"Invalid JSON or missing 'children' key: {e}")
        raise

# Loads a previously saved raw API response (written by save_response() in
# write_data.py) for offline replay/testing — not used by main.py's live flow.
def load_response(filename):
    path = Path('data/responses') / f"{filename}.txt"

    with open(path, 'r', encoding='utf-8') as f:
            content = json.load(f)

    return content['children']

# Used by update_cookies() (helper_functions.py) to pull tokens out of a
# pasted browser cURL command. NOTE: returns None (no exception) on no match,
# so a malformed/unexpected paste silently writes None into cookies.json
# instead of failing loudly — see the NOTE on modify_cookies().
def extract_regex(pattern, line):
    match = re.search(pattern, line)
    if match:
        token = match.group(1)
        return token

def retry_with_backoff(
    func: Callable,
    max_retries: int = 5,
    initial_wait: int = 1,
    backoff_factor: float = 2.0,
    max_wait: Optional[int] = None,
    exceptions: tuple = (Exception,)
) -> Any:
    """
    Retry a function with exponential backoff.
    
    Args:
        func: Function to call
        max_retries: Maximum number of retry attempts
        initial_wait: Initial wait time in seconds
        backoff_factor: Multiplier for exponential backoff
        max_wait: Maximum wait time between retries (None = unlimited)
        exceptions: Tuple of exceptions to catch and retry on
    
    Returns:
        Result from successful function call
    """
    for attempt in range(max_retries):
        try:
            print(f"Getting data... Attempt:{attempt + 1}/{max_retries}")
            return func()
        except exceptions as e:
            if attempt == max_retries - 1:
                raise
            
            wait_time = initial_wait * (backoff_factor ** attempt)
            if max_wait:
                wait_time = min(wait_time, max_wait)
            
            print(f"Attempt {attempt + 1}/{max_retries} failed: {type(e).__name__}")
            print(f"Retrying in {wait_time}s...")
            time.sleep(wait_time)

# Usage with get_data
def fetch_with_retry(url, referrer, tag='content', max_retries=3):
    """Wrapper to call get_data with retry logic.

    Returns: API response in JSON format.

    initial_wait=5s, backoff_factor=2.0, max_wait=30s -> retry delays of
    5s, 10s, 20s, 30s, 30s... capped at max_retries attempts. All exceptions
    are retried (exceptions=(Exception,)); the last one is re-raised if every
    attempt fails.
    """
    def _fetch():
        return get_data(url, referrer, tag=tag)
    
    return retry_with_backoff(
        _fetch,
        max_retries=max_retries,
        initial_wait=5,
        backoff_factor=2.0,
        max_wait=30,
        exceptions=(Exception,)
    )

