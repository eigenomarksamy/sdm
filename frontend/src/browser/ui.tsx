// What only the browser build shows: Python starting, a folder being picked,
// and the Spotify login. Shared components render these when `browser`
// (src/api.ts) is set.
import { useEffect, useState, type ReactNode } from "react";
import type { BootState, BrowserHooks, PickProgress, SpotifyState } from "../api";
import { bytes } from "../format";
import { href } from "../router";

/** The promise the page makes, and why it can keep it. Shown before anything is picked. */
export function PrivacyNote() {
  return (
    <p className="muted">
      Everything runs in this tab. Your files are read where they are and never leave the browser: the page is only
      allowed to connect to this site, which serves static files and has nothing to receive them with, and to Spotify,
      to read a playlist you log in for. Reports live in this tab and are gone when you reload or close it.
    </p>
  );
}

/** What a Spotify client ID looks like. Checked softly, so a typo shows before the trip to Spotify. */
const CLIENT_ID = /^[0-9a-f]{32}$/i;

/**
 * The Spotify login, above the form of a command that reads a playlist
 * (browser/spotify.ts). The client ID is the visitor's own: Spotify allows a
 * development-mode app five users and grants more only to businesses, so an
 * app built into the site would serve five people. The guide says how.
 */
export function SpotifyLogin({ browser }: { browser: BrowserHooks }) {
  const [state, setState] = useState<SpotifyState | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => browser.spotify.subscribe(setState), [browser]);
  if (!state) return null;

  const guide = (section: string, text: string) => <a href={href("/spotify", { section })}>{text}</a>;
  // Spotify refuses localhost as a redirect address; the IP literal is the same page.
  const onLocalhost = window.location.hostname === "localhost";
  const typo = state.clientId !== "" && !CLIENT_ID.test(state.clientId);
  const lost = browser.spotify.wouldForget();
  const shown = error ?? state.error;

  const login = () => {
    setError(null);
    setLeaving(true);
    browser.spotify.login().catch((e: unknown) => {
      setLeaving(false);
      setError(e instanceof Error ? e.message : String(e));
    });
  };

  return (
    <section className="form spotify-login" aria-label="Spotify login">
      <div className="field">
        <label htmlFor="spotify-client-id">
          <strong>Spotify login</strong> <span className="required">for a playlist link</span>
        </label>
        {state.loggedIn ? (
          <>
            <div className="input-row">
              <span className="spotify-who">
                Logged in{state.user && <> as <strong>{state.user}</strong></>}.
              </span>
              <button type="button" className="ghost" onClick={browser.spotify.logout}>
                Log out
              </button>
            </div>
            <p className="help">
              Kept in this browser until you log out. Read-only: sdm can read your playlists, not change them, and only
              playlists you own or collaborate on — {guide("playlists", "Spotify's rule")}.
            </p>
          </>
        ) : (
          <>
            <div className="input-row">
              <input
                id="spotify-client-id"
                placeholder="Client ID of your Spotify app"
                value={state.clientId}
                spellCheck={false}
                autoComplete="off"
                disabled={state.finishing}
                onChange={(e) => browser.spotify.setClientId(e.target.value)}
              />
              <button
                type="button"
                className="primary"
                disabled={!state.clientId || state.finishing || leaving || onLocalhost}
                onClick={login}
              >
                {state.finishing ? "Finishing the login…" : leaving ? "Opening Spotify…" : "Log in to Spotify"}
              </button>
            </div>
            <p className="help">
              A playlist link is read through your Spotify account, with the client ID of a Spotify app of your own:
              free, about five minutes to set up once, and it needs Premium. {guide("create", "How to create one")}.
            </p>
            {typo && (
              <p className="help warn">
                A client ID is 32 characters, digits and the letters a–f: the one on your app&apos;s Settings page. Not
                the client secret.
              </p>
            )}
            {onLocalhost ? (
              <p className="help warn">
                Spotify refuses <code>localhost</code> as an address to come back to. Open this page at{" "}
                <code>{window.location.href.replace("//localhost", "//127.0.0.1")}</code> to log in.
              </p>
            ) : (
              <p className={lost ? "help warn" : "help"}>
                {lost
                  ? `Logging in leaves this page for Spotify and reloads it on the way back, which forgets ${lost} in this tab. Log in first, then choose folders.`
                  : "Logging in leaves this page for Spotify and comes back. Do it before choosing a folder: the page reloads, and a reload forgets picked folders."}
              </p>
            )}
          </>
        )}
        {shown && (
          <p className="help error-text">
            {shown} {guide("troubleshooting", "What to check")}
          </p>
        )}
      </div>
    </section>
  );
}

