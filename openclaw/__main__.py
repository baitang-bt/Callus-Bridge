"""Entry: python -m openclaw  → non-GUI wejam.v1 bridge on WEJAM_PORT (default 7702)."""

from __future__ import annotations

import logging
import os
import sys

# Repo root on sys.path so `wejam.v1` and `openclaw` resolve.
_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from openclaw import DEFAULT_PORT  # noqa: E402
from openclaw.server import serve  # noqa: E402


def main() -> None:
    """Configure logging and serve gRPC."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    port = int(os.environ.get("WEJAM_PORT", str(DEFAULT_PORT)))
    serve(port=port)


if __name__ == "__main__":
    main()
