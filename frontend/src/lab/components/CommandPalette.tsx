import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { useDialogFocus } from "../../lib/dialog";
import { useLabStore } from "../store";
import type { LabView } from "../types";
import { Icon } from "./Icons";

export interface PaletteCommand {
  view: LabView;
  label: string;
  detail: string;
  keywords?: string;
}

export const COMMANDS: PaletteCommand[] = [
  { view: "explorer", label: "Explorer: Open Project Files", detail: "Browse and read the selected workspace", keywords: "code files tree" },
  { view: "search", label: "Search: Find in Files", detail: "Search safely across project text", keywords: "code query" },
  { view: "source_control", label: "Source Control: Git", detail: "Review, stage, commit, and push", keywords: "scm changes repository" },
  { view: "hq", label: "R&D: Open Headquarters", detail: "Agents, departments, and research activity", keywords: "home dashboard" },
  { view: "terminal", label: "Terminal: Open Trusted Shell", detail: "Local operator terminal, opt-in only", keywords: "command line cli" },
  { view: "organization", label: "R&D: Open Organization", detail: "Departments, teams, and duty cards", keywords: "agents people" },
  { view: "research", label: "R&D: Open Research Board", detail: "Projects, tasks, and findings", keywords: "work results" },
  { view: "knowledge", label: "R&D: Open Evidence Library", detail: "Sources, claims, search, and dossiers", keywords: "knowledge citations export" },
  { view: "evaluations", label: "R&D: Open Model Arena", detail: "Compare model responses with human scores", keywords: "eval experiment comparison" },
  { view: "meetings", label: "R&D: Open Meeting Rooms", detail: "Bounded agent collaboration", keywords: "transcript discussion" },
  { view: "operations", label: "R&D: Open Operations", detail: "Run history, budgets, templates, and automation", keywords: "jobs policy retry cancel" },
  { view: "security", label: "R&D: Open Security Center", detail: "Capabilities and trust boundary", keywords: "permissions safety" },
  { view: "workbench", label: "Open Ideation Workbench", detail: "Specs, mentor, diffs, and checks", keywords: "idea build" },
];

export function filterCommands(query: string, commands = COMMANDS): PaletteCommand[] {
  const terms = query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return commands;
  return commands.filter((command) => {
    const searchable = `${command.label} ${command.detail} ${command.keywords ?? ""}`.toLocaleLowerCase();
    return terms.every((term) => searchable.includes(term));
  });
}

export function CommandPalette({
  onClose,
  onNavigate,
}: {
  onClose: () => void;
  onNavigate?: (view: LabView) => void;
}) {
  const setView = useLabStore((state) => state.setView);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const dialogRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const results = useMemo(() => filterCommands(query), [query]);
  const boundedIndex = results.length === 0 ? 0 : Math.min(activeIndex, results.length - 1);
  useDialogFocus(dialogRef, onClose, inputRef);

  useEffect(() => setActiveIndex(0), [query]);

  function choose(command: PaletteCommand) {
    (onNavigate ?? setView)(command.view);
    onClose();
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => results.length === 0 ? 0 : (index + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => results.length === 0 ? 0 : (index - 1 + results.length) % results.length);
    } else if (event.key === "Home") {
      event.preventDefault();
      setActiveIndex(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActiveIndex(Math.max(0, results.length - 1));
    } else if (event.key === "Enter" && results[boundedIndex]) {
      event.preventDefault();
      choose(results[boundedIndex]);
    }
  }

  return (
    <div className="lab-command-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section
        ref={dialogRef}
        className="lab-command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        tabIndex={-1}
      >
        <header>
          <Icon name="search" size={16} />
          <label className="sr-only" htmlFor={`${listId}-input`}>Search workspace commands</label>
          <input
            ref={inputRef}
            id={`${listId}-input`}
            role="combobox"
            aria-autocomplete="list"
            aria-controls={listId}
            aria-expanded="true"
            aria-activedescendant={results[boundedIndex] ? `${listId}-${results[boundedIndex].view}` : undefined}
            autoComplete="off"
            placeholder="Navigate Lemma…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
          />
          <kbd>esc</kbd>
        </header>
        <div id={listId} role="listbox" aria-label="Workspace commands">
          {results.map((command, index) => {
            const shortcut = COMMANDS.indexOf(command);
            return (
              <button
                key={command.view}
                id={`${listId}-${command.view}`}
                type="button"
                role="option"
                aria-selected={index === boundedIndex}
                className={index === boundedIndex ? "is-active" : ""}
                onPointerMove={() => setActiveIndex(index)}
                onClick={() => choose(command)}
              >
                <span><strong>{command.label}</strong><small>{command.detail}</small></span>
                {shortcut >= 0 && shortcut < 9 && <kbd>⌘{shortcut + 1}</kbd>}
              </button>
            );
          })}
          {results.length === 0 && (
            <p className="lab-command-empty" role="status">No commands match “{query}”.</p>
          )}
        </div>
      </section>
    </div>
  );
}
