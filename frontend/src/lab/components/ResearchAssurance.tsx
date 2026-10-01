import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  acceptAssuredTask,
  approveResearchProtocol,
  createResearchProtocol,
  downloadResearchCapsule,
  getProjectDossier,
  getTaskAssurance,
  listResearchProtocols,
  verifyResearchCapsule,
  withdrawResearchProtocol,
} from "../../lib/api";
import { errorMessage, useAsyncAction } from "../../lib/asyncAction";
import { Icon } from "./Icons";
import { Badge, Button, Field, Modal, StatusBadge } from "./UI";
import { useLabStore } from "../store";
import type {
  Project,
  ProjectDossier,
  ResearchProtocol,
  ResearchTask,
  TaskAssurance,
} from "../types";

const CAPSULE_MAX_BYTES = 50_000_000;

function percent(value: number): number {
  const normalized = value <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, Math.round(normalized)));
}

function nonemptyLines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function ProtocolForm({
  project,
  initial,
  onClose,
  onSaved,
}: {
  project: Project;
  initial: ResearchProtocol | null;
  onClose: () => void;
  onSaved: (protocol: ResearchProtocol) => void;
}) {
  const [question, setQuestion] = useState(initial?.question ?? project.objective);
  const [hypothesis, setHypothesis] = useState(initial?.hypothesis ?? "");
  const [method, setMethod] = useState(initial?.method ?? "Use supplied sources, extract exact evidence, compare counter-evidence, and report uncertainty.");
  const [acceptanceCriteria, setAcceptanceCriteria] = useState(
    initial?.acceptance_criteria.join("\n")
      ?? "Every material claim links to exact supporting evidence.\nContradictory evidence is resolved or explicitly reflected in the conclusion.\nA human review of the findings is recorded.",
  );
  const [limitations, setLimitations] = useState(initial?.limitations.join("\n") ?? "");
  const action = useAsyncAction({ fallbackError: "Could not save the research protocol." });
  const criteriaEntries = nonemptyLines(acceptanceCriteria);
  const limitationEntries = nonemptyLines(limitations);
  const entriesValid = criteriaEntries.length > 0
    && criteriaEntries.length <= 20
    && criteriaEntries.every((item) => item.length <= 200)
    && new Set(criteriaEntries).size === criteriaEntries.length
    && limitationEntries.length <= 20
    && limitationEntries.every((item) => item.length <= 1_000)
    && new Set(limitationEntries).size === limitationEntries.length;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(() => createResearchProtocol(project.id, {
      question,
      hypothesis,
      method,
      acceptance_criteria: criteriaEntries,
      limitations: limitationEntries,
      created_by: "founder",
    }));
    if (result.ok) {
      onSaved(result.value);
      onClose();
    }
  }

  return (
    <form className="lab-form" aria-busy={action.pending} onSubmit={(event) => void submit(event)}>
      <Field label="Research question" hint="The decision or uncertainty this project must resolve.">
        <textarea required maxLength={20_000} rows={3} value={question} onChange={(event) => setQuestion(event.target.value)} autoFocus />
      </Field>
      <Field label="Hypothesis" hint="State what you currently expect so contrary evidence stays visible.">
        <textarea required maxLength={20_000} rows={3} value={hypothesis} onChange={(event) => setHypothesis(event.target.value)} />
      </Field>
      <Field label="Method" hint="How sources, comparisons, and uncertainty will be handled.">
        <textarea required maxLength={20_000} rows={4} value={method} onChange={(event) => setMethod(event.target.value)} />
      </Field>
      <Field label="Acceptance criteria" hint="One condition per line; up to 20 concise conditions.">
        <textarea required maxLength={20_000} rows={4} value={acceptanceCriteria} onChange={(event) => setAcceptanceCriteria(event.target.value)} />
      </Field>
      <Field label="Known limitations" hint="Optional; one limitation per line.">
        <textarea maxLength={20_000} rows={3} value={limitations} onChange={(event) => setLimitations(event.target.value)} />
      </Field>
      {!entriesValid && <p className="lab-inline-error" role="alert">Use 1–20 unique acceptance criteria (200 characters each) and no more than 20 unique limitations.</p>}
      {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}
      <div className="lab-form-actions">
        <Button onClick={onClose} disabled={action.pending}>Cancel</Button>
        <Button
          type="submit"
          variant="primary"
          disabled={action.pending || !question.trim() || !hypothesis.trim() || !method.trim() || !entriesValid}
        >
          {action.pending ? "Saving…" : "Save draft"}
        </Button>
      </div>
    </form>
  );
}

