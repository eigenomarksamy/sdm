// The browser build's Spotify login. The CLI and `sdm web` log in from the
// command (src/sdm/core/spotify.py): a loopback server waits for Spotify to
// send the browser back. A tab cannot listen on a port, so here the page goes
// itself: the whole tab is sent to Spotify's login page, which sends it back to
// the site's root with a code, traded for a token as this module loads. The
// rest is the CLI's flow: authorization code with PKCE, the visitor's own
// client ID, no secret, and core/spotify.py's read-only scopes (from boot).
//
// Each run of a playlist command is handed the access token (browser/api.ts),
// and core.spotify uses it instead of logging in. Python never sees the
// refresh token.
//
// Unlike the CLI, which keeps nothing, the login is kept in localStorage. A
// login here is a reload, which costs the tab its picked folders and reports,
// so asking once per browser rather than once per visit is what makes it
// bearable; the refresh token renews it silently. Log out forgets it, and the
// read-only scopes bound what anyone holding it could do.
import type { SpotifyState } from "../api";
import { store } from "../format";

const AUTHORIZE_URL = "https://accounts.spotify.com/authorize";
const TOKEN_URL = "https://accounts.spotify.com/api/token";
const ME_URL = "https://api.spotify.com/v1/me";

const CLIENT_ID_KEY = "sdm.spotify.clientId";
const LOGIN_KEY = "sdm.spotify.login";
/** The login in flight: what the trip to Spotify and back must not lose. */
const PENDING_KEY = "sdm.spotify.pending";

/** A token this close to expiring is renewed before a run is handed it. */
const RENEW_MS = 5 * 60_000;

/** Where Spotify sends the tab back: the site's root, as the setup guide says to register it. */
const redirectUri = new URL(import.meta.env.BASE_URL, window.location.origin).href;

interface Login {
  clientId: string;
  accessToken: string;
  refreshToken: string | null;
  /** Epoch milliseconds. */
  expiresAt: number;
  user: string | null;
}

interface Pending {
  clientId: string;
  verifier: string;
  state: string;
  /** The route the login started from, to come back to. */
  hash: string;
}

interface TokenReply {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
}

/** Spotify answered no, as opposed to not answering. The message is Spotify's. */
class Refused extends Error {}

const saved = () => store.get<Login | null>(LOGIN_KEY, null);

let state: SpotifyState = {
  clientId: store.get(CLIENT_ID_KEY, ""),
  loggedIn: saved() !== null,
  user: saved()?.user ?? null,
  finishing: false,
  error: null,
};
const listeners = new Set<(state: SpotifyState) => void>();

function update(patch: Partial<SpotifyState>): void {
  state = { ...state, ...patch };
  for (const listener of listeners) listener(state);
}

function forget(error: string | null = null): void {
  store.remove(LOGIN_KEY);
  update({ loggedIn: false, user: null, error });
}

