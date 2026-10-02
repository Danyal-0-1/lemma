import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import IdeWorkspace from "../lab/ide/IdeWorkspace";
import TerminalTab, { terminalCloseNotice } from "../panels/rightpane/TerminalTab";
import { useAppStore } from "../store/appStore";

const mocks = vi.hoisted(() => ({
  createTerminal: vi.fn(),
  getFile: vi.fn(),
  getWorkspaces: vi.fn(),
  getWorkspaceTree: vi.fn(),
  terminalWrites: [] as string[],
}));

vi.mock("../lib/api", () => ({
  createTerminal: mocks.createTerminal,
  getFile: mocks.getFile,
  getWorkspaces: mocks.getWorkspaces,
  getWorkspaceTree: mocks.getWorkspaceTree,
  ptyUrl: (terminalId: string) => `ws://127.0.0.1:8000/pty/${terminalId}`,
}));

vi.mock("../store/preferencesStore", () => ({
  usePreferencesStore: (selector: (state: { resolvedTheme: "dark"; editorFontSize: number }) => unknown) =>
    selector({ resolvedTheme: "dark", editorFontSize: 13 }),
}));

vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class {
    fit() {}
  },
}));

vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    cols = 80;
    rows = 24;
    options: Record<string, unknown> = {};

    loadAddon() {}
    open() {}
    dispose() {}
    write(value: string | Uint8Array) {
      if (typeof value === "string") mocks.terminalWrites.push(value);
    }
    onData() {}
  },
}));

class FakeResizeObserver {
  observe() {}
  disconnect() {}
}

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  binaryType = "blob";
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  sent: unknown[] = [];

  constructor(url: string | URL) {
    this.url = String(url);
    FakeWebSocket.instances.push(this);
  }

  send(value: unknown) {
    this.sent.push(value);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  failAndClose(code = 1011, reason = "") {
    this.onerror?.(new Event("error"));
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.(new CloseEvent("close", { code, reason }));
  }
}

beforeEach(() => {
  mocks.createTerminal.mockReset();
  mocks.getFile.mockReset();
  mocks.getWorkspaces.mockReset();
  mocks.getWorkspaceTree.mockReset();
  mocks.terminalWrites.length = 0;
  FakeWebSocket.instances.length = 0;
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  vi.stubGlobal("WebSocket", FakeWebSocket);
  useAppStore.setState({ hostExecutionEnabled: false });
});

describe("TerminalTab", () => {
  it("shows backend creation errors and retries with a new request", async () => {
    mocks.createTerminal
      .mockRejectedValueOnce(new Error("configured shell is not executable"))
      .mockResolvedValueOnce({ terminal_id: "pty-second" });
    const user = userEvent.setup();

    render(<TerminalTab workspaceId="workspace-1" active />);

    expect(await screen.findByRole("alert")).toHaveTextContent("configured shell is not executable");
    expect(mocks.terminalWrites.join("\n")).toContain("configured shell is not executable");

    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(mocks.createTerminal).toHaveBeenCalledTimes(2));
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => FakeWebSocket.instances[0].open());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("surfaces a socket close reason and can establish a replacement terminal", async () => {
    mocks.createTerminal
      .mockResolvedValueOnce({ terminal_id: "pty-first" })
      .mockResolvedValueOnce({ terminal_id: "pty-retry" });
    const user = userEvent.setup();

    render(<TerminalTab workspaceId="workspace-1" active />);
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => FakeWebSocket.instances[0].open());
    act(() => FakeWebSocket.instances[0].failAndClose(1011, "shell could not start"));

    expect(screen.getByRole("alert")).toHaveTextContent("shell could not start");
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    expect(mocks.createTerminal).toHaveBeenCalledTimes(2);
  });

  it("classifies a normal shell exit separately from a connection failure", () => {
    expect(terminalCloseNotice({ code: 1000, reason: "" })).toEqual({
      state: "closed",
      message: "Terminal session ended.",
    });
    expect(terminalCloseNotice({ code: 1006, reason: "" }, true).state).toBe("error");
  });
});

describe("terminal workspace prerequisites", () => {
  it("does not describe a missing workspace as a host-execution lock", async () => {
    useAppStore.setState({ hostExecutionEnabled: true });
    mocks.getWorkspaces.mockResolvedValue([]);

    render(<IdeWorkspace view="terminal" />);

    expect(await screen.findByRole("heading", { name: "No active workspace" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Trusted terminal is locked" })).not.toBeInTheDocument();
  });

  it("shows the opt-in lock when a workspace exists but host execution is disabled", async () => {
    mocks.getWorkspaces.mockResolvedValue([
      {
        id: "workspace-1",
        slug: "demo",
        path: "/tmp/demo",
        status: "active",
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    mocks.getWorkspaceTree.mockResolvedValue({ root: null, truncated: false });

    render(<IdeWorkspace view="terminal" />);

    expect(await screen.findByRole("heading", { name: "Trusted terminal is locked" })).toBeInTheDocument();
    expect(screen.getByText(/restart the backend and reload this page/i)).toBeInTheDocument();
  });
});
