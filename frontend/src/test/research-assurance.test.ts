import { describe, expect, it } from "vitest";

import { assuranceSteps } from "../lab/components/ResearchAssurance";
import type { TaskAssurance } from "../lab/types";

function assurance(overrides: Partial<TaskAssurance> = {}): TaskAssurance {
  return {
    task_id: "task-1",
    project_id: "project-1",
    run_id: "run-1",
    status: "ready",
    ready: true,
    snapshot_sha256: "abc",
    protocol: null,
    latest_protocol: null,
    coverage: {
      total_claims: 2,
      supported_claims: 2,
      unsupported_claims: 0,
      contradicted_claims: 0,
      coverage_percent: 100,
      unique_supporting_sources: 2,
      source_packet_count: 2,
      source_packet_candidate_count: 2,
      source_packet_link_count: 2,
      invalid_source_packet_refs: [],
      excluded_source_packet_refs: [],
      unlinked_supporting_source_ids: [],
    },
    checks: [],
    issues: [],
    claim_results: [],
    acceptance: null,
    ...overrides,
  };
}

describe("research assurance pipeline", () => {
  it("keeps human acceptance and capsule export as explicit final gates", () => {
    const ready = assuranceSteps({
      protocolApproved: true,
      sourceCount: 2,
      assurance: assurance(),
      capsuleDownloaded: false,
    });

    expect(ready.map((step) => [step.id, step.complete])).toEqual([
      ["protocol", true],
      ["sources", true],
      ["evidence", true],
      ["review", false],
      ["capsule", false],
    ]);

    const accepted = assuranceSteps({
      protocolApproved: true,
      sourceCount: 2,
      assurance: assurance({ status: "accepted", acceptance: { id: "acceptance-1" } }),
      capsuleDownloaded: true,
    });
    expect(accepted.every((step) => step.complete)).toBe(true);
  });

  it("does not pass evidence with unsupported or contradictory claims", () => {
    const steps = assuranceSteps({
      protocolApproved: true,
      sourceCount: 1,
      assurance: assurance({
        ready: false,
        status: "blocked",
        coverage: {
          total_claims: 3,
          supported_claims: 2,
          unsupported_claims: 1,
          contradicted_claims: 1,
          coverage_percent: 67,
          unique_supporting_sources: 1,
          source_packet_count: 1,
          source_packet_candidate_count: 1,
          source_packet_link_count: 1,
          invalid_source_packet_refs: [],
          excluded_source_packet_refs: [],
          unlinked_supporting_source_ids: [],
        },
      }),
      capsuleDownloaded: false,
    });

    expect(steps.find((step) => step.id === "evidence")?.complete).toBe(false);
  });

  it("shows the bounded runtime packet separately from all linked sources", () => {
    const steps = assuranceSteps({
      protocolApproved: true,
      sourceCount: 24,
      linkedSourceCount: 30,
      assurance: assurance(),
      capsuleDownloaded: false,
    });

    expect(steps.find((step) => step.id === "sources")?.detail).toBe("24 used / 30 linked");
  });
});
