"""Minimal HTTP client for OpenAI-compatible inference servers.

AutoTLDR runs locally but may borrow inference from any OpenAI-compatible server:
LM Studio on this machine, a llama.cpp router on another node, or an authenticated
gateway such as LiteLLM. This module is stdlib-only. It sends one request per
connection, never follows redirects, and never reads proxy environment variables,
so the configured base URL is the only peer that receives evidence.
"""

from __future__ import annotations

import http.client
import math
import re
import socket
import time
import urllib.parse
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
USER_AGENT = "AutoTLDR"
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_READ_CHUNK = 64 * 1024
_ERROR_DETAIL_BYTES = 300


class TransportError(RuntimeError):
    """The inference server could not be reached or returned a non-200 status."""

    def __init__(self, message: str, *, code: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class TransportTimeout(TransportError):
    """The request did not complete within its absolute deadline."""

    def __init__(self, message: str = "model request timed out") -> None:
        super().__init__(message, code="timeout")


def normalize_base_url(value: object) -> str:
    """Return a canonical OpenAI base URL such as ``https://host:4000/v1``.

    A bare origin gains ``/v1``. Any other path is kept, so servers that mount the
    API elsewhere (for example ``/api/v1``) work. A trailing ``/chat/completions``
    is accepted and stripped for convenience.
    """

    if type(value) is not str or not value or value.strip() != value:
        raise ValueError("base_url must be a non-empty, unpadded URL")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid base_url: {exc}") from exc
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ValueError("base_url scheme must be http or https")
    if not parsed.hostname:
        raise ValueError("base_url must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url must not embed credentials; use api_key_env")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not include a query string or fragment")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("base_url port is outside 1..65535")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    if not path:
        path = "/v1"
    return urllib.parse.urlunsplit((scheme, parsed.netloc.casefold(), path, "", ""))


def chat_completions_url(base_url: str) -> str:
    return normalize_base_url(base_url) + "/chat/completions"


def models_url(base_url: str) -> str:
    return normalize_base_url(base_url) + "/models"


def validate_env_name(value: object) -> str:
    if type(value) is not str or not _ENV_NAME.fullmatch(value):
        raise ValueError("api_key_env must be an environment variable name")
    return value


def validate_api_key(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or not value.isascii()
        or any(not character.isprintable() or character.isspace() for character in value)
    ):
        raise ValueError("API key must be non-empty printable ASCII without whitespace")
    return value


def request(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    api_key: str | None = None,
    timeout_seconds: float,
    max_response_bytes: int,
) -> bytes:
    """Perform one request and return the complete 200 response body."""

    if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
        raise TransportError("timeout must be positive", code="invalid-timeout")
    if type(max_response_bytes) is not int or max_response_bytes <= 0:
        raise TransportError("response limit must be positive", code="invalid-response-limit")
    parsed = urllib.parse.urlsplit(url)
    deadline = time.monotonic() + float(timeout_seconds)
    connection_type = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_type(parsed.hostname, parsed.port, timeout=timeout_seconds)
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if api_key is not None:
        headers["Authorization"] = f"Bearer {validate_api_key(api_key)}"
    target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    try:
        connection.request(method, target, body=body, headers=headers)
        _check_deadline(deadline)
        response = connection.getresponse()
        chunks: list[bytes] = []
        size = 0
        while True:
            _check_deadline(deadline, connection)
            chunk = response.read(_READ_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if response.status == 200 and size > max_response_bytes:
                raise TransportError(
                    f"response exceeded {max_response_bytes} bytes",
                    code="response-too-large",
                )
            if response.status != 200 and size > _ERROR_DETAIL_BYTES:
                chunks.append(chunk)
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
    except (TimeoutError, socket.timeout) as exc:
        raise TransportTimeout() from exc
    except TransportError:
        raise
    except (OSError, http.client.HTTPException) as exc:
        raise TransportError(
            f"cannot reach {parsed.scheme}://{parsed.netloc}: {type(exc).__name__}",
            code="transport-connect-error",
        ) from exc
    finally:
        connection.close()
    if response.status != 200:
        raise TransportError(
            f"HTTP {response.status} from {parsed.scheme}://{parsed.netloc}"
            + _error_detail(payload),
            code="http-status",
            status=response.status,
        )
    return payload


def _check_deadline(deadline: float, connection: Any | None = None) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TransportTimeout()
    sock = getattr(connection, "sock", None)
    if sock is not None:
        sock.settimeout(remaining)


def _error_detail(payload: bytes) -> str:
    """Surface the server's short error text, such as an auth or model-name failure."""

    import json

    text = payload[:_ERROR_DETAIL_BYTES].decode("utf-8", errors="replace")
    try:
        document = json.loads(payload)
        error = document.get("error") if isinstance(document, dict) else None
        message = error.get("message") if isinstance(error, dict) else error
        if isinstance(message, str):
            text = message
    except ValueError:
        pass
    text = " ".join(text.split())[:_ERROR_DETAIL_BYTES]
    return f": {text}" if text else ""


__all__ = [
    "DEFAULT_BASE_URL",
    "TransportError",
    "TransportTimeout",
    "chat_completions_url",
    "models_url",
    "normalize_base_url",
    "request",
    "validate_api_key",
    "validate_env_name",
]
