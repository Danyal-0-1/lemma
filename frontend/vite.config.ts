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

function securityHeaders({ development }: { development: boolean }) {
  const connectSources = [
    "'self'",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "ws://127.0.0.1:8000",
    "ws://localhost:8000",
    "ws://127.0.0.1:5173",
    "ws://localhost:5173",
  ].join(" ");
  return {
    "Cache-Control": "no-store",
    "Content-Security-Policy": [
      "default-src 'self'",
      "base-uri 'none'",
      `connect-src ${connectSources}`,
      "font-src 'self' data:",
      "form-action 'none'",
      "frame-ancestors 'none'",
      "img-src 'self' data: blob:",
      "object-src 'none'",
      // Vite injects one inline React-refresh bootstrap in development. Production
      // preview has no injected script and therefore keeps the stricter directive.
      development ? "script-src 'self' 'unsafe-inline'" : "script-src 'self'",
      "style-src 'self' 'unsafe-inline'",
      "worker-src 'self' blob:",
    ].join("; "),
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
  };
}

export default defineConfig({
  plugins: [react()],
  server: {
    // Localhost only, with an explicit Host/CORS boundary for the development server.
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    allowedHosts: ["127.0.0.1", "localhost"],
    cors: { origin: /^http:\/\/(127\.0\.0\.1|localhost):5173$/ },
    headers: securityHeaders({ development: true }),
    fs: {
      strict: true,
      deny: [".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx"],
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    allowedHosts: ["127.0.0.1", "localhost"],
    headers: securityHeaders({ development: false }),
  },
});
