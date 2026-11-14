import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { CitationChip } from "@/components/citation-chip";
import { SeverityBadge } from "@/components/severity-badge";
import type { FindingResponse } from "@/lib/types";

const CATEGORY_LABEL: Record<string, string> = {
  breaking_change: "Breaking change",
  bug_risk: "Bug risk",
  missing_test: "Missing test",
  security: "Security",
  style: "Style",
};

export interface FindingCardProps {
  finding: FindingResponse;
  repoUrl?: string;
  commitSha?: string | null;
}

export function FindingCard({ finding, repoUrl, commitSha }: FindingCardProps) {
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="flex-row items-start justify-between gap-2 px-4">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          <Badge variant="outline">
            {CATEGORY_LABEL[finding.category] ?? finding.category}
          </Badge>
        </div>
        {repoUrl ? (
          <CitationChip
            filePath={finding.file}
            startLine={finding.start_line}
            endLine={finding.end_line}
            repoUrl={repoUrl}
            commitSha={commitSha ?? null}
          />
        ) : (
          <span className="text-muted-foreground text-xs whitespace-nowrap">
            {finding.file}:{finding.start_line}-{finding.end_line}
          </span>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-2 px-4">
        <p className="text-sm">{finding.message}</p>
        {finding.evidence.length > 0 ? (
          <p className="text-muted-foreground text-xs">
            Evidence: {finding.evidence.join(", ")}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
