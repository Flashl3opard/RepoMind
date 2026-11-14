// Generic polling loop used by the repo-status poller (and reusable for anything
// else that needs "poll until terminal"). Pure logic around setTimeout so it's
// testable with vitest's fake timers; no fetch/DOM dependency here.

export interface PollOptions<T> {
  fetchValue: () => Promise<T>;
  isTerminal: (value: T) => boolean;
  intervalMs: number;
  onUpdate: (value: T) => void;
  onError?: (error: unknown) => void;
}

/** Starts polling immediately; returns a function that stops it. Stops itself once
 * `isTerminal` returns true, or after the first error (reported via `onError`,
 * not retried -- the caller decides whether to restart). */
export function startPolling<T>(options: PollOptions<T>): () => void {
  let stopped = false;
  let timeoutId: ReturnType<typeof setTimeout> | null = null;

  async function tick(): Promise<void> {
    if (stopped) return;
    let value: T;
    try {
      value = await options.fetchValue();
    } catch (error) {
      if (!stopped) options.onError?.(error);
      return;
    }
    if (stopped) return;
    options.onUpdate(value);
    if (options.isTerminal(value) || stopped) return;
    timeoutId = setTimeout(tick, options.intervalMs);
  }

  void tick();

  return () => {
    stopped = true;
    if (timeoutId !== null) clearTimeout(timeoutId);
  };
}

export const TERMINAL_REPOSITORY_STATUSES = new Set(["completed", "failed"]);

export function isTerminalRepositoryStatus(status: string): boolean {
  return TERMINAL_REPOSITORY_STATUSES.has(status);
}
