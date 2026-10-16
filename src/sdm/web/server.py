"""HTTP server for `sdm web`: the built React app, plus a small JSON API.

Stdlib `http.server`, like the login redirect in `core/spotify.py`: one local
user and a dozen endpoints earn no dependency.

**Who else can talk to it is the design question**, because the API starts
commands and reads files, and any website open in the browser can send requests
to 127.0.0.1. Four layers, each cheap:

  - Bound to 127.0.0.1 only, so nothing off this machine can connect.
  - A random token per launch, exchanged at `/auth` for an HttpOnly,
    SameSite=Strict cookie that every API call must carry. A website cannot
    read the token, and its requests do not carry the cookie.
  - The Host header must name this server. That stops DNS rebinding, where an
    attacker's hostname is re-pointed at 127.0.0.1 so that the browser treats
    the API as the attacker's own origin.
  - Cross-site requests (`Sec-Fetch-Site`) and state-changing requests from a
    foreign `Origin` are refused. SameSite counts every port on 127.0.0.1 as one
    site, so this is what keeps another local server's page from riding the
    cookie.

What it serves is narrow too: reports only from under the output root (or a
path a job said it wrote), audio only in `AUDIO_EXTS`, and directory listings —
names, never contents — for the path picker. It writes nothing itself; the only
writes are the ones the commands make, under their own read-only contracts.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import socket
import sys
import traceback
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from sdm import __version__
from sdm.core import paths
from sdm.core.track import AUDIO_EXTS
from sdm.web import DEFAULT_PORT, schema
from sdm.web.jobs import Busy, JobManager
from sdm.web.reports import TableReader, is_inside, list_reports, resolve

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

MAX_BODY = 1024 * 1024
CHUNK = 64 * 1024

#: Hardcoded rather than from `mimetypes`: on Windows that reads the registry,
#: where `.js` is often `text/plain` — and browsers refuse to run a module
#: script served as text.
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json",
}

_AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
    ".ogg": "audio/ogg",
}

_REPORT_TYPES = {
    ".json": "application/json; charset=utf-8",
    ".csv": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}

_CSP = (
    "default-src 'self'; img-src 'self' data:; media-src 'self'; "
    "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
)

_NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>sdm web</title>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto;line-height:1.5">
<h2>sdm web: the page has not been built yet</h2>
<p>The server is running, but the React app it serves is built separately, with
Node. From the repository root:</p>
<pre style="background:#8882;padding:1rem">cd frontend
npm install
npm run build</pre>
<p>then reload this page. The API works without it.</p></body>"""

_BAD_LINK = """<!doctype html><meta charset="utf-8"><title>sdm web</title>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto;line-height:1.5">
<h2>sdm web: that link is out of date</h2>
<p>Each launch of <code>sdm web</code> prints a new link. Open the one in its
terminal.</p></body>"""


