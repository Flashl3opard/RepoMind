"use client";

import { useEffect, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { StatusBadge } from "@/components/status-badge";
import { getRepoStatusAction } from "@/lib/actions";
import { isTerminalRepositoryStatus, startPolling } from "@/lib/polling";
import type { RepoStatusResponse } from "@/lib/types";

const POLL_INTERVAL_MS = 4000;

export function RepoOverviewStatus({
  initial,
}: {
  initial: RepoStatusResponse;
}) {
  const [state, setState] = useState(initial);

  useEffect(() => {
    if (isTerminalRepositoryStatus(state.status)) return;

    const stop = startPolling({
      intervalMs: POLL_INTERVAL_MS,
      fetchValue: () => getRepoStatusAction(initial.id),
      isTerminal: (result) =>
        !result.ok || isTerminalRepositoryStatus(result.data?.status ?? ""),
      onUpdate: (result) => {
        if (result.ok && result.data) setState(result.data);
      },
    });

    return stop;
  }, [initial.id, state.status]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-sm">Status</span>
          <StatusBadge status={state.status} />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-sm">Commit</span>
          <span className="font-mono text-sm">
            {state.last_commit_sha ? state.last_commit_sha.slice(0, 10) : "—"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-sm">Files</span>
          <span className="text-sm">{state.file_count}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-sm">Chunks</span>
          <span className="text-sm">{state.chunk_count}</span>
        </div>
      </div>

      {state.status === "failed" && state.error_message ? (
        <Alert variant="destructive">
          <AlertTitle>Ingestion failed</AlertTitle>
          <AlertDescription>{state.error_message}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}
