"""``python -m pocketmind`` — start the server and open the interface."""

from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from pocketmind import config


def main() -> None:
    parser = argparse.ArgumentParser(prog="pocketmind", description="Start PocketMind on this computer.")
    parser.add_argument("--host", default=config.SERVER_HOST, help="Interface to bind to (loopback by default).")
    parser.add_argument("--port", type=int, default=config.SERVER_PORT)
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window.")
    parser.add_argument("--reload", action="store_true", help="Reload on code changes (development only).")
    arguments = parser.parse_args()

    url = f"http://{arguments.host}:{arguments.port}"
    if not arguments.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    print(f"\n  PocketMind is starting at {url}\n  Press Ctrl+C to stop.\n")
    uvicorn.run(
        "pocketmind.main:app",
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
