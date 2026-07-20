#!/usr/bin/env python3
"""Docker health probe for the local Streamlit process."""

from __future__ import annotations

import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen


def _health_url() -> str:
    port = os.getenv("PORT", "8501")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("PORT must be an integer from 1 through 65535")
    url = os.getenv("AHS_HEALTH_URL", f"http://127.0.0.1:{port}/_stcore/health")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("AHS_HEALTH_URL must be a loopback HTTP URL")
    return url


def main() -> int:
    try:
        with urlopen(_health_url(), timeout=3) as response:  # noqa: S310 - validated loopback URL
            body = response.read(128).decode("utf-8", errors="replace").strip().lower()
            if response.status != 200 or body not in {"ok", "healthy"}:
                print(
                    f"Unhealthy response: status={response.status}, body={body!r}",
                    file=sys.stderr,
                )
                return 1
    except (HTTPError, OSError, URLError, ValueError) as exc:
        print(f"Health probe failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
