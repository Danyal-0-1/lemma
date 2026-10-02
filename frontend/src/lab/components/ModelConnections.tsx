import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { getModelConnections, testModelConnection } from "../../lib/api";
import { Field, Badge, Button } from "./UI";
import type {
  ModelConnection,
  ModelConnectionCatalog,
  ModelConnectionKind,
  ModelConnectionTestResult,
} from "../types";

const CONNECTION_KINDS: Array<{
  kind: Exclude<ModelConnectionKind, "legacy">;
  label: string;
  detail: string;
}> = [
  { kind: "api_key", label: "API key", detail: "Usage is billed separately by the API provider." },
  { kind: "subscription", label: "Account plan", detail: "Uses an eligible signed-in CLI or account allowance." },
  { kind: "local", label: "Local runtime", detail: "Runs on this computer through a verified loopback endpoint." },
  { kind: "custom", label: "Custom endpoint", detail: "Billing and data handling depend on the server you choose." },
];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The model connection request failed.";
}

export function connectionKindLabel(kind: ModelConnectionKind): string {
  return CONNECTION_KINDS.find((item) => item.kind === kind)?.label ?? "Legacy route";
}

export function isSelectableConnection(connection: ModelConnection): boolean {
  return connection.status === "ready" || connection.status === "available";
}

function statusTone(status: ModelConnection["status"]): string {
  if (status === "ready") return "ok";
  if (status === "available") return "warn";
  if (status === "error") return "err";
  return "neutral";
}

function statusLabel(connection: ModelConnection): string {
  if (connection.status === "available") {
    return connection.kind === "subscription"
      ? "available · test login first"
      : "available · test first";
  }
  return connection.status.replaceAll("_", " ");
}

export function useModelConnections() {
  const [catalog, setCatalog] = useState<ModelConnectionCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCatalog(await getModelConnections());
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);
  return { catalog, loading, error, reload };
}

export function ModelConnectionsPanel() {
  const { catalog, loading, error, reload } = useModelConnections();
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testModels, setTestModels] = useState<Record<string, string>>({});
  const [testResults, setTestResults] = useState<Record<string, ModelConnectionTestResult>>({});
  const [testErrors, setTestErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!catalog) return;
    setTestModels((current) => {
      const next = { ...current };
      for (const connection of catalog.connections) {
        if (!next[connection.id]) next[connection.id] = connection.models[0]?.id ?? "";
      }
      return next;
    });
  }, [catalog]);

  async function test(connection: ModelConnection) {
    const model = testModels[connection.id]?.trim() ?? "";
    if (!model) return;
    setTestingId(connection.id);
    setTestErrors((current) => ({ ...current, [connection.id]: "" }));
    try {
      const result = await testModelConnection(connection.id, model);
      setTestResults((current) => ({ ...current, [connection.id]: result }));
      if (!result.ok) {
        setTestErrors((current) => ({ ...current, [connection.id]: result.message }));
      }
      await reload();
    } catch (requestError) {
      setTestErrors((current) => ({ ...current, [connection.id]: errorMessage(requestError) }));
    } finally {
      setTestingId(null);
    }
  }

  return (
    <section className="shell-model-settings" aria-labelledby="model-connections-title">
      <h3 id="model-connections-title">Models and connections</h3>
      <p>Connections are configured by the local backend. Lemma never sends provider secrets to this browser.</p>
      <div className="shell-model-legend" aria-label="Connection types">
        {CONNECTION_KINDS.map((item) => (
          <div key={item.kind}>
            <Badge>{item.label}</Badge>
            <small>{item.detail}</small>
          </div>
        ))}
      </div>
      {catalog?.mock_mode && (
        <div className="shell-model-mode is-local">
          <strong>Mock mode is active</strong>
          <span>Research runs stay on the local mock until you set <code>MOCK_LLM=false</code> and restart. A connection test still calls the selected route.</span>
        </div>
      )}
      <p className="shell-model-test-note">Testing makes one small model request. API and custom routes may charge for it.</p>
      {loading && !catalog && <p className="shell-model-loading" role="status">Checking model connections…</p>}
      {error && !catalog && <div className="shell-model-error" role="alert"><span>{error}</span><Button onClick={() => void reload()}>Retry</Button></div>}
      <div className="shell-model-grid">
        {catalog?.connections.map((connection) => {
          const canTest = isSelectableConnection(connection) && Boolean(testModels[connection.id]?.trim());
          const testError = testErrors[connection.id];
          const result = testResults[connection.id];
          return (
            <article key={connection.id} className={`shell-model-card is-${connection.status}`}>
              <header>
                <div><strong>{connection.name}</strong><small>{connection.provider} · {connection.auth_mode}</small></div>
                <Badge tone={statusTone(connection.status)}>{statusLabel(connection)}</Badge>
              </header>
              <p>{connection.detail}</p>
              <div className="shell-model-boundaries">
                <Badge>{connectionKindLabel(connection.kind)}</Badge>
                <Badge tone={connection.egress === "local" ? "ok" : "warn"}>{connection.egress.replaceAll("_", " ")} egress</Badge>
                <Badge>{connection.billing} billing</Badge>
              </div>
              <div className="shell-model-setup"><strong>Setup</strong><span>{connection.setup}</span></div>
              <label className="shell-model-test-field">
                <span>Model for connection test</span>
                <input
                  list={`connection-models-${connection.id}`}
                  value={testModels[connection.id] ?? ""}
                  onChange={(event) => {
                    setTestModels((current) => ({ ...current, [connection.id]: event.target.value }));
                    setTestResults((current) => {
                      const next = { ...current };
                      delete next[connection.id];
                      return next;
                    });
                    setTestErrors((current) => ({ ...current, [connection.id]: "" }));
                  }}
                  placeholder={connection.supports_custom_model ? "Enter a model ID" : "Choose a configured model"}
                  disabled={!isSelectableConnection(connection)}
                />
                <datalist id={`connection-models-${connection.id}`}>
                  {connection.models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}
                </datalist>
              </label>
              <footer>
                <small>{connection.models.length} configured model{connection.models.length === 1 ? "" : "s"}</small>
                <Button onClick={() => void test(connection)} disabled={!canTest || testingId !== null}>
                  {testingId === connection.id ? "Testing…" : "Test connection"}
                </Button>
              </footer>
              {testError && <p className="shell-model-result is-error" role="alert">{testError}</p>}
              {!testError && result?.ok && (
                <p className="shell-model-result is-success" role="status">
                  {result.message} · {result.tokens_in + result.tokens_out} tokens
                </p>
              )}
            </article>
          );
        })}
      </div>
      {catalog && catalog.connections.length === 0 && <p className="shell-model-loading">No model connections are available in this build.</p>}
    </section>
  );
}

