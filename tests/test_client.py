"""Verify secure transport and timeout configuration for upstream HTTP sessions."""

import pytest
import requests

from app.client import DEFAULT_TIMEOUT, create_http_session


def test_session_rejects_plain_http_and_disables_redirects() -> None:
    """The client refuses HTTP URLs before a request can reach the network."""
    with create_http_session() as session:
        with pytest.raises(requests.exceptions.InvalidURL, match="HTTPS"):
            session.get("http://example.invalid")

        assert session.timeout == DEFAULT_TIMEOUT
