// ─────────────────────────────────────────────────────────────────────────────
// JsonTree.tsx — render any JSON value as an indented, color-coded tree.
// READING ORDER: frontend #20  (teaches: recursion in React)
//
// WHAT IT DOES: given any value (object, array, string, number…), it renders a
// readable tree. It calls itself for nested values — the classic recursive shape.
// This is the "tree" half of the Spec tab (the "raw" half is Monaco).
//
// WHY hand-rolled instead of a library: it's ~40 lines, it teaches recursion, and it
// needs no extra dependency (PROMPT.md §4 lists a JSON-view lib as optional).
// ─────────────────────────────────────────────────────────────────────────────

/** One node in the tree: an optional key label plus the value it points at. */
function Node({ label, value }: { label?: string; value: unknown }) {
  const key = label !== undefined ? <span className="text-role-pm">{label}: </span> : null;

  if (value === null || value === undefined) {
    return (
      <div>
        {key}
        <span className="text-muted">null</span>
      </div>
    );
  }

  if (typeof value === "string") {
    return (
      <div>
        {key}
        <span className="text-ok">&quot;{value}&quot;</span>
      </div>
    );
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return (
      <div>
        {key}
        <span className="text-role-generator">{String(value)}</span>
      </div>
    );
  }

  // Arrays and objects both recurse into an indented, left-bordered block.
  const isArray = Array.isArray(value);
  const entries = isArray
    ? (value as unknown[]).map((item, index) => [String(index), item] as const)
    : Object.entries(value as Record<string, unknown>);

  return (
    <div>
      {key}
      <span className="text-muted">{isArray ? `[${entries.length}]` : "{}"}</span>
      <div className="ml-3 border-l border-line pl-3">
        {entries.map(([childKey, childValue]) => (
          <Node key={childKey} label={isArray ? undefined : childKey} value={childValue} />
        ))}
      </div>
    </div>
  );
}

/** Render a JSON value as a color-coded tree. */
export default function JsonTree({ value }: { value: unknown }) {
  return (
    <div className="font-mono text-[12px] leading-relaxed">
      <Node value={value} />
    </div>
  );
}