class _HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class _App:
    """Everything a request handler needs, shared across threads."""

    def __init__(self, out_root: str, tmp_root: str, cwd: str):
        self.out_root = out_root
        self.tmp_root = tmp_root
        self.cwd = cwd
        self.token = secrets.token_urlsafe(24)
        self.jobs = JobManager(out_root, tmp_root, cwd)
        self.tables = TableReader()
        self.port = 0
        self.hosts: set[str] = set()
        self.origins: set[str] = set()
        self.cookie = "sdm_session"

    def bound(self, port: int) -> None:
        self.port = port
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{h}" for h in self.hosts}
        # Cookies ignore ports, so two servers (or the Vite dev server beside
        # this one) would overwrite each other's session under one name.
        self.cookie = f"sdm_session_{port}"


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second socket bind a port that is in use,
    # so a taken port would be shared silently instead of reported.
    allow_reuse_address = os.name != "nt"

    def __init__(self, address, app: _App):
        self.app = app
        super().__init__(address, _Handler)

    def server_bind(self) -> None:
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(port: Optional[int] = None, open_browser: bool = True) -> int:
    app = _App(
        out_root=os.path.abspath(paths.out_root()),
        tmp_root=os.path.abspath(paths.tmp_root()),
        cwd=os.getcwd(),
    )
    try:
        server = _bind(app, port)
    except OSError as exc:
        print(f"error: cannot listen on 127.0.0.1:{port} ({exc})", file=sys.stderr)
        return 2
    app.bound(server.server_address[1])

    url = f"http://127.0.0.1:{app.port}/auth?token={app.token}"
    print(f"sdm web on http://127.0.0.1:{app.port}")
    if port is None and app.port != DEFAULT_PORT:
        print(f"  (port {DEFAULT_PORT} was taken)")
    print(f"  reports: {app.out_root}")
    if not os.path.isfile(os.path.join(STATIC_DIR, "index.html")):
        print("  note: the page is not built yet - run `npm install` and "
              "`npm run build` in frontend/")
    print(f"open this link to use it (it changes every launch):\n  {url}")
    # Flushed: redirected to a file, stdout is block-buffered and the link —
    # the one thing needed to get in — would not appear until the server stops.
    print("Ctrl-C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopping")
    finally:
        app.jobs.shutdown()
        server.server_close()
    return 0


