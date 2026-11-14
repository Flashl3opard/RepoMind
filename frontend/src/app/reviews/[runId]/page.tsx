import { Suspense } from "react";
import { notFound } from "next/navigation";

import { ErrorState } from "@/components/error-state";
import { FindingsList } from "@/components/findings-list";
import { RiskBadge } from "@/components/risk-badge";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, getRepository, getReviewRun } from "@/lib/api";

export default function ReviewDetailPage({
  params,
}: PageProps<"/reviews/[runId]">) {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <ReviewDetailContent params={params} />
    </Suspense>
  );
}

async function ReviewDetailContent({
  params,
}: {
  params: PageProps<"/reviews/[runId]">["params"];
}) {
  const { runId } = await params;

  let run;
  try {
    run = await getReviewRun(runId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <ErrorState
        message={
          error instanceof Error ? error.message : "Failed to load this review."
        }
      />
    );
  }

  const repo = await getRepository(run.repository_id).catch(() => null);
  // A manual run's head_sha is a synthetic placeholder (see routes.py), not a real
  // commit -- only link to GitHub when we have the PR's actual head commit.
  const commitSha = run.source === "manual" ? null : run.head_sha;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">
          {run.pr_number > 0 ? `PR #${run.pr_number}` : "Manual review"}
        </h1>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="capitalize">
            {run.source}
          </Badge>
          <StatusBadge status={run.status} />
          <RiskBadge risk={run.risk_level} />
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Summary</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <p className="text-sm">{run.summary ?? "No summary available."}</p>
          {run.error ? (
            <ErrorState title="Review error" message={run.error} />
          ) : null}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">
          Findings ({run.finding_count})
        </h2>
        <FindingsList
          findings={run.findings ?? []}
          repoUrl={repo?.url}
          commitSha={commitSha}
        />
      </div>
    </div>
  );
}
