"""`sdm` in a browser tab — the third front end, beside `cli.py` and `sdm web`.

The browser build (`build_browser.py`, deployed to sdm.eigenomar.com) is static
files only. Python runs in the visitor's browser through Pyodide, in a Web
Worker (`frontend/src/browser/worker.ts`), and this module is that worker's
Python half: the forms, the runs and the reports, behind one entry point,
`call`. The visitor picks a folder, the worker mounts its files read-only, and
they never leave the tab — the page's Content-Security-Policy forbids connecting
anywhere but its own origin and, to read a playlist, Spotify's two hosts.

**Not a feature, and imports none (rule 1)** — it drives commands the way
`sdm.web` does: the argparse tree via `web/schema.py`, the reports via
`web/reports.py`. What differs is how a command runs. `sdm web` starts a
subprocess per run, for three reasons `web/jobs.py` gives; a tab has no
processes, and each reason is answered another way here:

  - stdout: one run at a time in the whole tab (Pyodide is single-threaded), so
    no two runs share it. The worker forwards each line as it is printed.
  - `core.paths` roots: set once at boot to `/out` and `/tmp` and never changed.
  - cancelling: the page writes SIGINT into Pyodide's interrupt buffer, shared
    memory the worker reads while Python runs, and the command stops on a
    KeyboardInterrupt as it would on Ctrl-C, `finally` blocks and all. The
    worker then drops whatever the run wrote (`worker.ts`). That needs
    cross-origin isolation (`_headers`); a page without it, or a command that
    does not stop in time, gets the old cancel instead: the page terminates the
    worker and starts another.

**What runs here.** `ONLINE_COMMANDS`, and the reason each other command does
not is a missing piece of the machine, not of the browser build: `duplicates`
and `rekordbox` fingerprint through the `fpcalc` binary, `quality` through
ffmpeg. Their code is not removed from the wheel, only left off the forms;
`prepare` refuses them by name.

**Spotify** (`playlist-export`, and `playlist-diff` given a link) logs in from
the page, not from here. The CLI's login waits on a loopback server for
Spotify's redirect, and a tab cannot listen on a port, so the page sends the
whole tab to Spotify and back (`frontend/src/browser/spotify.ts`) and hands
each run its token. `core.spotify`'s two hooks do the rest: `supplied_token`
answers `login` for the run (`_spotify_login`), and `transport` sends requests
through XMLHttpRequest (`_xhr`), since Pyodide's urllib has no sockets either.
`fetch_playlist`, its errors and its messages are the CLI's own.
"""
from __future__ import annotations

import contextlib
import email.message
import http.client
import importlib.util
import io
import json
import os
import signal
import sys
import traceback
import types
import urllib.error
import urllib.request
from typing import Any, Callable, Iterator, Optional

from sdm.web import reports, schema

#: The commands offered in the browser. See the module docstring for the rest.
ONLINE_COMMANDS = ("catalog", "analyze", "playlist-diff", "playlist-export")

#: Fields that mean nothing in a tab. Output locations: every report goes to
#: `OUT_ROOT`, the only place the page lists. The Spotify client ID and the
#: login browser: the page logs in itself, from one box above both playlist
#: commands' forms, and hands the run its login (see `run`).
HIDDEN_FIELDS = frozenset({"output_dir", "output_csv", "client_id", "no_browser"})

#: playlist-diff's positional: the page gives the box a CSV picker, and a link
#: can be pasted into the same box.
PLAYLIST_HELP = ("A Spotify playlist link - log in to Spotify above first - or "
                 "a CSV export of any playlist (Exportify, TuneMyMusic and "
                 "similar tools), which needs no login.")

OUT_ROOT = "/out"
TMP_ROOT = "/tmp"

#: Where the worker mounts what the visitor picks. Read by the page too.
MUSIC_ROOT = "/music"
PLAYLIST_ROOT = "/playlist"