interface AssuranceStep {
  id: "protocol" | "sources" | "evidence" | "review" | "capsule";
  label: string;
  detail: string;
  complete: boolean;
}

export function assuranceSteps({
  protocolApproved,
  sourceCount,
  linkedSourceCount = sourceCount,
  assurance,
  capsuleDownloaded,
}: {
  protocolApproved: boolean;
  sourceCount: number;
  linkedSourceCount?: number;
  assurance: TaskAssurance | null;
  capsuleDownloaded: boolean;
}): AssuranceStep[] {
  const coverage = percent(assurance?.coverage.coverage_percent ?? 0);
  const evidenceComplete = Boolean(
    assurance
    && assurance.coverage.total_claims > 0
    && assurance.coverage.unsupported_claims === 0
    && assurance.coverage.contradicted_claims === 0
    && coverage === 100,
  );
  const reviewComplete = assurance?.status === "accepted";
  return [
    { id: "protocol", label: "Protocol", detail: "Freeze scope", complete: protocolApproved },
    {
      id: "sources",
      label: "Sources",
      detail: linkedSourceCount > sourceCount
        ? `${sourceCount} used / ${linkedSourceCount} linked`
        : `${sourceCount} attached`,
      complete: sourceCount > 0,
    },
    { id: "evidence", label: "Evidence", detail: `${coverage}% covered`, complete: evidenceComplete },
    { id: "review", label: "Review", detail: reviewComplete ? "Accepted" : "Human gate", complete: reviewComplete },
    { id: "capsule", label: "Capsule", detail: capsuleDownloaded ? "Project exported" : "Project snapshot", complete: capsuleDownloaded },
  ];
}

