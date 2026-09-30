// Catch security-header mistakes that compile successfully but prevent React mounting.
import { loadConfigFromFile } from "vite";
import { fileURLToPath } from "node:url";

const loaded = await loadConfigFromFile(
  { command: "serve", mode: "development" },
  fileURLToPath(new URL("../vite.config.ts", import.meta.url)),
);

if (!loaded) throw new Error("could not load vite.config.ts");

const development = loaded.config.server?.headers ?? {};
const preview = loaded.config.preview?.headers ?? {};
const developmentCsp = String(development["Content-Security-Policy"] ?? "");
const previewCsp = String(preview["Content-Security-Policy"] ?? "");
const directive = (csp, name) => csp.split(";").map((part) => part.trim())
  .find((part) => part.startsWith(`${name} `)) ?? "";
const developmentScripts = directive(developmentCsp, "script-src");
const previewScripts = directive(previewCsp, "script-src");
const requiredApiSources = [
  "http://127.0.0.1:8000",
  "http://localhost:8000",
  "ws://127.0.0.1:8000",
  "ws://localhost:8000",
];

if (development["X-Frame-Options"] !== "DENY" || preview["X-Frame-Options"] !== "DENY") {
  throw new Error("development and preview must both deny framing");
}
if (developmentScripts !== "script-src 'self' 'unsafe-inline'") {
  throw new Error("development CSP must allow Vite's inline React-refresh bootstrap");
}
if (previewScripts !== "script-src 'self'") {
  throw new Error("preview CSP must keep scripts self-only");
}
for (const source of requiredApiSources) {
  if (!directive(developmentCsp, "connect-src").split(/\s+/).includes(source)) {
    throw new Error(`development CSP must allow the local API source ${source}`);
  }
  if (!directive(previewCsp, "connect-src").split(/\s+/).includes(source)) {
    throw new Error(`preview CSP must allow the local API source ${source}`);
  }
}

console.log("Vite development and preview security headers are compatible.");
