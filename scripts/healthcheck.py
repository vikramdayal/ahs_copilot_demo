#!/usr/bin/env python3
"""Docker health probe for the Streamlit process."""

from __future__ import annotations

import os
import sys
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    port = os.getenv("PORT", "8501")
    url = os.getenv("AHS_HEALTH_URL", f"http://127.0.0.1:{port}/_stcore/health")
    try:
        with urlopen(url, timeout=3) as response:  # noqa: S310 - loopback-only default
            body = response.read(128).decode("utf-8", errors="replace").strip().lower()
            if response.status != 200 or body not in {"ok", "healthy"}:
                print(f"Unhealthy response: status={response.status}, body={body!r}", file=sys.stderr)
                return 1
    except (OSError, URLError) as exc:
        print(f"Health probe failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
