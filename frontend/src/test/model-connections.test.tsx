import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ModelConnectionsPanel } from "../lab/components/ModelConnections";
import ShellOverlays from "../lab/components/ShellOverlays";
import { useLabStore } from "../lab/store";
import type { Agent, ModelConnectionCatalog } from "../lab/types";
import { AgentForm, AgentInspector } from "../lab/views/OrganizationView";
import { useShellStore } from "../store/shellStore";

const apiMocks = vi.hoisted(() => ({
  createLabEntity: vi.fn(),
  getModelConnections: vi.fn(),
  testModelConnection: vi.fn(),
  updateLabEntity: vi.fn(),
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, ...apiMocks };
});

const catalog: ModelConnectionCatalog = {
  mock_mode: false,
  connections: [
    {
      id: "openai-api",
      name: "OpenAI API",
      provider: "openai",
      kind: "api_key",
      auth_mode: "api_key",
      status: "ready",
      egress: "remote",
      billing: "api",
      configured: true,
      models: [{ id: "openai/gpt-5", label: "GPT-5" }],
      supports_custom_model: true,
      detail: "Direct provider API; usage is metered separately from consumer plans.",
      setup: "Set OPENAI_API_KEY in backend/.env, then restart Lemma.",
    },
    {
      id: "claude-subscription",
      name: "Claude plan via Claude Code",
      provider: "anthropic",
      kind: "subscription",
      auth_mode: "account_session",
      status: "available",
      egress: "remote",
      billing: "subscription",
      configured: true,
      models: [{ id: "sonnet", label: "Sonnet" }],
      supports_custom_model: true,
      detail: "Uses the signed-in Claude Code account session and never an API key.",
      setup: "Install and run `claude` once in macOS Terminal to sign in.",
    },
    {
      id: "ollama-local",
      name: "Ollama on this Mac",
      provider: "ollama",
      kind: "local",
      auth_mode: "none",
      status: "ready",
      egress: "local",
      billing: "none",
      configured: true,
      models: [{ id: "ollama/qwen3", label: "Qwen 3" }],
      supports_custom_model: true,
      detail: "Loopback-only local inference.",
      setup: "Start Ollama and restart Lemma.",
    },
    {
      id: "custom-openai",
      name: "Custom endpoint",
      provider: "custom",
      kind: "custom",
      auth_mode: "none",
      status: "setup_required",
      egress: "operator_defined",
      billing: "custom",
      configured: false,
      models: [],
      supports_custom_model: true,
      detail: "Data handling depends on the endpoint operator.",
      setup: "Set LEMMA_CUSTOM_OPENAI_BASE_URL in backend/.env, then restart Lemma.",
    },
  ],
};

const emptySnapshot = {
  departments: [{
    id: "group-1",
    name: "Evidence",
    description: "",
    kind: "department" as const,
    status: "active",
  }],
  agents: [],
  projects: [],
  tasks: [],
  results: [],
  findings: [],
  meetings: [],
  meeting_messages: [],
  runs: [],
  activities: [],
};

beforeEach(() => {
  apiMocks.createLabEntity.mockReset().mockResolvedValue({});
  apiMocks.getModelConnections.mockReset().mockResolvedValue(catalog);
  apiMocks.testModelConnection.mockReset().mockResolvedValue({
    ok: true,
    message: "Connected",
    connection_id: "openai-api",
    model: "openai/gpt-5",
    tokens_in: 2,
    tokens_out: 1,
  });
  apiMocks.updateLabEntity.mockReset().mockResolvedValue({});
  useLabStore.setState({
    snapshot: emptySnapshot,
    selectedDepartmentId: "group-1",
    refresh: vi.fn().mockResolvedValue(undefined),
  });
  useShellStore.setState({ overlay: null });
});

describe("model connection settings", () => {
  it("is available as a focused Settings category", async () => {
    const user = userEvent.setup();
    useShellStore.setState({ overlay: "settings" });
    render(<ShellOverlays />);

    await user.click(screen.getByRole("button", { name: "Models" }));
    expect(await screen.findByRole("heading", { name: "Models and connections" })).toBeInTheDocument();
  });

  it("makes auth, billing, and egress routes distinct without collecting secrets", async () => {
    const user = userEvent.setup();
    render(<ModelConnectionsPanel />);

    const apiCard = (await screen.findByText("OpenAI API")).closest("article");
    expect(apiCard).not.toBeNull();
    expect(within(apiCard!).getByText("API key")).toBeInTheDocument();
    expect(within(apiCard!).getByText("remote egress")).toBeInTheDocument();
    expect(within(apiCard!).getByText("api billing")).toBeInTheDocument();
    expect(screen.getAllByText("Account plan").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Local runtime").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Custom endpoint").length).toBeGreaterThan(0);
    expect(document.querySelector('input[type="password"]')).toBeNull();

    await user.click(within(apiCard!).getByRole("button", { name: "Test connection" }));
    await waitFor(() => expect(apiMocks.testModelConnection).toHaveBeenCalledWith("openai-api", "openai/gpt-5"));
    expect(await within(apiCard!).findByRole("status")).toHaveTextContent("Connected · 3 tokens");
  });
});

describe("agent model routing", () => {
  it("creates an agent with an explicit account-plan connection and model", async () => {
    const user = userEvent.setup();
    render(<AgentForm onClose={vi.fn()} />);

    await screen.findByRole("option", { name: /OpenAI API/ });
    await user.type(screen.getByLabelText("Agent name"), "Mira");
    await user.type(screen.getByLabelText("Role"), "Evidence analyst");
    await user.selectOptions(screen.getByLabelText("Model connection"), "claude-subscription");
    expect(screen.getByLabelText("Model")).toHaveValue("sonnet");
    await user.type(screen.getByRole("textbox", { name: /^Mission/ }), "Review evidence carefully.");

    const create = screen.getByRole("button", { name: "Create agent" });
    await waitFor(() => expect(create).toBeEnabled());
    await user.click(create);

    await waitFor(() => expect(apiMocks.createLabEntity).toHaveBeenCalled());
    expect(apiMocks.createLabEntity).toHaveBeenCalledWith("agents", expect.objectContaining({
      model_connection: "claude-subscription",
      model: "sonnet",
    }));
  });

  it("updates both route and model on an existing duty card", async () => {
    const user = userEvent.setup();
    const agent: Agent = {
      id: "agent-1",
      department_id: "group-1",
      name: "Mira",
      role: "Evidence analyst",
      mission: "Review evidence carefully.",
      duties: [],
      focus: [],
      priorities: [],
      model_connection: "claude-subscription",
      model: "sonnet",
      status: "active",
      communication_scope: "department",
    };
    render(<AgentInspector agent={agent} />);

    await screen.findByRole("option", { name: /OpenAI API/ });
    await user.selectOptions(screen.getByLabelText("Model connection"), "openai-api");
    expect(screen.getByLabelText("Model")).toHaveValue("openai/gpt-5");
    await user.click(screen.getByRole("button", { name: "Save duty card" }));

    await waitFor(() => expect(apiMocks.updateLabEntity).toHaveBeenCalled());
    expect(apiMocks.updateLabEntity).toHaveBeenCalledWith("agents", "agent-1", expect.objectContaining({
      model_connection: "openai-api",
      model: "openai/gpt-5",
    }));
  });
});
