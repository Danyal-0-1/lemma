import { create } from "zustand";

type ShellOverlay = "account" | "settings" | null;

interface ShellState {
  overlay: ShellOverlay;
  setOverlay: (overlay: ShellOverlay) => void;
}

export const useShellStore = create<ShellState>((set) => ({
  overlay: null,
  setOverlay: (overlay) => set({ overlay }),
}));

