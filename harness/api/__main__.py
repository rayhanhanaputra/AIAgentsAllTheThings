"""Start the local workbench API."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("AAT_WORKBENCH_PORT", "8787"))
    uvicorn.run("harness.api.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
