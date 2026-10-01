import { useCallback, useEffect, useRef, useState } from "react";

import { useAppStore } from "../store/appStore";

export type AsyncActionResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string };

export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  return fallback;
}

/**
 * A small, shared state machine for user-triggered requests.
 *
 * The hook deliberately owns only pending/error state. Form values remain in the
 * calling component, so a rejected request never clears the user's draft and the
 * same action can be retried in place.
 */
export function useAsyncAction({
  fallbackError = "The request failed.",
  notify = true,
}: {
  fallbackError?: string;
  notify?: boolean;
} = {}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const inFlight = useRef(false);

  useEffect(() => () => {
    mounted.current = false;
  }, []);

  const clearError = useCallback(() => setError(null), []);

  const run = useCallback(async <T,>(task: () => Promise<T>): Promise<AsyncActionResult<T>> => {
    if (inFlight.current) {
      return { ok: false, error: "This action is already in progress." };
    }

    inFlight.current = true;
    setPending(true);
    setError(null);
    try {
      return { ok: true, value: await task() };
    } catch (cause) {
      const nextError = errorMessage(cause, fallbackError);
      if (mounted.current) {
        setError(nextError);
        if (notify) useAppStore.getState().pushToast(nextError);
      }
      return { ok: false, error: nextError };
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending(false);
    }
  }, [fallbackError, notify]);

  return { clearError, error, pending, run };
}