function base64url(bytes: Uint8Array): string {
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const random = (bytes: number) => base64url(crypto.getRandomValues(new Uint8Array(bytes)));

/**
 * Leave for Spotify's login page. The PKCE pair as core/spotify.py makes it:
 * 64 random bytes give an 86-character verifier, inside the 43-128 allowed.
 */
async function login(scopes: string): Promise<void> {
  const clientId = state.clientId;
  const verifier = random(64);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  const pending: Pending = { clientId, verifier, state: random(16), hash: window.location.hash };
  store.set(PENDING_KEY, pending);
  // Read back: a browser that stores nothing would bring the visitor back to a
  // login that cannot finish, after the reload has already cost them the tab.
  if (store.get<Pending | null>(PENDING_KEY, null)?.verifier !== verifier) {
    throw new Error(
      "This browser is not letting the page store anything (a private window, or blocked site data), and the login " +
        "has to remember where it was across the trip to Spotify.",
    );
  }
  const params = new URLSearchParams({
    client_id: clientId,
    response_type: "code",
    redirect_uri: redirectUri,
    scope: scopes,
    state: pending.state,
    code_challenge_method: "S256",
    code_challenge: base64url(new Uint8Array(digest)),
  });
  window.location.assign(`${AUTHORIZE_URL}?${params}`);
}

/**
 * Back from Spotify, with `code` (or `error`) and `state` in the query. Runs as
 * the module loads, before anything renders or reads the address. The query
 * comes off at once, so a reload cannot send a used code again.
 */
function comeBack(): void {
  const params = new URLSearchParams(window.location.search);
  if (!params.has("state")) return;
  const pending = store.get<Pending | null>(PENDING_KEY, null);
  store.remove(PENDING_KEY);
  window.history.replaceState(null, "", window.location.pathname + (pending?.hash ?? ""));

  if (!pending || params.get("state") !== pending.state) {
    state.error = "That Spotify login was not started from this page, or has been used already. Log in again.";
    return;
  }
  const error = params.get("error");
  const code = params.get("code");
  if (error || !code) {
    state.error =
      error === "access_denied"
        ? "The Spotify login was cancelled on Spotify's page."
        : `Spotify refused the login: ${error ?? "no code came back"}.`;
    return;
  }
  state.finishing = true;
  void finish(pending, code);
}

async function finish(pending: Pending, code: string): Promise<void> {
  try {
    const reply = await requestToken({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
      client_id: pending.clientId,
      code_verifier: pending.verifier,
    });
    const user = await whoIs(reply.access_token);
    const login: Login = {
      clientId: pending.clientId,
      accessToken: reply.access_token,
      refreshToken: reply.refresh_token ?? null,
      expiresAt: Date.now() + reply.expires_in * 1000,
      user,
    };
    store.set(LOGIN_KEY, login);
    update({ loggedIn: true, user, finishing: false, error: null });
  } catch (e) {
    state.finishing = false;
    forget(e instanceof Refused ? `Spotify refused the login: ${e.message}.` : e instanceof Error ? e.message : String(e));
  }
}

async function requestToken(body: Record<string, string>): Promise<TokenReply> {
  let response: Response;
  try {
    response = await fetch(TOKEN_URL, { method: "POST", body: new URLSearchParams(body) });
  } catch {
    throw new Error("Could not reach Spotify. Check the connection and try again.");
  }
  const data = (await response.json().catch(() => ({}))) as Partial<TokenReply> & {
    error?: string;
    error_description?: string;
  };
  if (!response.ok || !data.access_token) {
    throw new Refused(data.error_description || data.error || `${response.status} ${response.statusText}`);
  }
  return data as TokenReply;
}

/**
 * The account's name — and the one check that a login is any use. Spotify lets
 * anyone log in to a development-mode app, then answers 403 to every request
 * from an account not on the app's user list, so without this a login that
 * looked fine would fail only at the first run.
 */
async function whoIs(accessToken: string): Promise<string | null> {
  let response: Response;
  try {
    response = await fetch(ME_URL, { headers: { Authorization: `Bearer ${accessToken}` } });
  } catch {
    return null; // the login itself worked; a run will say if Spotify cannot be reached
  }
  const data = (await response.json().catch(() => null)) as {
    display_name?: string;
    id?: string;
    error?: { message?: string };
  } | null;
  if (response.status === 403) {
    const said = data?.error?.message ? ` (Spotify said: ${data.error.message})` : "";
    throw new Error(
      `Spotify logged you in, but refuses to answer for this account${said}. The account has to be the app's owner ` +
        "or be on its User Management list, and the owner needs Premium. See the setup guide.",
    );
  }
  return (response.ok && (data?.display_name || data?.id)) || null;
}

/** The login a run is handed, renewed first if it is about to run out; null without one. */
async function forRun(): Promise<{ client_id: string; token: string } | null> {
  let login = saved();
  if (!login) return null;
  if (login.expiresAt - Date.now() < RENEW_MS) {
    if (!login.refreshToken) {
      if (login.expiresAt > Date.now()) return { client_id: login.clientId, token: login.accessToken };
      forget("The Spotify login has run out. Log in again.");
      return null;
    }
    try {
      const reply = await requestToken({
        grant_type: "refresh_token",
        refresh_token: login.refreshToken,
        client_id: login.clientId,
      });
      // Spotify may send a new refresh token or not; without one, the old one stands.
      login = {
        ...login,
        accessToken: reply.access_token,
        refreshToken: reply.refresh_token ?? login.refreshToken,
        expiresAt: Date.now() + reply.expires_in * 1000,
      };
      store.set(LOGIN_KEY, login);
    } catch (e) {
      if (e instanceof Refused) {
        forget(`The Spotify login could not be renewed (Spotify said: ${e.message}). Log in again.`);
        return null;
      }
      // No answer at all: hand over the old token, and the run says Spotify cannot be reached.
    }
  }
  return { client_id: login.clientId, token: login.accessToken };
}

// Another tab logging in or out changes this one too: they share the storage.
window.addEventListener("storage", (event) => {
  if (event.key !== LOGIN_KEY) return;
  const login = saved();
  update({ loggedIn: login !== null, user: login?.user ?? null, error: null });
});

comeBack();

export const spotify = {
  redirectUri,
  subscribe(listener: (state: SpotifyState) => void): () => void {
    listeners.add(listener);
    listener(state);
    return () => void listeners.delete(listener);
  },
  setClientId(id: string): void {
    const clientId = id.trim();
    store.set(CLIENT_ID_KEY, clientId);
    update({ clientId, error: null });
  },
  login,
  logout: () => forget(),
  forRun,
};
