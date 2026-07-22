// ─────────────────────────────────────────────────────────────────────────────
// tailwind.config.js — maps our VS Code Dark+ color tokens to Tailwind classes.
// READING ORDER: frontend #4
//
// WHY it's set up this way: the ACTUAL color values live as CSS variables in
// src/theme.css (one place to tweak the theme). Here we just point Tailwind's color
// names at those variables. So `bg-panel` in JSX resolves to `var(--color-bg)`.
// This indirection is deliberate — it keeps the palette in CSS (easy to see and
// change) while still giving us Tailwind's convenient utility classes.
// ─────────────────────────────────────────────────────────────────────────────

/** @type {import('tailwindcss').Config} */
export default {
  // Which files Tailwind scans for class names (so it only generates what we use).
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces + text (Section 12 of PROMPT.md).
        panel: "var(--color-bg)", // main editor background  #1e1e1e
        sidebar: "var(--color-sidebar)", // #252526
        line: "var(--color-line)", // 1px borders            #3c3c3c
        fg: "var(--color-fg)", // primary text            #cccccc
        muted: "var(--color-muted)", // dim/secondary text      #8c8c8c
        accent: "var(--color-accent)", // #0e639c
        "accent-hover": "var(--color-accent-hover)", // #1177bb
        ok: "var(--color-ok)", // #89d185
        warn: "var(--color-warn)", // #cca700
        err: "var(--color-err)", // #f48771
        // Per-role speaker colors used in the Conversation.
        "role-generator": "var(--role-generator)",
        "role-researcher": "var(--role-researcher)",
        "role-critic": "var(--role-critic)",
        "role-pm": "var(--role-pm)",
        "role-mentor": "var(--role-mentor)",
      },
      fontFamily: {
        // 13px system UI stack for chrome; monospace for code + terminal.
        ui: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "SF Mono", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
