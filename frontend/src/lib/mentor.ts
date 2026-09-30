// ─────────────────────────────────────────────────────────────────────────────
// mentor.ts — one entry point for asking the mentor to explain something.
// READING ORDER: frontend #29
//
// WHAT IT DOES: shows the founder's question as a "You" bubble, then calls /api/explain
// with the question/content PLUS whatever the active review tab set as context (so
// "what does this diff do?" is grounded in the actual diff). The mentor's answer then
// streams back over /ws as role "mentor" — no separate panel (PROMPT.md §11).
//
// WHY a plain function (not a store action): it needs both the store (to read context /
// add the bubble) and the API. Keeping it here lets the store stay free of network code.
// ─────────────────────────────────────────────────────────────────────────────

import { useAppStore } from "../store/appStore";
import { postExplain } from "./api";

const MAX_MENTOR_CONTEXT_CHARS = 50_000;

function bounded(value?: string): string | undefined {
  return value?.slice(0, MAX_MENTOR_CONTEXT_CHARS);
}

/** Ask the mentor. `userLabel` is the bubble we show for what the founder asked. */
export async function askMentor(options: {
  userLabel: string;
  content?: string;
  question?: string;
}): Promise<void> {
  const store = useAppStore.getState();
  // Optimistically show what we're asking, so the conversation reads naturally.
  store.addUserTurn(options.userLabel);

  const context = store.mentorContext;
  await postExplain({
    content: bounded(options.content),
    question: options.question,
    context: bounded(context?.content),
    context_label: context?.label,
  });
}
