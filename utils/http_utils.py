"""
HTTP Utilities for AFL Dashboard Scrapers
==========================================
Provides a pre-configured requests.Session with automatic retries
and exponential backoff for all HTTP scrapers.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Default User-Agent for all scrapers
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def create_retry_session(
    retries: int = 3,
    backoff_factor: float = 1.0,
    status_forcelist: tuple = (429, 500, 502, 503, 504),
    timeout: int = 15,
    user_agent: str = DEFAULT_USER_AGENT,
) -> requests.Session:
    """
    Create a requests.Session with automatic retry and backoff.

    Default behaviour:
      - 3 retries with 1s / 2s / 4s exponential backoff
      - Retries on 429, 5xx status codes
      - 15-second timeout per request

    Args:
        retries: Maximum number of retries per request.
        backoff_factor: Multiplier for exponential backoff between retries.
        status_forcelist: HTTP status codes that trigger a retry.
        timeout: Default timeout in seconds for each request.
        user_agent: User-Agent header string.

    Returns:
        A configured requests.Session.
    """
    session = requests.Session()

    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["HEAD", "GET", "OPTIONS"],  # Safe methods only
        raise_on_status=False,  # Let caller handle status codes
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update({"User-Agent": user_agent})

    # Store default timeout on the session for convenience
    session._default_timeout = timeout

    # Monkey-patch .get/.post to inject default timeout when not specified
    _orig_request = session.request

    def _request_with_timeout(*args, **kwargs):
        if "timeout" not in kwargs:
            kwargs["timeout"] = timeout
        return _orig_request(*args, **kwargs)

    session.request = _request_with_timeout

    return session
