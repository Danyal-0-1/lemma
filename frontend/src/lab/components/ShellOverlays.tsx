import { useEffect, useRef, useState } from "react";

import { useAppStore } from "../../store/appStore";
import {
  type ThemePreference,
  usePreferencesStore,
} from "../../store/preferencesStore";
import { useShellStore } from "../../store/shellStore";
import { Icon } from "./Icons";

const THEMES: { id: ThemePreference; label: string; detail: string }[] = [
  { id: "system", label: "System", detail: "Follow your operating system live" },
  { id: "dark", label: "Dark", detail: "VS Code Dark modern palette" },
  { id: "light", label: "Light", detail: "VS Code Light modern palette" },
  { id: "gray", label: "Gray", detail: "Neutral charcoal, lower saturation" },
];

function useDismiss(ref: React.RefObject<HTMLElement>, close: () => void) {
  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) close();
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    window.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [close, ref]);
}

function AccountMenu() {
  const setOverlay = useShellStore((state) => state.setOverlay);
  const status = useAppStore((state) => state.status);
  const mock = useAppStore((state) => state.mock);
  const hostExecution = useAppStore((state) => state.hostExecutionEnabled);
  const ref = useRef<HTMLDivElement>(null);
  useDismiss(ref, () => setOverlay(null));

  return (
    <div ref={ref} className="shell-popover shell-account-menu" role="dialog" aria-label="Account">
      <header>
        <span className="shell-account-avatar"><Icon name="account" size={18} /></span>
        <span><strong>Local profile</strong><small>Lemma R&amp;D Studio</small></span>
      </header>
      <div className="shell-menu-section">
        <span><i className={`shell-status-dot is-${status}`} />Backend</span><b>{status}</b>
        <span>Provider</span><b>{mock ? "Mock / local" : "Configured"}</b>
        <span>Host tools</span><b>{hostExecution ? "Enabled" : "Locked"}</b>
      </div>
      <p>Account data and research stay on this machine. No cloud identity is required.</p>
      <button type="button" onClick={() => setOverlay("settings")}>
        <Icon name="settings" size={15} /> Manage Settings
      </button>
    </div>
  );
}

function SettingsModal() {
  const [category, setCategory] = useState<"appearance" | "editor" | "security">("appearance");
  const setOverlay = useShellStore((state) => state.setOverlay);
  const theme = usePreferencesStore((state) => state.theme);
  const setTheme = usePreferencesStore((state) => state.setTheme);
  const fontSize = usePreferencesStore((state) => state.editorFontSize);
  const setFontSize = usePreferencesStore((state) => state.setEditorFontSize);
  const minimap = usePreferencesStore((state) => state.minimap);
  const setMinimap = usePreferencesStore((state) => state.setMinimap);
  const wordWrap = usePreferencesStore((state) => state.wordWrap);
  const setWordWrap = usePreferencesStore((state) => state.setWordWrap);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOverlay(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOverlay]);

  return (
    <div className="shell-settings-backdrop" onMouseDown={(event) => event.currentTarget === event.target && setOverlay(null)}>
      <section className="shell-settings" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <header>
          <div><span>Preferences</span><h2 id="settings-title">Settings</h2></div>
          <button type="button" className="lab-icon-button" onClick={() => setOverlay(null)} aria-label="Close settings"><Icon name="close" /></button>
        </header>
        <div className="shell-settings-body">
          <nav aria-label="Settings categories">
            <button type="button" className={category === "appearance" ? "is-active" : ""} onClick={() => setCategory("appearance")}>Appearance</button>
            <button type="button" className={category === "editor" ? "is-active" : ""} onClick={() => setCategory("editor")}>Editor</button>
            <button type="button" className={category === "security" ? "is-active" : ""} onClick={() => setCategory("security")}>Security</button>
          </nav>
          <div className="shell-settings-content">
            {category === "appearance" && <section>
              <h3>Color theme</h3>
              <p>Applied to the complete shell, code editor, and terminal.</p>
              <div className="shell-theme-grid">
                {THEMES.map((item) => (
                  <button key={item.id} type="button" className={theme === item.id ? "is-selected" : ""} onClick={() => setTheme(item.id)}>
                    <i className={`theme-swatch theme-swatch-${item.id}`}><span /><span /><span /></i>
                    <span><strong>{item.label}</strong><small>{item.detail}</small></span>
                    {theme === item.id && <Icon name="check" size={15} />}
                  </button>
                ))}
              </div>
            </section>}
            {category === "editor" && <section>
              <h3>Editor</h3>
              <p>These preferences are stored only in this browser.</p>
              <label className="shell-setting-row">
                <span><strong>Font size</strong><small>Code editor text size in pixels.</small></span>
                <input aria-label="Editor font size" type="number" min="10" max="22" value={fontSize} onChange={(event) => setFontSize(Number(event.target.value))} />
              </label>
              <label className="shell-setting-row">
                <span><strong>Minimap</strong><small>Show a compact code overview.</small></span>
                <input type="checkbox" checked={minimap} onChange={(event) => setMinimap(event.target.checked)} />
              </label>
              <label className="shell-setting-row">
                <span><strong>Word wrap</strong><small>Wrap long lines at the editor edge.</small></span>
                <input type="checkbox" checked={wordWrap} onChange={(event) => setWordWrap(event.target.checked)} />
              </label>
            </section>}
            {category === "security" && (
              <section>
                <h3>Local security boundary</h3>
                <p>Lemma is designed for one trusted operator on the loopback interface.</p>
                <div className="shell-security-note">
                  <Icon name="security" size={18} />
                  <span><strong>Secure by default</strong><small>Git mutations and terminal access require explicit host-execution enablement.</small></span>
                </div>
                <div className="shell-security-note">
                  <Icon name="check" size={18} />
                  <span><strong>Agents remain isolated</strong><small>Research roles and duty cards never grant shell, filesystem, connector, or credential access.</small></span>
                </div>
              </section>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

export default function ShellOverlays() {
  const overlay = useShellStore((state) => state.overlay);
  if (overlay === "account") return <AccountMenu />;
  if (overlay === "settings") return <SettingsModal />;
  return null;
}