export function ModelRouteFields({
  connectionId,
  model,
  onConnectionChange,
  onModelChange,
  onValidityChange,
  preserveSavedRoute = false,
}: {
  connectionId: string;
  model: string;
  onConnectionChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onValidityChange?: (valid: boolean) => void;
  preserveSavedRoute?: boolean;
}) {
  const { catalog, loading, error, reload } = useModelConnections();
  const listId = useId();
  const savedRoute = useRef({ connectionId, model });
  const connections = catalog?.connections ?? [];
  const selected = connections.find((connection) => connection.id === connectionId) ?? null;
  const selectable = useMemo(
    () => connections.filter(isSelectableConnection),
    [connections],
  );
  const selectedIsUsable = selected ? isSelectableConnection(selected) : false;
  const savedRouteUnavailable = preserveSavedRoute
    && Boolean(connectionId)
    && !selectedIsUsable
    && connectionId === savedRoute.current.connectionId;
  const preserved = preserveSavedRoute
    && connectionId === savedRoute.current.connectionId
    && model === savedRoute.current.model;
  const knownModel = selected?.models.some((item) => item.id === model) ?? false;
  const valid = Boolean(connectionId && model.trim())
    && (preserved || Boolean(selected && selectedIsUsable && (selected.supports_custom_model || knownModel)));

  useEffect(() => { onValidityChange?.(valid); }, [onValidityChange, valid]);

  useEffect(() => {
    if (!catalog || connectionId || selectable.length === 0) return;
    const preferred = catalog.mock_mode
      ? selectable.find((connection) => connection.id === "mock")
      : selectable.find((connection) => (
        connection.id !== "mock"
        && connection.id !== "legacy"
        && connection.status === "ready"
      ));
    const initial = preferred ?? selectable.find((connection) => connection.id === "mock") ?? selectable[0];
    onConnectionChange(initial.id);
    onModelChange(initial.models[0]?.id ?? "");
  }, [catalog, connectionId, onConnectionChange, onModelChange, selectable]);

  function chooseConnection(nextId: string) {
    const next = connections.find((connection) => connection.id === nextId);
    onConnectionChange(nextId);
    onModelChange(next?.models[0]?.id ?? "");
  }

  const hint = selected
    ? `${connectionKindLabel(selected.kind)} · ${selected.billing} billing · ${selected.egress.replaceAll("_", " ")} egress${selected.status === "available" ? selected.kind === "subscription" ? " · test login first in Settings → Models" : " · test this route in Settings → Models" : ""}`
    : savedRouteUnavailable
      ? "This saved route is no longer available. Keep it unchanged or choose an available connection."
      : "Choose where this agent's prompts are processed and billed.";

  return (
    <>
      <Field label="Model connection" hint={hint}>
        <select
          required
          aria-label="Model connection"
          value={connectionId}
          onChange={(event) => chooseConnection(event.target.value)}
          disabled={loading && !catalog}
        >
          <option value="" disabled>{loading ? "Checking connections…" : "Select a connection"}</option>
          {savedRouteUnavailable && <option value={connectionId}>Current saved route · unavailable</option>}
          {selectable.map((connection) => (
            <option key={connection.id} value={connection.id}>
              [{connectionKindLabel(connection.kind)}] {connection.name}{connection.status === "available" ? connection.kind === "subscription" ? " · test login first" : " · test first" : ""}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Model" hint={selected?.supports_custom_model ? "Choose a discovered model or enter the exact custom model ID." : "Select a model offered by this connection."}>
        <input
          required
          aria-label="Model"
          list={listId}
          value={model}
          onChange={(event) => onModelChange(event.target.value)}
          placeholder={selected?.supports_custom_model ? "Enter a model ID" : "Choose a model"}
          disabled={!connectionId || savedRouteUnavailable || (!selected && !preserved)}
        />
        <datalist id={listId}>
          {selected?.models.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </datalist>
      </Field>
      {error && <p className="lab-inline-error lab-field-span-2" role="alert">Could not load model connections: {error} <button type="button" onClick={() => void reload()}>Retry</button></p>}
    </>
  );
}
