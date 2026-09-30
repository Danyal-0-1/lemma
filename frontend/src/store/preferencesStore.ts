import { useEffect, useState } from "react";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type ThemePreference = "system" | "dark" | "light" | "gray";
export type ResolvedTheme = Exclude<ThemePreference, "system">;

interface PreferencesState {
  theme: ThemePreference;
  resolvedTheme: ResolvedTheme;
  editorFontSize: number;
  minimap: boolean;
  wordWrap: boolean;
  setTheme: (theme: ThemePreference) => void;
  setEditorFontSize: (size: number) => void;
  setMinimap: (enabled: boolean) => void;
  setWordWrap: (enabled: boolean) => void;
  setResolvedTheme: (theme: ResolvedTheme) => void;
}

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      theme: "system",
      resolvedTheme: window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
      editorFontSize: 13,
      minimap: false,
      wordWrap: false,
      setTheme: (theme) => set({ theme }),
      setEditorFontSize: (editorFontSize) =>
        set({ editorFontSize: Math.min(22, Math.max(10, editorFontSize)) }),
      setMinimap: (minimap) => set({ minimap }),
      setWordWrap: (wordWrap) => set({ wordWrap }),
      setResolvedTheme: (resolvedTheme) => set({ resolvedTheme }),
    }),
    {
      name: "lemma-workbench-preferences",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        theme: state.theme,
        editorFontSize: state.editorFontSize,
        minimap: state.minimap,
        wordWrap: state.wordWrap,
      }),
    },
  ),
);

function resolveTheme(preference: ThemePreference, dark: boolean): ResolvedTheme {
  if (preference === "system") return dark ? "dark" : "light";
  return preference;
}

/** Applies the stored preference and follows OS changes while System is selected. */
export function useApplyTheme(): ResolvedTheme {
  const preference = usePreferencesStore((state) => state.theme);
  const setResolvedTheme = usePreferencesStore((state) => state.setResolvedTheme);
  const [systemDark, setSystemDark] = useState(() =>
    window.matchMedia("(prefers-color-scheme: dark)").matches,
  );

  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const update = (event: MediaQueryListEvent | MediaQueryList) => setSystemDark(event.matches);
    update(query);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  const resolved = resolveTheme(preference, systemDark);
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = preference;
    root.dataset.resolvedTheme = resolved;
    root.style.colorScheme = resolved === "light" ? "light" : "dark";
    setResolvedTheme(resolved);
  }, [preference, resolved, setResolvedTheme]);

  return resolved;
}
