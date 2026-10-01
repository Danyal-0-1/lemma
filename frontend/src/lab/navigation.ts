import type { LabView } from "./types";

export const LAB_VIEWS = [
  "explorer",
  "search",
  "source_control",
  "hq",
  "terminal",
  "organization",
  "research",
  "knowledge",
  "evaluations",
  "meetings",
  "operations",
  "security",
  "workbench",
] as const satisfies readonly LabView[];

export function isLabView(value: string | null): value is LabView {
  return value !== null && (LAB_VIEWS as readonly string[]).includes(value);
}

export function viewFromHash(hash: string, fallback: LabView = "hq"): LabView {
  const raw = hash.replace(/^#/, "");
  if (isLabView(raw)) return raw;
  const value = new URLSearchParams(raw).get("view");
  return isLabView(value) ? value : fallback;
}

export function currentView(fallback: LabView = "hq"): LabView {
  return typeof window === "undefined" ? fallback : viewFromHash(window.location.hash, fallback);
}

export function viewHref(view: LabView): string {
  return `#view=${encodeURIComponent(view)}`;
}

/** Keep navigation shareable without requiring server-side SPA routing. */
export function writeViewToUrl(view: LabView, { replace = false } = {}): void {
  if (typeof window === "undefined") return;
  const hash = viewHref(view);
  if (window.location.hash === hash) return;
  const next = `${window.location.pathname}${window.location.search}${hash}`;
  window.history[replace ? "replaceState" : "pushState"]({ view }, "", next);
}
