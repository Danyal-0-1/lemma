import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CommandPalette, filterCommands } from "../lab/components/CommandPalette";
import { viewFromHash } from "../lab/navigation";
import { useLabStore } from "../lab/store";
import { normalizeLabSnapshot } from "../lab/types";

describe("shareable Studio navigation", () => {
  it("restores both direct and parameterized research views", () => {
    expect(viewFromHash("#knowledge")).toBe("knowledge");
    expect(viewFromHash("#view=evaluations")).toBe("evaluations");
    expect(viewFromHash("#not-a-view", "hq")).toBe("hq");
  });

  it("filters the real command palette by labels and keywords", () => {
    expect(filterCommands("evidence").map((item) => item.view)).toContain("knowledge");
    expect(filterCommands("jobs policy").map((item) => item.view)).toEqual(["operations"]);
  });
});

describe("CommandPalette", () => {
  it("supports keyboard filtering and selection", async () => {
    const user = userEvent.setup();
    const close = vi.fn();
    const navigate = vi.fn();
    render(<CommandPalette onClose={close} onNavigate={navigate} />);

    const input = screen.getByRole("combobox");
    await user.type(input, "model arena");
    expect(screen.getByRole("option", { name: /model arena/i })).toBeInTheDocument();
    await user.keyboard("{Enter}");

    expect(navigate).toHaveBeenCalledWith("evaluations");
    expect(close).toHaveBeenCalledOnce();
  });
});

describe("lab snapshot normalization", () => {
  it("keeps optional collections and retry metadata safe", () => {
    const snapshot = normalizeLabSnapshot({
      projects: [{ id: "project-1", name: "Study", objective: "Test it" }],
      runs: [{
        id: "run-2",
        project_id: "project-1",
        retry_of_run_id: "run-1",
        attempt: 2,
        status: "running",
      }],
    });

    expect(snapshot.projects[0].name).toBe("Study");
    expect(snapshot.runs[0]).toMatchObject({ retry_of_run_id: "run-1", attempt: 2 });
    expect(snapshot.agents).toEqual([]);
  });
});

describe("live research run state", () => {
  it("reflects a cancellation event immediately", () => {
    vi.useFakeTimers();
    try {
      useLabStore.setState({ liveRuns: {} });
      useLabStore.getState().applyEvent({
        v: 1,
        seq: 1,
        ts: "2026-01-01T00:00:00Z",
        session_id: null,
        event: "lab_run_cancelled",
        payload: { run_id: "run-cancelled", task_id: "task-1" },
      });

      expect(useLabStore.getState().liveRuns["run-cancelled"]).toMatchObject({
        status: "cancelled",
        error: null,
      });
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
      useLabStore.setState({ liveRuns: {} });
    }
  });
});
