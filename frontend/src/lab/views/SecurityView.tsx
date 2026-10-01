// Honest threat-model dashboard: enforced controls, boundaries, and known limitations.

import { Icon } from "../components/Icons";
import { AgentAvatar, Badge } from "../components/UI";
import { useLabStore } from "../store";
import { useAppStore } from "../../store/appStore";

const CONTROLS = [
  { title: "Research agents", state: "enforced", detail: "Prompt-only. No shell, filesystem, browser tool, connector, environment, or secret capability." },
  { title: "Agent communication", state: "enforced", detail: "Explicit isolated, same-group, or organization scope. Every meeting roster is checked before execution." },
  { title: "Meeting protocol", state: "bounded", detail: "One contribution per selected participant, followed by one facilitator synthesis. No recursive free-chat loop." },
  { title: "Browser boundary", state: "local", detail: "Loopback peer, trusted Host, exact Origin checks, deny-framing headers, and a local CSP protect the browser boundary." },
  { title: "Child credentials", state: "filtered", detail: "Optional human tools receive a minimal allowlisted environment; provider and cloud credentials are not copied." },
  { title: "Evidence provenance", state: "durable", detail: "Captured source hashes, exact excerpts, human reviews, claim/evidence stance, trace links, and model-call prompts are retained locally." },
  { title: "Project governance", state: "bounded", detail: "Model allowlists, cumulative per-run budgets, project spend ceilings, concurrency, cancellation, and retry lineage are enforced; classification is an explicit audit label." },
  { title: "Research verification", state: "manual", detail: "Automatic browsing is intentionally absent. Model syntheses must be checked against sources before use." },
];

export default function SecurityView() {
  const agents = useLabStore((state) => state.snapshot.agents);
  const groups = useLabStore((state) => state.snapshot.departments);
  const hostExecution = useAppStore((state) => state.hostExecutionEnabled);
  const headlessCoding = useAppStore((state) => state.headlessCodingEnabled);
  const executionEnabled = hostExecution || headlessCoding;
  return (
    <main className="lab-view lab-security-view">
      <header className="lab-page-header"><div><span className="lab-eyebrow">TRUST & CAPABILITIES</span><h1>Security center</h1><p>Permissions are enforced in code and kept separate from anything an agent says in a prompt.</p></div><Badge tone={executionEnabled ? "err" : "ok"}>{executionEnabled ? "EXECUTION SWITCH ON" : "SAFE DEFAULT"}</Badge></header>
      <section className={`lab-security-banner ${hostExecution ? "is-warn" : "is-safe"}`}><Icon name={hostExecution ? "warning" : "security"} size={24} /><div><h2>{hostExecution ? "Human host execution is enabled" : "Host execution is locked"}</h2><p>{hostExecution ? "The Workbench terminal and checks run as your OS user. They are not a sandbox and remain unavailable to research agents." : "Terminal, checks, editor launch, and file-manager launch are denied by the backend until ENABLE_HOST_EXECUTION=true is set intentionally."}</p></div></section>
      <section className={`lab-security-banner ${headlessCoding ? "is-warn" : "is-safe"}`}><Icon name={headlessCoding ? "warning" : "security"} size={24} /><div><h2>{headlessCoding ? "Headless coding switch is enabled" : "Headless coding is independently locked"}</h2><p>{headlessCoding ? "Every job still needs a persisted human approval, an active workspace, and the validated CLI path. The external process is not a sandbox; inspect its diff and billing mode." : "M9 cannot run unless its separate environment switch, host execution, executable validation, and per-job approval all succeed."}</p></div></section>
      <div className="lab-security-grid">{CONTROLS.map((control) => <article key={control.title}><div className="lab-control-icon"><Icon name="check" size={17} /></div><div><header><h2>{control.title}</h2><Badge tone={control.state === "manual" ? "warn" : "ok"}>{control.state}</Badge></header><p>{control.detail}</p></div></article>)}</div>
      <section className="lab-panel-card"><header className="lab-card-header"><div><h2>Communication matrix</h2><p>The effective collaboration boundary published on every duty card</p></div></header><div className="lab-policy-table" role="table"><div className="lab-policy-head" role="row"><span>Agent</span><span>Home</span><span>Scope</span><span>Meeting access</span></div>{agents.map((agent) => { const group = groups.find((item) => item.id === agent.department_id); const meetingAccess = agent.communication_scope === "isolated" ? "Solo room only" : agent.communication_scope === "department" ? "Same group" : "Cross-group"; return <div key={agent.id} role="row"><span><AgentAvatar name={agent.name} size="sm" /><strong>{agent.name}</strong></span><span>{group?.name ?? "Independent"}</span><span><Badge>{agent.communication_scope}</Badge></span><span>{meetingAccess}</span></div>; })}{agents.length === 0 && <p className="lab-card-empty">Agent communication policies will appear here.</p>}</div></section>
      <section className="lab-known-limit"><Icon name="warning" size={18} /><div><h2>Local-first is not multi-user isolation</h2><p>This build is for one trusted OS user on loopback. A shared or remote service still requires HTTPS authentication, per-project authorization, durable scoped event delivery, and rootless container or microVM workers. See <code>SECURITY.md</code> before deployment changes.</p></div></section>
    </main>
  );
}
