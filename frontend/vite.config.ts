// ─────────────────────────────────────────────────────────────────────────────
// vite.config.ts — how the dev server and build are configured.
// READING ORDER: frontend #2
//
// WHY this file: Vite is the tool that serves the app during development (with
// instant hot-reload) and bundles it for production. This config keeps it minimal:
// enable React (JSX + fast refresh) and pin the dev server to localhost:5173 so it
// matches the backend's CORS allow-list and the URL in the README.
// ─────────────────────────────────────────────────────────────────────────────

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // Localhost only, same as the backend — see README "Why it binds to 127.0.0.1".
    host: "127.0.0.1",
    port: 5173,
  },
});