def _bind(app: _App, port: Optional[int]) -> _Server:
    if port is not None:
        return _Server(("127.0.0.1", port), app)
    try:
        return _Server(("127.0.0.1", DEFAULT_PORT), app)
    except OSError:
        return _Server(("127.0.0.1", 0), app)


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    server_version = "sdm-web"

    # --- dispatch ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def log_message(self, format, *args) -> None:  # noqa: A002 - quiet by default
        pass

    def _dispatch(self, method: str) -> None:
        url = urlsplit(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/auth" and method == "GET":
                return self._auth(query)
            if url.path.startswith("/api/"):
                self._check_trusted(method)
                return self._api(method, url.path, query)
            if method != "GET":
                raise _HttpError(405, "method not allowed")
            return self._static(url.path)
        except _HttpError as exc:
            self._send_json({"error": exc.message}, exc.status)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # the browser gave up on a response, routinely so for audio
        except Exception as exc:  # noqa: BLE001 - one bad request must not end the server
            traceback.print_exc()
            try:
                self._send_json({"error": f"internal error: {exc}"}, 500)
            except OSError:
                pass

    def _api(self, method: str, path: str, query: dict) -> None:
        app = self.server.app
        if path == "/api/session" and method == "GET":
            return self._send_json({
                "version": __version__,
                "out_root": app.out_root,
                "tmp_root": app.tmp_root,
                "cwd": app.cwd,
                "sep": os.sep,
                "spotify_client_id": bool(os.environ.get("SDM_SPOTIFY_CLIENT_ID")),
            })
        if path == "/api/commands" and method == "GET":
            return self._send_json(schema.commands())
        if path == "/api/jobs":
            if method == "GET":
                return self._send_json([j.summary() for j in app.jobs.all()])
            return self._start_job()
        match = re.fullmatch(r"/api/jobs/(\d+)(/cancel)?", path)
        if match:
            job = app.jobs.get(match.group(1))
            if job is None:
                raise _HttpError(404, f"no job {match.group(1)}")
            if match.group(2):
                if method != "POST":
                    raise _HttpError(405, "cancel is a POST")
                app.jobs.cancel(job)
            return self._send_json(job.detail(_int(query, "since", 0), app.out_root))
        if method != "GET":
            raise _HttpError(405, "method not allowed")
        if path == "/api/reports":
            return self._send_json({"root": app.out_root, "files": list_reports(app.out_root)})
        if path == "/api/reports/table":
            full = self._report_path(query)
            sort = query.get("sort")
            return self._send_json(app.tables.page(
                full,
                offset=_int(query, "offset", 0),
                limit=_int(query, "limit", 100),
                query=query.get("q", ""),
                sort=int(sort) if sort not in (None, "") else None,
                descending=query.get("desc") == "1",
            ))
        if path == "/api/reports/raw":
            full = self._report_path(query)
            ext = os.path.splitext(full)[1].lower()
            return self._send_file(full, _REPORT_TYPES.get(ext, "application/octet-stream"))
        if path == "/api/fs":
            return self._send_json(_listing(query.get("path", ""),
                                            files=query.get("files") == "1",
                                            accept=query.get("accept", "")))
        if path == "/api/audio":
            return self._audio(query.get("path", ""))
        raise _HttpError(404, "no such endpoint")

    # --- trust ---------------------------------------------------------------

    def _check_trusted(self, method: str) -> None:
        app = self.server.app
        if self.headers.get("Host") not in app.hosts:
            raise _HttpError(403, "unexpected Host header")
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            raise _HttpError(403, "cross-site request refused")
        if method != "GET":
            origin = self.headers.get("Origin")
            if origin is not None and origin not in app.origins:
                raise _HttpError(403, "foreign origin refused")
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if ctype != "application/json":
                raise _HttpError(415, "expected application/json")
        if not self._has_session():
            raise _HttpError(401, "not signed in: open the link `sdm web` printed in its terminal")

    def _has_session(self) -> bool:
        app = self.server.app
        try:
            morsel = SimpleCookie(self.headers.get("Cookie", "")).get(app.cookie)
        except Exception:  # noqa: BLE001 - a malformed cookie header is just no session
            return False
        return morsel is not None and hmac.compare_digest(
            morsel.value.encode("utf-8"), app.token.encode("utf-8"))

    def _auth(self, query: dict) -> None:
        app = self.server.app
        token = query.get("token", "")
        if self.headers.get("Host") not in app.hosts or not hmac.compare_digest(
                token.encode("utf-8"), app.token.encode("utf-8")):
            return self._send_html(_BAD_LINK, 403)
        self.send_response(303)
        self.send_header("Set-Cookie", f"{app.cookie}={app.token}; Path=/; HttpOnly; SameSite=Strict")
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    # --- endpoints -----------------------------------------------------------

    def _start_job(self) -> None:
        body = self._read_json()
        try:
            invocation = schema.build(body.get("command", ""), body.get("values", {}))
            job = self.server.app.jobs.start(invocation)
        except schema.InvalidRequest as exc:
            raise _HttpError(400, str(exc)) from None
        except Busy as exc:
            return self._send_json({"error": str(exc), "job": exc.job.id}, 409)
        self._send_json(job.detail(0, self.server.app.out_root), 201)

    def _report_path(self, query: dict) -> str:
        app = self.server.app
        try:
            return resolve(app.out_root, query.get("path", ""), app.jobs.output_paths())
        except PermissionError as exc:
            raise _HttpError(403, str(exc)) from None
        except FileNotFoundError as exc:
            raise _HttpError(404, str(exc)) from None

    def _audio(self, path: str) -> None:
        full = os.path.abspath(path) if path else ""
        ext = os.path.splitext(full)[1].lower()
        if ext not in AUDIO_EXTS:
            raise _HttpError(403, "only audio files can be played")
        if not os.path.isfile(full):
            raise _HttpError(404, f"no such file: {path}")
        self._send_file(full, _AUDIO_TYPES.get(ext, "application/octet-stream"), ranges=True)

    def _static(self, path: str) -> None:
        index = os.path.join(STATIC_DIR, "index.html")
        if not os.path.isfile(index):
            return self._send_html(_NOT_BUILT, 503)
        rel = path.lstrip("/")
        full = os.path.abspath(os.path.join(STATIC_DIR, rel)) if rel else index
        if not is_inside(STATIC_DIR, full) or not os.path.isfile(full):
            full = index  # client-side routes all resolve to the app
        ext = os.path.splitext(full)[1].lower()
        # Vite fingerprints everything under assets/, so it can be cached for
        # good; index.html names the current fingerprints and must not be.
        immutable = rel.startswith("assets/") and full != index
        self._send_file(full, _STATIC_TYPES.get(ext, "application/octet-stream"),
                        cache="public, max-age=31536000, immutable" if immutable else "no-cache")

    # --- responses -----------------------------------------------------------

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise _HttpError(400, "bad Content-Length") from None
        if length > MAX_BODY:
            raise _HttpError(413, "request body too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise _HttpError(400, "request body is not JSON") from None
        if not isinstance(body, dict):
            raise _HttpError(400, "request body must be a JSON object")
        return body

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", _CSP)

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, full: str, ctype: str, *, ranges: bool = False,
                   cache: str = "no-store") -> None:
        """Send a file, honouring a single byte range when `ranges` — which is
        what lets an <audio> element seek without downloading the whole track."""
        size = os.path.getsize(full)
        start, end, status = 0, size - 1, 200
        header = self.headers.get("Range") if ranges else None
        if header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
            if match and (match.group(1) or match.group(2)):
                if match.group(1):
                    start = int(match.group(1))
                    end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
                else:
                    start = max(size - int(match.group(2)), 0)
                status = 206
            if status != 206 or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1 if size else 0))
        self.send_header("Cache-Control", cache)
        if ranges:
            self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self._security_headers()
        self.end_headers()

        with open(full, "rb") as f:
            f.seek(start)
            remaining = end - start + 1 if size else 0
            while remaining > 0:
                chunk = f.read(min(CHUNK, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def _int(query: dict, name: str, default: int) -> int:
    try:
        return int(query.get(name, default))
    except (TypeError, ValueError):
        raise _HttpError(400, f"{name} must be an integer") from None


# --- the path picker -------------------------------------------------------

#: Windows' hidden and system attributes: `System Volume Information`,
#: `$RECYCLE.BIN` and friends. Nobody picks a music folder from those.
_HIDDEN = 0x2 | 0x4


def _listing(path: str, *, files: bool, accept: str) -> dict:
    """The directories (and optionally files) in `path`; with no path, the roots."""
    exts = tuple(e.strip().lower() for e in accept.split(",") if e.strip())
    if not path:
        return {"path": "", "parent": None, "entries": _roots()}

    if re.fullmatch(r"[A-Za-z]:", path):
        path += "\\"  # "C:" alone means C:'s current directory, not its root
    full = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(full):
        full = os.path.dirname(full)
    if not os.path.isdir(full):
        raise _HttpError(404, f"not a folder: {path}")

    entries = []
    try:
        with os.scandir(full) as it:
            for entry in it:
                try:
                    is_dir = entry.is_dir()
                    if entry.name.startswith(".") or _is_hidden(entry):
                        continue
                    if not is_dir and (not files or (exts and not entry.name.lower().endswith(exts))):
                        continue
                except OSError:
                    continue
                entries.append({"name": entry.name, "path": entry.path, "dir": is_dir})
    except PermissionError:
        raise _HttpError(403, f"no permission to list {full}") from None

    entries.sort(key=lambda e: (not e["dir"], e["name"].casefold()))
    parent = os.path.dirname(full)
    return {
        "path": full,
        # At a root, "up" goes to the list of drives (Windows) or nowhere.
        "parent": ("" if os.name == "nt" else None) if parent == full else parent,
        "entries": entries[:5000],
    }


def _is_hidden(entry: os.DirEntry) -> bool:
    attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attrs & _HIDDEN)


def _roots() -> list[dict]:
    if os.name != "nt":
        home = os.path.expanduser("~")
        return [{"name": "/", "path": "/", "dir": True},
                {"name": home, "path": home, "dir": True}]
    import ctypes
    import string

    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [
        {"name": f"{letter}:\\", "path": f"{letter}:\\", "dir": True}
        for i, letter in enumerate(string.ascii_uppercase)
        if mask & (1 << i)
    ]
