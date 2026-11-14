"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { TableCell, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/components/status-badge";
import { getRepoStatusAction } from "@/lib/actions";
import { isTerminalRepositoryStatus, startPolling } from "@/lib/polling";
import type { RepoListItem } from "@/lib/types";

const POLL_INTERVAL_MS = 4000;

export function RepoRow({ repo }: { repo: RepoListItem }) {
  const [status, setStatus] = useState(repo.status);
  const [fileCount, setFileCount] = useState(repo.file_count);
  const [chunkCount, setChunkCount] = useState(repo.chunk_count);
  const [commitSha, setCommitSha] = useState(repo.commit_sha);

  useEffect(() => {
    if (isTerminalRepositoryStatus(status)) return;

    const stop = startPolling({
      intervalMs: POLL_INTERVAL_MS,
      fetchValue: () => getRepoStatusAction(repo.id),
      isTerminal: (result) =>
        !result.ok || isTerminalRepositoryStatus(result.data?.status ?? ""),
      onUpdate: (result) => {
        if (!result.ok || !result.data) return;
        setStatus(result.data.status);
        setFileCount(result.data.file_count);
        setChunkCount(result.data.chunk_count);
        setCommitSha(result.data.last_commit_sha);
      },
    });

    return stop;
  }, [repo.id, status]);

  return (
    <TableRow>
      <TableCell>
        <Link
          href={`/repos/${repo.id}`}
          className="font-medium hover:underline"
        >
          {repo.full_name}
        </Link>
      </TableCell>
      <TableCell>
        <StatusBadge status={status} />
      </TableCell>
      <TableCell className="font-mono text-xs">
        {commitSha ? commitSha.slice(0, 7) : "—"}
      </TableCell>
      <TableCell>{fileCount}</TableCell>
      <TableCell>{chunkCount}</TableCell>
    </TableRow>
  );
}
