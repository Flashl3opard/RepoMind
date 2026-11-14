import { FindingCard } from "@/components/finding-card";
import { EmptyState } from "@/components/empty-state";
import { groupFindingsByFile } from "@/lib/severity";
import type { FindingResponse } from "@/lib/types";

export interface FindingsListProps {
  findings: FindingResponse[];
  repoUrl?: string;
  commitSha?: string | null;
}

/** Findings grouped by file, each group's findings severity-ordered. Shared between
 * the review detail page and the playground so both render identically. */
export function FindingsList({
  findings,
  repoUrl,
  commitSha,
}: FindingsListProps) {
  if (findings.length === 0) {
    return (
      <EmptyState
        title="No findings"
        description="This review didn't surface anything worth flagging."
      />
    );
  }

  const groups = groupFindingsByFile(findings);

  return (
    <div className="flex flex-col gap-6">
      {groups.map((group) => (
        <div key={group.file} className="flex flex-col gap-3">
          <h3 className="font-mono text-sm font-medium">{group.file}</h3>
          <div className="flex flex-col gap-3">
            {group.findings.map((finding, index) => (
              <FindingCard
                key={`${group.file}-${index}`}
                finding={finding}
                repoUrl={repoUrl}
                commitSha={commitSha}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
