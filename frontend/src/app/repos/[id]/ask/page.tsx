import { Suspense } from "react";
import { notFound } from "next/navigation";

import { AskPanel } from "@/components/ask-panel";
import { ErrorState } from "@/components/error-state";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, getRepository } from "@/lib/api";

export default function AskPage({ params }: PageProps<"/repos/[id]/ask">) {
  return (
    <Suspense fallback={<Skeleton className="h-48 w-full" />}>
      <AskPageContent params={params} />
    </Suspense>
  );
}

async function AskPageContent({
  params,
}: {
  params: PageProps<"/repos/[id]/ask">["params"];
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

  if (repo.status !== "completed") {
    return (
      <EmptyState
        title="Repository isn't ready yet"
        description={`This repo's ingestion status is "${repo.status}". Come back once it's complete.`}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Ask about {repo.url}</h1>
      <AskPanel
        repositoryId={id}
        repoUrl={repo.url}
        commitSha={repo.last_commit_sha}
      />
    </div>
  );
}
