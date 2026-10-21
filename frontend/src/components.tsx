// Small components shared by several pages.
import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, browser, type Field, type FormValue, type FsListing, type JobStatus } from "./api";
import { PathPickRow } from "./browser/ui";
import { copyText } from "./format";

export function StatusBadge({ status, cancelling }: { status: JobStatus; cancelling?: boolean }) {
  const label = status === "running" && cancelling ? "cancelling" : status;
  return <span className={`badge status-${status}`}>{label}</span>;
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="ghost small"
      onClick={async () => {
        if (await copyText(text)) {
          setDone(true);
          window.setTimeout(() => setDone(false), 1200);
        }
      }}
    >
      {done ? "Copied" : label}
    </button>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return <div className="error-box">{message}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

// --- form fields -------------------------------------------------------------

export function FieldInput({
  field,
  value,
  onChange,
}: {
  field: Field;
  value: FormValue;
  onChange: (v: FormValue) => void;
}) {
  const [picking, setPicking] = useState(false);
  const id = `f-${field.dest}`;
  const help = field.help ? <p className="help">{field.help}</p> : null;

  if (field.kind === "flag") {
    return (
      <div className="field field-flag">
        <label htmlFor={id}>
          <input id={id} type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
          <code>{field.label}</code>
        </label>
        {help}
      </div>
    );
  }

  if (field.kind === "optional_value") {
    // Off, on with the default location (true), or on with a path (string).
    const on = value === true || (typeof value === "string" && value !== "");
    return (
      <div className="field">
        <label htmlFor={id} className="inline">
          <input
            type="checkbox"
            checked={on}
            onChange={(e) => onChange(e.target.checked ? true : null)}
          />
          <code>{field.label}</code>
        </label>
        <input
          id={id}
          type="text"
          disabled={!on}
          placeholder="default location"
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value === "" ? true : e.target.value)}
        />
        {help}
      </div>
    );
  }

  const text = typeof value === "string" ? value : "";
  const placeholder =
    field.default !== null && field.default !== "" ? `default: ${field.default}` : field.metavar ?? "";

  let input: ReactNode;
  if (field.kind === "choice" && field.choices) {
    input = (
      <select id={id} value={text} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">{placeholder || "(default)"}</option>
        {field.choices.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    );
  } else {
    input = (
      <input
        id={id}
        type={field.kind === "integer" || field.kind === "number" ? "number" : "text"}
        step={field.kind === "integer" ? 1 : "any"}
        placeholder={placeholder}
        value={text}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
      />
    );
  }

  return (
    <div className="field">
      <label htmlFor={id}>
        {field.positional ? <strong>{field.label}</strong> : <code>{field.label}</code>}
        {field.required && <span className="required"> required</span>}
      </label>
      {browser && field.path ? (
        // No server to browse in the browser build: the visitor picks instead.
        <PathPickRow browser={browser} mode={field.path} accept={field.accept} input={input} onPicked={onChange} />
      ) : (
        <div className="input-row">
          {input}
          {field.path && (
            <button type="button" onClick={() => setPicking(true)}>
              Browse…
            </button>
          )}
        </div>
      )}
      {help}
      {picking && field.path && (
        <PathPicker
          mode={field.path}
          accept={field.accept}
          start={text}
          onPick={(p) => {
            onChange(p);
            setPicking(false);
          }}
          onClose={() => setPicking(false)}
        />
      )}
    </div>
  );
}

// --- path picker ---------------------------------------------------------------

/**
 * A folder browser over the server's filesystem. Needed because a browser
 * never tells a page the path of a folder the user picks; this server is on
 * the same machine, so it can list one instead.
 */
export function PathPicker({
  mode,
  accept,
  start,
  onPick,
  onClose,
}: {
  mode: "dir" | "file";
  accept: string[];
  start: string;
  onPick: (path: string) => void;
  onClose: () => void;
}) {
  const [listing, setListing] = useState<FsListing | null>(null);
  const [typed, setTyped] = useState(start);
  const [error, setError] = useState<string | null>(null);

  const open = async (path: string) => {
    try {
      const next = await api.fs(path, mode === "file", accept);
      setListing(next);
      setTyped(next.path);
      setError(null);
    } catch (e) {
      if (path && e instanceof ApiError && e.status === 404) {
        // A stale remembered path: start from the roots instead.
        setError(e.message);
        const roots = await api.fs("", mode === "file", accept).catch(() => null);
        if (roots) setListing(roots);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    }
  };

  useEffect(() => {
    void open(start);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []); // once, on open: `start` is only where browsing begins

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="Choose a path">
        <div className="modal-head">
          <strong>{mode === "dir" ? "Choose a folder" : `Choose a file${accept.length ? ` (${accept.join(", ")})` : ""}`}</strong>
          <button className="ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <form
          className="input-row"
          onSubmit={(e) => {
            e.preventDefault();
            void open(typed);
          }}
        >
          <input value={typed} onChange={(e) => setTyped(e.target.value)} spellCheck={false} placeholder="Type a path" />
          <button type="submit">Go</button>
          <button
            type="button"
            disabled={!listing || listing.parent === null}
            onClick={() => listing && listing.parent !== null && void open(listing.parent)}
          >
            Up
          </button>
        </form>
        {error && <div className="error-text">{error}</div>}
        <ul className="fs-list">
          {listing?.entries.map((entry) => (
            <li key={entry.path}>
              <button
                className={`fs-entry ${entry.dir ? "dir" : "file"}`}
                onClick={() => (entry.dir ? void open(entry.path) : onPick(entry.path))}
              >
                <span aria-hidden>{entry.dir ? "📁" : "📄"}</span> {entry.name}
              </button>
            </li>
          ))}
          {listing && listing.entries.length === 0 && <li className="muted">Nothing here.</li>}
        </ul>
        <div className="modal-foot">
          <span className="muted mono">{listing?.path || "This computer"}</span>
          {mode === "dir" && (
            <button className="primary" disabled={!listing?.path} onClick={() => listing && onPick(listing.path)}>
              Use this folder
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
