// Hash routing, because the server serves one page and every route is a view
// of it: #/run/duplicates, #/jobs/3, #/report?path=duplicates/duplicates.json.
import { useEffect, useState } from "react";

export interface Route {
  path: string;
  segments: string[];
  query: URLSearchParams;
}

function parse(hash: string): Route {
  const raw = hash.replace(/^#/, "") || "/";
  const [path, search = ""] = raw.split("?", 2);
  return {
    path,
    segments: path.split("/").filter(Boolean).map(decodeURIComponent),
    query: new URLSearchParams(search),
  };
}

export function useRoute(): Route {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return parse(hash);
}

export function href(path: string, query?: Record<string, string>): string {
  const search = query ? new URLSearchParams(query).toString() : "";
  return `#${path}${search ? `?${search}` : ""}`;
}

export function navigate(path: string, query?: Record<string, string>): void {
  window.location.hash = href(path, query).slice(1);
}
