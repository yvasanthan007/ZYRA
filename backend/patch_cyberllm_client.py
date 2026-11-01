"""Patches for the CyberLLM client integration."""

import os


def patch_cyberllm_client():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "backend",
        "cyberllm_client.py",
    )
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    old = '''def check_health() -> dict:
    """CyberLLM health-check helper."""
    base_url = os.getenv("CYBERLLM_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise CyberLLMClientError("CyberLLM base URL configuration is invalid.", status_code=503)'''

    new = """def check_health() -> dict:
    """CyberLLM health-check helper."""
    # Load Zyra's .env so the base URL is available even when the process
    # was started without the environment variables exported.
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    base_url = os.getenv("CYBERLLM_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise CyberLLMClientError("CyberLLM base URL configuration is invalid.", status_code=503)"""

    if old in content:
        content = content.replace(old, new)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Patched {path}")


if __name__ == "__main__":
    patch_cyberllm_client()