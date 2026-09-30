// Small dependency-free icon set for the Studio activity rail and controls.

import type { ReactNode } from "react";

export type IconName =
  | "hq"
  | "organization"
  | "research"
  | "meetings"
  | "security"
  | "workbench"
  | "explorer"
  | "search"
  | "sourceControl"
  | "terminal"
  | "account"
  | "settings"
  | "folder"
  | "file"
  | "branch"
  | "cloudUpload"
  | "chevronRight"
  | "chevronDown"
  | "collapse"
  | "plus"
  | "refresh"
  | "play"
  | "users"
  | "agent"
  | "task"
  | "check"
  | "warning"
  | "close";

const PATHS: Record<IconName, ReactNode> = {
  hq: <><path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10.5V20h13v-9.5M9 20v-6h6v6"/></>,
  organization: <><circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M12 7.5v4M5 15.5v-2h14v2"/></>,
  research: <><path d="M9 3h6M10 3v5l-5.5 9.5A2.3 2.3 0 0 0 6.5 21h11a2.3 2.3 0 0 0 2-3.5L14 8V3"/><path d="M7.5 15h9"/></>,
  meetings: <><path d="M4 5h16v11H8l-4 4V5Z"/><path d="M8 9h8M8 12h5"/></>,
  security: <><path d="M12 3 5 6v5c0 4.6 2.8 8.2 7 10 4.2-1.8 7-5.4 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-5"/></>,
  workbench: <><rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M8 4v16M8 9h13M13 9v11"/></>,
  explorer: <><path d="M4 3h10l2 2h4v14H4z"/><path d="M8 8h8M8 12h8M8 16h5"/></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/></>,
  sourceControl: <><circle cx="6" cy="5" r="2.5"/><circle cx="6" cy="19" r="2.5"/><circle cx="18" cy="12" r="2.5"/><path d="M6 7.5v9M8.5 5c6.5 0 7 4.5 7 4.5"/></>,
  terminal: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M12.5 15h4.5"/></>,
  account: <><circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/></>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.86 2.86-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21H9.55v-.09A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.86-2.86.06-.06A1.7 1.7 0 0 0 4.1 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H2.3V9.55h.1A1.7 1.7 0 0 0 4.1 8.5a1.7 1.7 0 0 0-.34-1.88L3.7 6.56 6.56 3.7l.06.06A1.7 1.7 0 0 0 8.5 4.1a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V2.3h4.05v.1A1.7 1.7 0 0 0 15 4.1a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.86 2.86-.06.06A1.7 1.7 0 0 0 19.4 8.5c.16.4.37.75.7 1 .3.24.7.38 1.1.4h.1v4.05h-.1A1.7 1.7 0 0 0 19.4 15Z"/></>,
  folder: <path d="M3 6h7l2 2h9v11H3z"/>,
  file: <><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h4"/></>,
  branch: <><circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="7" r="2"/><path d="M6 7v10M8 17c6 0 8-3 8-8"/></>,
  cloudUpload: <><path d="M7 18H5a3 3 0 0 1-.2-6A7 7 0 0 1 18 9.5a4.5 4.5 0 0 1 .5 8.5H17"/><path d="M12 20V11m-4 4 4-4 4 4"/></>,
  chevronRight: <path d="m9 5 7 7-7 7"/>,
  chevronDown: <path d="m5 9 7 7 7-7"/>,
  collapse: <><path d="m8 3-5 5 5 5M3 8h11M16 11l5 5-5 5M21 16H10"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  refresh: <><path d="M20 7v5h-5"/><path d="M18.5 15a7.5 7.5 0 1 1 .2-6.3L20 12"/></>,
  play: <path d="m8 5 11 7-11 7V5Z"/>,
  users: <><circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3.5 20c.5-4 2.3-6 5.5-6s5 2 5.5 6M14 15c3.6-.4 5.5 1.3 6 4"/></>,
  agent: <><rect x="4" y="7" width="16" height="13" rx="3"/><path d="M12 3v4M8 12h.01M16 12h.01M8 16h8"/></>,
  task: <><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  warning: <><path d="M12 3 2.8 20h18.4L12 3Z"/><path d="M12 9v5M12 17h.01"/></>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {PATHS[name]}
    </svg>
  );
}