/** Until Python is ready: the download (cached by the browser after the first visit), then the start. */
export function BootScreen({ browser }: { browser: BrowserHooks }) {
  const [state, setState] = useState<BootState | null>(null);
  useEffect(() => browser.subscribeBoot(setState), [browser]);

  const downloading = state !== null && state.total > 0 && state.loaded < state.total;
  // Empty until there is something to count, full once the downloads are done
  // and the rest is Python starting up.
  const pct = state && state.total ? Math.min(100, (100 * state.loaded) / state.total) : 0;
  return (
    <div className="centered">
      <h2>sdm</h2>
      <p>Checks a music folder or a Rekordbox USB: missing tags, beat grids and phrases, playlist gaps.</p>
      {state?.error ? (
        <div className="error-box">
          Python did not start in this tab: {state.error}. sdm needs a current Chrome, Edge, Firefox or Safari.
        </div>
      ) : (
        <div className="progress" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
          <div className="progress-bar" style={{ width: `${pct}%` }} />
          <span>
            {state === null
              ? "Starting…"
              : downloading
                ? `${state.step}: ${bytes(state.loaded)} of ${bytes(state.total)}`
                : `${state.step}…`}
          </span>
        </div>
      )}
      <PrivacyNote />
    </div>
  );
}

/**
 * A path box with a picker instead of the server's folder browser. Picking
 * mounts the folder (or copies the CSV) into the worker, and the box gets the
 * path the commands see it at — still editable, so a subfolder can be typed.
 */
export function PathPickRow({
  browser,
  mode,
  accept,
  input,
  onPicked,
}: {
  browser: BrowserHooks;
  mode: "dir" | "file";
  accept: string[];
  input: ReactNode;
  onPicked: (path: string) => void;
}) {
  const [progress, setProgress] = useState<PickProgress | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const folder = mode === "dir";

  // Busy only once the picker has returned: a browser that never reports a
  // dismissed picker must not leave the button disabled.
  const start = (fallback: boolean) => {
    setError(null);
    browser
      .pick(mode, accept, setProgress, { fallback })
      .then((result) => {
        if (!result) return;
        setPicked(result.summary);
        onPicked(result.path);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setProgress(null));
  };

  let status: ReactNode;
  if (progress) {
    const pct = progress.total ? (100 * (progress.done ?? 0)) / progress.total : 100;
    status = (
      <div className="progress">
        <div className="progress-bar" style={{ width: `${pct}%` }} />
        <span>{progress.text}</span>
      </div>
    );
  } else if (picked) {
    status = <p className="help">Picked: {picked}.</p>;
  } else if (folder) {
    status = (
      <p className="help">
        {browser.canViewFolders
          ? "Your browser will ask to let this page view the folder's files. They are read here, in this tab — nothing is uploaded. A large folder takes a few seconds to read."
          : "Your browser may call this an upload. Nothing is uploaded: the files are read here, in this tab. With a large folder the browser can take several seconds to list it before anything appears."}
      </p>
    );
  }

  return (
    <>
      <div className="input-row">
        {input}
        <button type="button" disabled={progress !== null} onClick={() => start(false)}>
          {folder ? "Choose folder…" : "Choose CSV…"}
        </button>
      </div>
      {status}
      {error && <p className="help error-text">{error}</p>}
      {folder && browser.canViewFolders && !progress && (
        <p className="help">
          If your browser will not open a folder this way,{" "}
          <button type="button" className="link" onClick={() => start(true)}>
            use the other picker
          </button>
          .
        </p>
      )}
    </>
  );
}
