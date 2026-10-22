"""Read a playlist through Spotify's Web API, logged in as the user.

Shared by `playlist-diff` and `playlist-export`, which is why it lives in core.

**Only playlists the user owns or collaborates on.** Since Spotify's February
2026 Development Mode changes, `GET /playlists/{id}/items` answers 403 for any
other playlist, and the playlist object itself comes back without its `items`.
There is no app-only way around it: the client-credentials flow has no user, so
it owns nothing and reads no contents. A 403 is raised as `PlaylistNotAccessible`
so each caller can say what to do instead — the advice differs per command. The
same changes require the account that registered the app to have Premium.

Login is the Authorization Code flow with PKCE, which needs a client ID and no
client secret, so there is nothing secret to keep. The redirect lands on a
one-shot HTTP server on a loopback address — the only place Spotify accepts a
plain-http redirect URI (`localhost` is rejected by name; the IP literal is
required). The token is not saved: every run logs in again, which after the
first consent is a redirect the user barely sees. Saving it would need a
persistent per-user location, which this project has not settled (see `dig` in
CLAUDE.md), and `out/` and `tmp/` are each wrong for it.

The scopes are read-only, so the token cannot modify a playlist even by mistake.

**Two hooks, for the browser build** (`supplied_token`, `transport`). It runs
the commands in a browser tab, where neither half of the above works: there is
no socket to listen for the redirect on, and none for urllib to send through.
Its page logs in itself and supplies the token, and its worker sends requests
through XMLHttpRequest (`sdm.browser`). Everything between, from
`fetch_playlist` to the messages, stays this module's, so the commands cannot
tell which front end they run under.

Stdlib only (`urllib`, `http.server`): one GET per 50 tracks does not justify a
dependency.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

from sdm.core.playlist import Playlist, PlaylistTrack

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"

CLIENT_ID_ENV = "SDM_SPOTIFY_CLIENT_ID"
REDIRECT_URI_ENV = "SDM_SPOTIFY_REDIRECT_URI"
#: Must be registered, character for character, on the app in Spotify's
#: dashboard. Not 8888: Jupyter's default, and a busy port fails the login.
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8765/callback"

SCOPES = "playlist-read-private playlist-read-collaborative"
LOGIN_TIMEOUT = 180
PAGE_SIZE = 50  # the endpoint's maximum
MAX_ATTEMPTS = 4

_LOOPBACK_HOSTS = ("127.0.0.1", "::1")


class SpotifyError(RuntimeError):
    """A Spotify step failed. The message is written for the user, not for a traceback."""


class PlaylistNotAccessible(SpotifyError):
    """Spotify will not list this playlist's tracks for this user (403): it is someone else's."""

    def __init__(self, message: str, name: str, owner: str):
        super().__init__(message)
        self.name = name
        self.owner = owner


class _ApiError(SpotifyError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Spotify answered {status}: {message}")
        self.status = status
        self.message = message


def resolve_client_id(explicit: Optional[str]) -> Optional[str]:
    """The explicitly passed client ID if any, else `$SDM_SPOTIFY_CLIENT_ID`, else None."""
    return explicit or os.environ.get(CLIENT_ID_ENV) or None


def _urlopen(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


#: An access token a front end obtained itself. When set, `login` returns it
#: instead of logging in. Set and cleared around each run by `sdm.browser`.
supplied_token: Optional[str] = None

#: Sends a request and returns the response body, failing as `urlopen` does:
#: `HTTPError` for an error status, `URLError` for no answer. `sdm.browser`
#: replaces it; nothing else should.
transport: Callable[[urllib.request.Request], bytes] = _urlopen


# --- login ---------------------------------------------------------------


class _IPv6HTTPServer(HTTPServer):
    address_family = socket.AF_INET6


class _CallbackServer:
    """Listens on the loopback redirect URI until the browser delivers one callback."""

    def __init__(self, host: str, port: int, path: str):
        result: dict[str, str] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server's naming
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != path:
                    # Browsers also ask for /favicon.ico; that is not the callback.
                    self.send_error(404)
                    return
                result.update({k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()})
                ok = "code" in result
                body = (
                    "<h3>sdm: logged in to Spotify.</h3><p>You can close this tab.</p>"
                    if ok else
                    "<h3>sdm: Spotify login did not complete.</h3><p>See the terminal.</p>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # noqa: A002 - silence per-request logging
                pass

        server_cls = _IPv6HTTPServer if ":" in host else HTTPServer
        try:
            self._server = server_cls((host, port), Handler)
        except OSError as exc:
            raise SpotifyError(
                f"cannot listen on {host}:{port} for the login redirect ({exc}). "
                f"Free that port, or register another loopback redirect URI on "
                f"your Spotify app and set {REDIRECT_URI_ENV} to it."
            ) from None
        self._server.timeout = 0.5
        self._result = result
        self.port: int = self._server.server_address[1]

    def wait(self, timeout: float) -> Optional[dict[str, str]]:
        deadline = time.monotonic() + timeout
        while not self._result and time.monotonic() < deadline:
            self._server.handle_request()
        return dict(self._result) or None

    def close(self) -> None:
        self._server.server_close()


def _pkce_pair() -> tuple[str, str]:
    """Return `(verifier, challenge)`. 86 URL-safe characters, inside the 43-128 Spotify allows."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def login(
    client_id: str,
    *,
    redirect_uri: Optional[str] = None,
    open_browser: bool = True,
    timeout: float = LOGIN_TIMEOUT,
    log: Callable[[str], None] = print,
) -> str:
    """Run the PKCE login in the user's browser and return an access token.

    With `supplied_token` set, return that: the front end has logged in already.
    """
    if supplied_token is not None:
        return supplied_token
    redirect_uri = redirect_uri or os.environ.get(REDIRECT_URI_ENV) or DEFAULT_REDIRECT_URI
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK_HOSTS:
        raise SpotifyError(
            f"redirect URI must be http:// on 127.0.0.1 or [::1] so sdm can receive "
            f"the login itself; got {redirect_uri}"
        )
    path = parsed.path or "/"

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    server = _CallbackServer(parsed.hostname, parsed.port or 0, path)
    try:
        if not parsed.port:
            # Registered without a port: Spotify lets a loopback redirect take
            # whatever port the OS handed out, so add it to the request.
            host = "[::1]" if parsed.hostname == "::1" else parsed.hostname
            redirect_uri = f"http://{host}:{server.port}{path}"

        url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        })
        log("log in to Spotify in the browser to continue. If no browser opens, visit:")
        log(f"  {url}")
        if open_browser:
            webbrowser.open(url)
        params = server.wait(timeout)
    finally:
        server.close()

    if params is None:
        raise SpotifyError(f"no Spotify login within {int(timeout)}s")
    if params.get("state") != state:
        raise SpotifyError("the login response did not match this run; try again")
    if "error" in params:
        hint = ""
        if params["error"] == "access_denied":
            hint = " (cancelled in the browser)"
        raise SpotifyError(f"Spotify refused the login: {params['error']}{hint}")
    if "code" not in params:
        raise SpotifyError("the login redirect carried no authorization code")

    token = _request(urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": params["code"],
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        }).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    ))
    return token["access_token"]


