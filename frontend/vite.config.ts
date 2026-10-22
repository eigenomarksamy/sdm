import react from "@vitejs/plugin-react";
import { createReadStream, existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, normalizePath, type Plugin } from "vite";

// The Python server (`sdm web`) serves the built page from inside the package,
// so `npm run build` writes straight into it.
//
// `npm run dev` serves the page with hot reload instead and forwards the API to
// a running `sdm web`. Open the link `sdm web` prints, with the port changed to
// Vite's: /auth goes through the proxy and sets the session cookie here.
//
// `--mode browser` builds the other front end instead: the same page with no
// server behind it, Python running in the tab (src/browser/), into ../dist for
// Cloudflare. `build_browser.py` at the repo root runs it and adds the Python.
const backend = process.env.SDM_WEB_BACKEND ?? "http://127.0.0.1:8770";
const here = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig(({ mode }) => {
  const forBrowser = mode === "browser";
  return {
    plugins: [react(), ...(forBrowser ? [browserBuild()] : [])],
    build: {
      outDir: forBrowser ? "../dist" : "../src/sdm/web/static",
      emptyOutDir: true,
    },
    // Module workers: Pyodide refuses to run in a classic one.
    worker: { format: "es" },
    server: forBrowser
      ? // As src/browser/_headers sets them, so a cancel interrupts Python here too.
        { headers: { "Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Embedder-Policy": "require-corp" } }
      : {
          proxy: {
            "/api": {
              target: backend,
              changeOrigin: true,
              // The server refuses a POST from a foreign Origin, and this page's
              // origin is Vite's. The proxy speaks for it.
              configure: (proxy) => {
                proxy.on("proxyReq", (req) => {
                  if (req.getHeader("origin")) req.setHeader("origin", backend);
                });
              },
            },
            "/auth": { target: backend, changeOrigin: true },
          },
        },
  };
});

/**
 * What `--mode browser` changes. Every import of src/api.ts resolves to
 * src/browser/api.ts instead — except from src/browser/ itself, which builds
 * on the real one — and the `_headers` file Cloudflare reads is emitted beside
 * the page. In dev, the Python (python.json, pyodide/, wheels/) is served from
 * the last `build_browser.py` run in ../dist.
 */
function browserBuild(): Plugin {
  const real = normalizePath(path.join(here, "src/api.ts"));
  const swap = normalizePath(path.join(here, "src/browser/api.ts"));
  const own = normalizePath(path.join(here, "src/browser")) + "/";
  const dist = path.resolve(here, "../dist");
  const types: Record<string, string> = {
    ".json": "application/json",
    ".mjs": "text/javascript",
    ".wasm": "application/wasm",
    ".zip": "application/zip",
    ".whl": "application/zip",
  };
  return {
    name: "sdm-browser-build",
    enforce: "pre",
    async resolveId(source, importer, options) {
      if (!importer || !/(^|\/)api(\.ts)?$/.test(source) || normalizePath(importer).startsWith(own)) return null;
      const resolved = await this.resolve(source, importer, { ...options, skipSelf: true });
      return resolved && normalizePath(resolved.id) === real ? swap : null;
    },
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "_headers", source: readFileSync(path.join(here, "src/browser/_headers"), "utf-8") });
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = decodeURIComponent((req.url ?? "").split("?")[0]);
        if (!/^\/(python\.json$|pyodide\/|wheels\/)/.test(url)) return next();
        const file = path.join(dist, url);
        if (!file.startsWith(dist) || !existsSync(file)) {
          res.statusCode = 404;
          res.end("Not built yet: run `python build_browser.py` once.");
          return;
        }
        res.setHeader("Content-Type", types[path.extname(file)] ?? "application/octet-stream");
        createReadStream(file).pipe(res);
      });
    },
  };
}
