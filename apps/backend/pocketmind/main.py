"""The local PocketMind server.

Binds to loopback only and serves both the setup wizard and the assistant from
the same origin. There is no account system and no cloud dependency: the only
security boundary this process enforces is the vault, plus an origin check so
that a web page open in the same browser cannot drive the API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pocketmind import config
from pocketmind.logs import configure as configure_logging
from pocketmind.logs import get_logger
from pocketmind.providers.base import RuntimeError_
from pocketmind.routers import chat, library, setup, system, vault
from pocketmind.services.session import DriveDisconnected, SessionNotReady, session
from pocketmind.services.vault import VaultAuthError, VaultExists, VaultLocked, VaultMissing

log = get_logger()

#: Names that all mean "this computer", so localhost and 127.0.0.1 are
#: interchangeable as long as the port matches.
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _split_host(value: str) -> tuple[str, int | None]:
    host, _, port = value.rpartition(":")
    if host and port.isdigit():
        return host.strip("[]").lower(), int(port)
    return value.strip("[]").lower(), None


def is_same_origin(origin: str, host_header: str) -> bool:
    """Does this Origin refer to the server handling the request?

    Compared against the request's own Host rather than a fixed port, so
    PocketMind still works when started with --port.
    """
    parsed = urlparse(origin)
    if parsed.scheme not in ("http", "https"):
        return False
    origin_host = (parsed.hostname or "").lower()
    origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)

    host, port = _split_host(host_header)
    host_port = port if port is not None else 80

    if origin_port != host_port:
        return False
    if origin_host in _LOOPBACK and host in _LOOPBACK:
        return True
    return origin_host == host


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log.info("PocketMind %s starting", config.APP_VERSION)
    try:
        opened = session.autobind()
        if opened:
            log.info("Opened %s automatically", opened.root)
        else:
            log.info("No single PocketMind drive found; starting in setup mode")
    except Exception as exc:  # a broken drive must not stop the wizard loading
        log.warning("Could not open a drive automatically: %s", exc.__class__.__name__)
    yield
    log.info("PocketMind shutting down")
    session.shutdown()


app = FastAPI(
    title="PocketMind",
    version=config.APP_VERSION,
    summary="Your AI. Your memories. Your drive.",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
app.include_router(system.router)
app.include_router(setup.router)
app.include_router(chat.router)
app.include_router(library.router)
app.include_router(vault.router)


@app.middleware("http")
async def guard_origin(request: Request, call_next: Callable):
    """Reject cross-origin writes.

    Everything here is served over loopback, so any request carrying a
    different Origin came from another page in the user's browser rather than
    from PocketMind itself.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and not is_same_origin(origin, request.headers.get("host", "")):
            log.warning("Blocked a cross-origin request from another page")
            return JSONResponse(
                {"detail": "This request did not come from PocketMind and was blocked."}, status_code=403
            )
    return await call_next(request)


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "local", "version": config.APP_VERSION}


def _problem(status: int, detail: str, hint: str = "") -> JSONResponse:
    body: dict[str, str] = {"detail": detail}
    if hint:
        body["hint"] = hint
    return JSONResponse(body, status_code=status)


@app.exception_handler(SessionNotReady)
async def _not_ready(request: Request, exc: SessionNotReady) -> JSONResponse:
    return _problem(409, str(exc))


@app.exception_handler(DriveDisconnected)
async def _disconnected(request: Request, exc: DriveDisconnected) -> JSONResponse:
    return _problem(410, str(exc))


@app.exception_handler(VaultLocked)
async def _locked(request: Request, exc: VaultLocked) -> JSONResponse:
    return _problem(423, str(exc))


@app.exception_handler(VaultAuthError)
async def _vault_auth(request: Request, exc: VaultAuthError) -> JSONResponse:
    return _problem(401, str(exc))


@app.exception_handler(VaultMissing)
async def _vault_missing(request: Request, exc: VaultMissing) -> JSONResponse:
    return _problem(404, str(exc))


@app.exception_handler(VaultExists)
async def _vault_exists(request: Request, exc: VaultExists) -> JSONResponse:
    return _problem(409, str(exc))


@app.exception_handler(RuntimeError_)
async def _runtime(request: Request, exc: RuntimeError_) -> JSONResponse:
    return _problem(503, str(exc), getattr(exc, "hint", ""))


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Never let a bare 'Internal Server Error' reach the interface.

    Without this, an unhandled error returns plain text, the interface cannot
    read a detail out of it, and the user is shown "Request failed (500)" —
    which tells them nothing and tells us nothing either.
    """
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return _problem(
        500,
        f"Something went wrong inside PocketMind ({exc.__class__.__name__}).",
        "The full details are in PocketMind/logs/pocketmind.log on your drive. "
        "If the drive was unplugged, reconnect it and reload this page.",
    )
