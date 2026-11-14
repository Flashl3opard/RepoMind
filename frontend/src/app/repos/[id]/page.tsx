import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ErrorState } from "@/components/error-state";
import { RepoOverviewStatus } from "@/components/repo-overview-status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, getRepository } from "@/lib/api";

export default function RepoOverviewPage({ params }: PageProps<"/repos/[id]">) {
  return (
    <Suspense fallback={<OverviewSkeleton />}>
      <RepoOverview params={params} />
    </Suspense>
  );
}

function OverviewSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <Skeleton className="h-7 w-80" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}

async function RepoOverview({
  params,
}: {
  params: PageProps<"/repos/[id]">["params"];
}) {
  const { id } = await params;

  let repo;
  try {
    repo = await getRepository(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <ErrorState
        message={
          error instanceof Error ? error.message : "Failed to load repository."
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold break-all">{repo.url}</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Overview</CardTitle>
        </CardHeader>
        <CardContent>
          <RepoOverviewStatus initial={repo} />
        </CardContent>
      </Card>

      <div className="flex gap-3">
        <Button asChild>
          <Link href={`/repos/${id}/ask`}>Ask a question</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href={`/repos/${id}/reviews`}>View reviews</Link>
        </Button>
      </div>
    </div>
  );
}
