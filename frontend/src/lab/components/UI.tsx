// Shared, accessible primitives for the R&D Studio. Styling lives in theme.css.

import { useEffect, type ButtonHTMLAttributes, type CSSProperties, type ReactNode } from "react";

import { Icon, type IconName } from "./Icons";

export function Button({
  variant = "secondary",
  icon,
  children,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  icon?: IconName;
}) {
  return (
    <button
      type="button"
      className={`lab-button lab-button-${variant} ${className}`}
      {...props}
    >
      {icon && <Icon name={icon} size={15} />}
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="lab-field">
      <span className="lab-field-label">{label}</span>
      {children}
      {hint && <span className="lab-field-hint">{hint}</span>}
    </label>
  );
}

export function Modal({
  title,
  description,
  children,
  onClose,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  onClose: () => void;
}) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="lab-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="lab-modal-title"
        className="lab-modal"
      >
        <header className="lab-modal-header">
          <div>
            <h2 id="lab-modal-title">{title}</h2>
            {description && <p>{description}</p>}
          </div>
          <button type="button" className="lab-icon-button" onClick={onClose} aria-label="Close dialog">
            <Icon name="close" size={18} />
          </button>
        </header>
        <div className="lab-modal-body">{children}</div>
      </section>
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`lab-badge lab-badge-${tone}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const tone = ["active", "completed", "approved", "open"].includes(normalized)
    ? "ok"
    : ["running", "queued", "waiting", "draft"].includes(normalized)
      ? "warn"
      : ["failed", "rejected", "blocked"].includes(normalized)
        ? "err"
        : "neutral";
  return <Badge tone={tone}>{status.replaceAll("_", " ")}</Badge>;
}

export function AgentAvatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "AI";
  let hash = 0;
  for (const character of name) hash = (hash * 31 + character.charCodeAt(0)) % 360;
  return (
    <span
      className={`lab-avatar lab-avatar-${size}`}
      style={{ "--avatar-hue": hash } as CSSProperties}
      aria-hidden="true"
    >
      {initials}
    </span>
  );
}

export function EmptyState({
  icon,
  title,
  detail,
  action,
}: {
  icon: IconName;
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="lab-empty">
      <span className="lab-empty-icon"><Icon name={icon} size={25} /></span>
      <h3>{title}</h3>
      <p>{detail}</p>
      {action}
    </div>
  );
}

export function LoadingState({ label = "Loading R&D Studio…" }: { label?: string }) {
  return (
    <div className="lab-loading" role="status">
      <span className="lab-spinner" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="lab-error" role="alert">
      <Icon name="warning" size={20} />
      <div><strong>Studio data is unavailable</strong><p>{message}</p></div>
      <Button variant="secondary" onClick={onRetry}>Retry</Button>
    </div>
  );
}

/** Honest research label: this secure MVP has no autonomous browser or source tools. */
export function UnverifiedNotice({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`lab-unverified ${compact ? "lab-unverified-compact" : ""}`}>
      <Icon name="warning" size={15} />
      <span>
        <strong>Model synthesis — unverified.</strong>{" "}
        No autonomous web or source tools are enabled. Validate claims against sources you supply.
      </span>
    </div>
  );
}