# --- reading -------------------------------------------------------------


def _error_message(exc: urllib.error.HTTPError) -> str:
    """Spotify's own explanation from an error body: `{"error": {"message"}}` from the
    API, `{"error", "error_description"}` from the accounts service."""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (ValueError, OSError):
        return exc.reason or "no detail"
    error = payload.get("error")
    if isinstance(error, dict):
        return error.get("message") or str(error)
    return payload.get("error_description") or str(error or payload)


def _request(request: urllib.request.Request) -> dict:
    """Send `request` and decode the JSON reply, waiting out rate limits."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return json.loads(transport(request).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < MAX_ATTEMPTS - 1:
                try:
                    delay = int(exc.headers.get("Retry-After", "1"))
                except ValueError:
                    delay = 1
                time.sleep(min(max(delay, 1), 30))
                continue
            raise _ApiError(exc.code, _error_message(exc)) from None
        except urllib.error.URLError as exc:
            raise SpotifyError(f"could not reach Spotify: {exc.reason}") from None
    raise SpotifyError("Spotify kept rate-limiting the request; try again in a minute")


def _get(url: str, token: str) -> dict:
    return _request(urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}))


def _names(objects) -> tuple[str, ...]:
    return tuple(o["name"] for o in objects or () if o.get("name"))


def track_from_entry(entry: dict) -> Optional[PlaylistTrack]:
    """One playlist entry as a `PlaylistTrack`, or None if it is not a comparable track.

    Reads `item`, falling back to `track`: February 2026 renamed the field and
    the reference still lists both, with `track` deprecated.
    """
    obj = entry.get("item") or entry.get("track")
    if not obj or obj.get("type", "track") != "track" or not obj.get("name"):
        return None
    album = obj.get("album") or {}
    return PlaylistTrack(
        title=obj["name"],
        artists=_names(obj.get("artists")),
        album=album.get("name") or "",
        duration_ms=obj.get("duration_ms"),
        isrc=(obj.get("external_ids") or {}).get("isrc") or "",
        uri=obj.get("uri") or "",
        is_local=bool(entry.get("is_local") or obj.get("is_local")),
        album_artists=_names(album.get("artists")),
        release_date=album.get("release_date") or "",
        disc_number=obj.get("disc_number"),
        track_number=obj.get("track_number"),
        explicit=obj.get("explicit"),
        added_at=entry.get("added_at") or "",
        added_by=(entry.get("added_by") or {}).get("id") or "",
    )


def fetch_playlist(playlist_id: str, token: str, *, log: Callable[[str], None] = print) -> Playlist:
    """Read a playlist's name, owner and every track.

    Raises `PlaylistNotAccessible` for someone else's playlist, `SpotifyError`
    for everything else that goes wrong.
    """
    meta_url = f"{API_URL}/playlists/{playlist_id}?" + urllib.parse.urlencode(
        {"fields": "name,owner(id,display_name)"}
    )
    try:
        meta = _get(meta_url, token)
    except _ApiError as exc:
        if exc.status == 404:
            raise SpotifyError(
                f"playlist {playlist_id} not found. Check the link; someone else's "
                "private playlist also looks like this."
            ) from None
        raise

    owner_obj = meta.get("owner") or {}
    playlist = Playlist(
        name=meta.get("name") or playlist_id,
        owner=owner_obj.get("display_name") or owner_obj.get("id") or "",
    )

    url: Optional[str] = f"{API_URL}/playlists/{playlist_id}/items?" + urllib.parse.urlencode(
        {"limit": PAGE_SIZE, "additional_types": "track"}
    )
    while url:
        try:
            page = _get(url, token)
        except _ApiError as exc:
            if exc.status == 403:
                raise PlaylistNotAccessible(
                    f"Spotify will not list the tracks of '{playlist.name}' "
                    f"(owner: {playlist.owner or 'unknown'}): since February 2026 "
                    "the API only returns playlists you own or collaborate on. "
                    f"(Spotify said: {exc.message})",
                    playlist.name,
                    playlist.owner,
                ) from None
            raise
        for entry in page.get("items") or ():
            track = track_from_entry(entry)
            if track is None:
                playlist.skipped += 1
            else:
                playlist.tracks.append(track)
        url = page.get("next")
        if url:
            log(f"read {len(playlist.tracks) + playlist.skipped} of {page.get('total', '?')} playlist entries")
    return playlist
