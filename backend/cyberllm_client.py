"""Async client for the local CyberLLM defensive-security API."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv

# Load Zyra's project configuration without overriding existing environment values.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
TIMEOUT_SECONDS = 8.0


class CyberLLMClientError(Exception):
    """Safe-to-display error from the CyberLLM integration."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _configuration():
    api_key = os.getenv("CYBERLLM_API_KEY", "").strip()
    base_url = os.getenv(
        "CYBERLLM_BASE_URL", DEFAULT_BASE_URL
    ).strip().rstrip("/")

    if not api_key:
        raise CyberLLMClientError(
            "CyberLLM API key is not configured in Zyra's environment.",
            status_code=503,
        )

    if not base_url.startswith(("http://", "https://")):
        raise CyberLLMClientError(
            "CyberLLM base URL configuration is invalid.",
            status_code=503,
        )

    return base_url, api_key


def _validate_url(url: str) -> str:
    value = str(url or "").strip()

    if not 8 <= len(value) <= 4096:
        raise CyberLLMClientError(
            "Provide a URL between 8 and 4096 characters.",
            status_code=400,
        )

    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme.lower() in {"http", "https"}
            and bool(parsed.hostname)
            and not any(char.isspace() for char in value)
        )
    except (ValueError, TypeError):
        valid = False

    if not valid:
        raise CyberLLMClientError(
            "Provide a valid HTTP or HTTPS URL.",
            status_code=400,
        )

    return value


async def predict_phishing(url: str) -> dict:
    """Request an advisory phishing assessment from CyberLLM."""
    value = _validate_url(url)
    base_url, api_key = _configuration()

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = await client.post(
                f"{base_url}/phishing/predict",
                headers={"X-API-Key": api_key},
                json={"url": value},
            )

    except httpx.TimeoutException:
        raise CyberLLMClientError(
            "CyberLLM request timed out. Try again later.",
            status_code=504,
        ) from None

    except httpx.RequestError:
        raise CyberLLMClientError(
            "CyberLLM is unreachable. Check that its local API server is running.",
            status_code=503,
        ) from None

    if response.status_code == 401:
        raise CyberLLMClientError(
            "CyberLLM authentication failed. Check Zyra's local API configuration.",
            status_code=502,
        )

    if response.status_code == 503:
        raise CyberLLMClientError(
            "CyberLLM's phishing model is currently unavailable.",
            status_code=503,
        )

    if response.status_code >= 400:
        raise CyberLLMClientError(
            f"CyberLLM returned an upstream HTTP {response.status_code} error.",
            status_code=502,
        )

    try:
        result = response.json()
    except ValueError:
        raise CyberLLMClientError(
            "CyberLLM returned an invalid response.",
            status_code=502,
        ) from None

    if not isinstance(result, dict):
        raise CyberLLMClientError(
            "CyberLLM returned an unexpected response format.",
            status_code=502,
        )

    if result.get("url") != value:
        raise CyberLLMClientError(
            "CyberLLM response URL did not match the requested URL.",
            status_code=502,
        )

    if result.get("prediction") not in {"PHISHING", "LEGITIMATE"}:
        raise CyberLLMClientError(
            "CyberLLM returned an unrecognized prediction.",
            status_code=502,
        )

    return result