#: Every path a run reported writing, for `reports.resolve`'s allow-list.
_written: set[str] = set()
_tables = reports.TableReader()

#: Whether a command is running, and whether a cancel has interrupted it. See `_on_cancel`.
_running = False
_interrupted = False


def call(name: str, args_json: str) -> str:
    """The worker's one entry point: `name(**args)`, answered as JSON.

    `{"ok": true, "data": ...}`, or `{"ok": false, "status": N, "error": "..."}`
    with the status `sdm web`'s server would have sent, so the page's
    `ApiError` handling is the same for both builds.
    """
    handler = _API.get(name)
    if handler is None:
        return _error(404, f"no such call: {name}")
    try:
        data = handler(**json.loads(args_json or "{}"))
        return json.dumps({"ok": True, "data": data}, ensure_ascii=False)
    except schema.InvalidRequest as exc:
        return _error(400, str(exc))
    except PermissionError as exc:
        return _error(403, str(exc))
    except FileNotFoundError as exc:
        return _error(404, str(exc))
    except Exception as exc:  # noqa: BLE001 - reported to the page, not swallowed
        traceback.print_exc()
        return _error(500, f"internal error: {exc}")


def boot() -> dict:
    """Ready the interpreter: shim pyrekordbox, set the roots, import the CLI."""
    _shim_pyrekordbox()
    from sdm import __version__, cli  # noqa: F401 - imports every add_parser
    from sdm.core import paths, spotify
    from sdm.core.anlz import USBANLZ_SUBDIR
    from sdm.core.track import AUDIO_EXTS

    paths.configure(OUT_ROOT, TMP_ROOT)
    spotify.transport = _xhr
    for root in (OUT_ROOT, TMP_ROOT, MUSIC_ROOT, PLAYLIST_ROOT):
        os.makedirs(root, exist_ok=True)
    signal.signal(signal.SIGINT, _on_cancel)
    return {
        "version": __version__,
        "out_root": OUT_ROOT,
        "music_root": MUSIC_ROOT,
        "playlist_root": PLAYLIST_ROOT,
        # What a picked folder is filtered down to before it is mounted. From
        # core, so the page's filter cannot drift from what the commands read.
        "mount": {
            "audio_exts": list(AUDIO_EXTS),
            "analysis_dir": USBANLZ_SUBDIR.replace(os.sep, "/").rsplit("/", 1)[-1],
        },
        "commands": commands(),
        # Named on the page, so it can say what needs sdm on a real machine.
        "offline": [c["name"] for c in schema.commands() if c["name"] not in ONLINE_COMMANDS],
        # What the page's login asks Spotify for: the CLI's read-only scopes, not a copy.
        "spotify_scopes": spotify.SCOPES,
    }


def commands() -> list[dict]:
    """`schema.commands()`, cut down to what runs in a tab."""
    online = []
    for spec in schema.commands():
        if spec["name"] not in ONLINE_COMMANDS:
            continue
        fields = []
        for field in spec["fields"]:
            if field["dest"] in HIDDEN_FIELDS:
                continue
            if field["dest"] == "playlist":
                # schema gives every playlist box a CSV picker; only playlist-diff reads a CSV.
                field = ({**field, "help": PLAYLIST_HELP} if spec["name"] == "playlist-diff"
                         else {**field, "path": None, "accept": []})
            fields.append(field)
        online.append({**spec, "fields": fields})
    return online


def prepare(command: str, values: Any, spotify: bool = False) -> dict:
    """Validate a form for `command` and return the argv to run, as `sdm web` would.

    `spotify` is whether the page has a Spotify login to hand the run.
    """
    if command not in ONLINE_COMMANDS:
        raise schema.InvalidRequest(
            f"sdm {command} does not run in a browser - use sdm on your own machine")
    if not isinstance(values, dict):
        raise schema.InvalidRequest("values must be an object")
    spec = next(c for c in commands() if c["name"] == command)
    visible = {field["dest"]: field for field in spec["fields"]}
    values = {dest: value for dest, value in values.items() if dest in visible}
    _check_paths(visible, values, spotify)
    invocation = schema.build(command, values)
    return {"argv": invocation.argv, "display": invocation.display}


