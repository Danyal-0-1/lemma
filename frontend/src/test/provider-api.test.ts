import { afterEach, describe, expect, it, vi } from "vitest";

import { getModelConnections, testModelConnection } from "../lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("model connection API", () => {
  it("loads only the redacted connection catalog", async () => {
    const catalog = { mock_mode: true, connections: [] };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(catalog), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getModelConnections()).resolves.toEqual(catalog);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/lab\/model-connections$/),
      expect.objectContaining({}),
    );
  });

  it("tests one explicitly selected connection and model", async () => {
    const result = {
      ok: true,
      message: "Connected",
      connection_id: "custom/one",
      model: "openai/research-model",
      tokens_in: 2,
      tokens_out: 1,
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(result), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(testModelConnection("custom/one", "openai/research-model")).resolves.toEqual(result);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/lab\/model-connections\/custom%2Fone\/test$/),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ model: "openai/research-model" }),
      }),
    );
  });
});
