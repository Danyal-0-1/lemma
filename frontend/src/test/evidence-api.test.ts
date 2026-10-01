import { afterEach, describe, expect, it, vi } from "vitest";

import {
  acceptAssuredTask,
  removeClaimEvidence,
  updateResearchClaimStatus,
} from "../lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("claim correction API", () => {
  it("updates a claim lifecycle with a bounded PATCH", async () => {
    const response = {
      id: "claim/one",
      project_id: "project-1",
      finding_id: "finding-1",
      statement: "A reviewable claim",
      confidence: null,
      status: "retired",
      created_at: "2026-01-01T00:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(updateResearchClaimStatus("claim/one", "retired")).resolves.toMatchObject({
      status: "retired",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/lab\/claims\/claim%2Fone$/),
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ status: "retired" }) }),
    );
  });

  it("accepts an empty 204 response when removing a mistaken evidence edge", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(removeClaimEvidence("edge/one")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/lab\/claim-evidence\/edge%2Fone$/),
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("sends explicit protocol-criteria confirmation at the human gate", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      task_id: "task-1",
      status: "accepted",
    }), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await acceptAssuredTask("task-1", ["Direct evidence is cited"], "Reviewed manually");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/lab\/tasks\/task-1\/accept$/),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          reviewer: "founder",
          notes: "Reviewed manually",
          confirmed_criteria: ["Direct evidence is cited"],
        }),
      }),
    );
  });
});
