// ─────────────────────────────────────────────────────────────────────────────
// main.tsx — the JavaScript entry point. READING ORDER: frontend #7
//
// WHAT IT DOES: finds <div id="root"> in index.html and mounts the React <App/>
// into it. This is the seam between the HTML page and the React component tree.
//
// WHY <React.StrictMode>: it double-invokes and double-mounts components in
// development to surface bugs — especially effects that don't clean up after
// themselves. We keep it ON from day one so the WebSocket code we write in M1 is
// forced to be correct (its useEffect must clean up, or you'll see two connections).
// ─────────────────────────────────────────────────────────────────────────────

import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./theme.css";

// The "!" tells TypeScript we're certain #root exists (it's hard-coded in index.html).
const rootElement = document.getElementById("root")!;

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