def run(argv: list[str], spotify: Optional[dict] = None) -> int:
    """Run one command in this interpreter; its exit code. Output goes to the worker.

    `spotify` is the page's login, `{"client_id", "token"}`, given to every run
    of a command that can read a playlist; see `_spotify_login`.
    """
    from sdm import cli
    from sdm.web.child import CANCELLED_EXIT

    global _running, _interrupted
    _interrupted = False
    try:
        try:
            _running = True
            with _spotify_login(spotify):
                code = cli.main(list(argv))
        finally:
            _running = False
    except KeyboardInterrupt:  # the page's Cancel; see `_on_cancel`
        print("cancelled", file=sys.stderr)
        code = CANCELLED_EXIT
    except SystemExit as exc:  # argparse, or a handler that exits
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except Exception:  # noqa: BLE001 - a traceback in the log, like a crashed child
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    return int(code or 0)


def outputs(command: str, started: float, wrote: list[str]) -> list[dict]:
    """What a run wrote: its `wrote <path>` lines, plus anything new in out/<command>/.

    The same rule `web/jobs.py` applies, for the same reason — `catalog` prints
    its results rather than "wrote". `started` is the run's start, epoch seconds.
    """
    found: list[str] = []
    for path in wrote:
        path = os.path.abspath(path)
        if path not in found:
            found.append(path)
    for root, _, names in os.walk(os.path.join(OUT_ROOT, command)):
        for name in sorted(names):
            path = os.path.join(root, name)
            if path not in found and os.path.getmtime(path) >= started - 2:
                found.append(path)
    _written.update(found)
    return [
        {
            "path": path,
            "rel": os.path.relpath(path, OUT_ROOT) if reports.is_inside(OUT_ROOT, path) else None,
            "exists": os.path.isfile(path),
        }
        for path in found
    ]


def table(path: str, offset: int = 0, limit: int = 100, q: str = "",
          sort: Optional[int] = None, desc: bool = False) -> dict:
    """A page of a report CSV — `reports.TableReader`, as `/api/reports/table`."""
    full = reports.resolve(OUT_ROOT, path, _written)
    return _tables.page(full, offset=offset, limit=limit, query=q, sort=sort, descending=desc)


_API: dict[str, Callable[..., Any]] = {
    "boot": boot,
    "commands": commands,
    "prepare": prepare,
    "run": run,
    "outputs": outputs,
    "table": table,
}


# --- internals ---------------------------------------------------------------


def _check_paths(fields: dict[str, dict], values: dict, logged_in: bool) -> None:
    """Refuse a path the tab cannot read, with a message that says what to do.

    A picked folder is mounted until the tab reloads, but the form remembers
    its path across reloads — so a stale path is the common case, not an edge.
    A playlist link is refused here without a login, rather than by the
    command, whose message would say to set an environment variable.
    """
    from sdm.core.playlist import parse_playlist_ref

    for dest, field in fields.items():
        value = values.get(dest)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if dest == "playlist":
            reads_csv = field["path"] == "file"
            if reads_csv and os.path.isfile(value):
                continue
            if parse_playlist_ref(value) is None:
                raise schema.InvalidRequest(
                    f"{field['label']}: "
                    + ("choose a CSV export with the button, or paste a Spotify "
                       "playlist link. A file picked before a reload has to be "
                       "picked again." if reads_csv else
                       "paste a Spotify playlist link (open.spotify.com/playlist/...)."))
            if not logged_in:
                raise schema.InvalidRequest(
                    f"{field['label']}: a playlist link is read through your "
                    "Spotify account - log in to Spotify above first"
                    + (", or choose a CSV export, which needs no login." if reads_csv else "."))
        elif field["path"] == "dir" and not os.path.isdir(value):
            raise schema.InvalidRequest(
                f"{field['label']}: {value} is not a folder picked in this tab. "
                "Choose it again - picks do not survive a reload.")