export default function ResearchAssurance({
  project,
  task,
}: {
  project: Project;
  task: ResearchTask | null;
}) {
  const [protocols, setProtocols] = useState<ResearchProtocol[]>([]);
  const [dossier, setDossier] = useState<ProjectDossier | null>(null);
  const [assurance, setAssurance] = useState<TaskAssurance | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [protocolModal, setProtocolModal] = useState<"create" | "review" | null>(null);
  const [acceptModal, setAcceptModal] = useState(false);
  const [confirmedCriteria, setConfirmedCriteria] = useState<string[]>([]);
  const [acceptanceNotes, setAcceptanceNotes] = useState("");
  const [capsuleDownloaded, setCapsuleDownloaded] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const verifyInput = useRef<HTMLInputElement>(null);
  const loadSequence = useRef(0);
  const action = useAsyncAction({ fallbackError: "The assurance action failed." });

  const latestProtocol = useMemo(
    () => [...protocols].sort((left, right) => right.version - left.version)[0] ?? null,
    [protocols],
  );
  const approvedProtocol = latestProtocol?.status === "approved"
    ? latestProtocol
    : protocols.find((protocol) => protocol.status === "approved") ?? null;
  const reviewProtocol = latestProtocol?.status === "draft"
    ? latestProtocol
    : approvedProtocol ?? latestProtocol;
  const activeSourceIds = new Set(
    dossier?.sources.filter((source) => source.status === "active").map((source) => source.id)
      ?? [],
  );
  const sourceCount = task
    ? dossier?.source_links.filter((link) => (
      link.task_id === task.id && activeSourceIds.has(link.source_id)
    )).length ?? 0
    : 0;
  const runtimeSourceCount = assurance?.coverage.source_packet_count
    ?? Math.min(sourceCount, 24);
  const steps = assuranceSteps({
    protocolApproved: Boolean(approvedProtocol && latestProtocol?.status !== "draft"),
    sourceCount: runtimeSourceCount,
    linkedSourceCount: sourceCount,
    assurance,
    capsuleDownloaded,
  });
  const currentStep = steps.find((step) => !step.complete) ?? steps.at(-1)!;
  const completedCount = steps.filter((step) => step.complete).length;
  const acceptanceCriteria = assurance?.protocol?.acceptance_criteria
    ?? approvedProtocol?.acceptance_criteria
    ?? [];
  const allCriteriaConfirmed = acceptanceCriteria.length > 0
    && acceptanceCriteria.every((criterion) => confirmedCriteria.includes(criterion));

  async function load() {
    const sequence = ++loadSequence.current;
    setLoading(true);
    setLoadError(null);
    try {
      const [nextProtocols, nextDossier, nextAssurance] = await Promise.all([
        listResearchProtocols(project.id),
        getProjectDossier(project.id),
        task ? getTaskAssurance(task.id) : Promise.resolve(null),
      ]);
      if (sequence !== loadSequence.current) return;
      setProtocols(nextProtocols);
      setDossier(nextDossier);
      setAssurance(nextAssurance);
    } catch (error) {
      if (sequence !== loadSequence.current) return;
      setLoadError(errorMessage(error, "Could not load research assurance."));
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }

  useEffect(() => {
    setCapsuleDownloaded(false);
    setNotice(null);
    setAcceptModal(false);
    setConfirmedCriteria([]);
    setAcceptanceNotes("");
    void load();
    // Material edits and completed runs can change the gate without changing record IDs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return () => { loadSequence.current += 1; };
  }, [project.id, project.objective, task?.id, task?.status, task?.updated_at]);

  async function approveProtocol() {
    if (!latestProtocol || latestProtocol.status !== "draft") return;
    const result = await action.run(() => approveResearchProtocol(latestProtocol.id));
    if (result.ok) {
      setNotice("Protocol approved. The research scope is now frozen for this version.");
      setProtocolModal(null);
      await load();
    }
  }

  async function withdrawProtocol() {
    if (!latestProtocol || latestProtocol.status !== "draft") return;
    const result = await action.run(() => withdrawResearchProtocol(latestProtocol.id));
    if (result.ok) {
      setNotice("Draft withdrawn with its audit history preserved. You can now create a corrected version.");
      setProtocolModal(null);
      await load();
    }
  }

  async function acceptTask() {
    if (!task || !allCriteriaConfirmed) return;
    const result = await action.run(() => acceptAssuredTask(
      task.id,
      acceptanceCriteria,
      acceptanceNotes,
    ));
    if (result.ok) {
      setAssurance(result.value);
      setNotice("Research accepted after passing the evidence gate.");
      setAcceptModal(false);
      setConfirmedCriteria([]);
      setAcceptanceNotes("");
      await useLabStore.getState().refresh();
    }
  }

  async function exportCapsule() {
    const result = await action.run(() => downloadResearchCapsule(project.id));
    if (result.ok) {
      setCapsuleDownloaded(true);
      setNotice("Project capsule exported with each task's accepted or blocked assurance status. It can be verified without running Lemma.");
    }
  }

  async function verifyCapsule(file: File) {
    if (file.size > CAPSULE_MAX_BYTES) {
      setNotice("That capsule is larger than the 50 MB verification limit.");
      return;
    }
    const result = await action.run(async () => {
      const payload = JSON.parse(await file.text()) as unknown;
      return await verifyResearchCapsule(payload);
    });
    if (result.ok) {
      const digest = result.value.manifest_sha256?.slice(0, 12);
      setNotice(result.value.valid
        ? `Capsule verified.${digest ? ` Manifest ${digest} matches its contents.` : ""}`
        : `Capsule verification failed: ${result.value.errors.join("; ") || "integrity mismatch"}`);
    }
    if (verifyInput.current) verifyInput.current.value = "";
  }

  function openEvidence() {
    useLabStore.getState().setView("knowledge");
  }

  const blockerSummary = assurance?.issues.slice(0, 2).join(" · ") ?? "";
  const firstFailedCheck = assurance?.checks.find((check) => !check.passed) ?? null;
  const needsResearchRun = [
    "completed_run",
    "protocol_before_run",
    "source_packet_before_run",
    "source_packet_run_binding",
    "run_input_snapshot",
    "task_result",
    "task_result_binding",
    "model_call_provenance",
    "protocol_run_binding",
    "findings_present",
  ].includes(
    firstFailedCheck?.code ?? "",
  );
  const needsProtocolRevision = ["protocol_scope", "protocol_integrity"].includes(
    firstFailedCheck?.code ?? "",
  );
  const policyNeedsAttention = dossier?.policy.data_classification === "confidential"
    && dossier.policy.allowed_models.length === 0;

  return (
    <section className="lab-assurance" aria-busy={loading}>
      <header className="lab-assurance-header">
        <span className="lab-assurance-mark"><Icon name="security" size={18} /></span>
        <div>
          <div className="lab-assurance-title">
            <h2>Research assurance</h2>
            <Badge tone={completedCount === steps.length ? "ok" : "neutral"}>{completedCount}/{steps.length}</Badge>
          </div>
          <p>One guided path from an approved question to evidence you can verify.</p>
        </div>
        <Button
          variant="ghost"
          icon="refresh"
          aria-label="Refresh research assurance"
          title="Refresh research assurance"
          disabled={loading || action.pending}
          onClick={() => void load()}
        />
        <Button
          variant="ghost"
          aria-expanded={detailsOpen}
          onClick={() => setDetailsOpen((open) => !open)}
        >
          {detailsOpen ? "Hide details" : "Details"}
          <Icon name={detailsOpen ? "chevronDown" : "chevronRight"} size={13} />
        </Button>
      </header>

      <ol className="lab-assurance-steps" aria-label="Research assurance pipeline">
        {steps.map((step) => (
          <li
            key={step.id}
            className={step.complete ? "is-complete" : currentStep.id === step.id ? "is-current" : ""}
            aria-current={currentStep.id === step.id ? "step" : undefined}
          >
            <span>{step.complete ? <Icon name="check" size={12} /> : steps.indexOf(step) + 1}</span>
            <div><strong>{step.label}</strong><small>{step.detail}</small></div>
          </li>
        ))}
      </ol>

      <div className="lab-assurance-next">
        {loading ? (
          <p role="status"><span className="lab-spinner" /> Checking the pipeline…</p>
        ) : loadError ? (
          <><p className="lab-inline-error" role="alert">{loadError}</p><Button icon="refresh" onClick={() => void load()}>Retry</Button></>
        ) : latestProtocol?.status === "draft" ? (
          <>
            <div><strong>Next: approve protocol v{latestProtocol.version}</strong><small>Approval freezes the question, method, and evidence threshold before execution.</small></div>
            <Button variant="primary" onClick={() => setProtocolModal("review")}>Review &amp; approve</Button>
          </>
        ) : !approvedProtocol ? (
          <>
            <div><strong>Next: define the research protocol</strong><small>Write the question, hypothesis, method, and acceptance criteria once.</small></div>
            <Button variant="primary" onClick={() => setProtocolModal("create")}>Define protocol</Button>
          </>
        ) : !task ? (
          <div><strong>Next: select a work package</strong><small>The evidence gate is evaluated for one task at a time.</small></div>
        ) : runtimeSourceCount === 0 ? (
          <>
            <div><strong>Next: attach trusted sources</strong><small>Give {task.title} an explicit source packet before relying on its output.</small></div>
            <Button variant="primary" onClick={openEvidence}>Open sources</Button>
          </>
        ) : assurance && !assurance.ready && assurance.status !== "accepted" ? (
          <>
            <div>
              <strong>{needsResearchRun ? "Next: run under the approved protocol" : needsProtocolRevision ? "Next: revise the protocol" : "Next: close the evidence gaps"}</strong>
              <small>{firstFailedCheck?.message || blockerSummary || "Every material claim needs exact evidence and a human decision."}</small>
            </div>
            {needsResearchRun ? (
              <span className="lab-assurance-hint">Use “Run research” in the work package panel.</span>
            ) : needsProtocolRevision ? (
              <Button variant="primary" onClick={() => setProtocolModal("create")}>Create revision</Button>
            ) : (
              <Button variant="primary" onClick={openEvidence}>Review evidence</Button>
            )}
          </>
        ) : assurance && assurance.status !== "accepted" ? (
          <>
            <div><strong>Ready for human acceptance</strong><small>Structural checks passed; confirm the protocol-specific criteria before accepting.</small></div>
            <Button variant="primary" disabled={action.pending} onClick={() => { setConfirmedCriteria([]); setAcceptanceNotes(""); setAcceptModal(true); }}>Review &amp; accept</Button>
          </>
        ) : (
          <>
            <div><strong>{capsuleDownloaded ? "Selected task complete" : "Next: export the project capsule"}</strong><small>Bundle every task's assurance status with the protocols, sources, hashes, claims, prompts, and decisions.</small></div>
            <Button variant="primary" disabled={action.pending} onClick={() => void exportCapsule()}>Export project capsule</Button>
            <Button disabled={action.pending} onClick={() => verifyInput.current?.click()}>Verify capsule</Button>
            <input
              ref={verifyInput}
              className="lab-visually-hidden"
              type="file"
              accept="application/json,.json"
              aria-label="Choose a research capsule to verify"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void verifyCapsule(file);
              }}
            />
          </>
        )}
      </div>

      {detailsOpen && (
        <div className="lab-assurance-details">
          <div>
            <span>Protocol</span>
            <strong>{reviewProtocol ? `v${reviewProtocol.version} · ${reviewProtocol.status}` : "Not defined"}</strong>
            {reviewProtocol?.content_sha256 && <code title={reviewProtocol.content_sha256}>{reviewProtocol.content_sha256.slice(0, 12)}</code>}
            {latestProtocol?.status === "withdrawn" && <small>latest draft v{latestProtocol.version} was withdrawn</small>}
          </div>
          <div><span>Sources</span><strong>{runtimeSourceCount} / {sourceCount}</strong><small>used at runtime / linked</small></div>
          <div><span>Claim coverage</span><strong>{percent(assurance?.coverage.coverage_percent ?? 0)}%</strong><small>{assurance?.coverage.unsupported_claims ?? 0} unsupported</small></div>
          <div><span>Contradictions</span><strong>{assurance?.coverage.contradicted_claims ?? 0}</strong><small>must be resolved</small></div>
          <div><span>Human review</span><StatusBadge status={assurance?.status ?? "pending"} /><small>server-enforced gate</small></div>
          {approvedProtocol && (
            <div className="lab-inline-actions">
              <Button variant="ghost" onClick={() => setProtocolModal("review")}>View protocol</Button>
              {latestProtocol?.status !== "draft" && <Button variant="ghost" onClick={() => setProtocolModal("create")}>Create new version</Button>}
            </div>
          )}
          {assurance && assurance.issues.length > 0 && (
            <ul>{assurance.issues.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>
          )}
        </div>
      )}

      {dossier && (
        <div className={`lab-assurance-policy ${policyNeedsAttention ? "is-attention" : ""}`}>
          <Icon name={policyNeedsAttention ? "warning" : "security"} size={13} />
          <span>
            {dossier.policy.data_classification === "local_only"
              ? "Local-only egress is enforced for mock models or IDs explicitly attested in LEMMA_LOCAL_MODEL_IDS."
              : dossier.policy.data_classification === "confidential"
                ? "Confidential research requires an explicit model allowlist before data can leave the machine."
                : "Public classification still follows the project's model allowlist and spend controls."}
          </span>
          {policyNeedsAttention && <Button variant="ghost" onClick={() => useLabStore.getState().setView("operations")}>Review policy</Button>}
        </div>
      )}

      {notice && <p className={notice.includes("failed") || notice.includes("larger") ? "lab-inline-error" : "lab-inline-success"} role="status">{notice}</p>}
      {action.error && <p className="lab-inline-error" role="alert">{action.error}</p>}

      {acceptModal && assurance?.protocol && (
        <Modal
          title={`Accept ${task?.title ?? "research"}`}
          description="The server has checked provenance and evidence structure. Your confirmation records the protocol-specific judgment."
          onClose={() => setAcceptModal(false)}
        >
          <div className="lab-acceptance-review">
            <section>
              <h3>Acceptance criteria</h3>
              <div className="lab-criteria-checklist">
                {acceptanceCriteria.map((criterion) => (
                  <label key={criterion}>
                    <input
                      type="checkbox"
                      checked={confirmedCriteria.includes(criterion)}
                      onChange={(event) => setConfirmedCriteria((current) => event.target.checked
                        ? [...current, criterion]
                        : current.filter((item) => item !== criterion))}
                    />
                    <span>{criterion}</span>
                  </label>
                ))}
              </div>
            </section>
            {assurance.protocol.limitations.length > 0 && (
              <section><h3>Known limitations</h3><ul>{assurance.protocol.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></section>
            )}
            <Field label="Acceptance note" hint="Optional: record why the evidence meets the criteria or what remains uncertain.">
              <textarea rows={3} maxLength={20_000} value={acceptanceNotes} onChange={(event) => setAcceptanceNotes(event.target.value)} />
            </Field>
          </div>
          <div className="lab-form-actions">
            <Button onClick={() => setAcceptModal(false)} disabled={action.pending}>Cancel</Button>
            <Button variant="primary" disabled={action.pending || !allCriteriaConfirmed} onClick={() => void acceptTask()}>
              {action.pending ? "Accepting…" : `Accept (${confirmedCriteria.length}/${acceptanceCriteria.length})`}
            </Button>
          </div>
        </Modal>
      )}

      {protocolModal === "create" && (
        <Modal
          title={latestProtocol ? `Research protocol v${latestProtocol.version + 1}` : "Research protocol"}
          description="Saving creates a reviewable draft. Approval is a separate, explicit gate."
          onClose={() => setProtocolModal(null)}
        >
          <ProtocolForm
            project={project}
            initial={latestProtocol}
            onClose={() => setProtocolModal(null)}
            onSaved={(protocol) => {
              setProtocols((current) => [...current, protocol]);
              setNotice("Protocol draft saved. Review it before approval.");
            }}
          />
        </Modal>
      )}
      {protocolModal === "review" && reviewProtocol && (
        <Modal
          title={`Review protocol v${reviewProtocol.version}`}
          description="Approval freezes this exact content hash. Create a new version for later changes."
          onClose={() => setProtocolModal(null)}
        >
          <div className="lab-protocol-review">
            <section><h3>Research question</h3><p>{reviewProtocol.question}</p></section>
            <section><h3>Hypothesis</h3><p>{reviewProtocol.hypothesis}</p></section>
            <section><h3>Method</h3><p>{reviewProtocol.method}</p></section>
            <section><h3>Acceptance criteria</h3><ul>{reviewProtocol.acceptance_criteria.map((criterion) => <li key={criterion}>{criterion}</li>)}</ul></section>
            {reviewProtocol.limitations.length > 0 && <section><h3>Known limitations</h3><ul>{reviewProtocol.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></section>}
            <code>{reviewProtocol.content_sha256}</code>
          </div>
          <div className="lab-form-actions">
            <Button onClick={() => setProtocolModal(null)}>Close</Button>
            {reviewProtocol.status === "draft" && (
              <>
                <Button variant="danger" disabled={action.pending} onClick={() => void withdrawProtocol()}>Withdraw draft</Button>
                <Button variant="primary" disabled={action.pending} onClick={() => void approveProtocol()}>Approve exact protocol</Button>
              </>
            )}
          </div>
        </Modal>
      )}
    </section>
  );
}
