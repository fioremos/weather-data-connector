"""Configure HTTPS-only HTTP sessions for resilient upstream API requests."""

import logging
import math
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 15.0)
DEFAULT_USER_AGENT: str = "Singular-Extract-WeatherConnector/1.0"
MAX_POOL_SIZE: int = 10


class HTTPSOnlySession(requests.Session):
    """A requests session that rejects non-HTTPS URLs before transmission."""

    timeout: tuple[float, float] = DEFAULT_TIMEOUT

    def send(
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        """Send a prepared HTTPS request without following redirects.

        Args:
            request: Prepared upstream request.
            **kwargs: Transport options forwarded to ``requests.Session``.

        Returns:
            The upstream HTTP response.

        Raises:
            requests.exceptions.InvalidURL: If the request is not HTTPS.
        """
        if not request.url or urlparse(request.url).scheme.lower() != "https":
            raise requests.exceptions.InvalidURL("Only HTTPS requests are permitted.")
        kwargs["timeout"] = self.timeout
        kwargs["allow_redirects"] = False
        return super().send(request, **kwargs)


def create_http_session(
    retries: int = 5,
    backoff_factor: float = 1.0,
    timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    pool_maxsize: int = MAX_POOL_SIZE,
    user_agent: str = DEFAULT_USER_AGENT,
) -> HTTPSOnlySession:
    """Create a pooled HTTPS session with retries and bounded timeouts.

    Args:
        retries: Number of retries for connection and transient HTTP failures.
        backoff_factor: Exponential backoff multiplier.
        timeout: Positive (connect, read) timeout in seconds.
        pool_maxsize: Maximum connections per origin.
        user_agent: Value for the HTTP User-Agent header.

    Returns:
        A configured session owned by the caller, which must close it.
    """
    if retries < 0 or not math.isfinite(backoff_factor) or backoff_factor < 0:
        raise ValueError("Retries and backoff_factor must be finite and non-negative.")
    if (
        len(timeout) != 2
        or any(not math.isfinite(value) or value <= 0 for value in timeout)
    ):
        raise ValueError("timeout must contain positive connect and read values.")
    if not 1 <= pool_maxsize <= MAX_POOL_SIZE:
        raise ValueError(f"pool_maxsize must be between 1 and {MAX_POOL_SIZE}.")

    retry_strategy = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"HEAD", "GET", "OPTIONS"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=pool_maxsize,
        pool_maxsize=pool_maxsize,
    )
    session = HTTPSOnlySession()
    session.timeout = timeout
    session.headers.update(
        {"User-Agent": user_agent, "Accept": "application/json"}
    )
    session.mount("https://", adapter)

    logger.debug(
        "Initialized HTTPS session (retries=%d, backoff=%.1f, pool_maxsize=%d)",
        retries,
        backoff_factor,
        pool_maxsize,
    )
    return session
