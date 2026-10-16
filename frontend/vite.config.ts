import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Python server (`sdm web`) serves the built page from inside the package,
// so `npm run build` writes straight into it.
//
// `npm run dev` serves the page with hot reload instead and forwards the API to
// a running `sdm web`. Open the link `sdm web` prints, with the port changed to
// Vite's: /auth goes through the proxy and sets the session cookie here.
const backend = process.env.SDM_WEB_BACKEND ?? "http://127.0.0.1:8770";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/sdm/web/static",
    emptyOutDir: true,
  },
  server: {
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
});