@contextlib.contextmanager
def _spotify_login(login: Optional[dict]) -> Iterator[None]:
    """The page's Spotify login, for one run.

    `core.spotify.login` answers with the page's token instead of starting its
    loopback server, and the client ID goes where the commands look for one,
    the environment, since the form has no box for it. Both are taken back
    after, so no later run can use a login it was not handed.
    """
    from sdm.core import spotify

    if not login:
        yield
        return
    before = os.environ.get(spotify.CLIENT_ID_ENV)
    os.environ[spotify.CLIENT_ID_ENV] = login["client_id"]
    spotify.supplied_token = login["token"]
    try:
        yield
    finally:
        spotify.supplied_token = None
        if before is None:
            os.environ.pop(spotify.CLIENT_ID_ENV, None)
        else:
            os.environ[spotify.CLIENT_ID_ENV] = before


def _xhr(request: urllib.request.Request) -> bytes:
    """`core.spotify.transport` in a tab: a synchronous XMLHttpRequest.

    Pyodide's urllib has no sockets to send through. A synchronous request is
    allowed in a worker and blocks only the worker, as `urlopen` blocks a
    process. It fails the way `urlopen` does, which is what `core.spotify`
    handles: `HTTPError` for an error status, `URLError` for no answer at all,
    which is also what a request the page's CSP blocks looks like.
    """
    from pyodide.http import pyxhr

    send = pyxhr.post if request.get_method() == "POST" else pyxhr.get
    body = request.data.decode("utf-8") if request.data else None
    try:
        response = send(request.full_url, headers=dict(request.header_items()), data=body)
    except pyxhr.XHRError as exc:
        raise urllib.error.URLError(str(exc)) from None
    if response.status_code >= 400:
        headers = email.message.Message()
        for name, value in response.headers.items():
            headers[name] = value
        raise urllib.error.HTTPError(
            request.full_url, response.status_code,
            http.client.responses.get(response.status_code, ""), headers,
            io.BytesIO(response.content))
    return response.content


def _on_cancel(signum: int, frame: Any) -> None:
    """SIGINT, which only the page's Cancel sends: interrupt the command, once.

    Only inside `run`'s `try`, where the KeyboardInterrupt is caught. The page
    cannot know exactly when a command ends, so a cancel may arrive after it
    has, while Python answers some other call — one that must not fail for it.
    And only once, because the page signals again until the run stops (Pyodide
    can lose a signal written as it clears the buffer), and a second
    KeyboardInterrupt would cut short the `finally` blocks the first one runs.
    """
    global _interrupted
    if _running and not _interrupted:
        _interrupted = True
        raise KeyboardInterrupt


def _shim_pyrekordbox() -> None:
    """Let `import pyrekordbox.anlz` skip `pyrekordbox/__init__.py`.

    That `__init__` re-exports the whole package, database layer included, so
    importing it pulls in sqlalchemy and sqlcipher3 — a C extension with no
    Pyodide build. `core.anlz` needs only `pyrekordbox.anlz`, which imports
    nothing from its parent (construct and numpy only). A bare module carrying
    the package's `__path__` stands in for the parent: the submodule is found
    and the parent's `__init__` never runs. Browser-only; a normal install has
    the dependencies and imports pyrekordbox the ordinary way.
    """
    if "pyrekordbox" in sys.modules:
        return
    spec = importlib.util.find_spec("pyrekordbox")  # finds the package, runs nothing
    if spec is None or spec.submodule_search_locations is None:
        return  # not installed: `analyze` reports it the way it always does
    package = types.ModuleType("pyrekordbox")
    package.__path__ = list(spec.submodule_search_locations)
    sys.modules["pyrekordbox"] = package


def _error(status: int, message: str) -> str:
    return json.dumps({"ok": False, "status": status, "error": message}, ensure_ascii=False)
