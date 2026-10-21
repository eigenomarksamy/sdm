// What only the browser build shows: Python starting, and a folder being picked.
// Shared components render these when `browser` (src/api.ts) is set.
import { useEffect, useState, type ReactNode } from "react";
import type { BootState, BrowserHooks, PickProgress } from "../api";
import { bytes } from "../format";

/** The promise the page makes, and why it can keep it. Shown before anything is picked. */
export function PrivacyNote() {
  return (
    <p className="muted">
      Everything runs in this tab. Your files are read where they are and nothing leaves the browser: the page is only
      allowed to connect to this site, which serves static files and has nothing to receive them with. Reports live in
      this tab and are gone when you reload or close it.
    </p>
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
